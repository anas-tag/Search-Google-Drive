import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_review_dates_sorting_pagination_and_reindex(library):
    root, database, indexer = library
    def write(name, stamp):
        path = root / name
        path.write_text("révision", encoding="utf-8")
        seconds = int(datetime.fromisoformat(stamp).timestamp())
        os.utime(path, ns=(seconds * 10**9, seconds * 10**9))

    # Deux jours locaux, à cheval sur le passage à l'heure d'été en France.
    write("before.md", "2026-03-27T22:59:59+00:00")
    write("start.MD", "2026-03-27T23:00:00+00:00")
    write("latest.md", "2026-03-29T21:59:59+00:00")
    write("after.md", "2026-03-29T22:00:00+00:00")
    write("image.txt", "2026-03-29T20:00:00+00:00")
    (root / "folder.md").mkdir()
    indexer.run()
    app = create_app(Settings(root, database))
    with TestClient(app, base_url="http://localhost") as browser:
        params = {"start": "2026-03-28T00:00:00+01:00", "end": "2026-03-30T00:00:00+02:00", "limit": 1}
        response = browser.get("/api/review", params=params)
        assert response.status_code == 200
        first = response.json()
        assert first["total"] == 2
        assert first["results"][0]["filename"] == "latest.md"
        assert first["results"][0]["relative_path"] == "latest.md"
        assert datetime.fromisoformat(first["results"][0]["modified_at"]) == datetime(2026, 3, 29, 21, 59, 59, tzinfo=timezone.utc)
        second = browser.get("/api/review", params={**params, "offset": 1}).json()
        assert second["results"][0]["filename"] == "start.MD"
        assert browser.get("/api/review", params={**params, "offset": 2}).json()["results"] == []
        write("latest.md", "2026-04-01T12:00:00+00:00")
        # L'index reste la source jusqu'au prochain scan.
        assert browser.get("/api/review", params=params).json()["total"] == 2
        indexer.run()
        assert browser.get("/api/review", params=params).json()["total"] == 1
        empty = browser.get("/api/review", params={"start": "2025-01-01T00:00:00Z", "end": "2025-01-02T00:00:00Z"}).json()
        assert empty["total"] == 0


@pytest.mark.parametrize("changes", [
    {"start": "bad"}, {"start": "2026-01-01T00:00:00"},
    {"end": "2026-01-01T00:00:00Z"}, {"end": "2025-01-01T00:00:00Z"},
    {"end": "9999-01-01T00:00:00Z"}, {"limit": 101}, {"offset": -1},
])
def test_review_validation(library, changes):
    root, database, indexer = library
    indexer.run()
    with TestClient(create_app(Settings(root, database)), base_url="http://localhost") as browser:
        response = browser.get("/api/review", params={
            "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z", **changes})
        assert response.status_code == 422
