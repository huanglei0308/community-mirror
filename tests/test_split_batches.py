"""Tests for split_batches.py — batch splitting and repo listing."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from tests.conftest import import_script

split_batches = import_script("split_batches")


# ═══════════════════════════════════════════════════════════════════════════
# parse_list
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("inp,expected", [
    ("a,b,c", ["a", "b", "c"]),
    ("", []),
    ("   ", []),
    ("  a  ,  b  ", ["a", "b"]),
    ("single", ["single"]),
    (",,,", []),
    ("a,,b", ["a", "b"]),
    (None, []),
])
def test_parse_list(inp, expected):
    assert split_batches.parse_list(inp) == expected


# ═══════════════════════════════════════════════════════════════════════════
# split_into_batches
# ═══════════════════════════════════════════════════════════════════════════

def test_split_into_batches_exact():
    items = ["a", "b", "c", "d"]
    assert split_batches.split_into_batches(items, 2) == ["a,b", "c,d"]


def test_split_into_batches_uneven():
    items = ["a", "b", "c", "d", "e"]
    assert split_batches.split_into_batches(items, 2) == ["a,b", "c,d", "e"]


def test_split_into_batches_single_batch():
    items = ["a", "b", "c"]
    assert split_batches.split_into_batches(items, 10) == ["a,b,c"]


def test_split_into_batches_empty():
    assert split_batches.split_into_batches([], 10) == []


def test_split_into_batches_single_item():
    assert split_batches.split_into_batches(["only"], 80) == ["only"]


def test_split_into_batches_large_batch():
    items = [f"repo{i}" for i in range(200)]
    batches = split_batches.split_into_batches(items, 80)
    assert len(batches) == 3
    assert len(batches[0].split(",")) == 80
    assert len(batches[1].split(",")) == 80
    assert len(batches[2].split(",")) == 40


# ═══════════════════════════════════════════════════════════════════════════
# _get_all_repo_names (paginated API listing)
# ═══════════════════════════════════════════════════════════════════════════

@patch.object(requests.Session, "get")
def test_get_all_repo_names_github(mock_get):
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [{"name": "r1"}, {"name": "r2"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    names = split_batches._get_all_repo_names(
        sess, "https://api.github.com/orgs/o/repos", "github",
    )
    assert names == ["r1", "r2"]


@patch.object(requests.Session, "get")
def test_get_all_repo_names_gitlab(mock_get):
    """GitLab uses 'path' field instead of 'name'."""
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [{"path": "p1"}, {"path": "p2"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    names = split_batches._get_all_repo_names(
        sess, "https://gitlab.com/api/v4/projects", "gitlab",
    )
    assert names == ["p1", "p2"]


@patch.object(requests.Session, "get")
def test_get_all_repo_names_pagination(mock_get):
    """First page has 100 items → triggers page 2."""
    page1 = [{"name": f"repo{i}"} for i in range(100)]
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: page1),
        MagicMock(status_code=200, json=lambda: [{"name": "extra"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    names = split_batches._get_all_repo_names(
        sess, "https://api.github.com/orgs/o/repos", "github",
    )
    assert len(names) == 101
    assert names[-1] == "extra"


@patch.object(requests.Session, "get")
def test_get_all_repo_names_http_error(mock_get):
    mock_get.return_value.status_code = 500
    mock_get.return_value.text = "error"
    sess = requests.Session()
    names = split_batches._get_all_repo_names(
        sess, "https://api.github.com/orgs/o/repos", "github",
    )
    assert names == []


@patch.object(requests.Session, "get")
def test_get_all_repo_names_network_error(mock_get):
    mock_get.side_effect = requests.RequestException("timeout")
    sess = requests.Session()
    names = split_batches._get_all_repo_names(
        sess, "https://api.github.com/orgs/o/repos", "github",
    )
    assert names == []


@patch.object(requests.Session, "get")
def test_get_all_repo_names_with_token(mock_get):
    """Token should be included in headers/params per platform."""
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [{"name": "r1"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    split_batches._get_all_repo_names(
        sess, "https://api.github.com/orgs/o/repos", "github", token="tok123",
    )
    # Verify Authorization header was set
    call_headers = mock_get.call_args_list[0][1]["headers"]
    assert call_headers["Authorization"] == "token tok123"


@patch.object(requests.Session, "get")
def test_get_all_repo_names_gitee_token(mock_get):
    """Gitee/Gitcode pass token as query param."""
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [{"name": "r1"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    split_batches._get_all_repo_names(
        sess, "https://gitee.com/api/v5/orgs/o/repos", "gitee", token="tok456",
    )
    call_params = mock_get.call_args_list[0][1]["params"]
    assert call_params["access_token"] == "tok456"


# ═══════════════════════════════════════════════════════════════════════════
# list_repos (top-level dispatcher)
# ═══════════════════════════════════════════════════════════════════════════

def test_list_repos_unsupported_platform():
    """Unsupported platform should raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported"):
        split_batches.list_repos(
            requests.Session(), "unknown", "acct", "org",
        )


@patch.object(requests.Session, "get")
def test_list_repos_standard_platform(mock_get):
    """Standard platform (github) calls the right URL."""
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [{"name": "r1"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    repos = split_batches.list_repos(sess, "github", "myorg", "org")
    assert repos == ["r1"]
    # URL should contain orgs/myorg/repos
    call_url = mock_get.call_args_list[0][0][0]
    assert "orgs/myorg/repos" in call_url


@patch.object(requests.Session, "get")
def test_list_repos_gitlab_group(mock_get):
    """GitLab group: first fetch group ID, then list group projects.
    Note: _get_all_repo_names uses 'path' field for GitLab."""
    mock_get.side_effect = [
        # Group lookup
        MagicMock(status_code=200, json=lambda: [
            {"path": "mygroup", "id": 42},
        ]),
        # Projects list page 1
        MagicMock(status_code=200, json=lambda: [{"path": "proj1"}]),
        # Projects list page 2 (empty)
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    repos = split_batches.list_repos(sess, "gitlab", "mygroup", "group", token="tok")
    assert repos == ["proj1"]


@patch.object(requests.Session, "get")
def test_list_repos_gitlab_group_not_found(mock_get):
    """GitLab group not found → empty list."""
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [
            {"path": "other", "id": 99},
        ]),
    ]
    sess = requests.Session()
    repos = split_batches.list_repos(sess, "gitlab", "mygroup", "group", token="tok")
    assert repos == []


@patch.object(requests.Session, "get")
def test_list_repos_gitlab_user(mock_get):
    """GitLab user account type — uses 'path' field."""
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda: [{"path": "uproj"}]),
        MagicMock(status_code=200, json=lambda: []),
    ]
    sess = requests.Session()
    repos = split_batches.list_repos(sess, "gitlab", "myuser", "user")
    assert repos == ["uproj"]
    call_url = mock_get.call_args_list[0][0][0]
    assert "users/myuser/projects" in call_url


# ═══════════════════════════════════════════════════════════════════════════
# main (smoke)
# ═══════════════════════════════════════════════════════════════════════════

@patch.object(requests.Session, "get")
def test_main_end_to_end(mock_get, tmp_path):
    """Full main() with mocked API, writing to tmp_path."""
    output_file = tmp_path / "batches.json"

    with patch("sys.argv", [
        "split_batches.py",
        "--src", "github/myorg",
        "--account-type", "org",
        "--batch-size", "80",
        "--output", str(output_file),
    ]):
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: [
                {"name": f"repo{i}"} for i in range(200)
            ]),
            MagicMock(status_code=200, json=lambda: []),
        ]

        split_batches.main()

    import json
    with open(output_file) as f:
        batches = json.load(f)
    assert len(batches) == 3
    assert len(batches[0].split(",")) == 80


@patch.object(requests.Session, "get")
def test_list_repos_gitlab_group_api_failure(mock_get):
    """GitLab group API RequestException → returns empty list (lines 128-129)."""
    mock_get.side_effect = requests.RequestException("connection refused")
    sess = requests.Session()
    repos = split_batches.list_repos(sess, "gitlab", "mygroup", "group", token="tok")
    assert repos == []


def test_main_no_repos_found():
    """When API returns no repos, main should exit with error (lines 186-187)."""
    with patch("sys.argv", [
        "split_batches.py",
        "--src", "github/myorg",
        "--account-type", "org",
        "--output", "/dev/null",
    ]):
        with patch.object(requests.Session, "get") as mock_get:
            mock_get.side_effect = [
                MagicMock(status_code=200, json=lambda: []),
            ]
            with pytest.raises(SystemExit) as exc_info:
                split_batches.main()
            assert exc_info.value.code == 1


def test_main_github_output_env(tmp_path):
    """When GITHUB_OUTPUT is set, batches should be written there too (lines 208-210)."""
    output_file = tmp_path / "batches.json"
    github_output = tmp_path / "github_output.txt"

    with patch("sys.argv", [
        "split_batches.py",
        "--src", "github/myorg",
        "--account-type", "org",
        "--output", str(output_file),
    ]):
        with patch.dict("os.environ", {"GITHUB_OUTPUT": str(github_output)}):
            with patch.object(requests.Session, "get") as mock_get:
                mock_get.side_effect = [
                    MagicMock(status_code=200, json=lambda: [{"name": "r1"}, {"name": "r2"}]),
                    MagicMock(status_code=200, json=lambda: []),
                ]
                split_batches.main()

    assert github_output.exists()
    content = github_output.read_text()
    assert "r1,r2" in content
