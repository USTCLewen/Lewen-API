"""Hybrid retriever: sparse (FTS5) + dense (Qdrant) with RRF fusion.

Supports three retrieval modes: sparse, dense, hybrid (default).
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

import config
from core.retrieve.sparse import fts5_search, fts5_search_title
from core.retrieve.dense import vector_search
from core.retrieve.embedding import encode
from core.citation.database import get_papers_by_ids

if TYPE_CHECKING:
    from core.retrieve.dense_search_batcher import DenseSearchBatcher
    from core.retrieve.fts5_search_batcher import FTS5SearchBatcher


def _rrf_fuse(
    ranked_lists: list[list[str]],
    k: int = config.RRF_K,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over multiple ranked ID lists.

    Args:
        ranked_lists: Each inner list contains paper_ids in rank order.
        k: RRF constant (default 60).

    Returns:
        List of (paper_id, fused_score) sorted by score desc.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, pid in enumerate(ranked, start=1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _parse_year_range(year_str: str) -> tuple[int | None, int | None]:
    """Parse S2-style year filter string.

    Supports: ``2019``, ``2016-2020``, ``2010-``, ``-2015``.

    Args:
        year_str: Year filter expression.

    Returns:
        (year_min, year_max) — either may be None for open-ended.
    """
    year_str = year_str.strip()
    if "-" not in year_str:
        y = int(year_str)
        return y, y
    parts = year_str.split("-", 1)
    lo = int(parts[0]) if parts[0] else None
    hi = int(parts[1]) if parts[1] else None
    return lo, hi


def _apply_metadata_filters(
    paper: dict[str, Any],
    *,
    year: str | None = None,
    venue: str | None = None,
    fields_of_study: str | None = None,
    publication_types: str | None = None,
    min_citation_count: int | None = None,
    open_access_pdf: bool = False,
) -> bool:
    """Return True if the paper passes all requested filters.

    Args:
        paper: S2-style paper dict.
        year: Year range filter string.
        venue: Comma-separated venue names.
        fields_of_study: Comma-separated fields of study.
        publication_types: Comma-separated publication types.
        min_citation_count: Minimum citation count.
        open_access_pdf: If True, require an open-access PDF.

    Returns:
        True if the paper satisfies all active filters.
    """
    if year:
        lo, hi = _parse_year_range(year)
        paper_year = paper.get("year")
        if paper_year is None:
            return False
        if lo is not None and paper_year < lo:
            return False
        if hi is not None and paper_year > hi:
            return False

    if venue:
        venues_lower = {v.strip().lower() for v in venue.split(",")}
        paper_venue = (paper.get("venue") or "").lower()
        if not any(v in paper_venue for v in venues_lower):
            return False

    if fields_of_study:
        required = {f.strip().lower() for f in fields_of_study.split(",")}
        paper_fos = {f.lower() for f in (paper.get("fieldsOfStudy") or [])}
        if not required & paper_fos:
            return False

    if publication_types:
        required = {t.strip() for t in publication_types.split(",")}
        paper_types = set(paper.get("publicationTypes") or [])
        if not required & paper_types:
            return False

    if min_citation_count is not None:
        if (paper.get("citationCount") or 0) < min_citation_count:
            return False

    if open_access_pdf:
        pdf = paper.get("openAccessPdf")
        if not pdf or not pdf.get("url"):
            return False

    return True


def _fetch_and_filter(
    ranked: list[str],
    *,
    year: Optional[str] = None,
    venue: Optional[str] = None,
    fields_of_study: Optional[str] = None,
    publication_types: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    open_access_pdf: bool = False,
) -> list[dict[str, Any]]:
    """Batch fetch papers by paper_ids and apply metadata filters.

    Preserves order of ranked list. Returns only papers that pass filters.
    """
    if not ranked:
        return []
    papers_map = get_papers_by_ids(ranked)
    filtered: list[dict[str, Any]] = []
    for pid in ranked:
        paper = papers_map.get(pid)
        if paper is None:
            continue
        if _apply_metadata_filters(
            paper,
            year=year,
            venue=venue,
            fields_of_study=fields_of_study,
            publication_types=publication_types,
            min_citation_count=min_citation_count,
            open_access_pdf=open_access_pdf,
        ):
            filtered.append(paper)
    return filtered


class Retriever:
    """Orchestrates sparse/dense/hybrid retrieval with filtering."""

    def __init__(
        self,
        search_batcher: "DenseSearchBatcher | None" = None,
        fts5_batcher: "FTS5SearchBatcher | None" = None,
    ) -> None:
        """Initialize retriever.

        Args:
            search_batcher: Optional batcher for dense search. When set, uses
                batch Qdrant search instead of per-request vector_search.
            fts5_batcher: Optional batcher for FTS5 sparse search. When set, uses
                batch FTS5 search instead of per-request fts5_search/fts5_search_title.
        """
        self._search_batcher = search_batcher
        self._fts5_batcher = fts5_batcher

    def search(
        self,
        query: str,
        *,
        retrieval: str = "hybrid",
        query_vec: Optional[list[float]] = None,
        year: Optional[str] = None,
        venue: Optional[str] = None,
        fields_of_study: Optional[str] = None,
        publication_types: Optional[str] = None,
        min_citation_count: Optional[int] = None,
        open_access_pdf: bool = False,
        limit: int = config.DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Retrieve papers with the specified retrieval mode.

        Args:
            query: Plain-text search query string.
            retrieval: One of "sparse", "dense", "hybrid".
            query_vec: Pre-computed dense embedding. If None and dense/hybrid,
                encode() is called (blocking). Pass from EmbeddingBatcher for async batching.
            year: Year range filter.
            venue: Comma-separated venue filter.
            fields_of_study: Comma-separated fields of study filter.
            publication_types: Comma-separated publication type filter.
            min_citation_count: Minimum citation count filter.
            open_access_pdf: If True, only return papers with open-access PDF.
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            Dict with keys: total, offset, next, data.
        """
        fetch_k = min(max(limit + offset + 50, 200), 1000)

        sparse_ranked: list[str] = []
        dense_ranked: list[str] = []

        if retrieval in ("sparse", "hybrid"):
            if self._fts5_batcher is not None:
                sparse_results = self._fts5_batcher.search(query, top_k=fetch_k, table="combined")
            else:
                sparse_results = fts5_search(query, top_k=fetch_k)
            sparse_ranked = [pid for pid, _ in sparse_results]

        if retrieval in ("dense", "hybrid"):
            if query_vec is not None:
                vec = query_vec
            else:
                vec = encode([query])[0].tolist()
            if self._search_batcher is not None:
                dense_results = self._search_batcher.search(vec, top_k=fetch_k)
            else:
                dense_results = vector_search(vec, top_k=fetch_k)
            dense_ranked = [pid for pid, _ in dense_results]

        if retrieval == "sparse":
            fused = [(pid, 1.0 / (i + 1)) for i, pid in enumerate(sparse_ranked)]
        elif retrieval == "dense":
            fused = [(pid, 1.0 / (i + 1)) for i, pid in enumerate(dense_ranked)]
        else:
            ranked_lists = []
            if sparse_ranked:
                ranked_lists.append(sparse_ranked)
            if dense_ranked:
                ranked_lists.append(dense_ranked)
            fused = _rrf_fuse(ranked_lists) if ranked_lists else []

        ranked = [pid for pid, _ in fused]
        filtered = _fetch_and_filter(
            ranked,
            year=year,
            venue=venue,
            fields_of_study=fields_of_study,
            publication_types=publication_types,
            min_citation_count=min_citation_count,
            open_access_pdf=open_access_pdf,
        )

        total = len(filtered)
        page = filtered[offset: offset + limit]
        next_offset = offset + limit if offset + limit < total else None

        return {
            "total": total,
            "offset": offset,
            "next": next_offset,
            "data": page,
        }

    def search_title(
        self,
        query: str,
        *,
        year: Optional[str] = None,
        venue: Optional[str] = None,
        fields_of_study: Optional[str] = None,
        publication_types: Optional[str] = None,
        min_citation_count: Optional[int] = None,
        open_access_pdf: bool = False,
        limit: int = config.DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Retrieve papers by title match (paper_fts_title).

        Args:
            query: Plain-text search query.
            year: Year range filter.
            venue: Comma-separated venue filter.
            fields_of_study: Comma-separated fields of study filter.
            publication_types: Comma-separated publication type filter.
            min_citation_count: Minimum citation count filter.
            open_access_pdf: If True, only return papers with open-access PDF.
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            Dict with keys: total, offset, next, data.
        """
        fetch_k = min(max(limit + offset + 50, 200), 1000)
        if self._fts5_batcher is not None:
            results = self._fts5_batcher.search(query, top_k=fetch_k, table="title")
        else:
            results = fts5_search_title(query, top_k=fetch_k)
        ranked = [pid for pid, _ in results]
        filtered = _fetch_and_filter(
            ranked,
            year=year,
            venue=venue,
            fields_of_study=fields_of_study,
            publication_types=publication_types,
            min_citation_count=min_citation_count,
            open_access_pdf=open_access_pdf,
        )
        total = len(filtered)
        page = filtered[offset: offset + limit]
        next_offset = offset + limit if offset + limit < total else None
        return {
            "total": total,
            "offset": offset,
            "next": next_offset,
            "data": page,
        }
