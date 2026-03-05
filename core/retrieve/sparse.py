"""FTS5 sparse full-text search.

Queries paper_fts_title (title-only) and paper_fts_combined (title+abstract)
for arXiv papers. Used by /paper/search sparse/hybrid and /paper/search/title.
"""

from __future__ import annotations

import re
import sqlite3

from core.db_pool import pool


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a user query for FTS5 MATCH syntax.

    Splits into tokens, wraps each in double quotes to avoid FTS5
    syntax errors from special characters, then joins with space (implicit AND).

    Args:
        query: Raw user query string.

    Returns:
        Sanitized FTS5 query string.
    """
    tokens = re.findall(r"[a-zA-Z0-9]+", query)
    if not tokens:
        return '""'
    return " ".join(f'"{t}"' for t in tokens)


def fts5_search(
    query: str,
    top_k: int = 100,
) -> list[tuple[str, float]]:
    """Search papers via FTS5 BM25 on paper_fts_combined (title+abstract).

    Args:
        query: Plain-text search query.
        top_k: Max results to return.

    Returns:
        List of (paper_id, bm25_score) sorted by relevance.
    """
    fts_query = _sanitize_fts_query(query)
    if fts_query == '""':
        return []

    with pool.connection() as conn:
        try:
            cur = conn.execute(
                """SELECT paper_id, bm25(paper_fts_combined) AS score
                   FROM paper_fts_combined
                   WHERE paper_fts_combined MATCH ?
                   ORDER BY score
                   LIMIT ?""",
                (fts_query, top_k),
            )
            return [(row[0], -row[1]) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []


def fts5_search_title(
    query: str,
    top_k: int = 100,
) -> list[tuple[str, float]]:
    """Search papers by title match via paper_fts_title.

    Args:
        query: Plain-text search query.
        top_k: Max results to return.

    Returns:
        List of (paper_id, bm25_score) sorted by relevance.
    """
    fts_query = _sanitize_fts_query(query)
    if fts_query == '""':
        return []

    with pool.connection() as conn:
        try:
            cur = conn.execute(
                """SELECT paper_id, bm25(paper_fts_title) AS score
                   FROM paper_fts_title
                   WHERE paper_fts_title MATCH ?
                   ORDER BY score
                   LIMIT ?""",
                (fts_query, top_k),
            )
            return [(row[0], -row[1]) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []


def fts5_search_batch(
    requests: list[tuple[str, int, str]],
) -> list[list[tuple[str, float]]]:
    """Batch FTS5 search: run multiple queries in one connection.

    Args:
        requests: List of (query, top_k, table) where table is "combined" or "title".

    Returns:
        List of result lists; each inner list is (paper_id, score) tuples.
    """
    if not requests:
        return []

    with pool.connection() as conn:
        results = []
        for query, top_k, table in requests:
            fts_query = _sanitize_fts_query(query)
            if fts_query == '""':
                results.append([])
                continue
            table_name = "paper_fts_combined" if table == "combined" else "paper_fts_title"
            try:
                cur = conn.execute(
                    f"""SELECT paper_id, bm25({table_name}) AS score
                        FROM {table_name}
                        WHERE {table_name} MATCH ?
                        ORDER BY score
                        LIMIT ?""",
                    (fts_query, top_k),
                )
                results.append([(row[0], -row[1]) for row in cur.fetchall()])
            except sqlite3.OperationalError:
                results.append([])
        return results
