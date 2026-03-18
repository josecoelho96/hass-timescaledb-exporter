"""Buffered batch writer for TimescaleDB state change ingestion."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
import logging
from typing import Any

import asyncpg

from ..const import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_MAX_QUEUE_SIZE,
    IGNORED_STATES,
)

_LOGGER = logging.getLogger(__name__)

_MAX_RETRIES = 3
_PERMANENT_ERRORS = (asyncpg.DataError, asyncpg.IntegrityConstraintViolationError)

_INSERT_SQL = (
    "INSERT INTO ha_states "
    "(time, entity_id, state, state_numeric, attributes, "
    "context_id) "
    "VALUES ($1, $2, $3, $4, $5, $6)"
)


@dataclass(frozen=True, slots=True)
class StateChange:
    """Immutable representation of a Home Assistant state change."""

    time: datetime
    entity_id: str
    state: str | None
    state_numeric: float | None
    attributes: dict[str, Any]
    context_id: str | None


@dataclass
class ExporterStats:
    """Runtime statistics for the exporter."""

    total_writes: int = 0
    total_dropped: int = 0
    total_errors: int = 0
    total_retries: int = 0
    last_flush_at: datetime | None = None
    queue_high_watermark: int = 0


def parse_state_numeric(state: str | None) -> float | None:
    """Parse a state string to a float, returning None for non-numeric values."""
    if state is None or state in IGNORED_STATES:
        return None
    try:
        return float(state)
    except (ValueError, TypeError):
        return None


class TimescaleExporter:
    """Buffered async writer that batches state changes and writes to TimescaleDB."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: int = DEFAULT_FLUSH_INTERVAL,
        excluded_entity_globs: list[str] | None = None,
        excluded_domains: list[str] | None = None,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ) -> None:
        """Initialize the exporter."""
        self._pool = pool
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._excluded_entity_globs = excluded_entity_globs or []
        self._excluded_domains = set(excluded_domains or [])
        self._max_queue_size = max_queue_size

        self._queue: asyncio.Queue[StateChange] = asyncio.Queue(maxsize=max_queue_size)
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False
        self._consecutive_errors = 0
        self.stats = ExporterStats()

    @property
    def queue_size(self) -> int:
        """Return the current queue depth."""
        return self._queue.qsize()

    @property
    def is_healthy(self) -> bool:
        """Return True if the exporter is running and not in a sustained error state."""
        return self._running and self._consecutive_errors < _MAX_RETRIES

    def is_excluded(self, entity_id: str) -> bool:
        """Check if an entity should be excluded from export."""
        domain = entity_id.split(".", 1)[0]
        if domain in self._excluded_domains:
            return True
        return any(fnmatch(entity_id, glob) for glob in self._excluded_entity_globs)

    def update_filters(
        self,
        excluded_entity_globs: list[str] | None = None,
        excluded_domains: list[str] | None = None,
    ) -> None:
        """Update exclusion filters at runtime (e.g., from options flow)."""
        if excluded_entity_globs is not None:
            self._excluded_entity_globs = excluded_entity_globs
        if excluded_domains is not None:
            self._excluded_domains = set(excluded_domains)

    def enqueue(self, state_change: StateChange) -> bool:
        """Add a state change to the write queue.

        Returns True if enqueued, False if the queue is full (event dropped).
        """
        try:
            self._queue.put_nowait(state_change)
            if self._queue.qsize() > self.stats.queue_high_watermark:
                self.stats.queue_high_watermark = self._queue.qsize()
            warn_threshold = int(self._max_queue_size * 0.8)
            if self._queue.qsize() >= warn_threshold:
                _LOGGER.warning(
                    "Write queue is %d%% full (%d/%d)",
                    int(self._queue.qsize() / self._max_queue_size * 100),
                    self._queue.qsize(),
                    self._max_queue_size,
                )
            return True
        except asyncio.QueueFull:
            self.stats.total_dropped += 1
            _LOGGER.warning(
                "Write queue full (%d). Dropping state change for %s",
                self._max_queue_size,
                state_change.entity_id,
            )
            return False

    async def start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        _LOGGER.debug("TimescaleDB exporter started")

    async def stop(self) -> None:
        """Stop the flush loop and flush remaining items."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

        # Final flush of remaining queued items
        await self._flush_queue()
        _LOGGER.debug(
            "TimescaleDB exporter stopped. Total writes: %d, dropped: %d, errors: %d",
            self.stats.total_writes,
            self.stats.total_dropped,
            self.stats.total_errors,
        )

    async def _flush_loop(self) -> None:
        """Background loop that flushes the queue periodically."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush_queue()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Error in flush loop")
                self.stats.total_errors += 1

    async def _flush_queue(self) -> None:
        """Drain the queue and batch-write to TimescaleDB."""
        batch: list[StateChange] = []
        while not self._queue.empty() and len(batch) < self._batch_size * 10:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not batch:
            return

        await self._write_batch(batch)

    async def _write_batch(self, batch: list[StateChange]) -> None:
        """Write a batch of state changes to TimescaleDB with retry."""
        records = [
            (
                sc.time,
                sc.entity_id,
                sc.state,
                sc.state_numeric,
                sc.attributes,
                sc.context_id,
            )
            for sc in batch
        ]

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._pool.acquire() as conn:
                    await conn.executemany(_INSERT_SQL, records)
                self.stats.total_writes += len(batch)
                self.stats.last_flush_at = datetime.now(UTC)
                self._consecutive_errors = 0
                _LOGGER.debug("Flushed %d state changes to TimescaleDB", len(batch))
                break
            except _PERMANENT_ERRORS:
                _LOGGER.exception(
                    "Permanent error writing %d state changes (dropping batch)",
                    len(batch),
                )
                self.stats.total_errors += 1
                self._consecutive_errors += 1
                break
            except Exception:
                if attempt < _MAX_RETRIES:
                    delay = 2 ** (attempt - 1)
                    _LOGGER.warning(
                        "Write failed (attempt %d/%d), retrying in %ds",
                        attempt,
                        _MAX_RETRIES,
                        delay,
                    )
                    self.stats.total_retries += 1
                    await asyncio.sleep(delay)
                else:
                    _LOGGER.exception(
                        "Failed to write %d state changes after %d attempts",
                        len(batch),
                        _MAX_RETRIES,
                    )
                    self.stats.total_errors += 1
                    self._consecutive_errors += 1

        # Update entity metadata (best-effort, don't block on failures)
        await self._update_entity_metadata(batch)

    async def _update_entity_metadata(self, batch: list[StateChange]) -> None:
        """Upsert entity metadata from the batch (best-effort)."""
        seen: dict[str, StateChange] = {}
        for sc in batch:
            seen[sc.entity_id] = sc

        try:
            async with self._pool.acquire() as conn:
                for entity_id, sc in seen.items():
                    domain = entity_id.split(".", 1)[0]
                    friendly_name = sc.attributes.get("friendly_name") if sc.attributes else None
                    unit = sc.attributes.get("unit_of_measurement") if sc.attributes else None
                    device_class = sc.attributes.get("device_class") if sc.attributes else None
                    is_numeric = sc.state_numeric is not None

                    await conn.execute(
                        """
                        INSERT INTO ha_entity_metadata
                            (entity_id, domain, friendly_name, unit_of_measurement,
                             device_class, is_numeric, first_seen, last_seen)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                        ON CONFLICT (entity_id) DO UPDATE SET
                            friendly_name = COALESCE(
                                EXCLUDED.friendly_name,
                                ha_entity_metadata.friendly_name
                            ),
                            unit_of_measurement = COALESCE(
                                EXCLUDED.unit_of_measurement,
                                ha_entity_metadata.unit_of_measurement
                            ),
                            device_class = COALESCE(
                                EXCLUDED.device_class,
                                ha_entity_metadata.device_class
                            ),
                            is_numeric = EXCLUDED.is_numeric,
                            last_seen = NOW()
                        """,
                        entity_id,
                        domain,
                        friendly_name,
                        unit,
                        device_class,
                        is_numeric,
                    )
        except Exception:
            _LOGGER.debug("Failed to update entity metadata", exc_info=True)
