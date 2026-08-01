"""LAAP GitHub Review Submitter — 克隆 PR → 审查 → 提交 Review

流程:
  1. 从 GitHub API 获取 PR 信息
  2. clone/fetch 仓库, checkout PR 分支
  3. 获取 diff
  4. 调用 PRReviewEngine 审查
  5. 将结果提交为 GitHub Review (inline comments + summary)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from laap.colony.pr_review import PRReviewEngine

logger = logging.getLogger("laap.github.review_submitter")


def _run_cmd(cmd: List[str], cwd: Optional[str] = None, timeout: int = 120) -> str:
    """运行 shell 命令，返回 stdout。"""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if result.returncode != 0:
        logger.warning(f"命令失败: {' '.join(cmd)}: {result.stderr[:200]}")
    return result.stdout.strip()


def setup_gh_auth() -> Optional[str]:
    """获取 GitHub Token，优先 gh CLI，其次环境变量。

    Returns:
        token 字符串，或 None（无可用认证）
    """
    # 尝试 gh CLI
    try:
        token = _run_cmd(["gh", "auth", "token"])
        if token:
            return token
    except Exception:
        pass

    # 尝试环境变量
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token

    # 尝试 .env 文件
    for env_path in [os.path.expanduser("~/.hermes/.env"), os.path.expanduser("~/.env")]:
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        if line.startswith("GITHUB_TOKEN="):
                            return line.split("=", 1)[1].strip().strip("'\"")
            except Exception:
                pass

    return None


def get_diff_from_pr(repo_url: str, pr_number: int, work_dir: str) -> Optional[str]:
    """从 GitHub 获取 PR 的 unified diff。

    Args:
        repo_url: 仓库 clone URL
        pr_number: PR 编号
        work_dir: 工作目录

    Returns:
        diff 文本，或 None（失败）
    """
    repo_name = repo_url.rstrip(".git").split("/")[-1]
    repo_path = os.path.join(work_dir, repo_name)

    try:
        # clone 或 fetch
        if os.path.isdir(repo_path):
            _run_cmd(["git", "-C", repo_path, "fetch", "origin"])
        else:
            _run_cmd(["git", "clone", "--depth=50", repo_url, repo_path])

        # 获取 diff
        token = setup_gh_auth()
        if token:
            owner_repo = "/".join(repo_url.rstrip(".git").split("/")[-2:])
            import urllib.request
            req = urllib.request.Request(
                f"https://api.github.com/repos/{owner_repo}/pulls/{pr_number}",
                headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3.diff"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                diff_text = resp.read().decode("utf-8")
                if diff_text:
                    return diff_text
        elif _run_cmd(["which", "gh"]):
            diff_text = _run_cmd(["gh", "pr", "diff", str(pr_number)], cwd=repo_path)
            if diff_text:
                return diff_text

        # 最后手段：用 git fetch + diff
        _run_cmd(["git", "-C", repo_path, "fetch", "origin", f"pull/{pr_number}/head:pr-{pr_number}"])
        default_branch = _run_cmd(["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"])
        diff_text = _run_cmd(["git", "-C", repo_path, "diff", f"{default_branch}...pr-{pr_number}"])
        return diff_text or None

    except Exception as e:
        logger.error(f"获取 PR diff 失败: {e}")
        return None


def submit_review(
    repo_full_name: str,
    pr_number: int,
    verdict: str,
    body: str,
    comments: List[Dict[str, Any]],
    head_sha: str,
) -> dict:
    """向 GitHub 提交 Review。

    Args:
        repo_full_name: "owner/repo"
        pr_number: PR 编号
        verdict: APPROVE / REQUEST_CHANGES / COMMENT
        body: Review 正文 (Markdown)
        comments: inline comments 列表 [{path, line, body}]
        head_sha: PR 的 head commit SHA

    Returns:
        {"status": "ok"} 或 {"status": "error", "message": ...}
    """
    token = setup_gh_auth()
    if not token:
        return {"status": "error", "message": "No GitHub auth available"}

    import urllib.request
    review_data = {
        "commit_id": head_sha if head_sha else None,
        "event": verdict,
        "body": body,
        "comments": comments,
    }

    # 过滤掉空的 commit_id
    if not review_data["commit_id"]:
        del review_data["commit_id"]

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews",
            data=json.dumps(review_data).encode("utf-8"),
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github.v3+json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
            logger.info(f"Review 已提交: id={response_data.get('id')}")
            return {"status": "ok", "review_id": response_data.get("id")}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        logger.error(f"提交 Review 失败: {e.code} {error_body[:300]}")
        return {"status": "error", "code": e.code, "message": error_body[:300]}
    except Exception as e:
        logger.error(f"提交 Review 异常: {e}")
        return {"status": "error", "message": str(e)}


def run_pr_review(
    repo_url: str,
    pr_number: int,
    repo_full_name: str = "",
    head_sha: str = "",
    base_ref: str = "main",
) -> dict:
    """完整 PR Review 流程：获取 diff → 审查 → 提交 Review。

    Args:
        repo_url: Git clone URL
        pr_number: PR 编号
        repo_full_name: "owner/repo"（可选，自动推断）
        head_sha: PR head commit SHA（可选，用于 inline review）
        base_ref: 基准分支（默认 main）

    Returns:
        {"status": "...", "summary": "...", "verdict": "...", ...}
    """
    if not repo_full_name:
        parts = repo_url.rstrip(".git").split("/")
        repo_full_name = "/".join(parts[-2:]) if len(parts) >= 2 else ""

    with tempfile.TemporaryDirectory(prefix="laap-pr-") as work_dir:
        logger.info(f"获取 PR #{pr_number} diff...")
        diff_text = get_diff_from_pr(repo_url, pr_number, work_dir)

        if not diff_text:
            return {"status": "error", "message": "无法获取 PR diff"}

        logger.info(f"Diff 获取成功 ({len(diff_text)} bytes)，开始审查...")
        engine = PRReviewEngine()
        review_result = engine.review(diff_text, repo_path=os.path.join(work_dir, repo_url.rstrip(".git").split("/")[-1]))

        # 格式化为 Markdown
        body = PRReviewEngine.format_review_markdown(review_result)
        inline_comments = PRReviewEngine.build_inline_comments(review_result)
        verdict = review_result["verdict"]

        logger.info(f"审查完成: {review_result['summary']} → {verdict}")

        # 提交给 GitHub
        submit_result = submit_review(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            verdict=verdict,
            body=body,
            comments=inline_comments,
            head_sha=head_sha,
        )

        return {
            "status": submit_result.get("status", "completed"),
            "summary": review_result["summary"],
            "verdict": verdict,
            "findings_count": len(review_result["findings"]),
            "inline_comments": len(inline_comments),
            "review_submitted": submit_result.get("status") == "ok",
            "review_id": submit_result.get("review_id"),
        }
