"""Resolve multi-format paper_id input to canonical SHA paper_id.

Supports: SHA, arXiv ID, corpus ID, arXiv URL.
See plan Section 11 for full specification.
"""

from __future__ import annotations

import re
import sqlite3

from core.db_pool import pool

_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_CORPUS_PREFIX_RE = re.compile(r"^CorpusId:(\d+)$", re.IGNORECASE)


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """Strip version suffix from arXiv ID (e.g. 2309.06180v1 -> 2309.06180)."""
    s = arxiv_id.strip()
    match = re.match(r"^(\d{4}\.\d{4,5})(v\d+)?$", s)
    if match:
        return match.group(1)
    return s


def _extract_arxiv_from_url(url: str) -> str | None:
    """Extract arXiv ID from arxiv.org URL.

    Args:
        url: Full URL like https://arxiv.org/abs/2309.06180

    Returns:
        Normalized arXiv ID, or None if not parseable.
    """
    match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", url)
    if match:
        return _normalize_arxiv_id(match.group(1))
    return None


def resolve_paper_id(raw_id: str) -> str | None:
    """Resolve a user-provided paper identifier to canonical SHA paper_id.

    Resolution order:
    1. If URL containing arxiv.org -> extract arXiv ID -> lookup
    2. If pure digits or CorpusId:digits -> corpus_id lookup
    3. If matches arXiv ID pattern -> arXiv lookup
    4. Otherwise treat as SHA -> direct lookup

    Args:
        raw_id: User-provided paper identifier string.

    Returns:
        Canonical SHA paper_id if found, else None.
    """
    raw_id = raw_id.strip()
    if not raw_id:
        return None

    with pool.connection(row_factory=True) as conn:
        # 1. arXiv URL
        if "arxiv.org" in raw_id:
            arxiv_id = _extract_arxiv_from_url(raw_id)
            if arxiv_id:
                return _lookup_arxiv(conn, arxiv_id)
            return None

        # 2. Corpus ID (pure digits or CorpusId:digits)
        corpus_match = _CORPUS_PREFIX_RE.match(raw_id)
        if corpus_match:
            cid = int(corpus_match.group(1))
            return _lookup_corpus_id(conn, cid)

        if raw_id.isdigit():
            cid = int(raw_id)
            return _lookup_corpus_id(conn, cid)

        # 3. arXiv ID pattern
        if _ARXIV_ID_RE.match(raw_id):
            return _lookup_arxiv(conn, _normalize_arxiv_id(raw_id))

        # 4. SHA (40-char hex) or other format -> direct lookup
        if _SHA_RE.match(raw_id):
            cur = conn.execute(
                "SELECT paper_id FROM paper_metadata WHERE paper_id = ?",
                (raw_id,),
            )
            row = cur.fetchone()
            return row["paper_id"] if row else None

        return None


def _lookup_arxiv(conn: sqlite3.Connection, arxiv_id: str) -> str | None:
    """Lookup paper_id by normalized arXiv ID."""
    cur = conn.execute(
        "SELECT paper_id FROM arxiv_to_paper WHERE arxiv_id = ?",
        (arxiv_id,),
    )
    row = cur.fetchone()
    return row["paper_id"] if row else None


def _lookup_corpus_id(conn: sqlite3.Connection, corpus_id: int) -> str | None:
    """Lookup paper_id by corpus_id."""
    cur = conn.execute(
        "SELECT paper_id FROM corpus_id_mapping WHERE corpus_id = ?",
        (corpus_id,),
    )
    row = cur.fetchone()
    return row["paper_id"] if row else None
