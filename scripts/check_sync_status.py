#!/usr/bin/env python3
"""
Independent sync status checker.

Queries source and destination platform APIs to compare repo lists and
determine which repos have been successfully mirrored.  Does NOT depend on
hub-mirror-action — it replicates the minimal API-calling logic so the
action itself does not need to be modified.

Usage:
    python check_sync_status.py \
        --src gitcode/openeuler \
        --dst github/openeuler-mirror \
        --src-token "$SRC_TOKEN" \
        --dst-token "$DST_TOKEN" \
        --account-type org \
        --black-list "repo1,repo2" \
        --static-list "" \
        --mappings "" \
        --output mirror-results.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

# ---------------------------------------------------------------------------
# Platform API helpers (minimal re-implementation of hub-mirror-action logic)
# ---------------------------------------------------------------------------

PLATFORM_CONFIG: Dict[str, Dict[str, str]] = {
    "github": {
        "host": "github.com",
        "api_base": "https://api.github.com",
        "repo_field": "repos",
    },
    "gitee": {
        "host": "gitee.com",
        "api_base": "https://gitee.com/api/v5",
        "repo_field": "repos",
    },
    "gitcode": {
        "host": "gitcode.com",
        "api_base": "https://api.gitcode.com/api/v5",
        "repo_field": "repos",
    },
    "gitlab": {
        "host": "gitlab.com",
        "api_base": "https://gitlab.com/api/v4",
        "repo_field": "projects",
    },
}

ACCOUNT_TYPES: Dict[str, Tuple[str, ...]] = {
    "github": ("user", "org"),
    "gitee": ("user", "org"),
    "gitcode": ("user", "org"),
    "gitlab": ("user", "group"),
}


def _get_all_repo_names(
    session: requests.Session,
    api_url: str,
    platform_type: str,
    token: str = "",
    api_timeout: int = 60,
    page: int = 1,
    per_page: int = 100,
) -> List[str]:
    """Paginate through a platform's repo-list endpoint."""
    params: Dict[str, str] = {"page": str(page), "per_page": str(per_page)}
    headers: Dict[str, str] = {}

    if token:
        if platform_type == "github":
            headers["Authorization"] = f"token {token}"
        elif platform_type == "gitlab":
            headers["PRIVATE-TOKEN"] = token
        elif platform_type in ("gitee", "gitcode"):
            params["access_token"] = token

    try:
        resp = session.get(
            api_url,
            headers=headers,
            params=params,
            timeout=api_timeout,
        )
        if resp.status_code != 200:
            print(f"::warning::API returned {resp.status_code} for {api_url}: {resp.text[:200]}")
            return []
        items = resp.json()
        if not items:
            return []
        # GitLab returns a list of projects with "path" (not "name")
        field = "path" if platform_type == "gitlab" else "name"
        names = [item[field] for item in items if isinstance(item, dict) and field in item]
        return names + _get_all_repo_names(
            session, api_url, platform_type, token, api_timeout,
            page=page + 1, per_page=per_page,
        )
    except requests.RequestException as e:
        print(f"::warning::API request failed for {api_url}: {e}")
        return []


def list_repos(
    session: requests.Session,
    platform_type: str,
    account: str,
    account_type: str,
    token: str = "",
    api_timeout: int = 60,
) -> List[str]:
    """Return the full list of repo names for a platform account."""
    cfg = PLATFORM_CONFIG.get(platform_type)
    if not cfg:
        raise ValueError(f"Unsupported platform: {platform_type}")

    if platform_type == "gitlab":
        # GitLab's group API is under /groups/{account}/projects
        if account_type == "group":
            # First get group ID
            headers = {"PRIVATE-TOKEN": token} if token else {}
            group_url = f"{cfg['api_base']}/groups"
            try:
                resp = session.get(group_url, headers=headers, timeout=api_timeout)
                group_id = None
                if resp.status_code == 200:
                    for g in resp.json():
                        if g.get("path") == account:
                            group_id = g.get("id")
                            break
                if group_id:
                    url = f"{cfg['api_base']}/groups/{group_id}/projects"
                    # Override the standard URL pattern
                    return _get_all_repo_names(
                        session, url, platform_type, token, api_timeout,
                    )
            except requests.RequestException:
                pass
            return []
        else:
            url = f"{cfg['api_base']}/users/{account}/projects"
            return _get_all_repo_names(session, url, platform_type, token, api_timeout)
    else:
        url = f"{cfg['api_base']}/{account_type}s/{account}/{cfg['repo_field']}"
        return _get_all_repo_names(session, url, platform_type, token, api_timeout)


# ---------------------------------------------------------------------------
# Status checking logic
# ---------------------------------------------------------------------------

def parse_list(value: str) -> List[str]:
    """Parse a comma-separated string into a list, stripping whitespace."""
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_mappings(value: str) -> Dict[str, str]:
    """Parse 'A=>B, C=>CC' into a dict."""
    result: Dict[str, str] = {}
    if not value or not value.strip():
        return result
    for pair in value.split(","):
        pair = pair.strip()
        if "=>" in pair:
            src, dst = pair.split("=>", 1)
            result[src.strip()] = dst.strip()
    return result


def check_status(args: argparse.Namespace) -> Dict:
    """Main status-check logic.  Returns a JSON-serializable dict."""
    session = requests.Session()

    src_type, src_account = args.src.split("/", 1)
    dst_type, dst_account = args.dst.split("/", 1)

    src_account_type = args.src_account_type or args.account_type
    dst_account_type = args.dst_account_type or args.account_type

    # --- Get source repo list ---
    static_list = parse_list(args.static_list)
    if static_list:
        src_repos = static_list
        print(f"Using static list ({len(src_repos)} repos)")
    else:
        print(f"Fetching source repos from {args.src} ...")
        src_repos = list_repos(
            session, src_type, src_account, src_account_type,
            token=args.src_token, api_timeout=args.api_timeout,
        )
        print(f"Found {len(src_repos)} source repos")

    # --- Get destination repo list ---
    print(f"Fetching destination repos from {args.dst} ...")
    dst_repos = list_repos(
        session, dst_type, dst_account, dst_account_type,
        token=args.dst_token, api_timeout=args.api_timeout,
    )
    dst_repo_set = set(dst_repos)
    print(f"Found {len(dst_repos)} destination repos")

    # --- Apply filters ---
    black_list = parse_list(args.black_list)
    white_list = parse_list(args.white_list)
    mappings = parse_mappings(args.mappings)

    success_list: List[str] = []
    failed_list: List[str] = []
    skipped_list: List[str] = []

    for src_repo in src_repos:
        # Apply black list
        if src_repo in black_list:
            skipped_list.append(src_repo)
            continue
        # Apply white list
        if white_list and src_repo not in white_list:
            skipped_list.append(src_repo)
            continue
        # Apply name mapping
        dst_repo = mappings.get(src_repo, src_repo)
        # Check if destination exists
        if dst_repo in dst_repo_set:
            success_list.append(src_repo)
        else:
            failed_list.append(src_repo)

    total = len(src_repos)
    skipped = len(skipped_list)
    success = len(success_list)
    failed = len(failed_list)

    result = {
        "src": args.src,
        "dst": args.dst,
        "workflow": args.workflow_name or "unknown",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": total,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "success_list": success_list,
        "failed_list": failed_list,
        "skipped_list": skipped_list,
    }

    # Print summary
    print(f"\n{'='*50}")
    print(f"Sync Status Summary for {args.workflow_name or args.src}")
    print(f"  Total:   {total}")
    print(f"  Success: {success}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")
    if failed_list:
        print(f"  Failed repos: {', '.join(failed_list)}")
    print(f"{'='*50}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check sync status between two platforms"
    )
    parser.add_argument("--src", required=True, help="Source, e.g. gitcode/openeuler")
    parser.add_argument("--dst", required=True, help="Destination, e.g. github/openeuler-mirror")
    parser.add_argument("--src-token", default="", help="API token for source platform")
    parser.add_argument("--dst-token", required=True, help="API token for destination platform")
    parser.add_argument("--account-type", default="user", help="Account type (user/org/group)")
    parser.add_argument("--src-account-type", default="", help="Source account type override")
    parser.add_argument("--dst-account-type", default="", help="Destination account type override")
    parser.add_argument("--black-list", default="", help="Comma-separated blacklist")
    parser.add_argument("--white-list", default="", help="Comma-separated whitelist")
    parser.add_argument("--static-list", default="", help="Comma-separated static repo list")
    parser.add_argument("--mappings", default="", help="Repo name mappings, e.g. A=>B,C=>CC")
    parser.add_argument("--api-timeout", type=int, default=60, help="API timeout in seconds")
    parser.add_argument("--output", default="mirror-results.json", help="Output JSON file path")
    parser.add_argument("--workflow-name", default="", help="Workflow name for labeling")

    args = parser.parse_args()

    result = check_status(args)

    # Write JSON output
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {output_path}")

    # Set GitHub Actions output if running in a workflow
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"total={result['total']}\n")
            f.write(f"success={result['success']}\n")
            f.write(f"skipped={result['skipped']}\n")
            f.write(f"failed={result['failed']}\n")
            f.write(f"failed-list={','.join(result['failed_list'])}\n")
            f.write(f"results-file={output_path}\n")

    # Exit with error if there are failures
    if result["failed"] > 0:
        print(f"\n::error::{result['failed']} repos failed to sync")
        sys.exit(1)


if __name__ == "__main__":
    main()
