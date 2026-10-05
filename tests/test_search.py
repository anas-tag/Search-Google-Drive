from pathlib import Path

import pytest

from app.search import search


@pytest.fixture
def searchable(library):
    root, database, indexer = library
    folder = root / "Bootloader"
    folder.mkdir()
    (folder / "bootloader.md").write_text("Bootloader : résumé du firmware. bootloader bootloader.", encoding="utf-8")
    (root / "schema.png").write_bytes(b"Bootloader")
    (root / "linux.md").write_text("Le boot démarre, rebootloader continue.", encoding="utf-8")
    indexer.run()
    return root, database


@pytest.mark.parametrize("query", ["bootloader", "Bootloader", "BOOTLOADER"])
def test_case_insensitive(searchable, query):
    _, database = searchable
    assert search(database, query, "content").total == 1


def test_modes_and_deduplication(searchable):
    _, database = searchable
    assert search(database, "bootloader", "all").total == 2
    assert search(database, "bootloader", "files").total == 1
    assert search(database, "bootloader", "directories").total == 1
    assert search(database, "bootloader", "content").total == 1
    assert search(database, "schema", "content").total == 0
    assert search(database, "schema", "files").total == 1


@pytest.mark.parametrize("query", ["résumé", "resume", "RÉSUMÉ"])
def test_accents(searchable, query):
    _, database = searchable
    result = search(database, query, "content")
    assert result.total == 1
    assert "<mark>résumé</mark>" in result.results[0].snippet


def test_prefix_and_exact(searchable):
    _, database = searchable
    assert search(database, "boot", "content").total == 2
    exact = search(database, "boot", "content", exact=True)
    assert exact.total == 1
    assert exact.results[0].filename == "linux.md"
    assert "<mark>boot</mark>" in exact.results[0].snippet
    assert "<mark>rebootloader</mark>" not in exact.results[0].snippet


def test_no_results_and_pagination(searchable):
    _, database = searchable
    assert search(database, "inexistant").total == 0
    first = search(database, "boot", limit=1)
    second = search(database, "boot", limit=1, offset=1)
    assert first.total == second.total == 3
    assert first.results[0].id != second.results[0].id


def test_search_does_not_read_disk(searchable, monkeypatch):
    _, database = searchable

    def no_disk(*args, **kwargs):
        pytest.fail("Search must not read or scan documents")

    monkeypatch.setattr(Path, "read_text", no_disk)
    monkeypatch.setattr(Path, "stat", no_disk)
    assert search(database, "bootloader").total == 2


def test_safe_html_and_snippet(library):
    root, database, indexer = library
    (root / "note.md").write_text("<script>alert('x')</script> bootloader & " + "suite " * 200, encoding="utf-8")
    indexer.run()
    result = search(database, "bootloader").results[0]
    assert "<script>" not in result.snippet
    assert "&lt;script&gt;" in result.snippet
    assert "<mark>bootloader</mark>" in result.snippet
    assert len(result.snippet) < 400


@pytest.mark.parametrize("query", ['bootloader" OR *', 'bootloader NEAR(', "bootloader' --", "bootloader AND"])
def test_fts_operators_are_plain_words(searchable, query):
    _, database = searchable
    search(database, query)  # La ponctuation et les opérateurs ne deviennent pas du SQL/FTS.


def test_punctuation_only_rejected(searchable):
    _, database = searchable
    with pytest.raises(ValueError):
        search(database, "***")


def test_snippet_character_limit_for_long_tokens(library):
    import html
    import re
    root, database, indexer = library
    (root / "long.md").write_text("a" * 2000 + " bootloader " + "b" * 2000, encoding="utf-8")
    indexer.run()
    snippet = search(database, "bootloader").results[0].snippet
    assert "<mark>bootloader</mark>" in snippet
    assert len(html.unescape(re.sub("</?mark>", "", snippet))) <= 254


@pytest.fixture
def format_library(library):
    root, database, indexer = library
    for name in ("guide.md", "guide.PNG", "guide.jpeg", "guide.svg", "guide.PDF", "guide.docx", "guide.xlsx", "guide.txt", "guide.zip", "guide", "unrelated.md"):
        (root / name).write_text("guide content", encoding="utf-8")
    (root / "guide folder").mkdir()
    indexer.run()
    return database


@pytest.mark.parametrize("file_format,total", [("all", 12), ("markdown", 2), ("images", 3), ("pdf", 1), ("documents", 3), ("other", 2)])
def test_file_format_filter(format_library, file_format, total):
    result = search(format_library, "guide", file_format=file_format)
    assert result.total == total
    assert result.format == file_format
    if file_format != "all":
        assert all(item.type != "directory" for item in result.results)


def test_format_filter_applies_before_count_and_pagination(format_library):
    first = search(format_library, "guide", limit=1, file_format="images")
    second = search(format_library, "guide", limit=1, offset=1, file_format="images")
    assert first.total == second.total == 3
    assert first.results[0].id != second.results[0].id
    assert all(item.extension in (".png", ".jpeg", ".svg") for item in first.results + second.results)


def test_markdown_content_and_filename_scopes(format_library):
    assert search(format_library, "guide", "content", file_format="markdown").total == 2
    assert search(format_library, "guide", "files", file_format="markdown").total == 2
    assert search(format_library, "guide", "content", file_format="pdf").total == 0
    assert search(format_library, "guide", "directories", file_format="images").total == 0
    assert search(format_library, "content", file_format="pdf").total == 0


def test_unknown_format_rejected(format_library):
    with pytest.raises(ValueError, match="Format de fichier inconnu"):
        search(format_library, "guide", file_format="bad")


def test_files_find_names_and_content_once_without_snippets(library):
    root, database, indexer = library
    (root / "bootloader.md").write_text("bootloader et firmware", encoding="utf-8")
    (root / "stm32.md").write_text("Configurer le bootloader", encoding="utf-8")
    (root / "bootloader.pdf").write_bytes(b"pdf")
    (root / "bootloader folder").mkdir()
    indexer.run()
    response = search(database, "bootloader", "files")
    assert response.total == 3
    assert {result.filename: result.type for result in response.results} == {
        "bootloader.md": "file", "stm32.md": "file", "bootloader.pdf": "file"
    }
    assert len({item.id for item in response.results}) == 3
    assert all(item.snippet == "" for item in response.results)
    assert "<mark>bootloader</mark>" in search(database, "bootloader", "content").results[0].snippet
    first = search(database, "bootloader", "files", limit=1)
    second = search(database, "bootloader", "files", limit=1, offset=1)
    assert first.total == second.total == response.total
    assert first.results[0].id != second.results[0].id
    pdf = search(database, "bootloader", "files", file_format="pdf")
    assert pdf.total == 1


@pytest.fixture
def literal_library(library):
    root, database, indexer = library
    for name, content in {
        "github-perso.md": "Configuration du dépôt.",
        "github-notes.md": "github : compte perso.",
        "notes.md": "Utilisez GitHub-Perso pour ce dépôt.",
        "space.md": "github perso",
        "reverse.md": "perso github",
        "prefix.md": "github-personnel github perso",
        "embedded.md": "mongithub-perso2 github perso",
        "mixed.md": "github-perso dans le bon contexte, github ailleurs et perso plus loin.",
    }.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "github-perso").mkdir()
    indexer.run()
    return database


@pytest.mark.parametrize("scope,total", [("all", 4), ("files", 3), ("content", 2), ("directories", 1)])
def test_literal_preserves_hyphen_order_and_word_boundaries(literal_library, scope, total):
    response = search(literal_library, "github-perso", scope, literal=True)
    assert response.total == total
    assert not {"github-notes.md", "space.md", "reverse.md", "prefix.md", "embedded.md"}.intersection(item.filename for item in response.results)


def test_literal_highlighting_is_whole_expression_and_correct_excerpt(literal_library):
    results = search(literal_library, "github-perso", "all", literal=True).results
    titled = next(item for item in results if item.filename == "github-perso.md")
    assert titled.filename_highlight == "<mark>github-perso</mark>.md"
    contents = next(item for item in results if item.filename == "notes.md")
    assert "<mark>GitHub-Perso</mark>" in contents.snippet
    mixed = next(item for item in results if item.filename == "mixed.md")
    assert mixed.snippet.count("<mark>") == 1
    assert "<mark>github-perso</mark>" in mixed.snippet


def test_literal_filters_before_pagination_and_keeps_saved_formats(literal_library):
    first = search(literal_library, "github-perso", "files", limit=1, literal=True)
    second = search(literal_library, "github-perso", "files", limit=1, offset=1, literal=True)
    assert first.total == second.total == 3
    assert first.results[0].id != second.results[0].id
    assert all(item.snippet == "" for item in first.results + second.results)
    assert search(literal_library, "github-perso", "files", file_format="pdf", literal=True).total == 0


def test_word_exact_remains_different_from_literal(literal_library):
    assert search(literal_library, "github-perso", "files", exact=True).total > 3
    assert search(literal_library, "github-perso", "files", literal=True).total == 3


def test_literal_escapes_regex_and_html(library):
    root, database, indexer = library
    (root / "note.md").write_text("Recherche <github-perso> et autres github perso.", encoding="utf-8")
    (root / "decoy.md").write_text("github-perso", encoding="utf-8")
    indexer.run()
    response = search(database, "<github-perso>", "content", literal=True)
    assert response.total == 1
    assert "<mark>&lt;github-perso&gt;</mark>" in response.results[0].snippet


def test_literal_respects_exact_spacing(library):
    root, database, indexer = library
    (root / "one.md").write_text("github perso", encoding="utf-8")
    (root / "two.md").write_text("github  perso", encoding="utf-8")
    indexer.run()
    response = search(database, "github  perso", "content", literal=True)
    assert response.total == 1
    assert response.results[0].filename == "two.md"
