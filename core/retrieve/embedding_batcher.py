"""Async embedding batcher: queues queries and encodes in batches on GPU.

Reduces per-request overhead by batching multiple queries into a single GPU call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import config
from core.retrieve.embedding import encode


@dataclass
class _PendingRequest:
    """A single query waiting for embedding."""

    query: str
    future: asyncio.Future


class EmbeddingBatcher:
    """Batches embedding requests and processes them together on GPU.

    Uses a background task to collect requests from a queue. When either
    batch_size is reached or timeout elapses, encodes all pending queries
    in one GPU call and resolves each request's future.
    """

    def __init__(
        self,
        batch_size: int | None = None,
        batch_timeout_ms: float | None = None,
    ) -> None:
        """Initialize the batcher.

        Args:
            batch_size: Max queries per batch. Default from config.
            batch_timeout_ms: Max wait (ms) before processing. Default from config.
        """
        self._batch_size = batch_size or config.EMBEDDING_BATCH_SIZE
        self._batch_timeout_s = (batch_timeout_ms or config.EMBEDDING_BATCH_TIMEOUT_MS) / 1000.0
        self._queue: asyncio.Queue[_PendingRequest] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._shutdown = False

    def start(self) -> None:
        """Start the background batch processor."""
        if self._task is not None:
            return
        self._shutdown = False
        self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        """Signal shutdown and cancel the background task."""
        self._shutdown = True
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def encode_async(self, query: str) -> list[float]:
        """Submit a query for embedding and return the vector when ready.

        Args:
            query: Search query text.

        Returns:
            Dense vector of length VECTOR_DIM (1024).
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put(_PendingRequest(query=query, future=future))
        return await future

    async def _run_loop(self) -> None:
        """Background loop: collect requests and process in batches."""
        while not self._shutdown:
            batch: list[_PendingRequest] = []
            try:
                # Wait for first item (up to batch_timeout to avoid idle spin)
                first = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._batch_timeout_s,
                )
                batch.append(first)

                # Drain queue up to batch_size - 1 more, with short coalesce window
                coalesce_s = 0.01  # 10ms to gather concurrent requests
                deadline = asyncio.get_event_loop().time() + coalesce_s
                while len(batch) < self._batch_size:
                    try:
                        remaining = max(0.001, deadline - asyncio.get_event_loop().time())
                        item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                        batch.append(item)
                    except asyncio.TimeoutError:
                        break

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if not batch:
                continue

            queries = [p.query for p in batch]
            try:
                # Run sync encode in thread pool to avoid blocking event loop
                vectors = await asyncio.to_thread(encode, queries)
                for i, req in enumerate(batch):
                    if not req.future.done():
                        vec = vectors[i] if i < len(vectors) else None
                        req.future.set_result(vec.tolist() if vec is not None else [0.0] * config.VECTOR_DIM)
            except Exception as e:
                for req in batch:
                    if not req.future.done():
                        req.future.set_exception(e)
