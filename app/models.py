from typing import Literal

from pydantic import BaseModel, Field

SearchType = Literal["all", "content", "files", "directories"]
FileFormat = Literal["all", "markdown", "images", "pdf", "documents", "other"]


class IndexReport(BaseModel):
    success: bool = True
    added: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    skipped: int = 0
    warnings: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    id: int
    type: Literal["content", "file", "directory"]
    filename: str
    relative_path: str
    full_path: str
    snippet: str
    filename_highlight: str
    path_highlight: str
    extension: str = ""


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResult]
    limit: int
    offset: int
    format: FileFormat = "all"


class OpenRequest(BaseModel):
    target: Literal["file", "directory"] = "file"
