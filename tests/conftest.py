"""
tests/conftest.py

Root test configuration and shared fixtures for FoM Gift Planner.
Ensures repo root is on sys.path and exports synthetic test fixture generators.
"""

from pathlib import Path
import sys
import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fixtures import (
    create_mock_slot,
    create_synthetic_save_entries,
    create_synthetic_save_file,
    get_mock_recipes,
    get_mock_npcs,
    get_mock_meta,
)


@pytest.fixture
def mock_recipes():
    """Provides standard mock recipes dictionary."""
    return get_mock_recipes()


@pytest.fixture
def mock_npcs():
    """Provides standard mock NPC preferences."""
    return get_mock_npcs()


@pytest.fixture
def mock_meta():
    """Provides standard mock item metadata."""
    return get_mock_meta()
