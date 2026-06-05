#!/usr/bin/env python3
"""
Merge the current workflow's results.json with the existing results.json
already deployed on gh-pages.

This prevents multiple workflows (main mirror, large-repo mirror,
high-priority mirror) from overwriting each other's status data.

Logic:
  1. Download existing results.json from the gh-pages URL
  2. For each repo in the CURRENT results: update/override its status
  3. For repos ONLY in the existing results: keep them untouched
  4. Recalculate totals
  5. Keep per-workflow timestamps for debugging

Usage:
    python merge_results.py results.json \
        --merge-url https://my-org.github.io/sync-config/results.json \
        --output results.json
"""

import argparse
import json
import sys
from typing import Dict, Optional

import requests


def download_existing(url: str, timeout: int = 30) -> Optional[dict]:
    """Download existing results.json from gh-pages.  Returns None on failure."""
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"::warning::Existing results returned HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"::warning::Could not download existing results: {e}")
        return None


def merge(existing: dict, current: dict) -> dict:
    """Merge *current* into *existing* — current repo statuses take precedence."""

    # 1. Build a flat map: repo_name -> "success"|"failed"|"skipped"
    repo_status: Dict[str, str] = {}
    for status in ("success", "failed", "skipped"):
        for repo in existing.get(f"{status}_list", []):
            repo_status[repo] = status

    # 2. Override with current workflow's results
    for status in ("success", "failed", "skipped"):
        for repo in current.get(f"{status}_list", []):
            repo_status[repo] = status

    # 3. Merge diagnoses (current overrides for same repos)
    merged_diagnoses = dict(existing.get("diagnoses", {}))
    merged_diagnoses.update(current.get("diagnoses", {}))
    # Drop diagnoses for repos that are now successful
    for repo in list(merged_diagnoses.keys()):
        if repo_status.get(repo) == "success":
            del merged_diagnoses[repo]

    # 4. Rebuild sorted lists
    success_list = sorted(r for r, s in repo_status.items() if s == "success")
    failed_list = sorted(r for r, s in repo_status.items() if s == "failed")
    skipped_list = sorted(r for r, s in repo_status.items() if s == "skipped")

    # 5. Per-workflow metadata (for debugging)
    merged_workflows = dict(existing.get("workflows", {}))
    wf_name = current.get("workflow", "unknown")
    merged_workflows[wf_name] = {
        "timestamp": current.get("timestamp", ""),
        "total": current.get("total", 0),
        "success": current.get("success", 0),
        "failed": current.get("failed", 0),
        "skipped": current.get("skipped", 0),
    }

    # 6. Pick latest timestamp across all workflows
    timestamps = [current.get("timestamp", "")]
    if existing.get("timestamp"):
        timestamps.append(existing["timestamp"])
    for wf in merged_workflows.values():
        if wf.get("timestamp"):
            timestamps.append(wf["timestamp"])
    latest_ts = max(t for t in timestamps if t)

    merged = {
        "src": current.get("src", existing.get("src", "")),
        "dst": current.get("dst", existing.get("dst", "")),
        "workflow": wf_name,
        "timestamp": latest_ts,
        "total": len(repo_status),
        "success": len(success_list),
        "skipped": len(skipped_list),
        "failed": len(failed_list),
        "success_list": success_list,
        "failed_list": failed_list,
        "skipped_list": skipped_list,
        "diagnoses": merged_diagnoses,
        "workflows": merged_workflows,
    }

    # Summary
    old_total = existing.get("total", 0)
    print(f"Merged: total={merged['total']} (was {old_total})  "
          f"success={merged['success']}  failed={merged['failed']}  "
          f"skipped={merged['skipped']}")
    print(f"Contributing workflows: {list(merged_workflows.keys())}")

    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge results.json with existing gh-pages deployment"
    )
    parser.add_argument(
        "results_file", help="Current workflow's results.json to merge from"
    )
    parser.add_argument(
        "--merge-url", default="",
        help="URL of the existing results.json on gh-pages"
    )
    parser.add_argument(
        "--output", default="results.json",
        help="Output path for the merged JSON (default: results.json)"
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="HTTP timeout for downloading existing results (default: 30s)"
    )
    args = parser.parse_args()

    # Load current results
    with open(args.results_file) as f:
        current = json.load(f)

    if args.merge_url:
        existing = download_existing(args.merge_url, args.timeout)
        if existing is not None:
            merged = merge(existing, current)
        else:
            print("::warning::No existing results to merge — deploying current as-is")
            merged = current
    else:
        merged = current

    with open(args.output, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
