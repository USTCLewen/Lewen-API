"""Paper search API router — GET /paper/search with sparse/dense/hybrid modes."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Query, Request

import config
from core.retrieve import Retriever
from schemas import filter_paper_fields, parse_fields_param

router = APIRouter(prefix="/paper", tags=["paper"])

_heavy_ops_semaphore = asyncio.Semaphore(config.HEAVY_OPS_MAX_CONCURRENT)


async def run_heavy_op(executor, func, timeout: float | None = None) -> Any:
    """Run sync func in executor with timeout. Frees semaphore on timeout to avoid backlog.

    Args:
        executor: ThreadPoolExecutor.
        func: Callable (no args) to run.
        timeout: Seconds before raising 504. Uses config.REQUEST_TIMEOUT if None.

    Returns:
        Result of func().

    Raises:
        HTTPException 504: When request exceeds timeout.
    """
    from fastapi import HTTPException

    timeout = timeout or config.REQUEST_TIMEOUT
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(executor, func)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Request timeout")


@router.get("/search/title")
async def search_papers_by_title(
    request: Request,
    query: str = Query(..., description="Plain-text search query for title match."),
    fields: Optional[str] = Query(default=None, description="Comma-separated fields to return. Use fields=* for all metadata."),
    year: Optional[str] = Query(default=None, description="Year or range filter."),
    venue: Optional[str] = Query(default=None, description="Comma-separated venue filter."),
    fieldsOfStudy: Optional[str] = Query(default=None, description="Comma-separated fields of study filter."),
    publicationTypes: Optional[str] = Query(default=None, description="Comma-separated publication type filter."),
    openAccessPdf: Optional[str] = Query(default=None, description="If present, only papers with public PDF."),
    minCitationCount: Optional[int] = Query(default=None, description="Minimum citation count."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
    limit: int = Query(default=config.DEFAULT_LIMIT, ge=1, le=config.MAX_LIMIT, description="Max results."),
) -> dict[str, Any]:
    """Search papers by closest title match to the query."""
    retriever: Retriever = request.app.state.retriever
    executor = request.app.state.executor

    def _run() -> dict[str, Any]:
        return retriever.search_title(
            query,
            year=year,
            venue=venue,
            fields_of_study=fieldsOfStudy,
            publication_types=publicationTypes,
            min_citation_count=minCitationCount,
            open_access_pdf=openAccessPdf is not None,
            limit=limit,
            offset=offset,
        )

    async with _heavy_ops_semaphore:
        result = await run_heavy_op(executor, _run)
    requested_fields, all_fields = parse_fields_param(fields)
    result["data"] = [filter_paper_fields(p, requested_fields, all_fields=all_fields) for p in result["data"]]
    return result


@router.get("/search")
async def search_papers(
    request: Request,
    query: str = Query(..., description="Plain-text search query string."),
    retrieval: str = Query(
        default="hybrid",
        description="Retrieval mode: sparse | dense | hybrid",
    ),
    fields: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated fields to return, e.g. abstract,year,authors. "
            "Use fields=* to return all metadata. Default: paperId and title only."
        ),
    ),
    year: Optional[str] = Query(
        default=None,
        description="Year or range filter. Examples: 2019, 2016-2020, 2010-, -2015",
    ),
    venue: Optional[str] = Query(
        default=None,
        description="Comma-separated venue filter.",
    ),
    fieldsOfStudy: Optional[str] = Query(
        default=None,
        description="Comma-separated fields of study filter.",
    ),
    publicationTypes: Optional[str] = Query(
        default=None,
        description="Comma-separated publication type filter.",
    ),
    openAccessPdf: Optional[str] = Query(
        default=None,
        description="If present, only return papers with a public PDF.",
    ),
    minCitationCount: Optional[int] = Query(
        default=None,
        description="Minimum citation count.",
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
    limit: int = Query(
        default=config.DEFAULT_LIMIT,
        ge=1,
        le=config.MAX_LIMIT,
        description="Max results to return (1-100).",
    ),
) -> dict[str, Any]:
    """Search for papers by relevance.

    Returns:
        S2-format response with total, offset, next, and data.
    """
    retriever: Retriever = request.app.state.retriever

    if retrieval not in ("sparse", "dense", "hybrid"):
        retrieval = "hybrid"

    query_vec = None
    if retrieval in ("dense", "hybrid"):
        batcher = getattr(request.app.state, "embedding_batcher", None)
        if batcher is not None:
            query_vec = await batcher.encode_async(query)

    executor = request.app.state.executor

    def _run() -> dict[str, Any]:
        return retriever.search(
            query,
            retrieval=retrieval,
            query_vec=query_vec,
            year=year,
            venue=venue,
            fields_of_study=fieldsOfStudy,
            publication_types=publicationTypes,
            min_citation_count=minCitationCount,
            open_access_pdf=openAccessPdf is not None,
            limit=limit,
            offset=offset,
        )

    async with _heavy_ops_semaphore:
        result = await run_heavy_op(executor, _run)

    requested_fields, all_fields = parse_fields_param(fields)
    result["data"] = [
        filter_paper_fields(paper, requested_fields, all_fields=all_fields)
        for paper in result["data"]
    ]

    return result
