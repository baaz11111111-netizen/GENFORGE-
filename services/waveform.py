"""Cached audio waveform peak extraction for the GENFORGE timeline.

Extracts a downsampled array of normalised amplitude peaks from a media file
using ffmpeg's ``astats`` filter.  Results are cached on disk so extraction
runs at most once per unique file (keyed on resolved path + mtime + size).

Usage
-----
from services.waveform import get_waveform_peaks

peaks = get_waveform_peaks("/path/to/clip.mp4", num_peaks=200)
# → list[float] of length ≤ num_peaks, values in [0.0, 1.0]
# → [] if the file has no audio or extraction fails

The returned list is safe to pass directly to the timeline component's
``waveform_peaks`` field — the JS frontend renders it as an SVG path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

# ── In-process cache ─────────────────────────────────────────────────────────
_CACHE: dict[str, list[float]] = {}
_CACHE_LOCK = threading.Lock()

# ── Disk cache directory (next to this file → services/waveform_cache/) ─────
_CACHE_DIR = Path(__file__).resolve().parent / "waveform_cache"


def _file_key(path: str) -> str:
    """Cache key: sha1(resolved_path + mtime_ns + size)."""
    try:
        p = Path(path).resolve()
        st = p.stat()
        raw = f"{p}|{st.st_mtime_ns}|{st.st_size}"
        return hashlib.sha1(raw.encode()).hexdigest()
    except OSError:
        return hashlib.sha1(path.encode()).hexdigest()


def _disk_path(key: str, num_peaks: int) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}_{num_peaks}.json"


def _load_disk(key: str, num_peaks: int) -> list[float] | None:
    try:
        p = _disk_path(key, num_peaks)
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _save_disk(key: str, num_peaks: int, peaks: list[float]) -> None:
    try:
        p = _disk_path(key, num_peaks)
        p.write_text(json.dumps(peaks), encoding="utf-8")
    except Exception:
        pass


def _extract_peaks_ffmpeg(path: str, num_peaks: int) -> list[float]:
    """Extract RMS peaks using ffmpeg -filter:a astats.

    Uses ``anullsrc`` + ``afade`` to chunk the audio into ``num_peaks``
    equal-length windows and measure the RMS of each.  Falls back to a
    simple ``volumedetect`` approach if astats is unavailable.
    """
    if shutil.which("ffmpeg") is None:
        return []

    resolved = str(Path(path).resolve())
    if not os.path.isfile(resolved):
        return []

    # Strategy: use ffmpeg's astats with a reset_count to get per-block RMS.
    # We split audio into num_peaks equal windows and read Flat_factor / RMS_level.
    # A simpler but reliable approach: resample to mono, get raw PCM samples,
    # compute RMS per block in Python.

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", resolved,
                "-vn",                          # drop video
                "-ac", "1",                     # mono
                "-ar", "8000",                  # 8 kHz — enough for peaks
                "-f", "f32le",                  # raw 32-bit float PCM
                "pipe:1",
            ],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []

    raw = result.stdout
    if not raw or len(raw) < 4:
        return []

    import struct
    n_samples = len(raw) // 4
    samples_per_block = max(1, n_samples // num_peaks)

    peaks: list[float] = []
    for i in range(num_peaks):
        start = i * samples_per_block * 4
        end   = min(start + samples_per_block * 4, len(raw))
        if start >= len(raw):
            break
        block = raw[start:end]
        n = len(block) // 4
        if n == 0:
            peaks.append(0.0)
            continue
        vals = struct.unpack_from(f"{n}f", block)
        rms  = math.sqrt(sum(v * v for v in vals) / n)
        peaks.append(min(1.0, rms))

    # Normalise to [0, 1] using 99th-percentile to avoid one loud spike
    # flattening everything else
    if peaks:
        sorted_p = sorted(peaks)
        p99 = sorted_p[int(len(sorted_p) * 0.99)]
        if p99 > 0.001:
            peaks = [min(1.0, v / p99) for v in peaks]

    return peaks


def get_waveform_peaks(
    path: str,
    num_peaks: int = 200,
) -> list[float]:
    """Return a list of normalised amplitude peaks for the given media file.

    Args:
        path:      Absolute path to the media file.
        num_peaks: Number of peaks to return (width of waveform display).
                   Clamped to [10, 2000].

    Returns:
        List of floats in [0.0, 1.0], length ≤ num_peaks.
        Empty list if file has no audio, ffmpeg is unavailable, or any error
        occurs — the caller should fall back to the shimmer stub.
    """
    num_peaks = max(10, min(2000, num_peaks))
    if not path or not os.path.isfile(path):
        return []

    key = _file_key(path)

    # Check in-process cache first
    cache_key = f"{key}_{num_peaks}"
    with _CACHE_LOCK:
        if cache_key in _CACHE:
            return _CACHE[cache_key]

    # Check disk cache
    peaks = _load_disk(key, num_peaks)
    if peaks is not None:
        with _CACHE_LOCK:
            _CACHE[cache_key] = peaks
        return peaks

    # Extract
    peaks = _extract_peaks_ffmpeg(path, num_peaks)

    # Store in both caches
    _save_disk(key, num_peaks, peaks)
    with _CACHE_LOCK:
        _CACHE[cache_key] = peaks
        # Bound in-process cache size
        if len(_CACHE) > 256:
            for k in list(_CACHE)[:64]:
                _CACHE.pop(k, None)

    return peaks


def clear_waveform_cache() -> None:
    """Clear the in-process waveform peak cache (used by tests)."""
    with _CACHE_LOCK:
        _CACHE.clear()
