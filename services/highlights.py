"""AI Highlights / Shorts generator built on the canonical services.

Detection is honest: audio-energy scoring via FFmpeg volumedetect when audio
exists, deterministic opening-segment fallback when it does not. Gemini text
enrichment is used only when configured; otherwise templates are clearly
labelled as heuristic (never fabricated AI output).

Rendering reuses the canonical trim + platform adaptation pipeline.
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from services.media_probe import probe_media
from production_features import trim_clip_for_timeline
from services.platform_profiles import PLATFORM_PROFILES, export_for_platform

logger = logging.getLogger(__name__)


class Highlight(BaseModel):
    """One detected highlight candidate with metadata for review and export."""

    highlight_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source_asset: str
    start: float
    end: float
    score: float
    reason: str
    hook: str
    title: str
    caption: str
    cta: str

    @field_validator("start", "end")
    @classmethod
    def _non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Highlight timestamps cannot be negative.")
        return value

    def model_post_init(self, __context: Any) -> None:
        if self.end <= self.start:
            raise ValueError("Highlight end must be after start.")

    @property
    def duration(self) -> float:
        return self.end - self.start


def _mean_volume_for_window(source: str, start: float, window: float) -> float | None:
    """Measure mean audio volume (dB) of one window using FFmpeg volumedetect."""
    command = [
        "ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{window:.3f}",
        "-i", source, "-vn", "-af", "volumedetect", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    for line in (result.stderr or "").splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().replace("dB", "").strip())
            except (IndexError, ValueError):
                return None
    return None


def detect_highlights(
    video_path: str,
    count: int = 3,
    min_duration: float = 4.0,
    max_duration: float = 15.0,
    window: float = 2.0,
) -> list[Highlight]:
    """Detect highlight candidates by scoring audio energy windows.

    Returns up to ``count`` candidates ordered by score. When the source has
    no audio, one honest opening-segment candidate is returned instead.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    meta = probe_media(video_path)
    duration = meta.duration
    clip_len = max(min_duration, min(max_duration, duration))

    if not meta.has_audio or duration <= clip_len:
        reason = ("source shorter than highlight length; using full clip"
                  if duration <= clip_len else "no audio stream; heuristic opening segment")
        return [_make_highlight(video_path, 0.0, min(clip_len, duration), 50.0, reason)]

    scores: list[tuple[float, float]] = []
    start = 0.0
    while start + window <= duration:
        level = _mean_volume_for_window(video_path, start, window)
        if level is not None:
            scores.append((start, level))
        start += window / 2  # 50% overlap

    if not scores:
        return [_make_highlight(video_path, 0.0, clip_len, 50.0,
                                "audio analysis unavailable; heuristic opening segment")]

    loudest = max(level for _, level in scores)
    # Rank windows by loudness, anchor each highlight on its window
    ordered = sorted(scores, key=lambda item: item[1], reverse=True)
    picked: list[Highlight] = []
    for window_start, level in ordered:
        if len(picked) >= count:
            break
        anchor = max(0.0, min(window_start, duration - clip_len))
        end = min(duration, anchor + clip_len)
        if any(abs(anchor - p.start) < clip_len * 0.6 for p in picked):
            continue  # skip overlapping candidates
        score = round(50.0 + 50.0 * max(0.0, min(1.0, (level + 60.0) / 60.0)), 1)
        picked.append(_make_highlight(
            video_path, anchor, end, score,
            f"peak audio energy window ({level:.1f} dB mean)",
        ))
    return picked or [_make_highlight(video_path, 0.0, clip_len, 50.0, "no scoreable audio windows")]


def _make_highlight(source: str, start: float, end: float, score: float, reason: str) -> Highlight:
    """Build a highlight with honest heuristic copy (AI text enrichment optional)."""
    hook, title, caption, cta = _copy_from_ai(source, start, end) if _ai_available() else _heuristic_copy(reason)
    return Highlight(
        source_asset=str(os.path.abspath(source)), start=round(start, 3), end=round(end, 3),
        score=score, reason=reason, hook=hook, title=title, caption=caption, cta=cta,
    )


def _ai_available() -> bool:
    try:
        from services.ai_service import get_gemini_client
        get_gemini_client()
        return True
    except Exception:
        return False


def _copy_from_ai(source: str, start: float, end: float) -> tuple[str, str, str, str]:
    """Ask Gemini for copy; fall back to labelled heuristics on any failure."""
    try:
        from services.ai_service import generate_json
        payload = generate_json(
            f"Write short-form copy for a video highlight at {start:.1f}s-{end:.1f}s of {os.path.basename(source)}. "
            'Return JSON: {"hook": "...", "title": "...", "caption": "...", "cta": "..."}'
        )
        return (str(payload.get("hook", "")).strip() or "Watch this moment",
                str(payload.get("title", "")).strip() or "Highlight",
                str(payload.get("caption", "")).strip() or "",
                str(payload.get("cta", "")).strip() or "Follow for more")
    except Exception as exc:
        logger.info("AI copy unavailable, using heuristic: %s", exc)
        return _heuristic_copy("AI copy unavailable")


def _heuristic_copy(reason: str) -> tuple[str, str, str, str]:
    return (
        "You need to see this moment",
        "Highlight reel",
        f"Auto-detected highlight ({reason}).",
        "Follow for more",
    )


def adjust_highlight(highlight: Highlight, start: float | None = None, end: float | None = None) -> Highlight:
    """Return a copy of the highlight with edited start/end (user review step)."""
    new_start = highlight.start if start is None else float(start)
    new_end = highlight.end if end is None else float(end)
    return highlight.model_copy(update={"start": round(new_start, 3), "end": round(new_end, 3)})


def render_highlight(highlight: Highlight, output_dir: str, profile: str = "final") -> str:
    """Trim the highlight through the canonical timeline trim renderer.

    ``profile`` picks the encode preset ("preview" for fast review renders,
    "final" for publish quality — the default).
    """
    if not os.path.isfile(highlight.source_asset):
        raise FileNotFoundError(f"Highlight source missing: {highlight.source_asset}")
    os.makedirs(output_dir, exist_ok=True)
    destination = os.path.join(output_dir, f"highlight_{highlight.highlight_id[:8]}.mp4")
    return trim_clip_for_timeline(highlight.source_asset, destination, highlight.start, highlight.end,
                                  profile=profile)


def render_highlight_versions(highlight: Highlight, output_dir: str, platforms: list[str] | None = None,
                              profile: str = "final") -> dict[str, str]:
    """Render the highlight plus one adapted version per requested platform."""
    base = render_highlight(highlight, output_dir, profile=profile)
    targets = platforms or list(PLATFORM_PROFILES)
    versions = {"master": base}
    for platform in targets:
        if platform not in PLATFORM_PROFILES:
            raise ValueError(f"Unknown platform profile: {platform}")
        version_path = os.path.join(output_dir, f"highlight_{highlight.highlight_id[:8]}_{platform.replace(' ', '_').lower()}.mp4")
        versions[platform] = export_for_platform(base, version_path, platform)
    return versions
