"""Configuration unique, indépendante du répertoire de lancement."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = r"G:\Mon Drive\Fillon Technologies\Résumer\Tutorial"


@dataclass(frozen=True)
class Settings:
    document_root: Path
    database_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_DIR / ".env", encoding="utf-8")
        root = Path(os.environ.get("DOCUMENT_ROOT", DEFAULT_ROOT)).expanduser()
        database = Path(os.environ.get("DATABASE_PATH", "data/search.db")).expanduser()
        return cls(
            root if root.is_absolute() else PROJECT_DIR / root,
            database if database.is_absolute() else PROJECT_DIR / database,
        )
