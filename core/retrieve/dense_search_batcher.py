"""Sync dense search batcher: queues vector searches and processes in batches via Qdrant.

Reduces per-request overhead by batching multiple vector searches into one API call.
Thread-safe for use from executor threads.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import config
from core.retrieve.dense import vector_search, vector_search_batch


@dataclass
class _PendingSearch:
    """A single vector search waiting for batch processing."""

    vector: list[float]
    top_k: int
    result_holder: list
    done: threading.Event


class DenseSearchBatcher:
    """Batches vector search requests and processes them via Qdrant search_batch.

    Uses a background thread to collect requests. When batch_size is reached or
    timeout elapses, runs search_batch and distributes results to waiters.
    """

    def __init__(
        self,
        batch_size: int | None = None,
        batch_timeout_ms: float | None = None,
    ) -> None:
        """Initialize the batcher.

        Args:
            batch_size: Max searches per batch. Default from config.
            batch_timeout_ms: Max wait (ms) before processing. Default from config.
        """
        self._batch_size = batch_size or config.DENSE_SEARCH_BATCH_SIZE
        self._batch_timeout_s = (batch_timeout_ms or config.DENSE_SEARCH_BATCH_TIMEOUT_MS) / 1000.0
        self._queue: queue.Queue[_PendingSearch | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._shutdown = False

    def start(self) -> None:
        """Start the background batch processor."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._shutdown = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal shutdown and wait for worker to finish."""
        self._shutdown = True
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def search(self, vector: list[float], top_k: int = 100) -> list[tuple[str, float]]:
        """Submit a vector search to batch; block until result ready.

        Args:
            vector: Query embedding (dim=1024).
            top_k: Number of results to return.

        Returns:
            List of (paper_id, cosine_score) tuples, sorted by score desc.
        """
        result_holder: list = [None]
        done = threading.Event()
        self._queue.put(_PendingSearch(vector=vector, top_k=top_k, result_holder=result_holder, done=done))
        completed = done.wait(timeout=25.0)
        if not completed:
            return []
        return result_holder[0] or []

    def _run_loop(self) -> None:
        """Background loop: collect requests and process in batches."""
        while not self._shutdown:
            batch: list[_PendingSearch] = []
            try:
                first = self._queue.get(timeout=self._batch_timeout_s)
                if first is None:
                    continue
                batch.append(first)

                coalesce_s = 0.01
                deadline = time.time() + coalesce_s
                while len(batch) < self._batch_size:
                    try:
                        remaining = max(0.001, deadline - time.time())
                        item = self._queue.get(timeout=remaining)
                        if item is None:
                            break
                        batch.append(item)
                    except queue.Empty:
                        break

            except queue.Empty:
                continue

            if not batch:
                continue

            vectors = [p.vector for p in batch]
            top_ks = [p.top_k for p in batch]
            max_top_k = max(top_ks)

            try:
                if len(vectors) == 1:
                    results = [vector_search(vectors[0], top_k=max_top_k)]
                else:
                    results = vector_search_batch(vectors, top_k=max_top_k)

                for i, req in enumerate(batch):
                    if i < len(results):
                        row = results[i]
                        if req.top_k < max_top_k:
                            row = row[: req.top_k]
                        req.result_holder[0] = row
                    else:
                        req.result_holder[0] = []
                    req.done.set()
            except Exception:
                for req in batch:
                    req.result_holder[0] = []
                    req.done.set()
