"""Application locale. Les opérations disque restent dans le pool de threads."""

import logging
import os
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings
from app.database import connect, has_saved_index, initialize
from app.formats import FORMAT_OPTIONS
from app.indexer import ROOT_ERROR, IndexBusy, Indexer, IndexUnavailable
from app.models import FileFormat, IndexReport, OpenRequest, SearchResponse, SearchType
from app.search import search

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    indexer = Indexer(settings.document_root, settings.database_path)
    csrf_token = secrets.token_urlsafe(32)
    base = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(base / "templates"))
    initial_index_done = threading.Event()

    def initial_index() -> None:
        try:
            indexer.run()
        except (IndexUnavailable, OSError, sqlite3.Error) as error:
            logger.warning("Initial indexing unavailable; serving existing index: %s", error)
            indexer.last_error = str(error)
        finally:
            initial_index_done.set()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
        logger.info("Starting local Markdown search")
        indexer.prepare_start()
        try:
            await run_in_threadpool(initialize, settings.database_path)
            reuse_index = await run_in_threadpool(has_saved_index, settings.database_path, indexer.root)
        except (IndexUnavailable, OSError, sqlite3.Error) as error:
            # L'interface reste accessible pour expliquer l'erreur et réessayer.
            logger.warning("Initial indexing unavailable; serving existing index")
            indexer.last_error = str(error)
            initial_index_done.set()
            yield
            return
        if reuse_index:
            logger.info("Using saved index. Startup scan skipped; use Réindexer to update files.")
            initial_index_done.set()
            try:
                yield
            finally:
                indexer.request_stop()
            return
        initial_index_done.clear()
        worker = threading.Thread(target=initial_index, name="initial-index", daemon=True)
        worker.start()
        try:
            yield
        finally:
            indexer.request_stop()
            await run_in_threadpool(worker.join, 2)

    application = FastAPI(title="Recherche dans les tutoriels", lifespan=lifespan)
    application.state.indexer = indexer
    application.state.initial_index_done = initial_index_done
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    application.mount("/static", StaticFiles(directory=base / "static"), name="static")

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def local_action(request: Request) -> None:
        token = request.headers.get("X-Local-Token", "")
        if not secrets.compare_digest(token, csrf_token):
            raise HTTPException(403, "Action locale non autorisée. Rechargez la page.")
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != request.url.scheme or parsed.netloc != request.headers.get("host"):
                raise HTTPException(403, "Origine de la requête non autorisée.")

    @application.exception_handler(sqlite3.Error)
    async def database_error(request: Request, error: sqlite3.Error):
        logger.error("SQLite error: %s", error)
        return JSONResponse(status_code=503, content={
            "detail": "L'index est temporairement indisponible. Réessayez dans quelques secondes."
        })

    @application.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request=request, name="index.html",
                                          context={"token": csrf_token, "formats": FORMAT_OPTIONS})

    @application.get("/api/search", response_model=SearchResponse)
    def api_search(q: str = Query(min_length=1, max_length=200),
                   type: SearchType = "all", exact: bool = False,
                   limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                   file_format: FileFormat = Query("all", alias="format"), literal: bool = False):
        query = q.strip()
        try:
            return search(settings.database_path, query, type, exact, limit, offset, file_format, literal)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @application.post("/api/reindex", response_model=IndexReport, dependencies=[Depends(local_action)])
    def reindex():
        try:
            if indexer.busy or not initial_index_done.is_set():
                raise IndexBusy("Une indexation est déjà en cours.")
            initialize(settings.database_path)
            return indexer.run()
        except IndexBusy as error:
            raise HTTPException(409, str(error)) from error
        except IndexUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except OSError as error:
            logger.error("Indexing filesystem error: %s", error)
            raise HTTPException(503, "Le dossier est momentanément inaccessible.") from error

    @application.get("/api/status")
    def status():
        with connect(settings.database_path) as db:
            counts = db.execute("""SELECT
                count(CASE WHEN kind='file' THEN 1 END) AS files,
                count(CASE WHEN kind='directory' THEN 1 END) AS directories,
                count(CASE WHEN extension='.md' THEN 1 END) AS markdown FROM documents""").fetchone()
            last = db.execute("SELECT value FROM metadata WHERE key='last_indexation'").fetchone()
        indexing = indexer.busy or not initial_index_done.is_set()
        # Ne pas solliciter le lecteur pendant le scan : le statut doit rester rapide.
        available = True if indexing else indexer.root_available
        return {"indexed_files": counts["files"], "indexed_directories": counts["directories"],
                "indexed_markdown": counts["markdown"], "last_indexation": last[0] if last else None,
                "root": str(indexer.root), "available": available, "indexing": indexing,
                "progress": indexer.progress,
                "error": ROOT_ERROR if not available else indexer.last_error}

    @application.post("/api/open/{document_id}", dependencies=[Depends(local_action)])
    def open_document(document_id: int, action: OpenRequest):
        with connect(settings.database_path) as db:
            row = db.execute("SELECT path, kind FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Ce résultat n'existe plus. Réindexez le dossier.")
        try:
            path = Path(row["path"]).resolve(strict=True)
            if not path.is_relative_to(indexer.root) or path == indexer.root:
                raise HTTPException(403, "Le chemin est en dehors du dossier autorisé.")
            target = path.parent if action.target == "directory" and row["kind"] == "file" else path
            if not target.is_relative_to(indexer.root):
                raise HTTPException(403, "Dossier non autorisé.")
            if not hasattr(os, "startfile"):
                raise HTTPException(501, "L'ouverture locale est disponible uniquement sous Windows.")
            os.startfile(str(target))
        except OSError as error:
            logger.warning("Cannot open indexed document: %s", error)
            raise HTTPException(409, "Impossible d'ouvrir cet élément. Vérifiez sa disponibilité et l'application associée.") from error
        return {"success": True}

    return application


app = create_app()
