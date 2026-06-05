#!/usr/bin/env python3
"""
Diagnose why mirroring failed for repos listed in results.json.

For each failed repo, runs basic checks to determine the likely reason
and enriches results.json with diagnostic information.

Usage:
    python diagnose_failures.py results.json --src-token TOKEN --dst-token TOKEN
"""

import argparse
import json
import os
import subprocess
import sys

import requests


def git_ls_remote(url: str, timeout: int = 30) -> str | None:
    """Try git ls-remote; returns error message on failure, None on success."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", url],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return result.stderr.strip() or f"git ls-remote exited with code {result.returncode}"
        return None  # success
    except subprocess.TimeoutExpired:
        return f"git ls-remote timed out after {timeout}s"
    except FileNotFoundError:
        return "git not found"
    except Exception as e:
        return str(e)


def check_api_repo(session: requests.Session, platform_type: str, account: str,
                   account_type: str, repo_name: str, token: str = "",
                   timeout: int = 30) -> str | None:
    """Try to fetch repo info via API; returns error message, None if accessible."""
    api_bases = {
        "github": "https://api.github.com",
        "gitee": "https://gitee.com/api/v5",
        "gitcode": "https://api.gitcode.com/api/v5",
        "gitlab": "https://gitlab.com/api/v4",
    }
    api_base = api_bases.get(platform_type)
    if not api_base:
        return f"Unknown platform: {platform_type}"

    if platform_type == "gitlab":
        url = f"{api_base}/projects/{account}%2F{repo_name}"
    else:
        url = f"{api_base}/repos/{account}/{repo_name}"

    params = {}
    headers = {}
    if token:
        if platform_type == "github":
            headers["Authorization"] = f"token {token}"
        elif platform_type == "gitlab":
            headers["PRIVATE-TOKEN"] = token
        elif platform_type in ("gitee", "gitcode"):
            params["access_token"] = token

    try:
        resp = session.get(url, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 200:
            # Check size
            data = resp.json()
            size_kb = data.get("size", 0)
            if isinstance(size_kb, (int, float)) and size_kb > 500000:
                return f"Repo is very large ({size_kb // 1000}MB) — may have timed out"
            return None  # accessible
        elif resp.status_code == 404:
            return "Source repo not found or not accessible with current token"
        elif resp.status_code == 401:
            return "Authentication failed — token may be expired or missing scope"
        elif resp.status_code == 403:
            return "API rate limit exceeded"
        else:
            return f"API returned HTTP {resp.status_code}"
    except requests.Timeout:
        return f"API request timed out after {timeout}s"
    except requests.ConnectionError:
        return "Network error — cannot connect to API"
    except Exception as e:
        return str(e)


def main():
    parser = argparse.ArgumentParser(description="Diagnose mirror failures")
    parser.add_argument("results_file", help="Path to results.json")
    parser.add_argument("--src", default="", help="Source platform/account, e.g. gitcode/lei0308")
    parser.add_argument("--dst", default="", help="Destination platform/account, e.g. github/huanglei0308")
    parser.add_argument("--src-token", default="", help="Source API token")
    parser.add_argument("--dst-token", default="", help="Destination API token")
    parser.add_argument("--account-type", default="user", help="Account type")
    parser.add_argument("--timeout", type=int, default=30, help="Check timeout in seconds")
    args = parser.parse_args()

    with open(args.results_file) as f:
        data = json.load(f)

    failed_list = data.get("failed_list", [])
    if not failed_list:
        print("No failed repos to diagnose")
        return

    # Parse src/dst
    src_type, src_account = "", ""
    dst_type, dst_account = "", ""
    if args.src and "/" in args.src:
        src_type, src_account = args.src.split("/", 1)
    if args.dst and "/" in args.dst:
        dst_type, dst_account = args.dst.split("/", 1)

    session = requests.Session()
    diagnoses = {}

    for repo in failed_list:
        reasons = []
        print(f"\nDiagnosing {repo}...")

        # 1. Check if source repo exists / is accessible
        if src_type and src_account:
            src_err = check_api_repo(
                session, src_type, src_account, args.account_type, repo,
                token=args.src_token, timeout=args.timeout,
            )
            if src_err:
                reasons.append(f"Source: {src_err}")
            else:
                reasons.append("Source: accessible")

        # 2. Check if destination repo exists
        if dst_type and dst_account:
            dst_err = check_api_repo(
                session, dst_type, dst_account, args.account_type, repo,
                token=args.dst_token, timeout=args.timeout,
            )
            if dst_err:
                reasons.append(f"Destination: {dst_err}")
            else:
                reasons.append("Destination: exists")

        # 3. Check cached repo (if hub-mirror cached it)
        cache_path = os.path.join("hub-mirror-cache", repo)
        if os.path.isdir(cache_path):
            reasons.append("Cached: local copy exists")
            # Check if it's a valid git repo
            if os.path.isdir(os.path.join(cache_path, ".git")):
                reasons.append("Cached: valid git repo")
        else:
            reasons.append("Cached: not found (download may have failed)")

        diagnoses[repo] = reasons
        for r in reasons:
            print(f"  - {r}")

    # Enrich results.json
    data["diagnoses"] = diagnoses

    with open(args.results_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nDiagnoses written to {args.results_file}")


if __name__ == "__main__":
    main()
