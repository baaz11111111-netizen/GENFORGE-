"""Deterministic generated-asset cache (Priority #16).

Reuses previously generated assets (e.g. auto thumbnails) when the source
file AND every generation parameter are identical. Key = source identity
(path + mtime + size) + operation name + sorted parameters, so any change to
the source or the request produces a different key and a fresh asset.

Caching never breaks generation: any cache error falls through to the real
pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading

CACHE_DIR = os.path.join("temp_inputs", "asset_cache")
_MAX_ENTRIES = 128

_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0}


def asset_cache_stats() -> dict[str, int]:
    with _lock:
        return {"hits": _stats["hits"], "misses": _stats["misses"],
                "entries": len(_entry_files())}


def clear_asset_cache() -> None:
    with _lock:
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        _stats["hits"] = 0
        _stats["misses"] = 0


def asset_cache_key(source: str, operation: str, **params) -> str:
    """Content-aware deterministic key for one generated asset."""
    stat = os.stat(source)
    payload = {
        "source": os.path.abspath(source),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "operation": operation,
        "params": {k: params[k] for k in sorted(params)},
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _entry_files() -> list[str]:
    if not os.path.isdir(CACHE_DIR):
        return []
    try:
        return [os.path.join(CACHE_DIR, name) for name in os.listdir(CACHE_DIR)]
    except OSError:
        return []


def _prune_unlocked() -> None:
    files = [f for f in _entry_files() if os.path.isfile(f)]
    if len(files) <= _MAX_ENTRIES:
        return
    files.sort(key=os.path.getmtime)
    for victim in files[:len(files) - _MAX_ENTRIES]:
        try:
            os.remove(victim)
        except OSError:
            pass


def fetch_asset(key: str, ext: str, dest: str) -> bool:
    """Copy a cached asset to dest. True on a genuine hit."""
    with _lock:
        cached = os.path.join(CACHE_DIR, f"{key}{ext}")
        if os.path.isfile(cached) and os.path.getsize(cached) > 0:
            try:
                shutil.copyfile(cached, dest)
            except OSError:
                return False
            _stats["hits"] += 1
            return True
        return False


def store_asset(key: str, ext: str, produced: str) -> None:
    """Persist a freshly generated asset for future reuse."""
    with _lock:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            _prune_unlocked()
            shutil.copyfile(produced, os.path.join(CACHE_DIR, f"{key}{ext}"))
            _stats["misses"] += 1
        except OSError:
            pass  # caching must never break generation


__all__ = [
    "CACHE_DIR",
    "asset_cache_stats",
    "clear_asset_cache",
    "asset_cache_key",
    "fetch_asset",
    "store_asset",
]
