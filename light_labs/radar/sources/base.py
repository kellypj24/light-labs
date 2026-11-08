"""The source interface and the runner that isolates one source's failure from the rest."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import duckdb

from light_labs.radar.config import Paths, Settings
from light_labs.radar.db import last_watermark

log = logging.getLogger("radar")


@dataclass(frozen=True)
class SyncContext:
    paths: Paths
    settings: Settings
    with_snippets: bool = False


@dataclass
class SourceResult:
    status: str = "ok"  # ok | skipped
    watermark: str | None = None
    rows_in: int = 0
    message: str | None = None


class SourceSkipped(Exception):
    """Raised when a source has nothing to read (not configured, no export yet)."""


class Source(Protocol):
    name: str

    def sync(
        self, con: duckdb.DuckDBPyConnection, ctx: SyncContext, watermark: str | None
    ) -> SourceResult:
        """Read new data since `watermark` and upsert it. Must be idempotent."""
        ...


def run_source(con: duckdb.DuckDBPyConnection, source: Source, ctx: SyncContext) -> SourceResult:
    """Run one source in its own transaction; a failure is logged and recorded, never raised."""
    run_id = uuid.uuid4().hex
    started = datetime.now(UTC)
    watermark = last_watermark(con, source.name)
    try:
        con.begin()
        result = source.sync(con, ctx, watermark)
        con.commit()
    except SourceSkipped as e:
        con.rollback()
        result = SourceResult(status="skipped", watermark=watermark, message=str(e))
        log.warning("%s: skipped: %s", source.name, e)
    except Exception as e:  # noqa: BLE001 - isolation is the contract
        con.rollback()
        result = SourceResult(
            status="failed", watermark=watermark, message=f"{type(e).__name__}: {e}"
        )
        log.warning("%s: failed: %s", source.name, result.message)
    con.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            run_id,
            source.name,
            started,
            datetime.now(UTC),
            result.status,
            result.watermark,
            result.rows_in,
            result.message,
        ],
    )
    return result
