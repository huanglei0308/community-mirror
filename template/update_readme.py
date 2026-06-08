"""Update README.md with detailed sync status from results.json.

Copy this file to your sync-config repo root alongside the workflow.
The workflow will call mirror_repos.py which generates results.json
natively — no separate check step needed.
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
errors = data.get("errors", {})
diagnoses = data.get("diagnoses", {})

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

if failed_list:
    md += "### ❌ Failed Repos\n\n"
    for r in failed_list:
        md += f"- `{r}`\n"
        if r in errors:
            md += f"  - {errors[r][:200]}\n"
        if r in diagnoses:
            for d in diagnoses[r]:
                md += f"  - {d}\n"
        md += "\n"

    repo = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
    md += f"[🔍 View workflow logs](https://github.com/{repo}/actions)\n\n"

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
