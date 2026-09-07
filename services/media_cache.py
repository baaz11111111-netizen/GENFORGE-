"""Disk cache for transition-normalized intermediates (Priority #10).

The transition engine normalizes every clip to the canonical spec before
xfade. When the same source clip participates in multiple transitions (or a
render is repeated), re-normalizing is pure waste. This cache stores the
normalized intermediate keyed by:

    source identity (path + mtime + size) + width + height + fps + duration

Invalidation: any change to the source file, resolution, FPS, or duration
produces a different key, so stale media can never be returned. Stage-2
validation in the transition engine still runs on cache hits, preserving the
verified-stable correctness guarantees.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading

CACHE_DIR = os.path.join("temp_inputs", "transition_cache")
_MAX_ENTRIES = 64

_LOCK = threading.Lock()
_STATS = {"hits": 0, "misses": 0}


def normalization_cache_stats() -> dict[str, int]:
    with _LOCK:
        return {"hits": _STATS["hits"], "misses": _STATS["misses"],
                "entries": len([f for f in _entries() if f.endswith(".mp4")])}


def _entries() -> list[str]:
    if not os.path.isdir(CACHE_DIR):
        return []
    try:
        return os.listdir(CACHE_DIR)
    except OSError:
        return []


def clear_normalization_cache() -> None:
    """Remove all cached intermediates and reset statistics."""
    with _LOCK:
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        _STATS["hits"] = 0
        _STATS["misses"] = 0


def normalization_cache_key(source: str, width: int, height: int,
                            fps: int, duration: float) -> str:
    """Content-aware key: source identity + every normalization parameter."""
    stat = os.stat(source)
    raw = (f"{os.path.abspath(source)}|{stat.st_mtime_ns}|{stat.st_size}"
           f"|{width}x{height}|{fps}|{round(duration, 3)}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _prune_unlocked() -> None:
    files = [os.path.join(CACHE_DIR, name) for name in _entries() if name.endswith(".mp4")]
    if len(files) <= _MAX_ENTRIES:
        return
    files.sort(key=lambda path: os.path.getmtime(path))
    for victim in files[:len(files) - _MAX_ENTRIES]:
        try:
            os.remove(victim)
        except OSError:
            pass


def fetch_normalized(key: str, dest: str) -> bool:
    """Copy a cached intermediate to dest. Returns True on a genuine hit."""
    with _LOCK:
        cached = os.path.join(CACHE_DIR, f"{key}.mp4")
        if os.path.isfile(cached) and os.path.getsize(cached) > 0:
            try:
                shutil.copyfile(cached, dest)
            except OSError:
                return False
            _STATS["hits"] += 1
            return True
        _STATS["misses"] += 1
        return False


def store_normalized(key: str, intermediate: str) -> None:
    """Persist a freshly normalized intermediate for future reuse."""
    with _LOCK:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            _prune_unlocked()
            shutil.copyfile(intermediate, os.path.join(CACHE_DIR, f"{key}.mp4"))
        except OSError:
            pass  # caching must never break a render


__all__ = [
    "CACHE_DIR",
    "normalization_cache_stats",
    "clear_normalization_cache",
    "normalization_cache_key",
    "fetch_normalized",
    "store_normalized",
]
