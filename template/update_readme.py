"""Update README.md with detailed sync status from results.json.

Copy this file to your sync-config repo root alongside the workflow.
The workflow will call it after check_sync_status.py generates results.json.
"""

import json
import os
import re

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
diagnoses = data.get("diagnoses", {})

batch_failed_count = data.get("batch_failed_count", 0)

if failed > 0:
    overall = f"⚠️ **{failed} repo(s) failed**"
elif batch_failed_count > 0:
    overall = f"⚠️ **{batch_failed_count} repo(s) push failed** (HEAD mismatch)"
else:
    overall = "✅ All repos synced successfully"

md = f"""**Last updated:** {ts}
**Flow:** `{src}` → `{dst}`
**Status:** {overall}

| Total | ✅ Synced | ❌ Failed | ⏭️ Skipped |
| ---: | ---: | ---: | ---: |
| {total} | {success} | {failed} | {skipped} |

"""

if failed_list:
    md += "### ❌ Failed Repos\n\n"
    for r in failed_list:
        md += f"- `{r}`\n"
        if r in diagnoses:
            for d in diagnoses[r]:
                md += f"  - {d}\n"
        md += "\n"

    # Link to Actions — derive from GITHUB_REPOSITORY env var
    repo = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
    md += f"[🔍 View workflow logs](https://github.com/{repo}/actions)\n\n"

if batch_failed_count > 0:
    batch_failed_list = data.get("batch_failed_list", [])
    md += f"### ❌ Push Failed (HEAD mismatch)\n\n"
    for r in batch_failed_list:
        md += f"- `{r}`\n"
        if r in diagnoses:
            for d in diagnoses[r]:
                md += f"  - {d}\n"
        md += "\n"
    md += f"[🔍 View workflow logs](https://github.com/{repo}/actions) for details.\n\n"

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

with open("README.md") as f:
    readme = f.read()

pattern = r"(<!-- SYNC_STATUS_START -->).*?(<!-- SYNC_STATUS_END -->)"
replacement = r"\1\n" + md + r"\n\2"
new_readme = re.sub(pattern, replacement, readme, flags=re.DOTALL)

with open("README.md", "w") as f:
    f.write(new_readme)

print("README.md updated with detailed sync status")
