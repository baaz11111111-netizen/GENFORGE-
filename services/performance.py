"""Phase 12 — Performance feedback loop: metrics only where APIs support them.

Truthfulness rules from the mandate: never fabricate unavailable metrics,
never invent numbers to fill gaps, and label deterministic interpretation as
deterministic. Metrics can enter from two honest sources:

1. An injected/real platform metrics transport (official analytics APIs).
2. Local measurement of published assets (file size / duration via ffprobe),
   which is real data and clearly labelled "local".

Interpretation and recommendations are pure functions over REAL numbers only;
missing metrics are reported as gaps, not guessed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

METRIC_KEYS = ("views", "watch_time", "retention", "engagement", "shares", "clicks")


def validate_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    """Accept only known metric keys with finite, non-negative values."""
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("At least one metric is required.")
    cleaned: dict[str, float] = {}
    for key, value in metrics.items():
        if key not in METRIC_KEYS:
            raise ValueError(f"Unknown metric '{key}'. Available: {', '.join(METRIC_KEYS)}")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Metric '{key}' must be numeric.") from exc
        if number < 0 or number != number:  # negative or NaN
            raise ValueError(f"Metric '{key}' must be a non-negative number.")
        cleaned[key] = number
    return cleaned


def fetch_platform_metrics(
    platform: str,
    external_id: str,
    transport: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch metrics from an official platform analytics API.

    Without a supplied transport (official API credentials) the result is an
    honest 'unavailable' report — no numbers are invented.
    """
    if not platform or not platform.strip():
        raise ValueError("Platform is required.")
    if not external_id or not external_id.strip():
        raise ValueError("external_id of the confirmed publication is required.")
    if transport is None:
        return {
            "status": "unavailable",
            "metrics": {},
            "source": None,
            "message": "METRICS UNAVAILABLE: no official analytics API credentials configured "
                       f"for {platform}. Metrics will not be fabricated.",
        }
    try:
        raw = transport(platform.strip(), external_id.strip())
    except Exception as exc:
        return {"status": "unavailable", "metrics": {}, "source": None,
                "message": f"Analytics API call failed: {exc}"}
    try:
        metrics = validate_metrics(raw or {})
    except ValueError as exc:
        return {"status": "invalid", "metrics": {}, "source": None,
                "message": f"Analytics API returned unusable metrics: {exc}"}
    return {"status": "fetched", "metrics": metrics, "source": "platform_api"}


def measure_local_metrics(asset_path: str) -> dict[str, Any]:
    """Real, honest local measurement of a rendered asset (no invented numbers).

    Only reports what ffprobe can actually measure: duration. File size is
    real filesystem data. Views/retention etc. are impossible locally and are
    deliberately absent.
    """
    import os
    from services.media_probe import probe_media
    if not os.path.isfile(asset_path):
        raise FileNotFoundError(f"Asset not found: {asset_path}")
    meta = probe_media(asset_path)
    metrics = {
        "duration": round(meta.duration, 3),
        "file_size_bytes": os.path.getsize(asset_path),
        "has_audio": bool(meta.has_audio),
    }
    return {"status": "measured", "metrics": metrics, "source": "local"}


def interpret_metrics(metrics: dict[str, float]) -> dict[str, Any]:
    """Deterministic interpretation over REAL metrics only.

    Derived rates are computed only from numbers that exist; absent metrics
    are listed as gaps instead of being estimated.
    """
    cleaned = validate_metrics(metrics)
    derived: dict[str, float] = {}
    gaps = [key for key in METRIC_KEYS if key not in cleaned]
    if "views" in cleaned and cleaned["views"] > 0:
        if "engagement" in cleaned:
            derived["engagement_rate"] = round(cleaned["engagement"] / cleaned["views"], 4)
        if "clicks" in cleaned:
            derived["click_through_rate"] = round(cleaned["clicks"] / cleaned["views"], 4)
        if "shares" in cleaned:
            derived["share_rate"] = round(cleaned["shares"] / cleaned["views"], 4)
    recommendations = []
    if "retention" in cleaned and cleaned["retention"] < 50.0:
        recommendations.append("Retention is below 50%: tighten the hook and cut dead air in the first 3 seconds.")
    if derived.get("engagement_rate") is not None and derived["engagement_rate"] < 0.02:
        recommendations.append("Engagement rate is under 2%: test a stronger CTA and reply to early comments.")
    if "views" in cleaned and cleaned["views"] < 100:
        recommendations.append("Distribution is low: verify posting time and hashtags; consider cross-posting variants.")
    if not recommendations:
        recommendations.append("No deterministic issues detected with the available metrics.")
    return {
        "metrics": cleaned,
        "derived": derived,
        "gaps": gaps,
        "recommendations": recommendations,
        "method": "deterministic (no AI inference)",
    }


def recommend_next_campaign(project, interpretation: dict[str, Any]) -> dict[str, Any]:
    """Feed interpretation results back as campaign guidance (no fabricated data)."""
    if "recommendations" not in interpretation:
        raise ValueError("An interpretation result is required.")
    guidance = {
        "guidance_id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "based_on_metrics": interpretation.get("metrics", {}),
        "gaps": interpretation.get("gaps", []),
        "recommendations": list(interpretation["recommendations"]),
        "method": interpretation.get("method", "deterministic"),
    }
    telemetry = list(getattr(project, "telemetry", []) or [])
    telemetry.append({"type": "performance_feedback", **guidance})
    project.telemetry = telemetry
    return guidance


def record_performance(project, publication_entry: dict[str, Any],
                       report: dict[str, Any]) -> dict[str, Any]:
    """Attach a metrics report to the project (additive, versioned telemetry)."""
    if report.get("status") not in {"fetched", "measured"}:
        raise ValueError("Only fetched or measured reports can be recorded.")
    record = {
        "type": "performance_report",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "platform": publication_entry.get("platform"),
        "external_id": publication_entry.get("external_id"),
        "status": report["status"],
        "source": report.get("source"),
        "metrics": report.get("metrics", {}),
    }
    telemetry = list(getattr(project, "telemetry", []) or [])
    telemetry.append(record)
    project.telemetry = telemetry
    return record


__all__ = [
    "METRIC_KEYS",
    "validate_metrics",
    "fetch_platform_metrics",
    "measure_local_metrics",
    "interpret_metrics",
    "recommend_next_campaign",
    "record_performance",
]
