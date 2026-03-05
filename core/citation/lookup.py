"""Citation and reference lookup from unified papers.db.

All queries use parameterized statements to prevent SQL injection.
Simplified: citations table only has 3 columns (no contexts/intents/isInfluential).
"""

from __future__ import annotations

from typing import Any

from core.db_pool import pool


def corpus_id_to_paper_id(corpus_id: int) -> str | None:
    """Resolve corpus_id to paper_id (SHA).

    Args:
        corpus_id: S2 CorpusId.

    Returns:
        paper_id if found, else None.
    """
    with pool.connection(row_factory=True) as conn:
        cur = conn.execute(
            "SELECT paper_id FROM corpus_id_mapping WHERE corpus_id = ?",
            (corpus_id,),
        )
        row = cur.fetchone()
        return row["paper_id"] if row else None


def paper_id_to_corpus_id(paper_id: str) -> int | None:
    """Resolve paper_id (SHA) to corpus_id.

    Args:
        paper_id: S2 paperId (SHA).

    Returns:
        corpus_id if found, else None.
    """
    with pool.connection(row_factory=True) as conn:
        cur = conn.execute(
            "SELECT corpus_id FROM corpus_id_mapping WHERE paper_id = ?",
            (paper_id,),
        )
        row = cur.fetchone()
        return row["corpus_id"] if row else None


def _get_counts_from_metadata(corpus_id: int) -> tuple[int | None, int | None]:
    """Get citation_count and reference_count from paper_metadata (O(1) lookup).

    Returns (citation_count, reference_count); either may be None if not in metadata.
    """
    with pool.connection(row_factory=True) as conn:
        cur = conn.execute(
            "SELECT citation_count, reference_count FROM paper_metadata WHERE corpus_id = ?",
            (corpus_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None, None
        return row["citation_count"], row["reference_count"]


def count_citations(corpus_id: int) -> int:
    """Count papers that cite this paper.

    Uses paper_metadata.citation_count when available (O(1)); falls back to
    COUNT(*) on citations for papers not in metadata.
    """
    cite_count, _ = _get_counts_from_metadata(corpus_id)
    if cite_count is not None:
        return cite_count
    with pool.connection() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM citations WHERE cited_corpus_id = ?",
            (corpus_id,),
        )
        return cur.fetchone()[0]


def count_references(corpus_id: int) -> int:
    """Count papers that this paper cites.

    Uses paper_metadata.reference_count when available (O(1)); falls back to
    COUNT(*) on citations for papers not in metadata.
    """
    _, ref_count = _get_counts_from_metadata(corpus_id)
    if ref_count is not None:
        return ref_count
    with pool.connection() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM citations WHERE citing_corpus_id = ?",
            (corpus_id,),
        )
        return cur.fetchone()[0]


def get_citations(
    corpus_id: int,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Get citing_corpus_ids for papers that cite this paper.

    Args:
        corpus_id: Cited paper's corpus_id.
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of dicts with citing_corpus_id.
    """
    with pool.connection(row_factory=True) as conn:
        cur = conn.execute(
            """SELECT citing_corpus_id
               FROM citations
               WHERE cited_corpus_id = ?
               ORDER BY citation_id
               LIMIT ? OFFSET ?""",
            (corpus_id, limit, offset),
        )
        return [{"citing_corpus_id": row["citing_corpus_id"]} for row in cur.fetchall()]


def get_references(
    corpus_id: int,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Get cited_corpus_ids for papers that this paper cites.

    Args:
        corpus_id: Citing paper's corpus_id.
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of dicts with cited_corpus_id.
    """
    with pool.connection(row_factory=True) as conn:
        cur = conn.execute(
            """SELECT cited_corpus_id
               FROM citations
               WHERE citing_corpus_id = ? AND cited_corpus_id IS NOT NULL
               ORDER BY citation_id
               LIMIT ? OFFSET ?""",
            (corpus_id, limit, offset),
        )
        return [{"cited_corpus_id": row["cited_corpus_id"]} for row in cur.fetchall()]
