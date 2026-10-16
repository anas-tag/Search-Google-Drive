"""Exercise the actual Windows task script with isolated documents and servers."""

import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest


PROJECT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows task script")


@pytest.fixture
def scheduled_library(tmp_path):
    root = tmp_path / "documents test"
    root.mkdir()
    (root / "note.md").write_text("test indexation automatique", encoding="utf-8")
    database = tmp_path / "search.db"
    env = {**os.environ, "DOCUMENT_ROOT": str(root), "DATABASE_PATH": str(database)}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return root, database, env, port, tmp_path / "reindex.log"


def run_task(library):
    _, _, env, port, log = library
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(PROJECT / "scripts" / "reindex.ps1"),
         "-Port", str(port), "-LogPath", str(log)],
        cwd=PROJECT.parent, env=env, capture_output=True, timeout=90,
    )
    return result, log.read_text(encoding="utf-8-sig")


def listening(port):
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def test_stopped_server_indexes_and_closes(scheduled_library):
    _, database, _, port, _ = scheduled_library
    result, log = run_task(scheduled_library)
    assert result.returncode == 0, (log, result.stderr)
    assert "START:" in log and "OK:" in log and "STOP:" in log
    assert not listening(port)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT filename FROM documents").fetchall() == [("note.md",)]


def test_existing_server_is_kept_running(scheduled_library):
    root, database, env, port, _ = scheduled_library
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port)], cwd=PROJECT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1) as response:
                    if not json.load(response)["indexing"]:
                        break
            except (URLError, OSError):
                pass
            assert time.monotonic() < deadline, "Test server did not become ready"
            time.sleep(0.1)
        (root / "added.md").write_text("nouveau document", encoding="utf-8")
        result, log = run_task(scheduled_library)
        assert result.returncode == 0, (log, result.stderr)
        assert "OK: ajoutes=1" in log
        assert "START:" not in log and "STOP:" not in log
        assert server.poll() is None and listening(port)
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 2
    finally:
        if server.poll() is None:
            subprocess.run(["taskkill.exe", "/PID", str(server.pid), "/T", "/F"],
                           capture_output=True, check=True)
        server.wait(timeout=10)


def test_unavailable_root_reports_failure_and_closes(scheduled_library):
    root, _, env, port, _ = scheduled_library
    env["DOCUMENT_ROOT"] = str(root / "missing")
    result, log = run_task(scheduled_library)
    assert result.returncode == 1, (log, result.stderr)
    assert "START:" in log and "ERROR:" in log and "STOP:" in log
    assert not listening(port)


def test_occupied_port_is_left_alone(scheduled_library):
    _, _, _, port, _ = scheduled_library
    with socket.socket() as other_server:
        other_server.bind(("127.0.0.1", port))
        other_server.listen()
        result, log = run_task(scheduled_library)
        assert result.returncode == 1, (log, result.stderr)
        assert "ERROR:" in log
        assert listening(port)
