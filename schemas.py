"""Pydantic models aligned with Semantic Scholar API response format."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ── Nested Models ──────────────────────────────────────────────────────


class Author(BaseModel):
    """A paper author."""

    authorId: Optional[str] = None
    name: Optional[str] = None


class OpenAccessPdf(BaseModel):
    """Open-access PDF metadata."""

    url: Optional[str] = None
    status: Optional[str] = None


# ── Paper Model ────────────────────────────────────────────────────────

ALWAYS_RETURNED_FIELDS = {"paperId", "title"}

ALL_PAPER_FIELDS = {
    "paperId",
    "title",
    "abstract",
    "year",
    "authors",
    "venue",
    "citationCount",
    "referenceCount",
    "fieldsOfStudy",
    "publicationTypes",
    "publicationDate",
    "openAccessPdf",
    "externalIds",
    "journal",
}


class Paper(BaseModel):
    """Full paper metadata, S2-compatible."""

    paperId: str
    title: Optional[str] = None
    abstract: Optional[str] = None
    year: Optional[int] = None
    authors: Optional[list[Author]] = None
    venue: Optional[str] = None
    citationCount: Optional[int] = None
    referenceCount: Optional[int] = None
    fieldsOfStudy: Optional[list[str]] = None
    publicationTypes: Optional[list[str]] = None
    publicationDate: Optional[str] = None
    openAccessPdf: Optional[OpenAccessPdf] = None
    externalIds: Optional[dict[str, Any]] = None
    journal: Optional[dict[str, Any]] = None


# ── Field Filtering ────────────────────────────────────────────────────


def parse_fields_param(fields: str | None) -> tuple[set[str] | None, bool]:
    """Parse the fields query parameter.

    Args:
        fields: Raw value from query, e.g. "abstract,year" or "*".

    Returns:
        (requested_fields, all_fields). When all_fields=True, return all metadata.
    """
    if not fields or not fields.strip():
        return None, False
    s = fields.strip().lower()
    if s in ("*", "all"):
        return None, True
    return {f.strip() for f in fields.split(",") if f.strip()}, False


def filter_paper_fields(
    paper: dict[str, Any],
    requested_fields: set[str] | None,
    *,
    all_fields: bool = False,
) -> dict[str, Any]:
    """Strip a paper dict to only the requested fields.

    Args:
        paper: Full paper dict.
        requested_fields: Set of field names the client asked for.
            If None and all_fields=False, only paperId and title are returned.
        all_fields: If True, return all available fields (ignore requested_fields).

    Returns:
        Filtered paper dict (only keys present in the source dict are kept).
    """
    if all_fields:
        return dict(paper)
    if requested_fields is None:
        keep = ALWAYS_RETURNED_FIELDS
    else:
        keep = ALWAYS_RETURNED_FIELDS | (requested_fields & ALL_PAPER_FIELDS)
    return {k: v for k, v in paper.items() if k in keep}
