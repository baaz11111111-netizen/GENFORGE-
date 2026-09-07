"""Canonical, strict media metadata probing.

Probe results are cached by file identity (path + mtime + size). A changed
file always produces a fresh probe — the cache never returns stale metadata.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROBE_CACHE: dict[tuple, Any] = {}
_PROBE_STATS = {"hits": 0, "misses": 0}
_CACHE_LOCK = threading.Lock()


def _identity(source: Path) -> tuple:
    """Cache key: resolved path + mtime + size. Any change invalidates."""
    stat = source.stat()
    return (str(source), stat.st_mtime_ns, stat.st_size)


def probe_cache_stats() -> dict[str, int]:
    with _CACHE_LOCK:
        return {"hits": _PROBE_STATS["hits"], "misses": _PROBE_STATS["misses"],
                "entries": len(_PROBE_CACHE)}


def clear_probe_cache() -> None:
    """Explicit invalidation (used by tests and cleanup tooling)."""
    with _CACHE_LOCK:
        _PROBE_CACHE.clear()
        _PROBE_STATS["hits"] = 0
        _PROBE_STATS["misses"] = 0


def _cache_get(key: tuple) -> Any | None:
    with _CACHE_LOCK:
        value = _PROBE_CACHE.get(key)
        if value is not None:
            _PROBE_STATS["hits"] += 1
        return value


def _cache_put(key: tuple, value: Any) -> None:
    with _CACHE_LOCK:
        _PROBE_STATS["misses"] += 1
        if len(_PROBE_CACHE) > 512:  # bounded; drop oldest entries
            for stale in list(_PROBE_CACHE)[:128]:
                _PROBE_CACHE.pop(stale, None)
        _PROBE_CACHE[key] = value


@dataclass(frozen=True)
class MediaMetadata:
    path: str
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    pixel_format: str | None
    has_audio: bool
    audio_sample_rate: int | None
    audio_channels: int | None
    video_codec: str | None
    audio_codec: str | None
    sar: str | None
    dar: str | None


def _fps(value: str | None) -> float | None:
    if not value or value in {"N/A", "0/0"}:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        result = float(numerator) / float(denominator)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe_media(path: str | Path) -> MediaMetadata:
    """Probe media and fail explicitly when required metadata is unavailable.

    Identical repeated probes of an unchanged file are served from cache.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Media input not found: {source}")
    key = _identity(source)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe was not found on PATH. Install FFmpeg.")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise RuntimeError(f"Could not probe media '{source}': {detail}") from exc

    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    raw_duration = payload.get("format", {}).get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Media has no usable duration: {source}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"Media duration must be positive: {source}")
    if video is None and audio is None:
        raise RuntimeError(f"Media has no audio or video stream: {source}")

    def integer(stream: dict | None, key: str) -> int | None:
        try:
            value = int(stream.get(key)) if stream and stream.get(key) not in (None, "N/A") else None
            return value if value and value > 0 else None
        except (TypeError, ValueError):
            return None

    metadata = MediaMetadata(
        path=str(source), duration=duration,
        width=integer(video, "width"), height=integer(video, "height"),
        fps=_fps(video.get("r_frame_rate") if video else None),
        pixel_format=video.get("pix_fmt") if video else None,
        has_audio=audio is not None,
        audio_sample_rate=integer(audio, "sample_rate"), audio_channels=integer(audio, "channels"),
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sar=video.get("sample_aspect_ratio") if video else None,
        dar=video.get("display_aspect_ratio") if video else None,
    )
    _cache_put(key, metadata)
    return metadata
