"""Tests for mirror_repos.py — pure functions, Platform, Hub, and error classification."""

import argparse
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
import requests

from tests.conftest import import_script

mirror = import_script("mirror_repos")


# ═══════════════════════════════════════════════════════════════════════════
# _parse_timeout
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("inp,expected", [
    ("30m", 1800),
    ("1h", 3600),
    ("3600", 3600),
    ("2d", 172800),
    ("10s", 10),
    ("0", 0),
    ("0s", 0),
    ("5m", 300),
])
def test_parse_timeout_valid(inp, expected):
    assert mirror._parse_timeout(inp) == expected


@pytest.mark.parametrize("inp", [
    "",
    "invalid",
    "m30",
    "abc",
])
def test_parse_timeout_invalid(inp):
    assert mirror._parse_timeout(inp) == 0


def test_parse_timeout_none():
    """_parse_timeout(None) raises TypeError from re.match — design quirk."""
    with pytest.raises(TypeError):
        mirror._parse_timeout(None)


# ═══════════════════════════════════════════════════════════════════════════
# _parse_mappings
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_mappings_empty():
    assert mirror._parse_mappings("") == {}
    assert mirror._parse_mappings("   ") == {}
    assert mirror._parse_mappings(None) == {}


def test_parse_mappings_basic():
    assert mirror._parse_mappings("A=>B") == {"A": "B"}


def test_parse_mappings_multiple():
    result = mirror._parse_mappings("A=>B,C=>D,old=>new")
    assert result == {"A": "B", "C": "D", "old": "new"}


def test_parse_mappings_whitespace():
    result = mirror._parse_mappings("  A  =>  B  ,  C  =>  D  ")
    assert result == {"A": "B", "C": "D"}


def test_parse_mappings_invalid_skipped():
    assert mirror._parse_mappings("A=>B,invalid") == {"A": "B"}
    assert mirror._parse_mappings("noarrow") == {}


# ═══════════════════════════════════════════════════════════════════════════
# _classify_error
# ═══════════════════════════════════════════════════════════════════════════

class FakeStderrExc(Exception):
    """Simulate subprocess.CalledProcessError with stderr."""
    def __init__(self, stderr_text):
        self.stderr = stderr_text
        super().__init__(stderr_text)


def test_classify_large_file_with_details():
    err = FakeStderrExc("remote: error: GH001: Large file detected. "
                         "File bigfile.iso is 150.00 MB")
    result = mirror._classify_error(err)
    assert result["category"] == "large_file"
    assert "bigfile.iso" in result["message"]
    assert "150.00 MB" in result["message"]


def test_classify_large_file_generic():
    err = FakeStderrExc("remote: error: GH001: Large file detected.")
    result = mirror._classify_error(err)
    assert result["category"] == "large_file"
    assert "100" in result["message"] or "MB" in result["message"]


def test_classify_large_file_lowercase():
    err = FakeStderrExc("file size limit exceeded")
    result = mirror._classify_error(err)
    assert result["category"] == "large_file"


def test_classify_push_protection():
    err = FakeStderrExc("remote: error: GH013: Push protection found secrets")
    result = mirror._classify_error(err)
    assert result["category"] == "push_protection"


def test_classify_push_protection_text():
    err = FakeStderrExc("Push protection blocked this push")
    result = mirror._classify_error(err)
    assert result["category"] == "push_protection"


def test_classify_hook_declined():
    err = FakeStderrExc("remote: pre-receive hook declined")
    result = mirror._classify_error(err)
    assert result["category"] == "hook_declined"


def test_classify_hook_declined_short():
    err = FakeStderrExc("hook declined by server")
    result = mirror._classify_error(err)
    assert result["category"] == "hook_declined"


def test_classify_branch_delete():
    err = FakeStderrExc("remote: error: refusing to delete refs/heads/main")
    result = mirror._classify_error(err)
    assert result["category"] == "branch_delete"
    assert "main" in result["message"]


def test_classify_branch_delete_unknown_branch():
    err = FakeStderrExc("refusing to delete the current branch")
    result = mirror._classify_error(err)
    assert result["category"] == "branch_delete"


def test_classify_rate_limited():
    err = FakeStderrExc("secondary rate limit reached, try again later")
    result = mirror._classify_error(err)
    assert result["category"] == "rate_limited"


def test_classify_rate_limited_simple():
    err = FakeStderrExc("rate limit exceeded")
    result = mirror._classify_error(err)
    assert result["category"] == "rate_limited"


def test_classify_repo_not_found():
    err = FakeStderrExc("remote: repository not found")
    result = mirror._classify_error(err)
    assert result["category"] == "repo_not_found"


def test_classify_repo_not_found_simple():
    err = FakeStderrExc("not found")
    result = mirror._classify_error(err)
    assert result["category"] == "repo_not_found"


def test_classify_clone_failed():
    err = FakeStderrExc("fatal: clone failed: could not read from remote")
    result = mirror._classify_error(err)
    assert result["category"] == "clone_failed"


def test_classify_clone_failed_read_remote():
    err = FakeStderrExc("could not read from remote repository")
    result = mirror._classify_error(err)
    assert result["category"] == "clone_failed"


def test_classify_timeout():
    err = FakeStderrExc("operation timed out after 30 minutes")
    result = mirror._classify_error(err)
    assert result["category"] == "timeout"


def test_classify_timeout_alt():
    err = FakeStderrExc("connection timeout")
    result = mirror._classify_error(err)
    assert result["category"] == "timeout"


def test_classify_fatal_error():
    """'fatal:' line should be extracted as push_failed (avoid 'not found' to
    prevent repo_not_found from matching first)."""
    err = FakeStderrExc("some preamble\nfatal: remote rejected: non-fast-forward\nmore output")
    result = mirror._classify_error(err)
    assert result["category"] == "push_failed"
    assert "fatal:" in result["message"]


def test_classify_rejected():
    err = FakeStderrExc("! [remote rejected] main -> main (non-fast-forward)\n"
                         "error: failed to push some refs")
    result = mirror._classify_error(err)
    assert result["category"] == "push_failed"
    assert "rejected" in result["message"].lower()


def test_classify_generic_error():
    err = FakeStderrExc("blah blah\nerror: something went wrong\nmore text")
    result = mirror._classify_error(err)
    assert result["category"] == "unknown"
    assert "something went wrong" in result["message"]


def test_classify_fallback_no_stderr():
    err = ValueError("something bizarre happened")
    result = mirror._classify_error(err)
    assert result["category"] == "unknown"
    assert "something bizarre happened" in result["message"]


def test_classify_empty_stderr():
    err = FakeStderrExc("")
    result = mirror._classify_error(err)
    assert result["category"] == "unknown"
    assert result["message"]  # fallback to type name


def test_classify_no_stderr_attr():
    """Exception without .stderr attribute uses str(exc)."""
    err = RuntimeError("network unreachable")
    result = mirror._classify_error(err)
    assert result["category"] == "unknown"
    assert "network unreachable" in result["message"]


def test_classify_truncation():
    """Very long messages are truncated to 200 chars."""
    long_msg = "x" * 500
    err = ValueError(long_msg)
    result = mirror._classify_error(err)
    assert len(result["message"]) <= 200


def test_classify_priority_large_file_before_rate_limit():
    """large_file should match before rate_limited even if both keywords present."""
    err = FakeStderrExc("file size limit exceeded and rate limit hit")
    result = mirror._classify_error(err)
    assert result["category"] == "large_file"


# ═══════════════════════════════════════════════════════════════════════════
# Platform
# ═══════════════════════════════════════════════════════════════════════════

def test_platform_clone_base_https():
    p = mirror.PLATFORMS["github"]
    assert p.clone_base("myorg", "https") == "https://github.com/myorg"


def test_platform_clone_base_ssh():
    p = mirror.PLATFORMS["github"]
    assert p.clone_base("myorg", "ssh") == "git@github.com:myorg"


def test_platform_push_base():
    p = mirror.PLATFORMS["github"]
    assert p.push_base("myorg") == "git@github.com:myorg"


def test_platform_repo_list_url_user():
    p = mirror.PLATFORMS["github"]
    url = p.repo_list_url("someuser", "user")
    assert url == "https://api.github.com/users/someuser/repos"


def test_platform_repo_list_url_org():
    p = mirror.PLATFORMS["gitee"]
    url = p.repo_list_url("myorg", "org")
    assert url == "https://gitee.com/api/v5/orgs/myorg/repos"


def test_platform_repo_list_url_gitlab():
    p = mirror.PLATFORMS["gitlab"]
    url = p.repo_list_url("mygroup", "group")
    assert "projects" in url


def test_platform_validate_success():
    p = mirror.PLATFORMS["github"]
    p.validate("org", "source")  # should not raise


def test_platform_validate_failure():
    p = mirror.PLATFORMS["github"]
    with pytest.raises(ValueError, match="account_type"):
        p.validate("group", "source")


def test_platform_validate_gitlab_allows_group():
    p = mirror.PLATFORMS["gitlab"]
    p.validate("group", "source")  # gitlab allows user and group


def test_all_platforms_defined():
    assert set(mirror.PLATFORMS.keys()) == {"github", "gitee", "gitcode", "gitlab"}


# ═══════════════════════════════════════════════════════════════════════════
# Hub
# ═══════════════════════════════════════════════════════════════════════════

def test_hub_init_parses_src_dst(sample_hub_args):
    hub = mirror.Hub(sample_hub_args)
    assert hub.src_type == "gitcode"
    assert hub.src_account == "openeuler"
    assert hub.dst_type == "github"
    assert hub.dst_account == "openeuler-mirror"


def test_hub_init_no_dst():
    args = argparse.Namespace(
        src="gitcode/openeuler", dst="", dst_token="", src_token="",
        account_type="org", api_timeout=60, clone_style="ssh",
    )
    hub = mirror.Hub(args)
    assert hub.dst_platform is None
    assert hub.dst_repo_base == ""


def test_hub_src_repo_base(sample_hub_args):
    hub = mirror.Hub(sample_hub_args)
    assert "gitcode.com" in hub.src_repo_base


def test_hub_dst_repo_base(sample_hub_args):
    hub = mirror.Hub(sample_hub_args)
    assert "github.com" in hub.dst_repo_base


def test_hub_dst_platform_validates(sample_hub_args):
    """Hub should validate destination platform on init."""
    sample_hub_args.dst_account_type = "group"  # invalid for github
    with pytest.raises(ValueError, match="account_type"):
        mirror.Hub(sample_hub_args)


@patch.object(requests.Session, "get")
def test_hub_list_repos(mock_get, sample_hub_args):
    """Return 3 items on page 1, empty on page 2 to stop pagination."""
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [{"name": "repo1"}, {"name": "repo2"}, {"name": "repo3"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    hub = mirror.Hub(sample_hub_args)
    repos = hub.list_repos()
    assert repos == ["repo1", "repo2", "repo3"]


@patch.object(requests.Session, "get")
def test_hub_list_repos_empty(mock_get, sample_hub_args):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = []
    hub = mirror.Hub(sample_hub_args)
    repos = hub.list_repos()
    assert repos == []


@patch.object(requests.Session, "get")
def test_hub_list_repos_pagination(mock_get, sample_hub_args):
    """When first page returns 100 items, should request page 2."""
    page1_items = [{"name": f"repo{i}"} for i in range(100)]
    page2_items = [{"name": "repo101"}, {"name": "repo102"}]
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: page1_items),
        MagicMock(status_code=200, json=lambda: page2_items),
        MagicMock(status_code=200, json=lambda: []),
    ]
    hub = mirror.Hub(sample_hub_args)
    repos = hub.list_repos()
    assert len(repos) == 102
    assert repos[-1] == "repo102"


@patch.object(requests.Session, "get")
def test_hub_list_repos_api_error(mock_get, sample_hub_args):
    mock_get.return_value.status_code = 500
    mock_get.return_value.text = "Internal Server Error"
    hub = mirror.Hub(sample_hub_args)
    repos = hub.list_repos()
    assert repos == []


@patch.object(requests.Session, "get")
def test_hub_list_repos_network_error(mock_get, sample_hub_args):
    mock_get.side_effect = requests.RequestException("connection refused")
    hub = mirror.Hub(sample_hub_args)
    repos = hub.list_repos()
    assert repos == []


@patch.object(requests.Session, "post")
def test_hub_ensure_dest_repo(mock_post, sample_hub_args):
    mock_post.return_value.status_code = 201
    hub = mirror.Hub(sample_hub_args)
    assert hub.ensure_dest_repo("my-repo") is True


@patch.object(requests.Session, "post")
def test_hub_ensure_dest_repo_fails(mock_post, sample_hub_args):
    mock_post.return_value.status_code = 422
    mock_post.return_value.text = "already exists"
    hub = mirror.Hub(sample_hub_args)
    assert hub.ensure_dest_repo("my-repo") is False


def test_hub_ensure_dest_repo_no_dst():
    args = argparse.Namespace(
        src="gitcode/openeuler", dst="", dst_token="", src_token="",
        account_type="org", api_timeout=60, clone_style="ssh",
    )
    hub = mirror.Hub(args)
    assert hub.ensure_dest_repo("any") is False


# ═══════════════════════════════════════════════════════════════════════════
# Platform.create_repo — per-platform branching
# ═══════════════════════════════════════════════════════════════════════════

@patch.object(requests.Session, "post")
def test_create_repo_github_org(mock_post):
    mock_post.return_value.status_code = 201
    p = mirror.PLATFORMS["github"]
    sess = requests.Session()
    result = p.create_repo(sess, "myorg", "org", "new-repo", "token123", 60)
    assert result is True
    call_args = mock_post.call_args
    assert "orgs/myorg/repos" in call_args[0][0]


@patch.object(requests.Session, "post")
def test_create_repo_github_user(mock_post):
    mock_post.return_value.status_code = 201
    p = mirror.PLATFORMS["github"]
    sess = requests.Session()
    result = p.create_repo(sess, "myuser", "user", "new-repo", "token123", 60)
    assert result is True
    call_args = mock_post.call_args
    assert "user/repos" in call_args[0][0]


@patch.object(requests.Session, "post")
def test_create_repo_gitee(mock_post):
    mock_post.return_value.status_code = 201
    p = mirror.PLATFORMS["gitee"]
    sess = requests.Session()
    result = p.create_repo(sess, "myorg", "org", "new-repo", "token123", 60)
    assert result is True
    call_args = mock_post.call_args
    assert "orgs/myorg/repos" in call_args[0][0]


@patch.object(requests.Session, "post")
def test_create_repo_failure(mock_post):
    mock_post.return_value.status_code = 422
    mock_post.return_value.text = "Validation failed"
    p = mirror.PLATFORMS["github"]
    sess = requests.Session()
    result = p.create_repo(sess, "myorg", "org", "new-repo", "token123", 60)
    assert result is False


@patch.object(requests.Session, "post")
@patch.object(requests.Session, "get")
def test_create_repo_gitlab_group(mock_get, mock_post):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [
        {"path": "mygroup", "id": 42},
        {"path": "other", "id": 99},
    ]
    mock_post.return_value.status_code = 201
    p = mirror.PLATFORMS["gitlab"]
    sess = requests.Session()
    result = p.create_repo(sess, "mygroup", "group", "new-repo", "token123", 60)
    assert result is True
    # GitLab passes data as a plain dict (not JSON string)
    call_data = mock_post.call_args[1]["data"]
    assert call_data["namespace_id"] == 42


@patch.object(requests.Session, "post")
@patch.object(requests.Session, "get")
def test_create_repo_gitlab_group_not_found(mock_get, mock_post):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [
        {"path": "other", "id": 99},
    ]
    mock_post.return_value.status_code = 201
    p = mirror.PLATFORMS["gitlab"]
    sess = requests.Session()
    result = p.create_repo(sess, "mygroup", "group", "new-repo", "token123", 60)
    assert result is True  # repo created without namespace_id


@patch.object(requests.Session, "post")
def test_create_repo_gitlab_user(mock_post):
    mock_post.return_value.status_code = 201
    p = mirror.PLATFORMS["gitlab"]
    sess = requests.Session()
    result = p.create_repo(sess, "myuser", "user", "new-repo", "token123", 60)
    assert result is True


def test_create_repo_unsupported_platform():
    """An unknown platform should return False."""
    p = mirror.Platform("unknown", "host", "api", "repos", ("user",))
    sess = requests.Session()
    result = p.create_repo(sess, "a", "user", "r", "tok", 60)
    assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# Mirror construction and helpers
# ═══════════════════════════════════════════════════════════════════════════

def test_mirror_construction(sample_hub_args):
    hub = mirror.Hub(sample_hub_args)
    m = mirror.Mirror(hub, "src-repo", "dst-repo", sample_hub_args)
    assert m.src_name == "src-repo"
    assert m.dst_name == "dst-repo"
    assert "src-repo.git" in m.src_url
    assert "dst-repo.git" in m.dst_url
    assert m.timeout == 1800


def test_mirror_no_timeout(sample_hub_args):
    sample_hub_args.timeout = "0"
    hub = mirror.Hub(sample_hub_args)
    m = mirror.Mirror(hub, "r1", "r2", sample_hub_args)
    assert m.timeout == 0


@patch.object(mirror.subprocess, "run")
def test_mirror_clone_uses_bare_mirror(mock_run, sample_hub_args):
    mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
    hub = mirror.Hub(sample_hub_args)
    m = mirror.Mirror(hub, "r1", "r1", sample_hub_args)

    m._clone()

    assert mock_run.call_args[0][0][:3] == ["git", "clone", "--mirror"]
    assert m.repo_path.endswith("r1.git")


@patch.object(mirror.subprocess, "run")
def test_mirror_update_fetches_and_prunes(mock_run, sample_hub_args):
    mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
    hub = mirror.Hub(sample_hub_args)
    m = mirror.Mirror(hub, "r1", "r1", sample_hub_args)

    m._update()

    assert mock_run.call_args[0][0] == ["git", "fetch", "--all", "--prune"]


@patch.object(mirror.subprocess, "run")
def test_mirror_push_uses_bare_refspec(mock_run, sample_hub_args):
    sample_hub_args.force_update = True

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "rev-list", "-n", "1", "--all"]:
            return subprocess.CompletedProcess(cmd, 0, "abc123\n", "")
        if cmd == ["git", "remote"]:
            return subprocess.CompletedProcess(cmd, 0, "origin\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    mock_run.side_effect = fake_run
    hub = mirror.Hub(sample_hub_args)
    m = mirror.Mirror(hub, "r1", "r1", sample_hub_args)

    m.push()

    assert mock_run.call_args[0][0] == [
        "git", "push", "github",
        "+refs/heads/*:refs/heads/*",
        "+refs/tags/*:refs/tags/*",
        "--prune",
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Branch rule cleanup
# ═══════════════════════════════════════════════════════════════════════════


def test_hub_clear_dest_branch_rules_for_gitee(sample_hub_args):
    sample_hub_args.dst = "gitee/openeuler-mirror"
    hub = mirror.Hub(sample_hub_args)
    branch_resp = MagicMock(status_code=200, headers={"total_page": "1"})
    branch_resp.json.return_value = [{"name": "master"}, {"name": "feature/foo"}]
    delete_resp = MagicMock(status_code=204)
    hub.session.get = MagicMock(return_value=branch_resp)
    hub.session.delete = MagicMock(return_value=delete_resp)

    deleted = hub.clear_dest_branch_rules("repo-a")

    assert deleted == 2
    assert hub.session.delete.call_count == 2
    assert "feature%2Ffoo/setting" in hub.session.delete.call_args_list[1][0][0]
    assert hub.session.delete.call_args_list[0][1]["params"] == {
        "access_token": "dst-token-123",
    }


def test_hub_clear_dest_branch_rules_for_github(sample_hub_args):
    sample_hub_args.dst = "github/openeuler-mirror"
    hub = mirror.Hub(sample_hub_args)
    branch_resp = MagicMock(status_code=200, headers={})
    branch_resp.json.return_value = [{"name": "main"}, {"name": "release/v1"}]
    delete_resp = MagicMock(status_code=204)
    hub.session.get = MagicMock(return_value=branch_resp)
    hub.session.delete = MagicMock(return_value=delete_resp)

    deleted = hub.clear_dest_branch_rules("repo-a")

    assert deleted == 2
    get_headers = hub.session.get.call_args[1]["headers"]
    assert get_headers["Authorization"] == "token dst-token-123"
    assert get_headers["Accept"] == "application/vnd.github+json"
    assert hub.session.delete.call_count == 2
    assert "release%2Fv1/protection" in hub.session.delete.call_args_list[1][0][0]
    delete_headers = hub.session.delete.call_args_list[1][1]["headers"]
    assert delete_headers["Authorization"] == "token dst-token-123"


def test_mirror_clear_branch_rules_if_needed_skips_by_default(sample_hub_args):
    hub = mirror.Hub(sample_hub_args)
    hub.clear_dest_branch_rules = MagicMock()
    m = mirror.Mirror(hub, "r1", "r1", sample_hub_args)

    m.clear_branch_rules_if_needed()

    hub.clear_dest_branch_rules.assert_not_called()


def test_mirror_clear_branch_rules_if_enabled(sample_hub_args):
    sample_hub_args.clear_branch_rules = True
    hub = mirror.Hub(sample_hub_args)
    hub.clear_dest_branch_rules = MagicMock()
    m = mirror.Mirror(hub, "r1", "r2", sample_hub_args)

    m.clear_branch_rules_if_needed()

    hub.clear_dest_branch_rules.assert_called_once_with("r2")


# ═══════════════════════════════════════════════════════════════════════════
# _ssh_setup
# ═══════════════════════════════════════════════════════════════════════════

def test_ssh_setup_no_key():
    """_ssh_setup with empty key should do nothing."""
    mirror._ssh_setup("")  # should not raise


def test_ssh_setup_with_key(tmp_path):
    """_ssh_setup should create key and config files."""
    import os
    home = str(tmp_path)
    ssh_dir = os.path.join(home, ".ssh")
    # We need to mock os.path.expanduser and the file writes
    with patch("os.path.expanduser", return_value=home):
        with patch("os.makedirs") as mock_mkdir:
            with patch("builtins.open", create=True) as mock_open:
                with patch("os.chmod"):
                    mirror._ssh_setup("fake-ssh-key-data")
                    mock_mkdir.assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# parse_args
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_args_minimal():
    args = mirror.parse_args(["--src", "gitcode/openeuler"])
    assert args.src == "gitcode/openeuler"
    assert args.dst == ""
    assert args.account_type == "user"


def test_parse_args_full():
    argv = [
        "--src", "gitcode/openeuler",
        "--dst", "github/mirror",
        "--dst-token", "tok1",
        "--src-token", "tok2",
        "--dst-key", "ssh-key-data",
        "--account-type", "org",
        "--clone-style", "https",
        "--cache-path", "/tmp/cache",
        "--black-list", "r1,r2",
        "--white-list", "r3",
        "--static-list", "r4,r5",
        "--force-update",
        "--timeout", "1h",
        "--api-timeout", "120",
        "--mappings", "A=>B",
        "--clear-branch-rules",
        "--output", "out.json",
        "--workflow", "custom",
        "--debug",
    ]
    args = mirror.parse_args(argv)
    assert args.src == "gitcode/openeuler"
    assert args.dst == "github/mirror"
    assert args.dst_token == "tok1"
    assert args.src_token == "tok2"
    assert args.dst_key == "ssh-key-data"
    assert args.account_type == "org"
    assert args.clone_style == "https"
    assert args.cache_path == "/tmp/cache"
    assert args.black_list == "r1,r2"
    assert args.white_list == "r3"
    assert args.static_list == "r4,r5"
    assert args.force_update is True
    assert args.timeout == "1h"
    assert args.api_timeout == 120
    assert args.mappings == "A=>B"
    assert args.clear_branch_rules is True
    assert args.output == "out.json"
    assert args.workflow == "custom"
    assert args.debug is True


def test_parse_args_list_only_defaults():
    args = mirror.parse_args(["--src", "gitcode/openeuler", "--list-only"])
    assert args.list_only is True


# ═══════════════════════════════════════════════════════════════════════════
# main (smoke tests with heavy mocking)
# ═══════════════════════════════════════════════════════════════════════════

@patch("builtins.open")
@patch.object(mirror, "_ssh_setup")
@patch.object(mirror, "logging")
def test_main_list_only(mock_logging, mock_ssh, mock_open, sample_hub_args):
    """main with --list-only should print repos and return."""
    with patch.object(mirror.Hub, "list_repos", return_value=["r1", "r2", "r3"]):
        result = mirror.main(["--src", "gitcode/openeuler", "--list-only"])
    assert result["total"] == 3
    assert result["repos"] == ["r1", "r2", "r3"]
    mock_ssh.assert_called_once()


@patch("builtins.open")
@patch.object(mirror, "_ssh_setup")
def test_main_with_static_list(mock_ssh, mock_open):
    """main with static list should mirror specified repos."""
    repos_iter = iter(["repo-a"])

    with patch.object(mirror.Hub, "list_repos") as mock_list:
        with patch.object(mirror, "Mirror") as MockMirror:
            mock_instance = MockMirror.return_value
            mock_instance.download = MagicMock()
            mock_instance.create = MagicMock()
            mock_instance.clear_branch_rules_if_needed = MagicMock()
            mock_instance.push = MagicMock()
            mock_list.return_value = ["should-not-be-used"]

            result = mirror.main([
                "--src", "gitcode/openeuler",
                "--dst", "github/mirror",
                "--static-list", "repo-a",
                "--output", "/dev/null",
            ])

    assert result["total"] == 1
    assert result["success"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == 0


@patch("builtins.open")
@patch.object(mirror, "_ssh_setup")
def test_main_with_black_and_white_list(mock_ssh, mock_open):
    """Black-listed repos are skipped, white-list filters others."""
    with patch.object(mirror.Hub, "list_repos", return_value=["r1", "r2", "r3", "r4"]):
        with patch.object(mirror, "Mirror") as MockMirror:
            mock_instance = MockMirror.return_value
            mock_instance.download = MagicMock()
            mock_instance.create = MagicMock()
            mock_instance.clear_branch_rules_if_needed = MagicMock()
            mock_instance.push = MagicMock()

            result = mirror.main([
                "--src", "gitcode/openeuler",
                "--dst", "github/mirror",
                "--black-list", "r1",
                "--white-list", "r2,r3",
                "--output", "/dev/null",
            ])

    assert result["total"] == 4
    assert result["success"] == 2  # r2, r3
    assert result["skipped"] == 2  # r1 (black), r4 (not in white)


@patch("builtins.open")
@patch.object(mirror, "_ssh_setup")
def test_main_mirror_failure_captured(mock_ssh, mock_open):
    """When a Mirror step fails, it's captured as failed with error classification."""
    with patch.object(mirror.Hub, "list_repos", return_value=["bad-repo"]):
        with patch.object(mirror, "Mirror") as MockMirror:
            mock_instance = MockMirror.return_value
            mock_instance.download = MagicMock()
            mock_instance.create = MagicMock()
            mock_instance.clear_branch_rules_if_needed = MagicMock()
            mock_instance.push = MagicMock(
                side_effect=RuntimeError("remote: repository not found")
            )

            result = mirror.main([
                "--src", "gitcode/openeuler",
                "--dst", "github/mirror",
                "--static-list", "bad-repo",
                "--output", "/dev/null",
            ])

    assert result["failed"] == 1
    assert "bad-repo" in result["failed_list"]
    assert "bad-repo" in result["errors"]
    assert result["errors"]["bad-repo"]["category"] == "repo_not_found"


@patch("builtins.open")
@patch.object(mirror, "_ssh_setup")
def test_main_mappings_applied(mock_ssh, mock_open):
    """Repo name mappings are applied to destination names."""
    with patch.object(mirror.Hub, "list_repos", return_value=["old-name"]):
        with patch.object(mirror, "Mirror") as MockMirror:
            mock_instance = MockMirror.return_value
            mock_instance.download = MagicMock()
            mock_instance.create = MagicMock()
            mock_instance.clear_branch_rules_if_needed = MagicMock()
            mock_instance.push = MagicMock()

            result = mirror.main([
                "--src", "gitcode/openeuler",
                "--dst", "github/mirror",
                "--static-list", "old-name",
                "--mappings", "old-name=>new-name",
                "--output", "/dev/null",
            ])

    # Check Mirror was constructed with mapped name
    call_kwargs = MockMirror.call_args
    assert call_kwargs[0][2] == "new-name"  # dst_name position


@patch("builtins.open")
@patch.object(mirror, "_ssh_setup")
def test_main_results_json_structure(mock_ssh, mock_open):
    """Output JSON has all expected top-level keys."""
    with patch.object(mirror.Hub, "list_repos", return_value=[]):
        result = mirror.main([
            "--src", "gitcode/openeuler",
            "--dst", "github/mirror",
            "--output", "/dev/null",
        ])

    for key in ("src", "dst", "workflow", "total", "success", "failed",
                "skipped", "success_list", "failed_list", "skipped_list",
                "errors", "timestamp"):
        assert key in result, f"Missing key: {key}"
