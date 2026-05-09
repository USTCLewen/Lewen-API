"""Background job runner for admin operations.

Jobs are intentionally simple and local-process scoped. The panel is designed
for an administrator running this service locally or on an internal host.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

LOG_DIR = config.PROJECT_ROOT / "logs" / "admin_jobs"

_ALLOWED_INCREMENTAL_ACTIONS = {"full", "download", "validate", "merge", "qdrant"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail_text(path: Path, max_bytes: int = 16000) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read()
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _safe_incremental_dir(raw_path: str) -> str:
    if not raw_path:
        raise ValueError("Incremental directory is required.")
    base = (config.PAPER_DATA_DIR / "incremental").resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = config.PROJECT_ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("Incremental directory must be under PaperData/incremental/.") from exc
    if not resolved.is_dir():
        raise ValueError(f"Incremental directory not found: {resolved}")
    return str(resolved.relative_to(config.PROJECT_ROOT))


class AdminJobManager:
    """Start and track local admin background jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _snapshot(self, job: dict[str, Any], include_log: bool = False) -> dict[str, Any]:
        data = dict(job)
        data["log_path"] = str(job["log_path"])
        if include_log:
            data["log_tail"] = _tail_text(job["log_path"])
        return data

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item["started_at"],
                reverse=True,
            )[:limit]
            return [self._snapshot(job) for job in jobs]

    def get_job(self, job_id: str, include_log: bool = True) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._snapshot(job, include_log=include_log) if job else None

    def _start_process(
        self,
        *,
        kind: str,
        command: list[str],
        display_command: list[str] | None = None,
        env_updates: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        log_path = LOG_DIR / f"{job_id}_{kind}.log"
        job = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "started_at": _now_iso(),
            "ended_at": None,
            "returncode": None,
            "command": display_command or command,
            "log_path": log_path,
            "metadata": metadata or {},
            "cancel_requested": False,
        }
        with self._lock:
            self._jobs[job_id] = job

        env = os.environ.copy()
        if env_updates:
            env.update(env_updates)

        def runner() -> None:
            with open(log_path, "w", encoding="utf-8") as log:
                log.write(f"$ {' '.join(job['command'])}\n\n")
                log.flush()
                try:
                    proc = subprocess.Popen(
                        command,
                        cwd=str(config.PROJECT_ROOT),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        env=env,
                        text=True,
                        start_new_session=True,
                    )
                    with self._lock:
                        self._processes[job_id] = proc
                    returncode = proc.wait()
                    status = (
                        "cancelled"
                        if job.get("cancel_requested")
                        else ("succeeded" if returncode == 0 else "failed")
                    )
                except Exception as exc:  # pragma: no cover - defensive runner
                    log.write(f"\nJob failed to start/run: {type(exc).__name__}: {exc}\n")
                    returncode = -1
                    status = "failed"
                with self._lock:
                    job["status"] = status
                    job["returncode"] = returncode
                    job["ended_at"] = _now_iso()
                    self._processes.pop(job_id, None)

        thread = threading.Thread(target=runner, name=f"admin-job-{job_id}", daemon=True)
        thread.start()
        return self._snapshot(job)

    def interrupt_job(self, job_id: str) -> dict[str, Any] | None:
        """Request termination of a running job and its process group."""
        with self._lock:
            job = self._jobs.get(job_id)
            proc = self._processes.get(job_id)
            if job is None:
                return None
            if job["status"] != "running" or proc is None or proc.poll() is not None:
                return self._snapshot(job, include_log=True)
            job["status"] = "stopping"
            job["cancel_requested"] = True

        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            proc.terminate()
        return self.get_job(job_id, include_log=True)

    def start_load_test(
        self,
        *,
        base_url: str,
        workers: int,
        requests_per_endpoint: int,
        timeout: int,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        workers = max(1, min(workers, 256))
        requests_per_endpoint = max(1, min(requests_per_endpoint, 5000))
        timeout = max(1, min(timeout, 600))
        command = [
            sys.executable,
            "-u",
            "test/test_load.py",
            "--base-url",
            base_url,
            "--workers",
            str(workers),
            "--requests",
            str(requests_per_endpoint),
            "--timeout",
            str(timeout),
            "--no-log-failures",
        ]
        env_updates = {"Lewen_API_KEY": api_key} if api_key else None
        return self._start_process(
            kind="load-test",
            command=command,
            env_updates=env_updates,
            metadata={
                "base_url": base_url,
                "workers": workers,
                "requests_per_endpoint": requests_per_endpoint,
                "timeout": timeout,
                "api_key_provided": bool(api_key),
            },
        )

    def start_db_stats_refresh(self) -> dict[str, Any]:
        return self._start_process(
            kind="db-stats",
            command=[sys.executable, "-u", "-m", "core.admin_status", "--refresh-db-stats"],
        )

    def start_incremental(
        self,
        *,
        action: str,
        target: str = "latest",
        incr_dir: str | None = None,
        gpu_list: str = "0,2,3",
    ) -> dict[str, Any]:
        if action not in _ALLOWED_INCREMENTAL_ACTIONS:
            raise ValueError(f"Unsupported incremental action: {action}")

        if action == "full":
            command = ["bash", "incremental/update.sh", target or "latest"]
        elif action == "download":
            command = ["bash", "incremental/update_download.sh", target or "latest"]
        elif action == "validate":
            command = ["bash", "incremental/update_validate.sh", target or "latest"]
        elif action == "merge":
            safe_dir = _safe_incremental_dir(incr_dir or "")
            command = ["bash", "incremental/update_merge.sh", safe_dir]
        else:
            safe_dir = _safe_incremental_dir(incr_dir or "")
            command = ["bash", "incremental/update_qdrant_incremental.sh", safe_dir, gpu_list or "0,2,3"]

        return self._start_process(
            kind=f"incremental-{action}",
            command=command,
            metadata={
                "action": action,
                "target": target,
                "incr_dir": incr_dir,
                "gpu_list": gpu_list,
            },
        )


manager = AdminJobManager()
