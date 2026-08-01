#!/usr/bin/env python3
"""LAAP PR Review — self-contained GitHub Action script.
Zero external dependencies, zero LLM calls, pure Python."""
import json, os, re, sys

class Finding:
    __slots__ = ('severity','category','file','line','title','desc','suggestion')
    def __init__(self, sev, cat, f, line=None, title='', desc='', sug=''):
        self.severity=sev; self.category=cat; self.file=f; self.line=line
        self.title=title; self.desc=desc; self.suggestion=sug

SECRETS = [
    re.compile(r'\b(?:api[_-]?key|apikey)\s*[:=]\s*["\'][A-Za-z0-9_\-]{8,}', re.I),
    re.compile(r'\bpassword\s*[:=]\s*["\'][^"\']{4,}', re.I),
    re.compile(r'\b(?:access[_-]?token|auth[_-]?token)\s*[:=]\s*["\'][A-Za-z0-9_\-]{8,}', re.I),
]
SQL_PAT = re.compile(r'(?:execute|query|cursor\.\w+)\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE)', re.I)
XSS_PAT = re.compile(r'\.innerHTML\s*=\s*[^"\'<]', re.I)

def get_changed(files):
    lines = []
    for fc in files:
        for h in fc.get('hunks',[]):
            for l in h.get('lines',[]):
                if l[0] in '+-': lines.append(l)
    return '\n'.join(lines)

def review(diff):
    files, cur, cur_hunk, cur_lines = [], None, None, []
    for line in diff.splitlines():
        if line.startswith('diff --git'):
            if cur: cur['hunks'].append({'lines':cur_lines}) if cur_hunk else None; files.append(cur)
            p = line.split()[-1].lstrip('b/') if len(line.split())>=4 else 'x'
            cur = {'path':p,'additions':0,'deletions':0,'hunks':[]}; cur_hunk=None; cur_lines=[]
        elif line.startswith('@@ '):
            if cur and cur_hunk: cur['hunks'].append({'lines':cur_lines})
            m = re.match(r'@@ -\d+,?\d* \+(\d+),?\d* @@', line)
            cur_hunk = int(m.group(1)) if m else None; cur_lines=[]
        elif cur_hunk is not None:
            cur_lines.append(line)
            if cur:
                if line.startswith('+'): cur['additions']+=1
                elif line.startswith('-'): cur['deletions']+=1
    if cur:
        if cur_hunk: cur['hunks'].append({'lines':cur_lines})
        files.append(cur)

    findings = []
    for fc in files:
        content = get_changed([fc])
        lines = content.splitlines()
        for i, raw in enumerate(lines, 1):
            text = raw[1:] if raw[0] in '+-' else raw
            if raw[0] != '+': continue
            for pat in SECRETS:
                if pat.search(text):
                    findings.append(Finding('critical','security',fc['path'],i,'硬编码密钥','密钥泄漏风险','使用环境变量'))
                    break
            if SQL_PAT.search(text):
                findings.append(Finding('high','security',fc['path'],i,'SQL注入','可能的SQL注入','使用参数化查询'))
            if XSS_PAT.search(text):
                findings.append(Finding('high','security',fc['path'],i,'XSS风险','未转义HTML输出','使用HTML转义'))
            if any(kw in text for kw in ['<<<<<<<','=======','>>>>>>>']):
                findings.append(Finding('critical','merge',fc['path'],i,'合并冲突','未解决的冲突标记','请解决后提交'))
            if any(kw in text for kw in ['print(','console.log(','debugger']):
                findings.append(Finding('low','debug',fc['path'],i,'调试语句',text[:60],'生产代码中移除'))
        if fc['additions'] > 500:
            findings.append(Finding('medium','size',fc['path'],None,'大变更',f'{fc["additions"]}行新增','考虑拆分'))

    py_changes = [f for f in files if f['path'].endswith('.py') and f['additions']>0]
    doc_changes = [f for f in files if f['path'].endswith(('.md','.rst','README'))]
    if py_changes and not doc_changes:
        findings.append(Finding('low','docs','(global)',None,'文档待更新',f'{len(py_changes)}个源码文件修改','检查README是否需同步'))

    counts = {}
    for f in findings: counts[f.severity] = counts.get(f.severity,0)+1
    summary = ', '.join(f'{v} {k}' for k,v in sorted(counts.items())) or 'no issues'

    if 'critical' in counts or 'high' in counts: verdict = 'REQUEST_CHANGES'
    elif 'medium' in counts: verdict = 'COMMENT'
    else: verdict = 'APPROVE'

    labels = {'REQUEST_CHANGES':'🔴 Changes Requested','COMMENT':'💬 Comments','APPROVE':'✅ Approved'}
    md = [f'## LAAP Colony Review — {labels.get(verdict,verdict)}','',
          f'**Summary:** {summary}',
          f'**Stats:** {len(files)} files | +{sum(f["additions"] for f in files)}/'
          f'-{sum(f["deletions"] for f in files)} lines','']
    if not findings:
        md.append('No issues found. Looks clean! 🎉')
    else:
        for sev,lb in [('critical','### 🔴 Critical'),('high','### ⚠️ High'),
                       ('medium','### 🟡 Medium'),('low','### 🔵 Low')]:
            g = [f for f in findings if f.severity==sev]
            if not g: continue
            md.append(lb); md.append('')
            for f in g:
                loc = f'`{f.file}`'+ (f':{f.line}' if f.line else '')
                md.append(f'- **{f.title}** ({loc})')
                if f.desc: md.append(f'  - {f.desc[:200]}')
                if f.suggestion: md.append(f'  - 💡 {f.suggestion}')
            md.append('')
    md.append('---\n*Reviewed by LAAP Colony Agents (zero LLM)*')

    return {'verdict':verdict,'summary':summary,'markdown':'\n'.join(md)}

if __name__ == '__main__':
    diff_path = sys.argv[1] if len(sys.argv)>1 else None
    if diff_path:
        with open(diff_path) as f: diff = f.read()
    else:
        diff = sys.stdin.read()
    result = review(diff)
    print(result['markdown'])
    print()
    print(f'VERDICT={result["verdict"]}', file=sys.stderr)
