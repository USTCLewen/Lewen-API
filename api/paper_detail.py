"""Paper detail API — GET /paper/{paper_id}."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Query, Request, HTTPException

from api.paper import _heavy_ops_semaphore, run_heavy_op
from core.paper_id_resolver import resolve_paper_id
from core.citation.database import get_paper_by_paper_id
from schemas import filter_paper_fields, parse_fields_param

router = APIRouter(prefix="/paper", tags=["paper-detail"])


def _fetch_paper_detail_sync(paper_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Sync: resolve and fetch paper. Returns (paper_dict, error_detail)."""
    resolved = resolve_paper_id(paper_id)
    if resolved is None:
        return None, f"Paper not found: {paper_id}"
    paper = get_paper_by_paper_id(resolved)
    if paper is None:
        return None, f"Paper not found: {paper_id}"
    return paper, None


@router.get("/{paper_id}")
async def get_paper_detail(
    request: Request,
    paper_id: str,
    fields: Optional[str] = Query(
        default=None,
        description="Comma-separated fields to return. Use fields=* for all metadata.",
    ),
) -> dict[str, Any]:
    """Get full metadata for a single paper.

    Supports SHA, arXiv ID, corpus ID, and arXiv URL as paper_id input.

    Raises:
        HTTPException 404: Paper not found.
    """
    async with _heavy_ops_semaphore:
        paper, err = await run_heavy_op(
            request.app.state.executor,
            lambda: _fetch_paper_detail_sync(paper_id),
        )
    if err:
        raise HTTPException(status_code=404, detail=err)

    requested_fields, all_fields = parse_fields_param(fields)
    return filter_paper_fields(paper, requested_fields, all_fields=all_fields)
