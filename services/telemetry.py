"""Structured, secret-free project stage telemetry."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any


def stage_event(stage: str, status: str, started: float, input_path: str | None = None, output_path: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "start_time": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(),
        "duration": max(0.0, time.time() - started),
        "input": input_path,
        "output": output_path,
        "error": error,
    }
