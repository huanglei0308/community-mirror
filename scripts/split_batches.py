#!/usr/bin/env python3
"""
Fetch repo list from a source platform and split into batches for parallel
mirroring via GitHub Actions matrix strategy.

Usage:
    python split_batches.py \
        --src gitcode/openeuler \
        --src-token "$SRC_TOKEN" \
        --account-type org \
        --black-list "kernel,qemu" \
        --batch-size 80

Outputs a JSON array of comma-separated repo-name strings, one per batch:

    ["repo1,repo2,...,repo80", "repo81,...,repo160", ...]

Also writes the JSON to --output file (default: batches.json) and sets the
GITHUB_OUTPUT variable ``batches`` for use in a GitHub Actions matrix.
"""

import argparse
import json
import os
import sys
from typing import Dict, List

import requests

# ---------------------------------------------------------------------------
# Platform API helpers (mirrors check_sync_status.py — kept self-contained)
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
            api_url, headers=headers, params=params, timeout=api_timeout,
        )
        if resp.status_code != 200:
            print(f"::warning::API returned {resp.status_code} for {api_url}: {resp.text[:200]}")
            return []
        items = resp.json()
        if not items:
            return []
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
        if account_type == "group":
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
                    return _get_all_repo_names(session, url, platform_type, token, api_timeout)
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
# Batch splitting
# ---------------------------------------------------------------------------

def parse_list(value: str) -> List[str]:
    """Parse a comma-separated string into a list, stripping whitespace."""
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def split_into_batches(items: List[str], batch_size: int) -> List[str]:
    """Split a list of repo names into batches, each a comma-separated string."""
    batches = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        batches.append(",".join(batch))
    return batches


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch repo list and split into batches for matrix workflows"
    )
    parser.add_argument("--src", required=True, help="Source, e.g. gitcode/openeuler")
    parser.add_argument("--src-token", default="", help="API token for source platform")
    parser.add_argument("--account-type", default="user", help="Account type (user/org/group)")
    parser.add_argument("--black-list", default="", help="Comma-separated repos to exclude")
    parser.add_argument("--batch-size", type=int, default=80, help="Repos per batch (default: 80)")
    parser.add_argument("--api-timeout", type=int, default=60, help="API timeout in seconds")
    parser.add_argument("--output", default="batches.json", help="Output JSON file path")

    args = parser.parse_args()

    src_type, src_account = args.src.split("/", 1)
    black_list = parse_list(args.black_list)

    # --- Fetch repos ---
    print(f"Fetching repos from {args.src} ...")
    session = requests.Session()
    all_repos = list_repos(
        session, src_type, src_account, args.account_type,
        token=args.src_token, api_timeout=args.api_timeout,
    )
    print(f"Found {len(all_repos)} total repos")

    if not all_repos:
        print("::error::No repos found — check token and account type")
        sys.exit(1)

    # --- Filter ---
    black_set = set(black_list)
    filtered = [r for r in all_repos if r not in black_set]
    if black_list:
        print(f"After black_list filter: {len(filtered)} repos "
              f"(removed {len(all_repos) - len(filtered)})")

    # --- Split ---
    batches = split_into_batches(filtered, args.batch_size)
    batch_sizes = [len(b.split(",")) for b in batches]
    print(f"Split into {len(batches)} batches: {batch_sizes}")

    # --- Output ---
    with open(args.output, "w") as f:
        json.dump(batches, f)
    print(f"Batches written to {args.output}")

    # Also set GITHUB_OUTPUT for workflow matrix
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"batches={json.dumps(batches)}\n")
        print("GITHUB_OUTPUT set")


if __name__ == "__main__":
    main()
