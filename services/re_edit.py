"""Bounded, honest analytics-driven re-edit orchestration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _score(analytics: dict[str, Any]) -> float | None:
    if analytics.get("status") == "unavailable":
        return None
    values = [analytics.get(key) for key in ("hook_score", "pacing_score", "audio_score", "visual_score")]
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return sum(numeric) / len(numeric) if numeric else None


def improve_once(
    source_path: str,
    analyzer: Callable[[str], dict[str, Any]],
    editor: Callable[[str, dict[str, Any]], str],
    max_iterations: int = 1,
    minimum_improvement: float = 2.0,
) -> dict[str, Any]:
    """Render at most ``max_iterations`` improvements and select only measurable gains."""
    if max_iterations < 0 or max_iterations > 3:
        raise ValueError("max_iterations must be between 0 and 3")
    baseline = analyzer(source_path)
    baseline_score = _score(baseline)
    if baseline_score is None:
        return {"status": "analysis_unavailable", "selected_path": source_path, "iterations": 0}

    selected_path = source_path
    selected_score = baseline_score
    iterations = 0
    for _ in range(max_iterations):
        candidate = editor(selected_path, baseline)
        candidate_analytics = analyzer(candidate)
        candidate_score = _score(candidate_analytics)
        iterations += 1
        if candidate_score is None:
            break
        if candidate_score >= selected_score + minimum_improvement:
            selected_path, selected_score, baseline = candidate, candidate_score, candidate_analytics
        # No break on non-improvement: allow subsequent iterations with updated context
    return {
        "status": "completed", "selected_path": selected_path,
        "baseline_score": baseline_score, "selected_score": selected_score,
        "iterations": iterations,
    }
