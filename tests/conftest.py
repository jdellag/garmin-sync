"""Shared pytest fixtures."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db_path(temp_dir):
    """Create a temporary database path."""
    return temp_dir / "test_garmin.db"
