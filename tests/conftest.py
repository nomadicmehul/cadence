"""Test fixtures.

Each test gets a fresh, isolated SQLite database in a temp directory. We
import `app` once, then point its module-level DB_PATH at the temp file and
re-run init_db. This works because every helper in app.py opens a new
connection on demand (no module-level connection to invalidate).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Make sure no parent-process key pollutes the test environment
os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """Import (or re-init) the Flask app against a fresh temp DB."""
    db_path = tmp_path / "pipeline.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    # Import lazily so DB_PATH override happens before init_db runs again
    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module  # noqa: WPS433
    app_module.DB_PATH = db_path
    app_module.DATA_DIR = tmp_path
    app_module.init_db()
    return app_module


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()
