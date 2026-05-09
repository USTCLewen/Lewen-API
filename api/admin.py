"""Admin API — manage API keys and local administration jobs.

All endpoints require the ``X-Admin-Secret`` header to match
``config.ADMIN_SECRET``.  When ``ADMIN_SECRET`` is empty the
JSON admin API returns 503.  The HTML panel itself is public so that an
administrator can open it and enter the secret client-side.
"""

from __future__ import annotations

import time
import os
from typing import Any, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

import config
from api.admin_panel import panel_response
from auth.database import delete_key, list_keys, set_key_active
from auth.key_manager import create_api_key
from auth.middleware import invalidate_key_cache
from core.admin_jobs import manager as job_manager
from core.admin_status import get_status, read_db_stats_cache

router = APIRouter(prefix="/admin", tags=["admin"])


def _default_api_key() -> str | None:
    """Return a configured API key for admin-triggered local tests."""
    return (
        os.getenv("Lewen_API_KEY")
        or os.getenv("PAPER_SEARCH_API_KEY")
        or os.getenv("API_KEY")
    )


def _target_api_base(request: Request) -> str:
    """Return the Paper API base URL used by admin-triggered test requests."""
    return (
        getattr(request.app.state, "target_api_base_url", None)
        or config.ADMIN_TARGET_API_BASE_URL
        or str(request.base_url).rstrip("/")
    ).rstrip("/")


# ── Admin auth dependency ──────────────────────────────────────────────

def _verify_admin(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    if not config.ADMIN_SECRET:
        raise HTTPException(503, detail="Admin API disabled (ADMIN_SECRET not set).")
    if x_admin_secret != config.ADMIN_SECRET:
        raise HTTPException(403, detail="Invalid admin secret.")


# ── Request schemas ────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str
    email: str
    expires_at: Optional[str] = None


class ApiTestRequest(BaseModel):
    kind: str = "search"
    query: str = "transformer attention"
    paper_id: Optional[str] = None
    retrieval: str = "hybrid"
    limit: int = 5
    fields: Optional[str] = None
    api_key: Optional[str] = None


class LoadTestRequest(BaseModel):
    base_url: str = "http://localhost:4000"
    workers: int = 10
    requests_per_endpoint: int = 20
    timeout: int = 30
    api_key: Optional[str] = None


class IncrementalJobRequest(BaseModel):
    action: str = "full"
    target: str = "latest"
    incr_dir: Optional[str] = None
    gpu_list: str = "0,2,3"


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/panel", include_in_schema=False)
async def admin_panel():
    """Return the local HTML admin panel."""
    return panel_response()


@router.get("/status", dependencies=[Depends(_verify_admin)])
async def admin_status() -> dict[str, Any]:
    """Fast service, database, Qdrant, auth, and incremental status."""
    status = get_status()
    status["admin"] = {
        "standalone_port": config.ADMIN_PORT,
        "target_api_base_url": config.ADMIN_TARGET_API_BASE_URL,
    }
    return status


@router.get("/db/stats", dependencies=[Depends(_verify_admin)])
async def admin_db_stats() -> dict[str, Any]:
    """Return cached exact DB table counts, if a refresh job has produced them."""
    stats = read_db_stats_cache()
    return {"available": stats is not None, "stats": stats}


@router.post("/db/stats/refresh", dependencies=[Depends(_verify_admin)])
async def admin_refresh_db_stats() -> dict[str, Any]:
    """Start a background exact-count refresh for large SQLite tables."""
    return job_manager.start_db_stats_refresh()


@router.post("/keys", dependencies=[Depends(_verify_admin)])
async def admin_create_key(body: CreateKeyRequest) -> dict[str, Any]:
    """Create a new API key.  The raw key is returned **once** in the response."""
    raw_key, record = create_api_key(
        name=body.name,
        email=body.email,
        expires_at=body.expires_at,
    )
    invalidate_key_cache()
    return {"key": raw_key, **record}


@router.get("/keys", dependencies=[Depends(_verify_admin)])
async def admin_list_keys() -> list[dict[str, Any]]:
    """List all API keys (without hash values)."""
    return list_keys()


@router.post("/keys/{prefix}/revoke", dependencies=[Depends(_verify_admin)])
async def admin_revoke_key(prefix: str) -> dict[str, str]:
    """Disable an API key by its prefix."""
    if not set_key_active(prefix, active=False):
        raise HTTPException(404, detail=f"Key not found: {prefix}")
    invalidate_key_cache()
    return {"status": "revoked", "key_prefix": prefix}


@router.post("/keys/{prefix}/activate", dependencies=[Depends(_verify_admin)])
async def admin_activate_key(prefix: str) -> dict[str, str]:
    """Re-enable a previously revoked API key."""
    if not set_key_active(prefix, active=True):
        raise HTTPException(404, detail=f"Key not found: {prefix}")
    invalidate_key_cache()
    return {"status": "activated", "key_prefix": prefix}


@router.delete("/keys/{prefix}", dependencies=[Depends(_verify_admin)])
async def admin_delete_key(prefix: str) -> dict[str, str]:
    """Permanently delete an API key."""
    if not delete_key(prefix):
        raise HTTPException(404, detail=f"Key not found: {prefix}")
    invalidate_key_cache()
    return {"status": "deleted", "key_prefix": prefix}


@router.post("/api-test", dependencies=[Depends(_verify_admin)])
async def admin_api_test(request: Request, body: ApiTestRequest) -> dict[str, Any]:
    """Run one server-side API request and return timing plus response data."""
    base = _target_api_base(request)
    limit = max(1, min(body.limit, config.MAX_LIMIT))
    params: dict[str, Any] = {"limit": limit}

    if body.fields:
        params["fields"] = body.fields

    if body.kind == "search":
        path = "/paper/search"
        params.update({"query": body.query, "retrieval": body.retrieval})
    elif body.kind == "title":
        path = "/paper/search/title"
        params["query"] = body.query
    elif body.kind in ("detail", "citations", "references"):
        if not body.paper_id:
            raise HTTPException(400, detail="paper_id is required for this API test.")
        suffix = "" if body.kind == "detail" else f"/{body.kind}"
        path = f"/paper/{quote(body.paper_id, safe='')}{suffix}"
    else:
        raise HTTPException(400, detail=f"Unsupported API test kind: {body.kind}")

    api_key = body.api_key or _default_api_key()
    headers = {"X-API-Key": api_key} if api_key else {}
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT, trust_env=False) as client:
        response = await client.get(f"{base}{path}", params=params, headers=headers)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = response.text[:4000]
    return {
        "url": str(response.url),
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
        "ok": response.is_success,
        "api_key_source": "request" if body.api_key else (".env" if api_key else "none"),
        "response": payload,
    }


@router.get("/jobs", dependencies=[Depends(_verify_admin)])
async def admin_list_jobs() -> list[dict[str, Any]]:
    """List local background admin jobs."""
    return job_manager.list_jobs()


@router.post("/jobs/load-test", dependencies=[Depends(_verify_admin)])
async def admin_start_load_test(body: LoadTestRequest) -> dict[str, Any]:
    """Start a load test background job."""
    return job_manager.start_load_test(
        base_url=body.base_url,
        workers=body.workers,
        requests_per_endpoint=body.requests_per_endpoint,
        timeout=body.timeout,
        api_key=body.api_key or _default_api_key(),
    )


@router.post("/jobs/incremental", dependencies=[Depends(_verify_admin)])
async def admin_start_incremental(body: IncrementalJobRequest) -> dict[str, Any]:
    """Start a full or staged incremental update background job."""
    try:
        return job_manager.start_incremental(
            action=body.action,
            target=body.target,
            incr_dir=body.incr_dir,
            gpu_list=body.gpu_list,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", dependencies=[Depends(_verify_admin)])
async def admin_get_job(job_id: str) -> dict[str, Any]:
    """Return a background job with its current log tail."""
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(404, detail=f"Job not found: {job_id}")
    return job


@router.post("/jobs/{job_id}/interrupt", dependencies=[Depends(_verify_admin)])
async def admin_interrupt_job(job_id: str) -> dict[str, Any]:
    """Request termination of a running background job."""
    job = job_manager.interrupt_job(job_id)
    if job is None:
        raise HTTPException(404, detail=f"Job not found: {job_id}")
    return job
