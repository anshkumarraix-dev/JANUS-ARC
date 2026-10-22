"""Pytest configuration and shared fixtures for Janus tests."""

import os
import sys
import tempfile
import pytest

# Ensure src directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from janus import storage


@pytest.fixture(autouse=True)
def default_test_identity(monkeypatch):
    """Set default admin identity and demo mode for direct unit tests."""
    monkeypatch.setenv("JANUS_DEMO_MODE", "1")
    monkeypatch.setenv("JANUS_ADMIN_TOKEN", "janus-test-admin-token")
    from janus.auth import current_identity, set_current_identity
    tok = set_current_identity({
        "actor": "test_admin",
        "role": "admin",
        "allowed_seniors": {"*"},
        "token": "janus-test-admin-token",
    })
    yield
    current_identity.reset(tok)


@pytest.fixture
def isolated_db(monkeypatch):
    """Create an isolated temporary SQLite database for each test."""
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test_janus.db")
    monkeypatch.setattr(storage, "DEFAULT_DB_PATH", test_db_path)
    storage.init_db(test_db_path)
    yield test_db_path
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass

