"""Scan incrémental : les recherches n'appellent jamais cet indexeur."""

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.database import connect
from app.models import IndexReport

logger = logging.getLogger(__name__)
ROOT_ERROR = (
    "Le dossier de documentation est inaccessible. "
    "Vérifiez que Google Drive est démarré et synchronisé."
)


class IndexUnavailable(RuntimeError):
    pass


class IndexBusy(RuntimeError):
    pass


class IndexCancelled(IndexUnavailable):
    pass


class Indexer:
    """Un seul scan simultané, suppression uniquement après un scan complet."""

    def __init__(self, root: Path, database: Path):
        self.root = root.resolve()
        self.database = database
        self._database_resolved = database.resolve()
        self._lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._stop = threading.Event()
        self._progress: dict = {"processed_files": 0, "processed_directories": 0, "current_path": "", "phase": "idle"}
        self.last_error: str | None = None

    @property
    def progress(self) -> dict:
        with self._progress_lock:
            return self._progress.copy()

    def request_stop(self) -> None:
        self._stop.set()

    def prepare_start(self) -> None:
        self._stop.clear()

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise IndexCancelled("Indexation interrompue. Cliquez sur Réindexer pour la relancer.")

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @property
    def root_available(self) -> bool:
        try:
            return self.root.is_dir()
        except OSError:
            return False

    def run(self) -> IndexReport:
        if not self._lock.acquire(blocking=False):
            raise IndexBusy("Une indexation est déjà en cours.")
        with self._progress_lock:
            self._progress = {"processed_files": 0, "processed_directories": 0, "current_path": "", "phase": "scanning"}
        self.last_error = None
        try:
            self._check_stop()
            report = self._scan()
            self.last_error = None if report.success else "Indexation partielle : consultez les avertissements."
            with self._progress_lock:
                self._progress.update(phase="completed", current_path="", **report.model_dump())
            return report
        except (IndexUnavailable, OSError, sqlite3.Error) as error:
            self.last_error = str(error)
            logger.error("[Index] %s", error)
            with self._progress_lock:
                self._progress["phase"] = "cancelled" if isinstance(error, IndexCancelled) else "error"
            raise
        finally:
            self._lock.release()

    def _scan(self) -> IndexReport:
        if not self.root_available:
            raise IndexUnavailable(ROOT_ERROR)
        # Tester l'accès avant toute mutation de l'index.
        try:
            with os.scandir(self.root):
                pass
        except OSError as error:
            raise IndexUnavailable(ROOT_ERROR) from error
        logger.info("[Index] Starting indexing. Root: %s", self.root)
        report = IndexReport()
        seen: set[str] = set()
        complete = True
        now = datetime.now(timezone.utc).isoformat()

        def warning(message: str) -> None:
            logger.warning("[Index] %s", message)
            report.skipped += 1
            # Limiter le volume de la réponse, les détails restent dans les logs.
            if len(report.warnings) < 30:
                report.warnings.append(message)

        def walk_error(error: OSError) -> None:
            nonlocal complete
            complete = False
            warning(f"Cannot scan directory: {error.filename}: {error.strerror}")

        with connect(self.database) as db:
            stored_root = db.execute("SELECT value FROM metadata WHERE key='root'").fetchone()
            if stored_root and stored_root[0] != str(self.root):
                db.execute("DELETE FROM documents")
                db.execute("DELETE FROM metadata")
            existing = {row["path"]: row for row in db.execute(
                "SELECT path, modified_at, size, kind FROM documents"
            )}
            count = 0
            for parent, directories, files in os.walk(self.root, onerror=walk_error, followlinks=False):
                self._check_stop()
                # Ne pas suivre les liens symboliques ni les jonctions Windows.
                directories[:] = [name for name in directories if not self._is_link(Path(parent) / name)]
                for name, kind in [(n, "directory") for n in directories] + [(n, "file") for n in files]:
                    self._check_stop()
                    path = Path(parent) / name
                    if self._is_link(path) or self._is_database(path):
                        continue
                    key = str(path)
                    seen.add(key)
                    count += 1
                    with self._progress_lock:
                        field = "processed_files" if kind == "file" else "processed_directories"
                        self._progress[field] += 1
                        self._progress["current_path"] = path.relative_to(self.root).as_posix()
                    if count % 100 == 0:
                        logger.info("[Index] %d entries processed", count)
                    try:
                        stat = path.stat()
                        old = existing.get(key)
                        if (old and old["modified_at"] == stat.st_mtime_ns
                                and old["size"] == stat.st_size and old["kind"] == kind):
                            report.unchanged += 1
                            continue
                        content = ""
                        extension = path.suffix.lower() if kind == "file" else ""
                        if extension == ".md":
                            content = path.read_text(encoding="utf-8-sig")
                            after = path.stat()
                            if (after.st_mtime_ns, after.st_size) != (stat.st_mtime_ns, stat.st_size):
                                warning(f"File changed while reading, retry next time: {path}")
                                continue
                        relative = path.relative_to(self.root)
                        directory = relative.parent.as_posix() if relative.parent != Path(".") else ""
                        db.execute("""
                            INSERT INTO documents(path, relative_path, filename, directory, kind,
                                extension, content, modified_at, size, indexed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(path) DO UPDATE SET
                                relative_path=excluded.relative_path, filename=excluded.filename,
                                directory=excluded.directory, kind=excluded.kind,
                                extension=excluded.extension, content=excluded.content,
                                modified_at=excluded.modified_at, size=excluded.size,
                                indexed_at=excluded.indexed_at
                        """, (key, relative.as_posix(), name, directory, kind, extension,
                              content, stat.st_mtime_ns, stat.st_size, now))
                        if old:
                            report.updated += 1
                        else:
                            report.added += 1
                    except (OSError, UnicodeError) as error:
                        warning(f"Cannot read file: {path}: {error}")
                    with self._progress_lock:
                        self._progress.update(report.model_dump())
            # Un lecteur démonté ne doit jamais vider un index valide.
            self._check_stop()
            if not self.root_available:
                raise IndexUnavailable(ROOT_ERROR)
            if complete:
                removed = set(existing) - seen
                db.executemany("DELETE FROM documents WHERE path=?", [(p,) for p in removed])
                report.deleted = len(removed)
            report.success = complete and report.skipped == 0
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('root', ?)", (str(self.root),))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_indexation', ?)", (now,))
        logger.info("[Index] Completed: %s", report.model_dump())
        return report

    @staticmethod
    def _is_link(path: Path) -> bool:
        return path.is_symlink() or path.is_junction()

    def _is_database(self, path: Path) -> bool:
        database = self._database_resolved
        return path.name in {
            database.name, database.name + "-wal", database.name + "-shm", database.name + "-journal"
        } and path.parent.resolve() == database.parent
