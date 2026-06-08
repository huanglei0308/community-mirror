#!/usr/bin/env python3
"""
Snapshot destination repos before mirror run so we can later distinguish
"newly synced" from "already existed" repos.

Usage:
    python snapshot_dst.py \
        --dst github/openeuler-mirror \
        --dst-token "$DST_TOKEN" \
        --account-type org \
        --output pre_dst.json
"""

import argparse
import json
from typing import Dict, List

import requests

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
        resp = session.get(api_url, headers=headers, params=params, timeout=api_timeout)
        if resp.status_code != 200:
            print(f"::warning::API returned {resp.status_code} for page {page}: {resp.text[:200]}")
            return []
        items = resp.json()
        if not items:
            return []
        field = "path" if platform_type == "gitlab" else "name"
        names = [item[field] for item in items if isinstance(item, dict) and field in item]
        print(f"  Page {page}: {len(names)} repos (total so far: ...)")
        return names + _get_all_repo_names(
            session, api_url, platform_type, token, api_timeout,
            page=page + 1, per_page=per_page,
        )
    except requests.RequestException as e:
        print(f"::warning::API request failed for page {page}: {e}")
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot destination repos")
    parser.add_argument("--dst", required=True, help="Destination, e.g. github/openeuler-mirror")
    parser.add_argument("--dst-token", required=True, help="API token for destination")
    parser.add_argument("--account-type", default="user", help="Account type (user/org/group)")
    parser.add_argument("--api-timeout", type=int, default=60)
    parser.add_argument("--output", default="pre_dst.json")

    args = parser.parse_args()

    dst_type, dst_account = args.dst.split("/", 1)
    cfg = PLATFORM_CONFIG[dst_type]

    print(f"Snapshotting destination: {args.dst} ...")
    session = requests.Session()

    if dst_type == "gitlab":
        if args.account_type == "group":
            headers = {"PRIVATE-TOKEN": args.dst_token} if args.dst_token else {}
            resp = session.get(f"{cfg['api_base']}/groups", headers=headers, timeout=args.api_timeout)
            group_id = None
            if resp.status_code == 200:
                for g in resp.json():
                    if g.get("path") == dst_account:
                        group_id = g.get("id")
                        break
            if group_id:
                url = f"{cfg['api_base']}/groups/{group_id}/projects"
                repos = _get_all_repo_names(session, url, dst_type, args.dst_token, args.api_timeout)
            else:
                repos = []
        else:
            url = f"{cfg['api_base']}/users/{dst_account}/projects"
            repos = _get_all_repo_names(session, url, dst_type, args.dst_token, args.api_timeout)
    else:
        url = f"{cfg['api_base']}/{args.account_type}s/{dst_account}/{cfg['repo_field']}"
        repos = _get_all_repo_names(session, url, dst_type, args.dst_token, args.api_timeout)

    print(f"Found {len(repos)} repos on destination")

    with open(args.output, "w") as f:
        json.dump(sorted(repos), f)
    print(f"Snapshot saved to {args.output}")


if __name__ == "__main__":
    main()
