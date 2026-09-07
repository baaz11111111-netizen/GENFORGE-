"""Safe storage cleanup (Priority #26).

Reclaims disk space from REGENERATABLE intermediates only. Hard safety
rules, enforced in code:

* NEVER touches uploads/ (source assets), projects/ (user projects), or
  outputs/ (selected versions / current renders).
* Only files strictly older than ``max_age_hours`` are candidates.
* Cleanup defaults to dry-run: callers must opt in to actual deletion.
* Every deletion is recorded in the returned report.

Candidate locations are intermediate scratch areas: temp_inputs/ (including
the regenerable transition/asset caches) and temp/.
"""

from __future__ import annotations

import os
import time
from typing import Any

PROTECTED_DIRS: tuple[str, ...] = ("uploads", "projects", "outputs")
CANDIDATE_DIRS: tuple[str, ...] = ("temp_inputs", "temp")


def scan_reclaimable(root: str = ".", max_age_hours: float = 24.0,
                     candidate_dirs: tuple[str, ...] = CANDIDATE_DIRS) -> dict[str, Any]:
    """List regeneratable files older than max_age_hours with reclaimable bytes."""
    if max_age_hours < 0:
        raise ValueError("max_age_hours cannot be negative")
    cutoff = time.time() - max_age_hours * 3600
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    for name in candidate_dirs:
        if name in PROTECTED_DIRS:
            continue  # belt & braces: protected dirs are never candidates
        base = os.path.join(root, name)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                if stat.st_mtime < cutoff:
                    entries.append({"path": path, "bytes": stat.st_size,
                                    "age_hours": round((time.time() - stat.st_mtime) / 3600, 2)})
                    total_bytes += stat.st_size
    entries.sort(key=lambda item: item["bytes"], reverse=True)
    return {"entries": entries, "total_bytes": total_bytes,
            "max_age_hours": max_age_hours}


def safe_cleanup(root: str = ".", max_age_hours: float = 24.0,
                 dry_run: bool = True,
                 candidate_dirs: tuple[str, ...] = CANDIDATE_DIRS) -> dict[str, Any]:
    """Remove stale regeneratable intermediates (dry_run=True reports only).

    Sources, projects, selected versions, and current renders live in the
    protected directories and can never be reached by this function.
    """
    scan = scan_reclaimable(root, max_age_hours, candidate_dirs)
    removed: list[str] = []
    failed: list[str] = []
    if not dry_run:
        for entry in scan["entries"]:
            try:
                os.remove(entry["path"])
                removed.append(entry["path"])
            except OSError:
                failed.append(entry["path"])
    return {
        "dry_run": dry_run,
        "candidates": len(scan["entries"]),
        "reclaimable_bytes": scan["total_bytes"],
        "removed": removed,
        "failed": failed,
        "protected_dirs": list(PROTECTED_DIRS),
    }


__all__ = [
    "PROTECTED_DIRS",
    "CANDIDATE_DIRS",
    "scan_reclaimable",
    "safe_cleanup",
]
