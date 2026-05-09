"""Admin status helpers for the Paper Search API.

The functions in this module intentionally prefer fast metadata checks over
large SQLite scans. Exact table counts are available through a background job
that writes a cache file.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from auth.database import list_keys

DB_STATS_CACHE_PATH = config.PROJECT_ROOT / "logs" / "admin_db_stats.json"

_CORE_TABLES = (
    "paper_metadata",
    "citations",
    "corpus_id_mapping",
    "arxiv_to_paper",
    "paper_fts_title",
    "paper_fts_combined",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _human_bytes(size: int | None) -> str | None:
    if size is None:
        return None
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _file_info(path: Path) -> dict[str, Any]:
    exists = path.exists()
    stat = path.stat() if exists else None
    modified_at = (
        datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        if stat is not None
        else None
    )
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": stat.st_size if stat is not None else None,
        "size_human": _human_bytes(stat.st_size if stat is not None else None),
        "modified_at": modified_at,
    }


def read_current_release() -> str | None:
    release_path = config.CORPUS_DIR / "current_release.txt"
    try:
        value = release_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def get_sqlite_health() -> dict[str, Any]:
    db_path = Path(config.PAPERS_DB_PATH)
    result: dict[str, Any] = {
        "database": _file_info(db_path),
        "wal": _file_info(db_path.with_name(db_path.name + "-wal")),
        "shm": _file_info(db_path.with_name(db_path.name + "-shm")),
        "tables": {},
        "ok": False,
        "error": None,
    }
    if not db_path.exists():
        result["error"] = "papers.db not found"
        return result

    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=3)
        try:
            rows = conn.execute(
                "SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            found = {name: type_ for name, type_ in rows}
            result["tables"] = {
                table: {"exists": table in found, "type": found.get(table)}
                for table in _CORE_TABLES
            }
            result["ok"] = all(result["tables"][table]["exists"] for table in _CORE_TABLES[:4])
        finally:
            conn.close()
    except Exception as exc:  # pragma: no cover - defensive status endpoint
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def get_auth_summary() -> dict[str, Any]:
    keys = list_keys()
    active = sum(1 for item in keys if item.get("is_active"))
    inactive = len(keys) - active
    last_used = sorted(
        (item.get("last_used_at") for item in keys if item.get("last_used_at")),
        reverse=True,
    )
    return {
        "total": len(keys),
        "active": active,
        "inactive": inactive,
        "last_used_at": last_used[0] if last_used else None,
    }


def get_qdrant_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "host": config.QDRANT_HOST,
        "port": config.QDRANT_PORT,
        "collection": config.QDRANT_COLLECTION_NAME,
        "ok": False,
        "exists": False,
        "vectors_count": None,
        "points_count": None,
        "error": None,
    }
    try:
        from qdrant_client import QdrantClient

        client = (
            QdrantClient(path=config.QDRANT_PATH)
            if config.QDRANT_PATH
            else QdrantClient(
                host=config.QDRANT_HOST,
                port=config.QDRANT_PORT,
                prefer_grpc=config.QDRANT_PREFER_GRPC,
                timeout=5,
            )
        )
        exists = client.collection_exists(config.QDRANT_COLLECTION_NAME)
        status["exists"] = exists
        if exists:
            info = client.get_collection(config.QDRANT_COLLECTION_NAME)
            status["vectors_count"] = getattr(info, "vectors_count", None)
            status["points_count"] = getattr(info, "points_count", None)
        status["ok"] = exists
    except Exception as exc:  # pragma: no cover - depends on local Qdrant
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def list_incremental_dirs(limit: int = 25) -> list[dict[str, Any]]:
    root = config.PAPER_DATA_DIR / "incremental"
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "path": str(path.relative_to(config.PROJECT_ROOT)),
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc
                ).isoformat(),
                "has_validation_progress": (path / "_download_validation_progress.json").exists(),
                "has_merge_progress": (path / "_merge_progress.json").exists(),
                "has_qdrant_task": (path / "_qdrant_task.json").exists(),
                "has_qdrant_embeddings": (path / "qdrant_embeddings").exists(),
            }
        )
    return sorted(items, key=lambda item: item["modified_at"], reverse=True)[:limit]


def read_db_stats_cache() -> dict[str, Any] | None:
    try:
        with open(DB_STATS_CACHE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_db_stats() -> dict[str, Any]:
    """Run exact SQLite counts and persist them for the admin panel."""
    started = time.time()
    db_path = Path(config.PAPERS_DB_PATH)
    stats: dict[str, Any] = {
        "generated_at": _now_iso(),
        "elapsed_s": None,
        "database": _file_info(db_path),
        "tables": {},
        "ok": False,
        "error": None,
    }
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        try:
            for table in _CORE_TABLES:
                try:
                    count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    stats["tables"][table] = {"count": count, "error": None}
                except Exception as exc:
                    stats["tables"][table] = {
                        "count": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
            stats["ok"] = True
        finally:
            conn.close()
    except Exception as exc:
        stats["error"] = f"{type(exc).__name__}: {exc}"
    stats["elapsed_s"] = round(time.time() - started, 3)
    DB_STATS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_STATS_CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    return stats


def get_status() -> dict[str, Any]:
    return {
        "generated_at": _now_iso(),
        "project_root": str(config.PROJECT_ROOT),
        "api": {
            "host": config.API_HOST,
            "port": config.API_PORT,
            "auth_enabled": config.AUTH_ENABLED,
            "admin_enabled": bool(config.ADMIN_SECRET),
            "uvicorn_workers": config.UVICORN_WORKERS,
            "heavy_ops_max_concurrent": config.HEAVY_OPS_MAX_CONCURRENT,
            "request_timeout": config.REQUEST_TIMEOUT,
        },
        "paths": {
            "papers_db": config.PAPERS_DB_PATH,
            "auth_db": config.AUTH_DB_PATH,
            "corpus_dir": str(config.CORPUS_DIR),
            "paper_data_dir": str(config.PAPER_DATA_DIR),
        },
        "release": read_current_release(),
        "sqlite": get_sqlite_health(),
        "auth": get_auth_summary(),
        "qdrant": get_qdrant_status(),
        "db_stats_cache": read_db_stats_cache(),
        "incremental_dirs": list_incremental_dirs(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin status maintenance helpers")
    parser.add_argument("--refresh-db-stats", action="store_true")
    args = parser.parse_args()
    if args.refresh_db_stats:
        stats = refresh_db_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
