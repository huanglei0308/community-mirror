"""Tests for merge_results.py — merge logic and download."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from tests.conftest import import_script

merge_results = import_script("merge_results")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers to build sample results dicts
# ═══════════════════════════════════════════════════════════════════════════

def _existing():
    return {
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
        "timestamp": "2025-01-01T00:00:00Z",
        "total": 4,
        "success": 2,
        "failed": 1,
        "skipped": 1,
        "success_list": ["repo-a", "repo-b"],
        "failed_list": ["repo-c"],
        "skipped_list": ["repo-d"],
        "errors": {"repo-c": {"category": "large_file", "message": "big"}},
        "diagnoses": {"repo-c": ["Source: accessible"]},
        "workflows": {
            "mirror-repos": {
                "timestamp": "2025-01-01T00:00:00Z",
                "total": 4,
                "success": 2,
                "failed": 1,
                "skipped": 1,
            }
        },
    }


def _current():
    return {
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
        "workflow": "large-repo",
        "timestamp": "2025-01-02T00:00:00Z",
        "total": 3,
        "success": 2,
        "failed": 0,
        "skipped": 1,
        "success_list": ["repo-a", "repo-e"],
        "failed_list": [],
        "skipped_list": ["repo-c"],
        "errors": {},
        "diagnoses": {},
    }


# ═══════════════════════════════════════════════════════════════════════════
# download_existing
# ═══════════════════════════════════════════════════════════════════════════

@patch.object(requests, "get")
def test_download_existing_ok(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"total": 10}
    result = merge_results.download_existing("https://example.com/results.json")
    assert result == {"total": 10}


@patch.object(requests, "get")
def test_download_existing_404(mock_get):
    mock_get.return_value.status_code = 404
    result = merge_results.download_existing("https://example.com/results.json")
    assert result is None


@patch.object(requests, "get")
def test_download_existing_network_error(mock_get):
    mock_get.side_effect = requests.ConnectionError("unreachable")
    result = merge_results.download_existing("https://example.com/results.json")
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# merge
# ═══════════════════════════════════════════════════════════════════════════

def test_merge_basic():
    existing = _existing()
    current = _current()
    result = merge_results.merge(existing, current)

    # Current success takes precedence
    assert "repo-e" in result["success_list"]
    assert "repo-a" in result["success_list"]


def test_merge_current_overrides_existing():
    """Current workflow's success should override existing failed status."""
    existing = {
        "timestamp": "",
        "failed_list": ["repo-x"],
        "errors": {"repo-x": {"category": "timeout", "message": "timeout"}},
    }
    current = {
        "timestamp": "2025-01-01T00:00:00Z",
        "success_list": ["repo-x"],
        "errors": {},
    }
    result = merge_results.merge(existing, current)
    assert "repo-x" in result["success_list"]
    assert "repo-x" not in result["failed_list"]
    # Error should be cleared since repo is now success
    assert "repo-x" not in result["errors"]


def test_merge_skipped_does_not_override_success():
    """Skipped in current must NOT override success from existing."""
    existing = {
        "timestamp": "2025-01-01T00:00:00Z",
        "success_list": ["repo-y"],
    }
    current = {
        "timestamp": "2025-01-02T00:00:00Z",
        "skipped_list": ["repo-y"],
    }
    result = merge_results.merge(existing, current)
    assert "repo-y" in result["success_list"]
    assert "repo-y" not in result["skipped_list"]


def test_merge_skipped_does_not_override_failed():
    """Skipped in current must NOT override failed from existing."""
    existing = {
        "timestamp": "2025-01-01T00:00:00Z",
        "failed_list": ["repo-y"],
        "errors": {"repo-y": {"category": "timeout", "message": "..."}},
    }
    current = {
        "timestamp": "2025-01-02T00:00:00Z",
        "skipped_list": ["repo-y"],
    }
    result = merge_results.merge(existing, current)
    assert "repo-y" in result["failed_list"]
    assert "repo-y" not in result["skipped_list"]


def test_merge_skipped_can_override_skipped():
    """Skipped CAN override another skipped (no info lost)."""
    existing = {"timestamp": "", "skipped_list": ["repo-z"]}
    current = {"timestamp": "2025-01-01T00:00:00Z", "skipped_list": ["repo-z"]}
    result = merge_results.merge(existing, current)
    assert "repo-z" in result["skipped_list"]


def test_merge_skipped_can_set_new():
    """Skipped for an unknown repo should be recorded."""
    existing = {}
    current = {"timestamp": "2025-01-01T00:00:00Z", "skipped_list": ["new-repo"]}
    result = merge_results.merge(existing, current)
    assert "new-repo" in result["skipped_list"]


def test_merge_errors_merged():
    """Current errors update existing, and success clears errors."""
    existing = {
        "timestamp": "2025-01-01T00:00:00Z",
        "failed_list": ["r1", "r2"],
        "success_list": [],
        "errors": {"r1": {"category": "timeout", "message": "t"}, "r2": {"category": "large_file", "message": "b"}},
    }
    current = {
        "timestamp": "2025-01-02T00:00:00Z",
        "failed_list": ["r1"],
        "success_list": ["r2"],
        "errors": {"r1": {"category": "rate_limited", "message": "rl"}},
    }
    result = merge_results.merge(existing, current)
    assert result["errors"]["r1"]["category"] == "rate_limited"  # updated
    assert "r2" not in result["errors"]  # cleared (now success)


def test_merge_diagnoses_merged():
    """Diagnoses should merge and clear for success repos."""
    existing = {
        "timestamp": "2025-01-01T00:00:00Z",
        "failed_list": ["r1"],
        "diagnoses": {"r1": ["old diag"]},
    }
    current = {
        "timestamp": "2025-01-02T00:00:00Z",
        "success_list": ["r1"],
        "diagnoses": {"r1": ["new diag"]},
    }
    result = merge_results.merge(existing, current)
    assert "r1" not in result["diagnoses"]  # cleared (now success)


def test_merge_workflows_accumulated():
    existing = {
        "workflows": {
            "mirror-repos": {"timestamp": "t1", "total": 5},
        }
    }
    current = {
        "workflow": "large-repo",
        "timestamp": "t2",
        "total": 3,
        "success": 2,
        "failed": 0,
        "skipped": 1,
    }
    result = merge_results.merge(existing, current)
    assert "mirror-repos" in result["workflows"]
    assert "large-repo" in result["workflows"]
    assert result["workflows"]["large-repo"]["total"] == 3


def test_merge_timestamp_picks_latest():
    existing = {"timestamp": "2025-01-01T00:00:00Z"}
    current = {"timestamp": "2025-06-01T00:00:00Z"}
    result = merge_results.merge(existing, current)
    assert result["timestamp"] == "2025-06-01T00:00:00Z"


def test_merge_timestamp_from_workflows():
    """Latest timestamp across all workflows should be used."""
    existing = {
        "workflows": {
            "wf1": {"timestamp": "2025-12-01T00:00:00Z"},
        }
    }
    current = {"timestamp": "2025-06-01T00:00:00Z"}
    result = merge_results.merge(existing, current)
    assert result["timestamp"] == "2025-12-01T00:00:00Z"


def test_merge_empty_existing():
    """Merge with empty existing dict."""
    result = merge_results.merge({}, _current())
    assert result["total"] == 3
    assert result["success"] == 2
    assert result["skipped"] == 1


def test_merge_empty_current():
    """Merge with empty-ish current."""
    existing = _existing()
    current = {"workflow": "empty"}
    result = merge_results.merge(existing, current)
    assert result["total"] == 4  # preserved from existing


def test_merge_repo_in_multiple_lists():
    """Repo appears only in the highest-priority status."""
    existing = {"timestamp": "", "success_list": ["dup"]}
    current = {"timestamp": "2025-01-01T00:00:00Z",
               "failed_list": ["dup"],
               "errors": {"dup": {"category": "timeout", "message": "t"}}}
    result = merge_results.merge(existing, current)
    # current failed overrides existing success
    assert "dup" in result["failed_list"]
    assert "dup" not in result["success_list"]


def test_merge_counts_match_lists():
    """Total, success, failed, skipped counts must match their list lengths."""
    result = merge_results.merge(_existing(), _current())
    assert result["total"] == len(result["success_list"]) + len(result["failed_list"]) + len(result["skipped_list"])
    assert result["success"] == len(result["success_list"])
    assert result["failed"] == len(result["failed_list"])
    assert result["skipped"] == len(result["skipped_list"])


def test_merge_lists_are_sorted():
    existing = {"timestamp": "", "failed_list": ["z", "a"], "errors": {"z": {}, "a": {}}}
    current = {"timestamp": "2025-01-01T00:00:00Z"}
    result = merge_results.merge(existing, current)
    assert result["failed_list"] == ["a", "z"]


# ═══════════════════════════════════════════════════════════════════════════
# main (smoke)
# ═══════════════════════════════════════════════════════════════════════════

def test_main_no_merge_url(tmp_path):
    """main without --merge-url should just pass through current."""
    import json
    current_file = tmp_path / "current.json"
    current_file.write_text(json.dumps({"total": 1, "success_list": ["r1"]}))
    output_file = tmp_path / "output.json"

    with patch("sys.argv", [
        "merge_results.py", str(current_file),
        "--output", str(output_file),
    ]):
        merge_results.main()

    with open(output_file) as f:
        data = json.load(f)
    assert data["total"] == 1


@patch.object(merge_results, "download_existing")
def test_main_with_merge_url(mock_download, tmp_path):
    """main with --merge-url should merge."""
    import json
    current_file = tmp_path / "current.json"
    current_file.write_text(json.dumps({
        "workflow": "large-repo",
        "timestamp": "2025-02-01T00:00:00Z",
        "success_list": ["repo-new"],
        "failed_list": [],
        "skipped_list": [],
    }))
    output_file = tmp_path / "output.json"

    mock_download.return_value = {
        "success_list": ["repo-old"],
        "failed_list": [],
        "skipped_list": [],
        "timestamp": "2025-01-01T00:00:00Z",
        "errors": {},
        "diagnoses": {},
        "workflows": {},
    }

    with patch("sys.argv", [
        "merge_results.py", str(current_file),
        "--merge-url", "https://example.com/old.json",
        "--output", str(output_file),
    ]):
        merge_results.main()

    with open(output_file) as f:
        data = json.load(f)
    assert "repo-new" in data["success_list"]
    assert "repo-old" in data["success_list"]
    assert data["total"] == 2


@patch.object(merge_results, "download_existing")
def test_main_merge_url_download_fails(mock_download, tmp_path):
    """When download_existing returns None, pass through current (lines 159-160)."""
    import json
    current_file = tmp_path / "current.json"
    current_file.write_text(json.dumps({
        "workflow": "mirror-repos",
        "timestamp": "2025-06-01T00:00:00Z",
        "total": 1,
        "success": 0,
        "failed": 1,
        "skipped": 0,
        "success_list": [],
        "failed_list": ["r1"],
        "skipped_list": [],
    }))
    output_file = tmp_path / "output.json"

    mock_download.return_value = None

    with patch("sys.argv", [
        "merge_results.py", str(current_file),
        "--merge-url", "https://example.com/old.json",
        "--output", str(output_file),
    ]):
        merge_results.main()

    with open(output_file) as f:
        data = json.load(f)
    assert data["failed"] == 1
    assert data["total"] == 1
