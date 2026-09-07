"""Future performance-metrics interface (§32, §33).

GENFORGE stores every confirmed publication's external id/url so real
performance data can be fetched later from official platform endpoints.

Honesty rules (§32):

* Numbers are NEVER invented, estimated, or defaulted to 0 "for display".
* When a provider cannot supply metrics, the entry says so (available=False)
  and carries no fabricated figures.
* Whatever the platform returns is passed through verbatim — including
  ``None`` fields, which mean "not available yet", not zero.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from services.publishing.base import BaseProvider
from services.publishing.history import PublishingStore


def collect_metrics(store: PublishingStore,
                    provider_factory: Callable[[str], BaseProvider]) -> list[dict]:
    """Fetch live metrics for every stored PUBLISHED post with an external id.

    ``provider_factory(platform)`` must return a provider able to answer
    ``get_metrics`` for that platform (or raise to declare it unavailable).
    """
    results: list[dict] = []
    for candidate in store.metrics_candidates():
        entry = {
            "job_id": candidate["job_id"],
            "platform": candidate["platform"],
            "external_post_id": candidate["external_post_id"],
            "external_url": candidate["external_url"],
            "available": False,
            "metrics": {},
            "reason": "",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            provider = provider_factory(candidate["platform"])
        except (ValueError, KeyError) as exc:
            entry["reason"] = f"No metrics provider configured: {exc}"
            results.append(entry)
            continue
        response = provider.get_metrics(candidate["external_post_id"])
        if response.is_failure:
            entry["reason"] = response.message or "Metrics unavailable."
            results.append(entry)
            continue
        # Verbatim pass-through: None means "not available", never 0.
        entry["available"] = True
        entry["metrics"] = dict(response.metadata or {})
        results.append(entry)
    return results


def metrics_without_numbers(entries: list[dict]) -> list[dict]:
    """Entries whose platform supplied no usable figures yet (all None/empty)."""
    honest: list[dict] = []
    for entry in entries:
        values = entry.get("metrics") or {}
        if not entry.get("available") or not any(v is not None for v in values.values()):
            honest.append(entry)
    return honest


__all__ = ["collect_metrics", "metrics_without_numbers"]
