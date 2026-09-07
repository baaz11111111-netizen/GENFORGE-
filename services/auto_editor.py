"""User-facing AI Auto-Editor: diagnose, recommend, and auto-optimize.

Built strictly on the existing bounded re-edit service (services.re_edit) and
deterministic FFmpeg probing — no second optimization engine is created.
Versions are appended through ProjectState.add_version so every iteration is
preserved and recoverable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from typing import Any, Callable

from production_features import _probe, _require_file, normalize_audio_lufs
from services.re_edit import improve_once

SCORE_KEYS = ("hook_score", "pacing_score", "audio_score", "visual_score")
LOW_SCORE_THRESHOLD = 60.0


def _deterministic_problems(path: str) -> tuple[list[str], list[str]]:
    """Problems + recommendations derived from real media metadata (always available)."""
    problems: list[str] = []
    recommendations: list[str] = []
    metadata = _probe(path)
    streams = metadata.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(metadata.get("format", {}).get("duration") or 0.0)

    if not audio_streams:
        problems.append("No audio track.")
        recommendations.append("Add a voiceover or music bed before publishing.")
    if duration and duration < 5.0:
        problems.append(f"Very short duration ({duration:.1f}s).")
        recommendations.append("Extend the edit or use it only as a teaser asset.")
    if duration and duration > 600.0:
        problems.append(f"Long-form duration ({duration:.0f}s).")
        recommendations.append("Use the AI Highlights generator to cut short-form versions.")
    for stream in video_streams:
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if width and height and min(width, height) < 720:
            problems.append(f"Low resolution ({width}x{height}).")
            recommendations.append("Re-record at 1080p or upscale before platform export.")
    return problems, recommendations


def diagnose_video(path: str, analyzer: Callable[[str], dict[str, Any]] | None = None) -> dict:
    """ANALYZE VIDEO → problems + recommendations (+ AI scores when available)."""
    source = _require_file(path, "Video to diagnose")
    problems, recommendations = _deterministic_problems(source)
    result: dict[str, Any] = {
        "status": "analyzed",
        "path": source,
        "problems": problems,
        "recommendations": recommendations,
        "scores": {},
        "ai_summary": None,
    }
    if analyzer is None:
        return result
    try:
        analytics = analyzer(source)
    except Exception as exc:  # analyzer failure must not break deterministic diagnosis
        result["ai_summary"] = f"AI analysis unavailable: {exc}"
        return result
    if analytics.get("status") == "unavailable":
        result["ai_summary"] = "AI analysis unavailable; deterministic checks only."
        return result
    scores = {key: analytics[key] for key in SCORE_KEYS if isinstance(analytics.get(key), (int, float))}
    result["scores"] = scores
    result["ai_summary"] = analytics.get("summary")
    for key, value in scores.items():
        if value < LOW_SCORE_THRESHOLD:
            problems.append(f"Weak {key.replace('_score', '')} ({value:.0f}/100).")
    return result


def default_optimizing_editor(source_path: str, analytics: dict[str, Any], output_dir: str = "temp_inputs") -> str:
    """Deterministic improvement pass: LUFS mastering, or visual grade when silent."""
    os.makedirs(output_dir, exist_ok=True)
    destination = os.path.join(output_dir, f"opt_{uuid.uuid4().hex}.mp4")
    streams = _probe(source_path).get("streams", [])
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    if has_audio:
        return normalize_audio_lufs(source_path, destination, target_lufs=-16.0)
    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", source_path,
        "-vf", "eq=contrast=1.05:saturation=1.1",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", destination,
    ]
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg was not found on PATH.")
    try:
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Optimization render exceeded 300 second timeout: {source_path}") from exc
    except subprocess.CalledProcessError as exc:
        diagnostics = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Optimization render failed: {diagnostics[-800:]}") from exc
    return destination


def auto_optimize(
    project,
    source_path: str,
    analyzer: Callable[[str], dict[str, Any]],
    editor: Callable[[str, dict[str, Any]], str] | None = None,
    max_iterations: int = 1,
    minimum_improvement: float = 2.0,
) -> dict:
    """AUTO-OPTIMIZE: analyze → render candidate → compare → keep best.

    Reuses services.re_edit.improve_once for the bounded loop; every selected
    version is appended to the project so older versions remain recoverable.
    """
    if max_iterations < 0 or max_iterations > 3:
        raise ValueError("max_iterations must be between 0 and 3.")
    if minimum_improvement < 0:
        raise ValueError("minimum_improvement cannot be negative.")
    _require_file(source_path, "Auto-optimize source")
    render = editor or (lambda path, analytics: default_optimizing_editor(path, analytics))

    outcome = improve_once(
        source_path, analyzer, render,
        max_iterations=max_iterations, minimum_improvement=minimum_improvement,
    )
    if outcome["status"] == "analysis_unavailable":
        return {"status": "analysis_unavailable", "message": "AI analysis unavailable; no auto-optimization performed.", "iterations": 0}

    if outcome["selected_path"] != source_path:
        project.add_version(
            outcome["selected_path"],
            analytics={"auto_optimized": True, "score": outcome["selected_score"]},
        )
        status = "improved"
    else:
        status = "kept_original"
    return {
        "status": status,
        "selected_path": outcome["selected_path"],
        "baseline_score": outcome["baseline_score"],
        "selected_score": outcome["selected_score"],
        "iterations": outcome["iterations"],
    }


__all__ = ["diagnose_video", "default_optimizing_editor", "auto_optimize", "LOW_SCORE_THRESHOLD"]
