from pathlib import Path

import pytest

from app.database import initialize
from app.indexer import Indexer


@pytest.fixture
def library(tmp_path: Path):
    root = tmp_path / "Tutoriels accentués"
    root.mkdir()
    database = tmp_path / "search.db"
    initialize(database)
    return root, database, Indexer(root, database)
