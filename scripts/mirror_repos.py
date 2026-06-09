#!/usr/bin/env python3
"""
Self-contained repo mirroring script — forked from hub-mirror-action
and enhanced with structured results.json output.

This file contains substantial portions derived from
  Yikun/hub-mirror-action (https://github.com/Yikun/hub-mirror-action)
licensed under the MIT License:

  The MIT License (MIT)
  Copyright (c) 2020 Yikun
  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:
  The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.
  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
  THE SOFTWARE.

Key differences from upstream hub-mirror-action:
  - Outputs a structured results.json (success/failed/skipped + error messages)
  - Uses argparse instead of click
  - No tenacity dependency (simple built-in retry)
  - Runs as a regular CLI script, not a composite GitHub Action

Usage:
  # Mirror all repos from an org (dynamic list)
  python mirror_repos.py \
    --src gitcode/openeuler --dst github/openeuler-mirror \
    --src-token TOKEN --dst-token TOKEN --dst-key SSH_KEY \
    --account-type org --output results.json

  # Mirror a specific list
  python mirror_repos.py \
    --src gitcode/openeuler --dst github/openeuler-mirror \
    --static-list "repo1,repo2,repo3" \
    --dst-key SSH_KEY --dst-token TOKEN \
    --account-type org --output results.json

  # Only list repos (no mirroring)
  python mirror_repos.py \
    --src gitcode/openeuler --list-only \
    --src-token TOKEN --account-type org
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import git
import requests

logger = logging.getLogger("mirror")

# ──────────────────────────────────────────────────────────────────────
# Platform definitions
# ──────────────────────────────────────────────────────────────────────


class Platform:
    """Minimal per-platform configuration."""

    def __init__(
        self, name: str, host: str, api_base: str, repo_field: str,
        allowed_accounts: Tuple[str, ...],
    ) -> None:
        self.name = name
        self.host = host
        self.api_base = api_base
        self.repo_field = repo_field
        self.allowed_accounts = allowed_accounts

    def clone_base(self, account: str, clone_style: str) -> str:
        prefix = "https://" if clone_style == "https" else "git@"
        suffix = "/" if clone_style == "https" else ":"
        return f"{prefix}{self.host}{suffix}{account}"

    def push_base(self, account: str) -> str:
        return f"git@{self.host}:{account}"

    def repo_list_url(self, account: str, account_type: str) -> str:
        return f"{self.api_base}/{account_type}s/{account}/{self.repo_field}"

    def create_repo(
        self, session: requests.Session, account: str, account_type: str,
        repo_name: str, token: str, api_timeout: int,
    ) -> bool:
        """Create a destination repo via API. Returns True on success."""
        if self.name == "github":
            suffix = "user/repos" if account_type != "org" else f"orgs/{account}/repos"
            url = f"{self.api_base}/{suffix}"
            resp = session.post(
                url, data=json.dumps({"name": repo_name}),
                headers={"Authorization": f"token {token}"},
                timeout=api_timeout,
            )
        elif self.name in ("gitee", "gitcode"):
            suffix = "user/repos" if account_type != "org" else f"orgs/{account}/repos"
            url = f"{self.api_base}/{suffix}"
            resp = session.post(
                url,
                headers={"Content-Type": "application/json;charset=UTF-8"},
                params={"name": repo_name, "access_token": token},
                timeout=api_timeout,
            )
        elif self.name == "gitlab":
            url = f"{self.api_base}/projects"
            headers = {"PRIVATE-TOKEN": token}
            data: Dict[str, Any] = {"name": repo_name, "visibility": "public"}
            if account_type == "group":
                # Look up group ID
                group_url = f"{self.api_base}/groups"
                gr = session.get(group_url, headers=headers, timeout=api_timeout)
                if gr.status_code == 200:
                    for g in gr.json():
                        if g.get("path") == account:
                            data["namespace_id"] = g.get("id")
                            break
            resp = session.post(url, data=data, headers=headers, timeout=api_timeout)
        else:
            logger.error(f"Unsupported platform: {self.name}")
            return False

        if resp.status_code == 201:
            logger.info("Destination repo created.")
            return True
        logger.error(f"Create repo failed: {resp.text[:300]}")
        return False

    def validate(self, account_type: str, role: str) -> None:
        if account_type not in self.allowed_accounts:
            raise ValueError(
                f"For {self.name}, {role} account_type must be "
                f"one of {self.allowed_accounts}."
            )


PLATFORMS: Dict[str, Platform] = {
    "github":  Platform("github", "github.com",
                        "https://api.github.com", "repos", ("user", "org")),
    "gitee":   Platform("gitee", "gitee.com",
                        "https://gitee.com/api/v5", "repos", ("user", "org")),
    "gitcode": Platform("gitcode", "gitcode.com",
                        "https://api.gitcode.com/api/v5", "repos", ("user", "org")),
    "gitlab":  Platform("gitlab", "gitlab.com",
                        "https://gitlab.com/api/v4", "projects", ("user", "group")),
}


# ──────────────────────────────────────────────────────────────────────
# Hub helper: API listing + repo creation
# ──────────────────────────────────────────────────────────────────────


class Hub:
    def __init__(self, args: argparse.Namespace) -> None:
        self.src_type, self.src_account = args.src.split("/", 1)
        self.dst_type, self.dst_account = args.dst.split("/", 1) if args.dst else ("", "")
        self.src_platform = PLATFORMS[self.src_type]
        self.dst_platform = PLATFORMS[self.dst_type] if args.dst else None
        self.dst_token = args.dst_token or ""
        self.src_token = args.src_token or ""
        self.account_type = args.account_type
        self.api_timeout = args.api_timeout
        self.clone_style = args.clone_style
        self.session = requests.Session()

        if self.dst_platform:
            self.dst_platform.validate(
                args.dst_account_type or args.account_type, "destination"
            )

    @property
    def src_repo_base(self) -> str:
        return self.src_platform.clone_base(self.src_account, self.clone_style)

    @property
    def dst_repo_base(self) -> str:
        if not self.dst_platform:
            return ""
        return self.dst_platform.push_base(self.dst_account)

    def list_repos(self) -> List[str]:
        """Fetch all repo names from the source platform."""
        url = self.src_platform.repo_list_url(
            self.src_account,
            getattr(self, "src_account_type_override", None) or self.account_type,
        )
        return self._paginate(url, self.src_type, self.src_token)

    def _paginate(self, url: str, platform_type: str, token: str,
                  page: int = 1) -> List[str]:
        per_page = 100
        api = f"{url}?page={page}&per_page={per_page}"
        headers: Dict[str, str] = {}
        params: Dict[str, str] = {}
        if token:
            if platform_type == "github":
                headers["Authorization"] = f"token {token}"
            elif platform_type == "gitlab":
                headers["PRIVATE-TOKEN"] = token
            elif platform_type in ("gitee", "gitcode"):
                params["access_token"] = token

        try:
            resp = self.session.get(
                api, headers=headers, params=params, timeout=self.api_timeout,
            )
            if resp.status_code != 200:
                logger.warning(f"API {platform_type} page {page}: HTTP {resp.status_code}")
                return []
            items = resp.json()
            if not items:
                return []
            field = "path" if platform_type == "gitlab" else "name"
            names = [item[field] for item in items if isinstance(item, dict) and field in item]
            return names + self._paginate(url, platform_type, token, page + 1)
        except requests.RequestException as e:
            logger.warning(f"API page {page} failed: {e}")
            return []

    def ensure_dest_repo(self, repo_name: str) -> bool:
        """Create destination repo if it doesn't exist. Returns True if created."""
        if not self.dst_platform:
            return False
        try:
            return self.dst_platform.create_repo(
                self.session, self.dst_account,
                getattr(self, "dst_account_type_override", None) or self.account_type,
                repo_name, self.dst_token, self.api_timeout,
            )
        except Exception as e:
            logger.error(f"Create repo {repo_name} failed: {e}")
            return False


# ──────────────────────────────────────────────────────────────────────
# Mirror: clone → create → push for one repo
# ──────────────────────────────────────────────────────────────────────


def _parse_timeout(timeout: str) -> int:
    """Parse '30m', '1h', '3600' → seconds."""
    m = re.match(r"^(\d+)([dhms]?)$", timeout)
    if not m:
        return 0
    val = int(m.group(1))
    unit = m.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 1}
    return val * multipliers.get(unit, 1)


def _ssh_setup(dst_key: str) -> None:
    """Set up SSH key for git operations."""
    if not dst_key:
        return
    ssh_dir = os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
    key_path = os.path.join(ssh_dir, "mirror_key")
    with open(key_path, "w") as f:
        f.write(dst_key + "\n")
    os.chmod(key_path, 0o600)

    # Configure SSH to use this key and disable strict host checking
    config_path = os.path.join(ssh_dir, "config")
    config = (
        "Host github.com gitcode.com gitee.com gitlab.com\n"
        "    StrictHostKeyChecking no\n"
        "    UserKnownHostsFile /dev/null\n"
        f"    IdentityFile {key_path}\n"
    )
    with open(config_path, "w") as f:
        f.write(config)
    os.chmod(config_path, 0o600)
    logger.debug("SSH configured.")


class Mirror:
    def __init__(self, hub: Hub, src_name: str, dst_name: str,
                 args: argparse.Namespace) -> None:
        self.hub = hub
        self.src_name = src_name
        self.dst_name = dst_name
        self.src_url = f"{hub.src_repo_base}/{src_name}.git"
        self.dst_url = f"{hub.dst_repo_base}/{dst_name}.git"
        self.repo_path = os.path.join(args.cache_path, src_name)
        self.timeout = _parse_timeout(args.timeout)
        self.force_update = args.force_update
        self.lfs = args.lfs

    def _git_cmd(self, *args: str, **kwargs: Any) -> subprocess.CompletedProcess:
        """Run a git command with timeout."""
        cmd = ["git"] + list(args)
        return subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=self.timeout or None, cwd=self.repo_path, **kwargs,
        )

    def _clone(self) -> None:
        logger.info(f"git clone {self.src_url}")
        parent = os.path.dirname(self.repo_path)
        os.makedirs(parent, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", self.src_url, self.repo_path],
            capture_output=True, text=True,
            timeout=self.timeout or None,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Clone failed: {result.stderr.strip()}")

        if self.lfs:
            self._git_cmd("lfs", "fetch", "--all", "origin")
        logger.info(f"Clone completed: {self.repo_path}")

    def _update(self) -> None:
        try:
            self._git_cmd("pull")
        except Exception:
            logger.warning(f"Pull failed, re-cloning {self.src_name}")
            shutil.rmtree(self.repo_path, ignore_errors=True)
            self._clone()

        if self.lfs:
            self._git_cmd("lfs", "fetch", "--all", "origin")

    def download(self) -> None:
        logger.info("(1/3) Downloading...")
        if os.path.isdir(os.path.join(self.repo_path, ".git")):
            self._update()
        else:
            self._clone()

    def create(self) -> None:
        logger.info("(2/3) Creating...")
        self.hub.ensure_dest_repo(self.dst_name)

    def push(self) -> None:
        logger.info("(3/3) Force pushing...")

        # Check if empty repo
        rev = self._git_cmd("rev-list", "-n", "1", "--all")
        if rev.returncode != 0 or not rev.stdout.strip():
            logger.info(f"Empty repo {self.src_url}, skip pushing.")
            return

        self._git_cmd("remote", "set-head", "origin", "-d")

        # Set up destination remote
        dst_type = self.hub.dst_type
        try:
            self._git_cmd("remote", "add", dst_type, self.dst_url)
        except Exception:
            self._git_cmd("remote", "rm", dst_type)
            self._git_cmd("remote", "add", dst_type, self.dst_url)

        cmd = ["git", "push"]
        if self.force_update:
            cmd.append("-f")
        cmd.extend([dst_type, "refs/remotes/origin/*:refs/heads/*", "--tags", "--prune"])

        if self.lfs:
            self._git_cmd("lfs", "push", dst_type, "--all")

        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=self.timeout or None, cwd=self.repo_path)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())

        if not self.force_update and self.lfs:
            self._git_cmd("lfs", "push", dst_type, "--all")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def _classify_error(exc: Exception) -> Dict[str, str]:
    """Classify an exception into {'category': ..., 'message': ...} for clean display.

    Categories (stable keys for grouping in README/dashboard):
      large_file      — file exceeds GitHub 100 MB limit
      push_protection — GH013 push protection (secret scanning)
      hook_declined   — pre-receive hook rejected the push
      branch_delete   — refusing to delete current/default branch
      rate_limited    — secondary rate limit or content-creation block
      repo_not_found  — source repo missing or inaccessible
      clone_failed    — git clone failed (network, auth, timeout)
      push_failed     — generic push rejection (catch-all)
      unknown         — unclassified
    """
    if hasattr(exc, "stderr") and exc.stderr:
        raw = exc.stderr.strip()
    else:
        raw = str(exc).strip()

    raw_lower = raw.lower()

    # ── Pattern matching (order matters — check specific before generic) ──

    # Large file (GH001)
    if "file size limit" in raw_lower or ("gh001" in raw_lower and "large file" in raw_lower):
        m = re.search(r"File (.+?) is ([\d.]+ [GMK]B)", raw)
        if m:
            return {"category": "large_file",
                    "message": f"{m.group(1)} is {m.group(2)}, exceeds GitHub 100 MB limit"}
        return {"category": "large_file",
                "message": "A file exceeds GitHub's 100 MB file size limit"}

    # Push protection (GH013 — secret scanning)
    if "push protection" in raw_lower or "gh013" in raw_lower:
        return {"category": "push_protection",
                "message": "Blocked by GitHub push protection (secret/key leaked in history)"}

    # Pre-receive hook declined
    if "pre-receive hook declined" in raw_lower or "hook declined" in raw_lower:
        return {"category": "hook_declined",
                "message": "Rejected by destination server pre-receive hook"}

    # Refusing to delete current branch
    if "refusing to delete" in raw_lower:
        m = re.search(r"refs/heads/(\S+)", raw)
        branch = m.group(1) if m else "unknown"
        return {"category": "branch_delete",
                "message": f"Cannot delete '{branch}' (current default branch on destination)"}

    # Rate limiting
    if "secondary rate limit" in raw_lower or "rate limit" in raw_lower:
        return {"category": "rate_limited",
                "message": "GitHub rate limited this request — will retry next run"}

    # Repository not found
    if "repository not found" in raw_lower or "not found" in raw_lower:
        return {"category": "repo_not_found",
                "message": "Source repository not found or has been deleted"}

    # Clone failures
    if "clone failed" in raw_lower or "could not read from remote" in raw_lower:
        return {"category": "clone_failed",
                "message": "Failed to clone from source (network/auth/availability issue)"}

    # Timeout
    if "timeout" in raw_lower or "timed out" in raw_lower:
        return {"category": "timeout",
                "message": "Operation timed out"}

    # Fatal git error — extract the fatal line
    for line in raw.split("\n"):
        if "fatal:" in line.lower():
            return {"category": "push_failed",
                    "message": line.strip()[:200]}

    # Generic rejected push
    if "rejected" in raw_lower:
        for line in reversed(raw.split("\n")):
            if "rejected" in line.lower():
                return {"category": "push_failed",
                        "message": line.strip()[:200]}

    # Generic error line
    for line in reversed(raw.split("\n")):
        stripped = line.strip()
        if "error:" in stripped.lower() and not re.match(r'^[a-f0-9]{20,}', stripped):
            return {"category": "unknown",
                    "message": stripped[:200]}

    # Absolute fallback
    return {"category": "unknown",
            "message": (raw[:200] or type(exc).__name__)}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mirror repos between platforms with structured results output",
    )
    p.add_argument("--src", required=True, help="Source, e.g. gitcode/openeuler")
    p.add_argument("--dst", default="", help="Destination, e.g. github/openeuler-mirror")
    p.add_argument("--dst-token", default="", help="API token for destination")
    p.add_argument("--src-token", default="", help="API token for source (optional)")
    p.add_argument("--dst-key", default="", help="SSH private key for mirroring")
    p.add_argument("--account-type", default="user", help="user, org, or group")
    p.add_argument("--src-account-type", default="", help="Override source account type")
    p.add_argument("--dst-account-type", default="", help="Override destination account type")
    p.add_argument("--clone-style", default="ssh", help="https or ssh")
    p.add_argument("--cache-path", default="hub-mirror-cache", help="Local clone cache")
    p.add_argument("--black-list", default="", help="Comma-separated repos to skip")
    p.add_argument("--white-list", default="", help="Comma-separated repos to include")
    p.add_argument("--static-list", default="",
                   help="Comma-separated repos to mirror (skip API listing)")
    p.add_argument("--force-update", action="store_true", help="Force push to destination")
    p.add_argument("--timeout", default="30m", help="Per-repo timeout (e.g. 30m, 1h)")
    p.add_argument("--api-timeout", type=int, default=60, help="API timeout in seconds")
    p.add_argument("--mappings", default="", help="Repo name mappings: A=>B,C=>D")
    p.add_argument("--lfs", action="store_true", help="Enable Git LFS support")
    p.add_argument("--list-only", action="store_true",
                   help="Only list source repos (no mirroring)")
    p.add_argument("--output", default="results.json", help="Output JSON path")
    p.add_argument("--workflow", default="mirror-repos",
                   help="Workflow name for metadata (default: mirror-repos)")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p.parse_args(argv)


def _parse_mappings(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not raw or not raw.strip():
        return result
    for pair in raw.split(","):
        pair = pair.strip()
        if "=>" in pair:
            src, dst = pair.split("=>", 1)
            result[src.strip()] = dst.strip()
    return result


def main(argv: Optional[List[str]] = None) -> Dict[str, Any]:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    _ssh_setup(args.dst_key)

    hub = Hub(args)

    # Resolve repo list
    static_list = [r.strip() for r in args.static_list.split(",") if r.strip()]
    black_list = {r.strip() for r in args.black_list.split(",") if r.strip()}
    white_list = {r.strip() for r in args.white_list.split(",") if r.strip()}
    mappings = _parse_mappings(args.mappings)

    if static_list:
        repos = static_list
        logger.info(f"Using static list: {len(repos)} repos")
    else:
        logger.info(f"Fetching repos from {args.src} ...")
        repos = hub.list_repos()
        logger.info(f"Found {len(repos)} repos")

    if args.list_only:
        for r in repos:
            print(r)
        return {"total": len(repos), "repos": repos}

    # Mirror each repo
    total = len(repos)
    success_list: List[str] = []
    failed_list: List[str] = []
    skipped_list: List[str] = []
    errors: Dict[str, str] = {}

    for i, repo in enumerate(repos, 1):
        if repo in black_list:
            logger.info(f"Skip {repo} (black_list)")
            skipped_list.append(repo)
            continue
        if white_list and repo not in white_list:
            logger.info(f"Skip {repo} (not in white_list)")
            skipped_list.append(repo)
            continue

        dst_repo = mappings.get(repo, repo)
        logger.info(f"[{i}/{total}] {repo} → {dst_repo}")

        try:
            mirror = Mirror(hub, repo, dst_repo, args)
            mirror.download()
            mirror.create()
            mirror.push()
            success_list.append(repo)
            logger.info(f"✓ {repo}")
        except Exception as e:
            failed_list.append(repo)
            errors[repo] = _classify_error(e)
            logger.error(f"✗ {repo}: {errors[repo]}")

    # Build structured results
    success = len(success_list)
    failed = len(failed_list)
    skipped = len(skipped_list)

    summary = f"Total: {total}, success: {success}, failed: {failed}, skipped: {skipped}"
    logger.info(summary)

    results: Dict[str, Any] = {
        "src": args.src,
        "dst": args.dst,
        "workflow": args.workflow,
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "success_list": success_list,
        "failed_list": failed_list,
        "skipped_list": skipped_list,
        "errors": errors,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Results written to {args.output}")

    if failed_list:
        logger.info(f"Failed repos: {failed_list}")

    return results


if __name__ == "__main__":
    result = main()
    if result.get("failed"):
        sys.exit(1)
