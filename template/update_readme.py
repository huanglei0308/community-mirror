"""Update README.md with detailed sync status from results.json.

Displays a category-based failure summary (readable labels, not raw logs)
followed by per-repo error details for diagnosis.
"""

import json
import os
import re
from collections import Counter

with open("results.json") as f:
    data = json.load(f)

failed = data.get("failed", 0)
failed_list = data.get("failed_list", [])
success = data.get("success", 0)
success_list = data.get("success_list", [])
skipped = data.get("skipped", 0)
skipped_list = data.get("skipped_list", [])
total = data.get("total", 0)
ts = data.get("timestamp", "N/A")
src = data.get("src", "")
dst = data.get("dst", "")
errors = data.get("errors", {})
diagnoses = data.get("diagnoses", {})

# ── Human-readable category labels ──
CATEGORY_LABELS = {
    "large_file":       "🔵 File Too Large (>100MB)",
    "push_protection":  "🛡️ Push Protection Blocked",
    "hook_declined":    "🔒 Pre-receive Hook Declined",
    "branch_delete":    "🚫 Branch Delete Refused",
    "rate_limited":     "⏳ GitHub Rate Limited",
    "repo_not_found":   "❓ Source Repo Not Found",
    "clone_failed":     "📥 Clone Failed",
    "push_failed":      "📤 Push Rejected",
    "timeout":          "⏱️ Operation Timed Out",
    "unknown":          "❔ Unclassified Error",
}

# ── Categorize failures ──
category_counts: Counter = Counter()
category_repos: dict = {}  # category -> [repo_names]
uncategorized = []  # repos with plain-string errors (backward compat)

for r in failed_list:
    err = errors.get(r, {})
    if isinstance(err, dict) and "category" in err:
        cat = err["category"]
        category_counts[cat] += 1
        category_repos.setdefault(cat, []).append(r)
    else:
        uncategorized.append(r)

# ── Overall status ──
if failed > 0:
    overall = f"⚠️ **{failed} repo(s) failed**"
else:
    overall = "✅ All repos synced successfully"

md = f"""**Last updated:** {ts}
**Flow:** `{src}` → `{dst}`
**Status:** {overall}

| Total | ✅ Synced | ❌ Failed | ⏭️ Skipped |
| ---: | ---: | ---: | ---: |
| {total} | {success} | {failed} | {skipped} |

"""

# ── Hub detail page link ──
hub_community = os.environ.get("HUB_COMMUNITY", "")
if hub_community:
    from urllib.parse import quote
    hub_url = f"https://huanglei0308.github.io/community-mirror/community.html?org={quote(hub_community)}"
    md += f"📊 [查看详细同步状态（含失败原因诊断）]({hub_url})\n\n---\n\n"

# ── Failure summary by category ──
if category_counts:
    md += "### 📊 Failure Summary\n\n"
    md += "| Category | Count |\n|----------|------:|\n"
    for cat, count in category_counts.most_common():
        label = CATEGORY_LABELS.get(cat, cat)
        md += f"| {label} | {count} |\n"
    md += "\n"

# ── Per-repo failure details ──
if failed_list:
    md += "### ❌ Failed Repos\n\n"
    for r in failed_list:
        md += f"- **`{r}`**"
        err = errors.get(r, {})

        if isinstance(err, dict) and "message" in err:
            md += f" — {err['message']}"
            # Show raw detail for debugging (collapsed)
            raw_msg = err.get("message", "")
            if len(raw_msg) > 120:
                pass  # already concise, no need to expand
        elif isinstance(err, str) and err.strip():
            # Backward compat: plain string error
            md += f" — {err.strip()[:200]}"

        # Add diagnoses if available
        if r in diagnoses:
            diag = diagnoses[r]
            if isinstance(diag, list):
                for d in diag:
                    md += f"<br>🔍 {d}"
            elif isinstance(diag, str):
                md += f"<br>🔍 {diag}"

        md += "\n\n"

    repo = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
    md += f"[🔍 View workflow logs](https://github.com/{repo}/actions)\n\n"

# ── Skipped / Success (collapsed) ──
if skipped_list:
    md += "<details>\n<summary><b>⏭️ Skipped Repos ({})</b></summary>\n\n".format(len(skipped_list))
    for r in skipped_list:
        md += f"- `{r}`\n"
    md += "\n</details>\n\n"

if success_list:
    md += "<details>\n<summary><b>✅ Synced Repos ({})</b></summary>\n\n".format(len(success_list))
    for r in success_list[:200]:
        md += f"- `{r}`\n"
    if len(success_list) > 200:
        md += f"- ... and {len(success_list) - 200} more\n"
    md += "\n</details>\n\n"

# ── Write to README ──
with open("README.md") as f:
    readme = f.read()

pattern = r"(<!-- SYNC_STATUS_START -->).*?(<!-- SYNC_STATUS_END -->)"
replacement = r"\1\n" + md + r"\n\2"
new_readme = re.sub(pattern, replacement, readme, flags=re.DOTALL)

with open("README.md", "w") as f:
    f.write(new_readme)

print("README.md updated with detailed sync status")
