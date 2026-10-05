"""Connexions courtes et synchronisation transactionnelle de FTS5."""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                relative_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                directory TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('file', 'directory')),
                extension TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                modified_at INTEGER NOT NULL,
                size INTEGER NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                content, filename, directory,
                content='documents', content_rowid='id',
                tokenize='unicode61 remove_diacritics 2', prefix='2 3 4'
            );
            CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, content, filename, directory)
                VALUES (new.id, new.content, new.filename, new.directory);
            END;
            CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, content, filename, directory)
                VALUES ('delete', old.id, old.content, old.filename, old.directory);
            END;
            CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, content, filename, directory)
                VALUES ('delete', old.id, old.content, old.filename, old.directory);
                INSERT INTO documents_fts(rowid, content, filename, directory)
                VALUES (new.id, new.content, new.filename, new.directory);
            END;
        """)
    logger.info("Database initialized: %s (SQLite %s, FTS5)", path, sqlite3.sqlite_version)


def has_saved_index(path: Path, root: Path) -> bool:
    """Reconnaît un scan validé, même si le dossier indexé était vide."""
    with connect(path) as db:
        metadata = dict(db.execute(
            "SELECT key, value FROM metadata WHERE key IN ('root', 'last_indexation')"
        ).fetchall())
    return bool(metadata.get("last_indexation")) and Path(metadata.get("root", "")) == root
