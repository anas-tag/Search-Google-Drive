import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import connect
from app.main import create_app


@pytest.fixture
def client(library):
    root, database, _ = library
    (root / "note.md").write_text("bootloader", encoding="utf-8")
    application = create_app(Settings(root, database))
    with TestClient(application, base_url="http://localhost") as client:
        assert application.state.initial_index_done.wait(5)
        yield client, root, database


def action_headers(client):
    html = client.get("/").text
    token = re.search(r'name="local-token" content="([^"]+)"', html)[1]
    return {"X-Local-Token": token, "Origin": "http://localhost"}


def test_home_api_and_manual_index(client):
    browser, root, _ = client
    assert browser.get("/").status_code == 200
    assert browser.get("/static/app.js").status_code == 200
    status = browser.get("/api/status").json()
    assert status["indexed_markdown"] == 1
    assert browser.get("/api/search", params={"q": "bootloader"}).json()["total"] == 1
    (root / "second.md").write_text("bootloader", encoding="utf-8")
    result = browser.post("/api/reindex", headers=action_headers(browser))
    assert result.status_code == 200
    assert result.json()["added"] == 1


@pytest.mark.parametrize("params", [{"q": ""}, {"q": "x" * 201}, {"q": "***"}, {"q": "x", "type": "bad"}, {"q": "x", "limit": 101}, {"q": "x", "offset": -1}])
def test_validation(client, params):
    browser, _, _ = client
    assert browser.get("/api/search", params=params).status_code == 422


def test_local_action_protection(client):
    browser, _, _ = client
    assert browser.post("/api/reindex").status_code == 403
    headers = action_headers(browser)
    headers["Origin"] = "https://evil.example"
    assert browser.post("/api/reindex", headers=headers).status_code == 403
    assert browser.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_open_uses_indexed_id(client, monkeypatch):
    browser, root, _ = client
    opened = []
    monkeypatch.setattr("app.main.os.startfile", opened.append, raising=False)
    item = browser.get("/api/search?q=bootloader").json()["results"][0]
    headers = action_headers(browser)
    assert browser.post(f'/api/open/{item["id"]}', json={"target": "file"}, headers=headers).status_code == 200
    assert Path(opened[-1]) == root / "note.md"
    assert browser.post(f'/api/open/{item["id"]}', json={"target": "directory"}, headers=headers).status_code == 200
    assert Path(opened[-1]) == root
    assert browser.post("/api/open/9999", json={}, headers=headers).status_code == 404


def test_open_outside_root_rejected(client, tmp_path, monkeypatch):
    browser, _, database = client
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    with connect(database) as db:
        db.execute("UPDATE documents SET path=?", (str(outside),))
    monkeypatch.setattr("app.main.os.startfile", lambda _: pytest.fail("Outside path must never open"), raising=False)
    item = browser.get("/api/search?q=bootloader").json()["results"][0]
    assert browser.post(f'/api/open/{item["id"]}', json={}, headers=action_headers(browser)).status_code == 403


def test_missing_drive_still_serves_ui(tmp_path):
    app = create_app(Settings(tmp_path / "missing", tmp_path / "index.db"))
    with TestClient(app, base_url="http://localhost") as browser:
        assert app.state.initial_index_done.wait(5)
        assert browser.get("/").status_code == 200
        assert not browser.get("/api/status").json()["available"]
        response = browser.post("/api/reindex", headers=action_headers(browser))
        assert response.status_code == 503
        assert "Google Drive" in response.json()["detail"]


def test_sqlite_lock_returns_readable_error(client):
    browser, _, database = client
    with connect(database) as db:
        db.execute("BEGIN IMMEDIATE")
        response = browser.post("/api/reindex", headers=action_headers(browser))
        assert response.status_code == 503
        assert "temporairement indisponible" in response.json()["detail"]


def test_permission_denied_on_drive_returns_readable_status(client, monkeypatch):
    browser, root, _ = client
    original = Path.is_dir

    def denied(path):
        if path == root:
            raise PermissionError("Drive unavailable")
        return original(path)

    monkeypatch.setattr(Path, "is_dir", denied)
    status = browser.get("/api/status")
    assert status.status_code == 200
    assert not status.json()["available"]
    assert "Google Drive" in status.json()["error"]
    assert browser.post("/api/reindex", headers=action_headers(browser)).status_code == 503


def test_format_api_and_interface(client):
    browser, root, _ = client
    (root / "bootloader.PNG").write_bytes(b"image")
    (root / "bootloader.pdf").write_bytes(b"pdf")
    browser.post("/api/reindex", headers=action_headers(browser))
    for file_format, extension in (("markdown", ".md"), ("images", ".png"), ("pdf", ".pdf")):
        response = browser.get("/api/search", params={"q": "bootloader", "format": file_format})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["format"] == file_format
        assert response.json()["results"][0]["extension"] == extension
    assert browser.get("/api/search?q=bootloader&format=bad").status_code == 422
    html = browser.get("/").text
    assert 'name="format" value="images"' in html
    assert 'name="format" value="pdf"' in html
    assert 'id="active-format"' in html


def test_page_available_while_initial_index_is_blocked(library, monkeypatch):
    import threading
    root, database, _ = library
    (root / "note.md").write_text("bootloader", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    original = Path.read_text

    def delayed_read(path, *args, **kwargs):
        if path == root / "note.md":
            entered.set()
            assert release.wait(5)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", delayed_read)
    app = create_app(Settings(root, database))
    with TestClient(app, base_url="http://localhost") as browser:
        try:
            assert entered.wait(2)
            assert browser.get("/").status_code == 200
            status = browser.get("/api/status").json()
            assert status["indexing"]
            assert status["progress"]["processed_files"] == 1
            assert status["progress"]["current_path"] == "note.md"
            assert browser.get("/api/search?q=bootloader").status_code == 200
            assert browser.post("/api/reindex", headers=action_headers(browser)).status_code == 409
        finally:
            release.set()
        assert app.state.initial_index_done.wait(5)
        assert not browser.get("/api/status").json()["indexing"]
        assert browser.get("/api/search?q=bootloader").json()["total"] == 1


def test_restart_reuses_index_without_scan_and_manual_reindex_updates(library, monkeypatch):
    import os
    root, database, indexer = library
    (root / "note.md").write_text("ancien bootloader", encoding="utf-8")
    indexer.run()
    (root / "note.md").write_text("nouveau firmware", encoding="utf-8")
    with connect(database) as db:
        last = db.execute("SELECT value FROM metadata WHERE key='last_indexation'").fetchone()[0]
    app = create_app(Settings(root, database))
    with monkeypatch.context() as patch:
        patch.setattr(os, "walk", lambda *args, **kwargs: pytest.fail("Restart must not scan the disk"))
        with TestClient(app, base_url="http://localhost") as browser:
            assert app.state.initial_index_done.is_set()
            status = browser.get("/api/status").json()
            assert not status["indexing"]
            assert status["last_indexation"] == last
            assert browser.get("/api/search?q=bootloader").json()["total"] == 1
            assert browser.get("/api/search?q=firmware").json()["total"] == 0
    with TestClient(app, base_url="http://localhost") as browser:
        response = browser.post("/api/reindex", headers=action_headers(browser))
        assert response.status_code == 200
        assert response.json()["updated"] == 1
        assert browser.get("/api/search?q=firmware").json()["total"] == 1
        assert browser.get("/api/search?q=bootloader").json()["total"] == 0


def test_restart_reuses_empty_index(library, monkeypatch):
    root, database, indexer = library
    indexer.run()
    monkeypatch.setattr("app.main.Indexer.run", lambda _: pytest.fail("An indexed empty folder must not be scanned again"))
    app = create_app(Settings(root, database))
    with TestClient(app, base_url="http://localhost") as browser:
        assert app.state.initial_index_done.is_set()
        assert browser.get("/api/status").json()["indexed_files"] == 0


def test_changing_root_indexes_the_new_folder(library, tmp_path):
    root, database, indexer = library
    (root / "old.md").write_text("ancien", encoding="utf-8")
    indexer.run()
    new_root = tmp_path / "new-root"
    new_root.mkdir()
    (new_root / "new.md").write_text("nouveau", encoding="utf-8")
    app = create_app(Settings(new_root, database))
    with TestClient(app, base_url="http://localhost") as browser:
        assert app.state.initial_index_done.wait(5)
        assert browser.get("/api/search?q=nouveau").json()["total"] == 1
        assert browser.get("/api/search?q=ancien").json()["total"] == 0
