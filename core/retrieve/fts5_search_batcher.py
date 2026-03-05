"""FTS5 search batcher — now a thin wrapper over connection-pool-backed queries.

Previously used a single background thread to batch FTS5 queries, which became
a bottleneck under load. Now each call runs directly against the connection pool,
allowing full concurrency. The class interface is preserved for compatibility.
"""

from __future__ import annotations

from core.retrieve.sparse import fts5_search, fts5_search_title


class FTS5SearchBatcher:
    """Concurrent FTS5 search using connection pool (no batching needed)."""

    def start(self) -> None:
        """No-op: pool is always ready."""

    def stop(self) -> None:
        """No-op: pool lifecycle managed by db_pool module."""

    def search(
        self, query: str, top_k: int = 100, table: str = "combined",
    ) -> list[tuple[str, float]]:
        """Run an FTS5 search directly via connection pool.

        Args:
            query: Plain-text search query.
            top_k: Number of results to return.
            table: "combined" (title+abstract) or "title" (title only).

        Returns:
            List of (paper_id, score) tuples, sorted by relevance.
        """
        if table == "title":
            return fts5_search_title(query, top_k=top_k)
        return fts5_search(query, top_k=top_k)
