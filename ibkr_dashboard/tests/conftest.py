import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.store import SnapshotStore  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(provider="demo", db_path=tmp_path / "test.sqlite3")


@pytest.fixture
def store(tmp_path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "store.sqlite3")
