"""
Test fixtures and import helpers.

Scripts under scripts/ use hyphens in filenames (e.g. mirror_repos.py),
which prevents plain ``import``.  Use ``import_script()`` to load them.
"""

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATE_DIR = REPO_ROOT / "template"


def import_script(name: str, *, from_dir: Optional[Path] = None) -> ModuleType:
    """Import a Python file by stem name (no .py), handling hyphens.

    ``import_script("mirror_repos")`` loads ``scripts/mirror_repos.py``.
    """
    if from_dir is None:
        from_dir = SCRIPTS_DIR
    path = from_dir / f"{name}.py"
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")

    module_name = name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sample_hub_args():
    """Return a minimal argparse.Namespace that Hub.__init__ accepts."""
    import argparse
    return argparse.Namespace(
        src="gitcode/openeuler",
        dst="github/openeuler-mirror",
        dst_token="dst-token-123",
        src_token="src-token-456",
        account_type="org",
        api_timeout=60,
        clone_style="ssh",
        # These are used by Mirror, not Hub:
        cache_path="hub-mirror-cache",
        timeout="30m",
        force_update=False,
        lfs=False,
        # Not strictly needed for Hub tests:
        src_account_type="",
        dst_account_type="",
        black_list="",
        white_list="",
        static_list="",
        mappings="",
        list_only=False,
        output="results.json",
        workflow="mirror-repos",
        debug=False,
    )
