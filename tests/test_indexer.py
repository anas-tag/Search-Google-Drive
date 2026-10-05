import os
from pathlib import Path

import pytest

from app.database import connect
from app.indexer import IndexBusy, IndexUnavailable
from app.search import search


def test_incremental_lifecycle(library, monkeypatch):
    root, database, indexer = library
    document = root / "résumé.md"
    document.write_text("Le bootloader démarre.", encoding="utf-8")
    assert indexer.run().added == 1
    assert search(database, "bootloader").total == 1
    with connect(database) as db:
        first = dict(db.execute("SELECT * FROM documents").fetchone())
    original = Path.read_text

    def forbid_read(path, *args, **kwargs):
        if path == document:
            pytest.fail("An unchanged Markdown file must not be read")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", forbid_read)
        assert indexer.run().unchanged == 1
    with connect(database) as db:
        assert db.execute("SELECT indexed_at FROM documents").fetchone()[0] == first["indexed_at"]
    document.write_text("Nouveau firmware à charger.", encoding="utf-8")
    assert indexer.run().updated == 1
    assert search(database, "bootloader").total == 0
    assert search(database, "firmware").total == 1
    (root / "nouveau.md").write_text("qemu", encoding="utf-8")
    assert indexer.run().added == 1
    document.unlink()
    assert indexer.run().deleted == 1
    assert search(database, "firmware").total == 0


def test_names_folders_and_bom(library):
    root, database, indexer = library
    folder = root / "Électronique"
    folder.mkdir()
    (folder / "schéma.PNG").write_bytes(b"not markdown")
    (folder / "boot.MD").write_text("œuvre résumé", encoding="utf-8-sig")
    report = indexer.run()
    assert report.added == 3
    assert search(database, "electronique", "directories").total == 1
    assert search(database, "schema", "files").total == 1
    assert search(database, "œuvre", "content").total == 1


def test_invalid_encoding_is_skipped(library, caplog):
    root, database, indexer = library
    (root / "invalid.md").write_bytes(b"\xff\xfe invalid")
    (root / "valid.md").write_text("bootloader", encoding="utf-8")
    report = indexer.run()
    assert report.skipped == 1
    assert not report.success
    assert "Cannot read file" in caplog.text
    assert search(database, "bootloader").total == 1


def test_permission_error_keeps_old_document(library, monkeypatch):
    root, database, indexer = library
    document = root / "note.md"
    document.write_text("ancien", encoding="utf-8")
    indexer.run()
    document.write_text("nouveau contenu", encoding="utf-8")
    original = Path.read_text

    def locked(path, *args, **kwargs):
        if path == document:
            raise PermissionError("locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", locked)
    assert indexer.run().skipped == 1
    assert search(database, "ancien").total == 1


def test_missing_root_preserves_index(library):
    root, database, indexer = library
    (root / "note.md").write_text("bootloader", encoding="utf-8")
    indexer.run()
    root.rename(root.with_name("disconnected"))
    with pytest.raises(IndexUnavailable):
        indexer.run()
    assert search(database, "bootloader").total == 1


def test_partial_scan_does_not_delete(library, monkeypatch):
    root, database, indexer = library
    folder = root / "private"
    folder.mkdir()
    (folder / "note.md").write_text("bootloader", encoding="utf-8")
    indexer.run()

    def incomplete_walk(path, onerror, followlinks):
        onerror(PermissionError(13, "denied", str(folder)))
        yield str(root), ["private"], []

    monkeypatch.setattr(os, "walk", incomplete_walk)
    report = indexer.run()
    assert not report.success
    assert report.deleted == 0
    assert search(database, "bootloader").total == 1


def test_concurrent_index_rejected(library):
    _, _, indexer = library
    indexer._lock.acquire()
    try:
        with pytest.raises(IndexBusy):
            indexer.run()
    finally:
        indexer._lock.release()


def test_database_inside_root_is_not_indexed(library):
    from app.database import initialize
    from app.indexer import Indexer
    root, _, _ = library
    database = root / "search.db"
    initialize(database)
    Indexer(root, database).run()
    with connect(database) as db:
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 0


def test_switching_root_clears_old_index(library, tmp_path):
    from app.indexer import Indexer
    root, database, indexer = library
    (root / "old.md").write_text("ancien", encoding="utf-8")
    indexer.run()
    other = tmp_path / "other"
    other.mkdir()
    (other / "new.md").write_text("nouveau", encoding="utf-8")
    Indexer(other, database).run()
    assert search(database, "ancien").total == 0
    assert search(database, "nouveau").total == 1


def test_file_removed_during_read_does_not_abort(library, monkeypatch):
    root, database, indexer = library
    document = root / "vanishing.md"
    document.write_text("gone", encoding="utf-8")
    (root / "valid.md").write_text("bootloader", encoding="utf-8")
    original = Path.read_text

    def vanishing(path, *args, **kwargs):
        if path == document:
            document.unlink()
            raise FileNotFoundError("removed")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", vanishing)
    assert indexer.run().skipped == 1
    assert search(database, "bootloader").total == 1


def test_root_disappears_during_scan_rolls_back(library, monkeypatch):
    root, database, indexer = library
    (root / "note.md").write_text("bootloader", encoding="utf-8")
    indexer.run()

    def disappearing_walk(path, onerror, followlinks):
        root.rename(root.with_name("disconnected"))
        yield str(root), [], []

    monkeypatch.setattr(os, "walk", disappearing_walk)
    with pytest.raises(IndexUnavailable):
        indexer.run()
    assert search(database, "bootloader").total == 1


def test_progress_counts_unchanged_files(library):
    root, _, indexer = library
    (root / "note.md").write_text("bootloader", encoding="utf-8")
    (root / "folder").mkdir()
    indexer.run()
    assert indexer.run().unchanged == 2
    assert indexer.progress["processed_files"] == 1
    assert indexer.progress["processed_directories"] == 1
    assert indexer.progress["phase"] == "completed"


def test_shutdown_cancellation_preserves_previous_index(library, monkeypatch):
    root, database, indexer = library
    (root / "note.md").write_text("bootloader", encoding="utf-8")
    indexer.run()
    (root / "new.md").write_text("firmware", encoding="utf-8")
    original = Path.read_text

    def cancel_after_read(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        indexer.request_stop()
        return result

    monkeypatch.setattr(Path, "read_text", cancel_after_read)
    with pytest.raises(IndexUnavailable, match="interrompue"):
        indexer.run()
    assert search(database, "bootloader").total == 1
    assert search(database, "firmware").total == 0
