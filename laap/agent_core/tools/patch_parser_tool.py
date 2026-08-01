"""PatchParserTool — 补丁解析"""
import json, re
class PatchParserTool:
    def parse(self, patch_text):
        files = re.findall(r'\+\+\+\s+b/(\S+)', patch_text)
        additions = len(re.findall(r'^\+[^+]', patch_text, re.MULTILINE))
        deletions = len(re.findall(r'^-[^-]', patch_text, re.MULTILINE))
        return json.dumps({"files": files, "additions": additions, "deletions": deletions})
TOOL_DEFS = [{"name":"parse_patch","fn":PatchParserTool().parse,"desc":"解析补丁","params":{"patch_text":{"type":"string"}},"req":["patch_text"]}]
