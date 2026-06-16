"""Tests for template/update_readme.py — run as subprocess to avoid
module-level import issues."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "template"


def _run_update_readme(results: dict, initial_readme: str, *, cwd: Path) -> str:
    """Run update_readme.py in a subprocess and return the modified README."""
    # Write inputs
    (cwd / "results.json").write_text(json.dumps(results))
    readme_path = cwd / "README.md"
    readme_path.write_text(initial_readme)

    result = subprocess.run(
        [sys.executable, str(TEMPLATE_DIR / "update_readme.py")],
        capture_output=True, text=True, cwd=str(cwd),
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"update_readme.py failed: {result.stderr}")

    return readme_path.read_text()


@pytest.fixture
def workdir(tmp_path):
    """Working directory with a minimal README placeholder."""
    return tmp_path


def test_update_readme_all_success(workdir):
    """When all repos succeed, README should show 'All synced'."""
    results = {
        "total": 3,
        "success": 3,
        "failed": 0,
        "skipped": 0,
        "success_list": ["repo-a", "repo-b", "repo-c"],
        "failed_list": [],
        "skipped_list": [],
        "errors": {},
        "timestamp": "2025-06-01T00:00:00Z",
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
    }
    initial = "before <!-- SYNC_STATUS_START -->\n<!-- SYNC_STATUS_END --> after"
    out = _run_update_readme(results, initial, cwd=workdir)
    assert "All repos synced successfully" in out
    assert "gitcode/openeuler" in out
    assert "github/mirror" in out


def test_update_readme_with_failures(workdir):
    """Failed repos should be listed with error messages from _classify_error."""
    results = {
        "total": 5,
        "success": 3,
        "failed": 2,
        "skipped": 0,
        "success_list": ["a", "b", "c"],
        "failed_list": ["bad-repo", "huge-repo"],
        "skipped_list": [],
        "errors": {
            "bad-repo": {"category": "repo_not_found", "message": "Source repository not found"},
            "huge-repo": {"category": "large_file", "message": "bigfile.iso is 150 MB, exceeds limit"},
        },
        "timestamp": "2025-06-01T00:00:00Z",
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
    }
    initial = "<!-- SYNC_STATUS_START -->\n<!-- SYNC_STATUS_END -->"
    out = _run_update_readme(results, initial, cwd=workdir)
    assert "bad-repo" in out
    assert "huge-repo" in out
    assert "repo_not_found" in out.lower() or "Source repository not found" in out
    assert "Failure Summary" in out
    assert "2 repo(s) failed" in out


def test_update_readme_with_skipped(workdir):
    """Skipped repos should appear in a collapsed section."""
    results = {
        "total": 4,
        "success": 2,
        "failed": 0,
        "skipped": 2,
        "success_list": ["a", "b"],
        "failed_list": [],
        "skipped_list": ["skip-1", "skip-2"],
        "errors": {},
        "timestamp": "2025-06-01T00:00:00Z",
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
    }
    initial = "<!-- SYNC_STATUS_START -->\n<!-- SYNC_STATUS_END -->"
    out = _run_update_readme(results, initial, cwd=workdir)
    assert "skip-1" in out
    assert "skip-2" in out
    assert "Skipped" in out


def test_update_readme_with_diagnoses(workdir):
    """Diagnosis info should appear alongside error messages."""
    results = {
        "total": 1,
        "success": 0,
        "failed": 1,
        "skipped": 0,
        "success_list": [],
        "failed_list": ["sick-repo"],
        "skipped_list": [],
        "errors": {
            "sick-repo": {"category": "clone_failed", "message": "Failed to clone"},
        },
        "diagnoses": {
            "sick-repo": ["Source: accessible", "Cached: not found"],
        },
        "timestamp": "2025-06-01T00:00:00Z",
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
    }
    initial = "<!-- SYNC_STATUS_START -->\n<!-- SYNC_STATUS_END -->"
    out = _run_update_readme(results, initial, cwd=workdir)
    assert "Source: accessible" in out
    assert "Cached: not found" in out


def test_update_readme_collapsed_success(workdir):
    """Success list over 200 should be truncated with '... and N more'."""
    repos = [f"repo-{i}" for i in range(250)]
    results = {
        "total": 250,
        "success": 250,
        "failed": 0,
        "skipped": 0,
        "success_list": repos,
        "failed_list": [],
        "skipped_list": [],
        "errors": {},
        "timestamp": "2025-06-01T00:00:00Z",
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
    }
    initial = "<!-- SYNC_STATUS_START -->\n<!-- SYNC_STATUS_END -->"
    out = _run_update_readme(results, initial, cwd=workdir)
    assert "repo-0" in out
    assert "50 more" in out


def test_update_readme_backward_compat_string_error(workdir):
    """Plain string errors (not dict) should still render."""
    results = {
        "total": 1,
        "success": 0,
        "failed": 1,
        "skipped": 0,
        "success_list": [],
        "failed_list": ["legacy-repo"],
        "skipped_list": [],
        "errors": {"legacy-repo": "something broke"},
        "timestamp": "2025-06-01T00:00:00Z",
        "src": "gitcode/openeuler",
        "dst": "github/mirror",
    }
    initial = "<!-- SYNC_STATUS_START -->\n<!-- SYNC_STATUS_END -->"
    out = _run_update_readme(results, initial, cwd=workdir)
    assert "legacy-repo" in out
    assert "something broke" in out
