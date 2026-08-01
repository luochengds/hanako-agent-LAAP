#!/usr/bin/env python3
"""Push LAAP PR Review files to GitHub."""
import base64, json, os, sys, urllib.request

REPO = "lorryjovens-hub/LAAP-Living-Agent-Application-Protocol-"

# Get token
token = os.popen("gh auth token 2>/dev/null").read().strip() or os.environ.get("GITHUB_TOKEN", "")
if not token:
    print("No GitHub token found")
    sys.exit(1)

def gh_api(method, path, data=None):
    url = f"https://api.github.com/{path}"
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:200]}")
        return None

# Read files
with open(".github/workflows/pr-review.yml", "rb") as f:
    wf_content = base64.b64encode(f.read()).decode()
with open("laap/colony/pr_review_action.py", "rb") as f:
    rv_content = base64.b64encode(f.read()).decode()

# Get latest commit SHA
main_ref = gh_api("GET", f"repos/{REPO}/git/refs/heads/main")
if not main_ref:
    print("Failed to get main ref")
    sys.exit(1)
base_sha = main_ref["object"]["sha"]
print(f"Base SHA: {base_sha}")

# Create blobs
wf_blob = gh_api("POST", f"repos/{REPO}/git/blobs",
    json.dumps({"content": wf_content, "encoding": "base64"}).encode())
rv_blob = gh_api("POST", f"repos/{REPO}/git/blobs",
    json.dumps({"content": rv_content, "encoding": "base64"}).encode())
print(f"Blobs created: wf={wf_blob['sha'][:8]} rv={rv_blob['sha'][:8]}")

# Get base tree SHA
base_commit = gh_api("GET", f"repos/{REPO}/git/commits/{base_sha}")
base_tree_sha = base_commit["tree"]["sha"]
print(f"Base tree: {base_tree_sha}")

# Create tree with new files
tree_data = {
    "base_tree": base_tree_sha,
    "tree": [
        {"path": ".github/workflows/pr-review.yml", "mode": "100644", "type": "blob", "sha": wf_blob["sha"]},
        {"path": "laap/colony/pr_review_action.py", "mode": "100644", "type": "blob", "sha": rv_blob["sha"]},
    ]
}
new_tree = gh_api("POST", f"repos/{REPO}/git/trees",
    json.dumps(tree_data).encode())
if not new_tree:
    print("Tree creation failed, trying without base_tree...")
    tree_data.pop("base_tree")
    new_tree = gh_api("POST", f"repos/{REPO}/git/trees", json.dumps(tree_data).encode())

new_tree_sha = new_tree["sha"]
print(f"New tree: {new_tree_sha}")

# Create commit
commit = gh_api("POST", f"repos/{REPO}/git/commits",
    json.dumps({
        "message": "feat: add LAAP Colony PR Review workflow",
        "tree": new_tree_sha,
        "parents": [base_sha],
    }).encode())
commit_sha = commit["sha"]
print(f"Commit: {commit_sha}")

# Create branch ref
gh_api("POST", f"repos/{REPO}/git/refs",
    json.dumps({"ref": "refs/heads/feat/laap-pr-review", "sha": commit_sha}).encode())
print("Branch created: feat/laap-pr-review")

# Create PR
pr = gh_api("POST", f"repos/{REPO}/pulls",
    json.dumps({
        "title": "feat: add LAAP Colony PR Review workflow",
        "head": "feat/laap-pr-review",
        "base": "main",
        "body": "## LAAP Colony PR Review\n\nZero-token, zero-LLM PR review bot for LAAP repos.\n\n### Detects\n- Hardcoded secrets, API keys, passwords\n- SQL injection patterns\n- Merge conflict markers\n- Debug statements (print, console.log)\n- Large file changes\n- Missing documentation updates\n\n### Tech\n- Pure Python, zero dependencies\n- Zero LLM calls, zero token cost\n- Self-contained in `laap/colony/pr_review_action.py`\n- Runs as GitHub Actions workflow",
    }).encode())
if pr:
    print(f"\nPR created: {pr.get('html_url', '')}")
else:
    print("\nBranch created but PR creation failed. Create manually:")
    print("  https://github.com/lorryjovens-hub/LAAP-Living-Agent-Application-Protocol-/pull/new/feat/laap-pr-review")
