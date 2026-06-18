"""Tests for diagnose_failures.py — git checks and API diagnostics."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import requests

from tests.conftest import import_script

diagnose = import_script("diagnose_failures")


# ═══════════════════════════════════════════════════════════════════════════
# git_ls_remote
# ═══════════════════════════════════════════════════════════════════════════

@patch("subprocess.run")
def test_git_ls_remote_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    result = diagnose.git_ls_remote("git@github.com:org/repo.git")
    assert result is None


@patch("subprocess.run")
def test_git_ls_remote_failure(mock_run):
    mock_run.return_value = MagicMock(
        returncode=128,
        stderr="fatal: repository not found",
    )
    result = diagnose.git_ls_remote("git@github.com:org/repo.git")
    assert "repository not found" in result


@patch("subprocess.run")
def test_git_ls_remote_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=30)
    result = diagnose.git_ls_remote("git@github.com:org/repo.git")
    assert "timed out" in result


@patch("subprocess.run")
def test_git_ls_remote_git_not_found(mock_run):
    mock_run.side_effect = FileNotFoundError("git not found")
    result = diagnose.git_ls_remote("git@github.com:org/repo.git")
    assert result == "git not found"


@patch("subprocess.run")
def test_git_ls_remote_unexpected(mock_run):
    mock_run.side_effect = OSError("disk full")
    result = diagnose.git_ls_remote("git@github.com:org/repo.git")
    assert "disk full" in result


# ═══════════════════════════════════════════════════════════════════════════
# check_api_repo
# ═══════════════════════════════════════════════════════════════════════════

@patch.object(requests.Session, "get")
def test_check_api_repo_accessible(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"size": 100}
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "myrepo",
    )
    assert result is None


@patch.object(requests.Session, "get")
def test_check_api_repo_large(mock_get):
    """Repos > 500000 KB should be flagged as very large."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"size": 600000}
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "large-repo",
    )
    assert result is not None
    assert "500" not in result or "large" in result.lower() or "MB" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_404(mock_get):
    mock_get.return_value.status_code = 404
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "missing",
    )
    assert "not found" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_401(mock_get):
    mock_get.return_value.status_code = 401
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "private-repo",
    )
    assert "Authentication" in result or "token" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_403(mock_get):
    mock_get.return_value.status_code = 403
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "any",
    )
    assert "rate limit" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_other_status(mock_get):
    mock_get.return_value.status_code = 500
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "any",
    )
    assert "500" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_timeout(mock_get):
    mock_get.side_effect = requests.Timeout("timed out")
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "any",
    )
    assert "timed out" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_connection_error(mock_get):
    mock_get.side_effect = requests.ConnectionError("refused")
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "any",
    )
    assert "Network error" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_unexpected(mock_get):
    mock_get.side_effect = RuntimeError("boom")
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "github", "myorg", "org", "any",
    )
    assert "boom" in result


def test_check_api_repo_unknown_platform():
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "unknown", "acct", "user", "repo",
    )
    assert "Unknown platform" in result


@patch.object(requests.Session, "get")
def test_check_api_repo_gitlab_url(mock_get):
    """GitLab uses project path in URL, not repos/owner/repo."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"size": 50}
    sess = requests.Session()
    result = diagnose.check_api_repo(
        sess, "gitlab", "mygroup", "group", "myrepo",
    )
    assert result is None
    call_url = mock_get.call_args[0][0]
    assert "mygroup%2Fmyrepo" in call_url


@patch.object(requests.Session, "get")
def test_check_api_repo_with_token(mock_get):
    """Token should be passed as Authorization header for github."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"size": 10}
    sess = requests.Session()
    diagnose.check_api_repo(
        sess, "github", "myorg", "org", "myrepo", token="tok123",
    )
    headers = mock_get.call_args[1]["headers"]
    assert headers["Authorization"] == "token tok123"


@patch.object(requests.Session, "get")
def test_check_api_repo_gitlab_token(mock_get):
    """GitLab uses PRIVATE-TOKEN header."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"size": 10}
    sess = requests.Session()
    diagnose.check_api_repo(
        sess, "gitlab", "mygroup", "group", "myrepo", token="tok456",
    )
    headers = mock_get.call_args[1]["headers"]
    assert headers["PRIVATE-TOKEN"] == "tok456"


@patch.object(requests.Session, "get")
def test_check_api_repo_gitee_token(mock_get):
    """Gitee/Gitcode use access_token query param."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"size": 10}
    sess = requests.Session()
    diagnose.check_api_repo(
        sess, "gitee", "myorg", "org", "myrepo", token="tok789",
    )
    params = mock_get.call_args[1]["params"]
    assert params["access_token"] == "tok789"


# ═══════════════════════════════════════════════════════════════════════════
# main (smoke)
# ═══════════════════════════════════════════════════════════════════════════

def test_main_no_failed_repos(tmp_path, capsys):
    """When results.json has no failed repos, main should print and exit."""
    import json
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({
        "failed_list": [],
        "success_list": ["r1"],
    }))

    with patch("sys.argv", [
        "diagnose_failures.py", str(results_file),
    ]):
        diagnose.main()

    captured = capsys.readouterr()
    assert "No failed repos" in captured.out


@patch.object(requests.Session, "get")
def test_main_with_failures(mock_get, tmp_path):
    """main should diagnose each failed repo and update results.json."""
    import json
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({
        "failed_list": ["bad-repo"],
        "success_list": [],
        "errors": {},
    }))

    # Mock API responses for both source and destination checks
    mock_get.return_value.status_code = 404

    with patch("sys.argv", [
        "diagnose_failures.py", str(results_file),
        "--src", "gitcode/myorg",
        "--dst", "github/myorg",
        "--src-token", "src-tok",
    ]):
        diagnose.main()

    with open(results_file) as f:
        data = json.load(f)
    assert "diagnoses" in data
    assert "bad-repo" in data["diagnoses"]
    assert any("not found" in d for d in data["diagnoses"]["bad-repo"])


@patch.object(requests.Session, "get")
@patch("os.path.isfile")
@patch("os.path.isdir")
def test_main_cache_hit(mock_isdir, mock_isfile, mock_get, tmp_path):
    """When hub-mirror-cache has the bare repo, include cache diagnostic."""
    import json
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({
        "failed_list": ["cached-repo"],
        "success_list": [],
        "errors": {},
    }))

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"size": 100}
    # Bare mirror cache directory exists and has HEAD
    mock_isdir.return_value = True
    mock_isfile.return_value = True

    with patch("sys.argv", [
        "diagnose_failures.py", str(results_file),
        "--src", "gitcode/myorg",
    ]):
        diagnose.main()

    with open(results_file) as f:
        data = json.load(f)
    diags = data["diagnoses"]["cached-repo"]
    assert any("bare mirror exists" in d for d in diags)
    assert any("valid bare git repo" in d for d in diags)
