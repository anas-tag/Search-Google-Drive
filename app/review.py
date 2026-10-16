"""Fichiers Markdown triés par dernière modification, depuis l'index."""

from datetime import datetime, timezone
from pathlib import Path

from app.database import connect


def recent_markdown(database: Path, start: datetime, end: datetime,
                    limit: int = 50, offset: int = 0) -> dict:
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("Les dates doivent inclure un fuseau horaire.")
    if start >= end:
        raise ValueError("La fin de période doit être postérieure au début.")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def nanoseconds(value: datetime) -> int:
        delta = value.astimezone(timezone.utc) - epoch
        result = ((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds) * 1000
        if not -(2**63) <= result < 2**63:
            raise ValueError("Cette date est hors de la plage prise en charge.")
        return result

    bounds = (nanoseconds(start), nanoseconds(end))
    where = "kind='file' AND extension='.md' AND modified_at >= ? AND modified_at < ?"
    with connect(database) as db:
        # Une seule vue de l'index pour le compteur et la page, même pendant un scan.
        db.execute("BEGIN")
        total = db.execute(f"SELECT count(*) FROM documents WHERE {where}", bounds).fetchone()[0]
        rows = db.execute(f"""SELECT id, filename, relative_path, modified_at
            FROM documents WHERE {where}
            ORDER BY modified_at DESC, relative_path COLLATE NOCASE, id
            LIMIT ? OFFSET ?""", (*bounds, limit, offset)).fetchall()
    return {"total": total, "limit": limit, "offset": offset, "results": [
        {"id": row["id"], "filename": row["filename"], "relative_path": row["relative_path"],
         "modified_at": datetime.fromtimestamp(row["modified_at"] / 1_000_000_000,
                                               timezone.utc).isoformat()}
        for row in rows
    ]}
