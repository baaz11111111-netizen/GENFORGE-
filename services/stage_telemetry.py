"""Honest stage telemetry (Priority #20).

Records REAL measured stage durations for render jobs. No simulated sleeps,
no fake percentages: progress is reported as which named stage is running
(PROBING → NORMALIZING → VALIDATING → RENDERING → FINALIZING) and how long
each completed stage actually took.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

JOB_STAGES: tuple[str, ...] = ("PROBING", "NORMALIZING", "VALIDATING", "RENDERING", "FINALIZING")
_MAX_RECORDS = 200

_lock = threading.Lock()
_records: list[dict] = []


@contextmanager
def stage_timer(stage: str) -> Iterator[None]:
    """Time one job stage; records completion or failure honestly."""
    if stage not in JOB_STAGES:
        raise ValueError(f"Unknown job stage: {stage!r}. Valid stages: {JOB_STAGES}")
    started = time.perf_counter()
    status = "completed"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        record = {
            "stage": stage,
            "status": status,
            "seconds": round(time.perf_counter() - started, 4),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        with _lock:
            _records.append(record)
            del _records[:-_MAX_RECORDS]


def stage_timings() -> list[dict]:
    """Chronological copy of recorded stage timings."""
    with _lock:
        return [dict(record) for record in _records]


def latest_stage() -> dict | None:
    """Most recent stage record (what the job last finished or failed on)."""
    with _lock:
        return dict(_records[-1]) if _records else None


def stage_label(stage: str) -> str:
    """Honest UI label for a running stage — never a fake percentage."""
    if stage not in JOB_STAGES:
        raise ValueError(f"Unknown job stage: {stage!r}. Valid stages: {JOB_STAGES}")
    return f"{stage}…"


def clear_stage_timings() -> None:
    with _lock:
        _records.clear()


__all__ = [
    "JOB_STAGES",
    "stage_timer",
    "stage_timings",
    "latest_stage",
    "stage_label",
    "clear_stage_timings",
]
