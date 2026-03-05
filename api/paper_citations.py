"""Paper citations and references API — GET /paper/{id}/citations, /paper/{id}/references.

Simplified: returns only citingPaper/citedPaper objects.
Does NOT return contexts, intents, or isInfluential (not stored).

Performance: Uses batch paper fetch (no N+1) and runs sync DB in thread pool
to avoid blocking the event loop under concurrent load.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request, HTTPException

import config
from api.paper import _heavy_ops_semaphore, run_heavy_op
from core.paper_id_resolver import resolve_paper_id
from core.citation.database import get_papers_by_corpus_ids
from core.citation.lookup import (
    paper_id_to_corpus_id,
    get_citations,
    get_references,
    count_citations,
    count_references,
)
from schemas import filter_paper_fields, parse_fields_param

router = APIRouter(prefix="/paper", tags=["paper-citations"])


def _resolve_to_corpus_id(raw_paper_id: str) -> int | None:
    """Resolve user-provided paper_id to corpus_id."""
    resolved = resolve_paper_id(raw_paper_id)
    if resolved is None:
        return None
    return paper_id_to_corpus_id(resolved)


def _fetch_citations_sync(
    paper_id: str,
    limit: int,
    offset: int,
    requested_fields: set[str] | None,
    all_fields: bool = False,
) -> dict[str, Any] | None:
    """Sync worker: fetch citations. Returns None if paper not found."""
    corpus_id = _resolve_to_corpus_id(paper_id)
    if corpus_id is None:
        return None

    total = count_citations(corpus_id)
    records = get_citations(corpus_id, limit=limit, offset=offset)
    corpus_ids = [r["citing_corpus_id"] for r in records]
    papers = get_papers_by_corpus_ids(corpus_ids)

    data: list[dict[str, Any]] = []
    for rec in records:
        cid = rec["citing_corpus_id"]
        paper = papers.get(cid)
        if paper:
            summary = filter_paper_fields(paper, requested_fields, all_fields=all_fields)
        else:
            summary = {"paperId": None, "title": None}
        data.append({"citingPaper": summary})

    next_offset = offset + limit if offset + limit < total else None
    return {"total": total, "offset": offset, "next": next_offset, "data": data}


def _fetch_references_sync(
    paper_id: str,
    limit: int,
    offset: int,
    requested_fields: set[str] | None,
    all_fields: bool = False,
) -> dict[str, Any] | None:
    """Sync worker: fetch references. Returns None if paper not found."""
    corpus_id = _resolve_to_corpus_id(paper_id)
    if corpus_id is None:
        return None

    total = count_references(corpus_id)
    records = get_references(corpus_id, limit=limit, offset=offset)
    corpus_ids = [r["cited_corpus_id"] for r in records if r.get("cited_corpus_id") is not None]
    papers = get_papers_by_corpus_ids(corpus_ids)

    data: list[dict[str, Any]] = []
    for rec in records:
        cid = rec["cited_corpus_id"]
        paper = papers.get(cid)
        if paper:
            summary = filter_paper_fields(paper, requested_fields, all_fields=all_fields)
        else:
            summary = {"paperId": None, "title": None}
        data.append({"citedPaper": summary})

    next_offset = offset + limit if offset + limit < total else None
    return {"total": total, "offset": offset, "next": next_offset, "data": data}


@router.get("/{paper_id}/citations")
async def get_paper_citations(
    request: Request,
    paper_id: str,
    limit: int = Query(default=10, ge=1, le=config.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    fields: Optional[str] = Query(default=None, description="Comma-separated fields to return. Use fields=* for all metadata."),
) -> dict[str, Any]:
    """Get papers that cite this paper.

    Returns:
        Paginated response with citingPaper objects.
    """
    requested_fields, all_fields = parse_fields_param(fields)

    async with _heavy_ops_semaphore:
        result = await run_heavy_op(
            request.app.state.executor,
            lambda: _fetch_citations_sync(paper_id, limit, offset, requested_fields, all_fields),
        )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Paper not found or no corpus mapping: {paper_id}",
        )
    return result


@router.get("/{paper_id}/references")
async def get_paper_references(
    request: Request,
    paper_id: str,
    limit: int = Query(default=10, ge=1, le=config.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    fields: Optional[str] = Query(default=None, description="Comma-separated fields to return. Use fields=* for all metadata."),
) -> dict[str, Any]:
    """Get papers that this paper cites.

    Returns:
        Paginated response with citedPaper objects.
    """
    requested_fields, all_fields = parse_fields_param(fields)

    async with _heavy_ops_semaphore:
        result = await run_heavy_op(
            request.app.state.executor,
            lambda: _fetch_references_sync(paper_id, limit, offset, requested_fields, all_fields),
        )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Paper not found or no corpus mapping: {paper_id}",
        )
    return result
