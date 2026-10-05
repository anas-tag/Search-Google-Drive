"""Recherche FTS5 paramétrée, pagination et extraits HTML échappés."""

import html
import re
import uuid
from pathlib import Path

from app.database import connect
from app.formats import FORMAT_EXTENSIONS
from app.models import FileFormat, SearchResponse, SearchResult, SearchType


def literal_pattern(query: str) -> re.Pattern[str]:
    """Expression entière, ponctuation conservée, sans préfixe de mot."""
    return re.compile(r"(?<![^\W_])" + re.escape(query) + r"(?![^\W_])", re.IGNORECASE)


def mark_literal(text: str, pattern: re.Pattern[str], start: str, end: str,
                 excerpt: bool = False) -> str:
    if excerpt:
        match = pattern.search(text)
        if match is None:
            return ""
        context = min(80, max(0, (250 - len(match.group())) // 2))
        left = max(0, match.start() - context)
        right = min(len(text), left + 250)
        window = text[left:right]
        marked = pattern.sub(lambda found: start + found.group() + end, window)
        return ("… " if left else "") + marked + (" …" if right < len(text) else "")
    return pattern.sub(lambda found: start + found.group() + end, text)


def snippet_html(value: str, start: str, end: str) -> str:
    """Fenêtre de 250 caractères, sans couper les balises de surlignage."""
    parts = re.split(f"({re.escape(start)}|{re.escape(end)})", value)
    text = ""
    ranges: list[tuple[int, int]] = []
    match_start = None
    for part in parts:
        if part == start:
            match_start = len(text)
        elif part == end:
            if match_start is not None:
                ranges.append((match_start, len(text)))
                match_start = None
        else:
            text += part
    left = max(0, ranges[0][0] - 80) if ranges else 0
    right = min(len(text), left + 250)
    cursor = left
    output = ["… " if left else ""]
    for first, last in ranges:
        first, last = max(left, first), min(right, last)
        if first >= last:
            continue
        output.extend([html.escape(text[cursor:first]), "<mark>", html.escape(text[first:last]), "</mark>"])
        cursor = last
    output.append(html.escape(text[cursor:right]))
    if right < len(text):
        output.append(" …")
    return "".join(output)


def match_expression(query: str, search_type: SearchType, exact: bool) -> str:
    # L'utilisateur saisit du texte, jamais une expression ou des opérateurs FTS.
    words = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if not words:
        raise ValueError("Saisissez au moins une lettre ou un chiffre.")
    terms = " AND ".join('"' + word + '"' + ("" if exact else "*") for word in words)
    scope = "content" if search_type == "content" else "filename"
    if search_type == "all":
        scope = "{content filename}"
    if search_type == "files":
        return f"(filename : ({terms})) OR (content : ({terms}))"
    return f"{scope} : ({terms})"


def search(database: Path, query: str, search_type: SearchType = "all",
           exact: bool = False, limit: int = 50, offset: int = 0,
           file_format: FileFormat = "all", literal: bool = False) -> SearchResponse:
    expression = match_expression(query, search_type, exact or literal)
    pattern = literal_pattern(query) if literal else None
    start, end = f"__{uuid.uuid4().hex}_start__", f"__{uuid.uuid4().hex}_end__"
    kind = "directory" if search_type == "directories" else "file"
    condition = "1=1" if search_type == "all" else "d.kind=?"
    filter_params: tuple[str, ...] = () if search_type == "all" else (kind,)
    if search_type == "content":
        condition += " AND d.extension='.md'"
    if file_format != "all":
        if file_format == "other":
            extensions = tuple(extension for group in FORMAT_EXTENSIONS.values() for extension in group)
            operator = "NOT IN"
        elif file_format in FORMAT_EXTENSIONS:
            extensions = FORMAT_EXTENSIONS[file_format]
            operator = "IN"
        else:
            raise ValueError("Format de fichier inconnu.")
        placeholders = ",".join("?" for _ in extensions)
        condition += f" AND d.kind='file' AND d.extension {operator} ({placeholders})"
        filter_params += extensions
    # Seules des constantes internes composent SQL, les valeurs sont paramétrées.
    with connect(database) as db:
        if pattern is not None:
            db.create_function("expression_matches", 1, lambda text: int(pattern.search(text) is not None), deterministic=True)
            columns = ("d.content",) if search_type == "content" else ("d.filename",)
            if search_type in ("all", "files"):
                columns = ("d.filename", "d.content")
            condition += " AND (" + " OR ".join(f"expression_matches({column})" for column in columns) + ")"
        content_column = "d.content" if literal else "''"
        total = db.execute(f"""
            SELECT count(*) FROM documents_fts JOIN documents d ON d.id=documents_fts.rowid
            WHERE documents_fts MATCH ? AND {condition}
        """, (expression, *filter_params)).fetchone()[0]
        rows = db.execute(f"""
            SELECT d.id, d.kind, d.filename, d.directory, d.relative_path, d.path, d.extension,
                {content_column} AS literal_content,
                snippet(documents_fts, 0, ?, ?, ' … ', 32) AS excerpt,
                highlight(documents_fts, 1, ?, ?) AS highlighted_name,
                highlight(documents_fts, 2, ?, ?) AS highlighted_directory
            FROM documents_fts JOIN documents d ON d.id=documents_fts.rowid
            WHERE documents_fts MATCH ? AND {condition}
            ORDER BY bm25(documents_fts, 1.0, 5.0, 1.0), d.relative_path COLLATE NOCASE, d.id
            LIMIT ? OFFSET ?
        """, (start, end, start, end, start, end, expression, *filter_params, limit, offset)).fetchall()

    def safe_highlight(value: str) -> str:
        return html.escape(value).replace(start, "<mark>").replace(end, "</mark>")

    results = []
    for row in rows:
        highlighted_name = row["highlighted_name"]
        highlighted_directory = row["highlighted_directory"]
        excerpt = row["excerpt"]
        if pattern is not None:
            highlighted_name = mark_literal(row["filename"], pattern, start, end)
            highlighted_directory = mark_literal(row["directory"], pattern, start, end)
            excerpt = mark_literal(row["literal_content"], pattern, start, end, excerpt=True)
        name = safe_highlight(highlighted_name)
        directory = safe_highlight(highlighted_directory)
        result_type = "directory" if row["kind"] == "directory" else "file"
        if start in excerpt and search_type in ("all", "content") and result_type == "file":
            result_type = "content"
        results.append(SearchResult(
            id=row["id"], type=result_type, filename=row["filename"],
            relative_path=row["relative_path"], full_path=row["path"],
            snippet=snippet_html(excerpt, start, end) if start in excerpt and search_type != "files" else "",
            filename_highlight=name, path_highlight=(directory + " / " if directory else "") + name,
            extension=row["extension"],
        ))
    return SearchResponse(query=query, total=total, results=results, limit=limit, offset=offset,
                          format=file_format)
