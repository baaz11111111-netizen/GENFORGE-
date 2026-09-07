"""Pure-Python timeline business logic for GENFORGE.

All functions in this module are intentionally free of Streamlit imports.
They accept and return plain Python dicts/lists so they can be:
  - Called from app.py (which passes st.session_state)
  - Tested in pytest without a running Streamlit server
  - Reused by any future non-Streamlit interface

app.py thin wrappers forward st.session_state to these functions.
"""

from __future__ import annotations

import os
from typing import Any


# ── Time formatting ───────────────────────────────────────────────────────────

def fmt_time(seconds: float) -> str:
    """Format seconds as MM:SS.cc for playhead display.

    >>> fmt_time(0.0)
    '00:00.00'
    >>> fmt_time(65.5)
    '01:05.50'
    """
    seconds = max(0.0, float(seconds))
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m:02d}:{s:05.2f}"


# ── Timeline duration math ────────────────────────────────────────────────────

def total_timeline_duration(
    clip_order: list[str],
    trims: dict[str, dict],
    durations: dict[str, float],
) -> float:
    """Return the sum of effective clip durations for the current sequence.

    For each clip:
    - If trim_end > trim_start: active duration = trim_end - trim_start
    - Else if real duration known: active duration = real_dur - trim_start
    - Else: contributes 0 (unknown duration)
    """
    total = 0.0
    for clip_id in clip_order:
        trim = trims.get(clip_id, {})
        t_start = float(trim.get("start", 0.0))
        t_end = float(trim.get("end", 0.0))
        real = float(durations.get(clip_id, 0.0))
        if t_end > t_start:
            total += t_end - t_start
        elif real > 0:
            total += max(real - t_start, 0.0)
    return total


# ── Split at point ────────────────────────────────────────────────────────────

def split_clip_at_point(
    clip_id: str,
    split_time: float,
    clip_map: dict[str, dict],
    current_order: list[str],
    trims: dict[str, dict],
    durations: dict[str, float],
) -> tuple[list[str], dict[str, dict], dict[str, dict]]:
    """Split a clip into two at split_time seconds *relative to trim_start*.

    Returns:
        (new_order, new_trims, new_clip_map) — all original references preserved,
        original clip_id removed, two new clip IDs inserted in its place.

    Raises:
        ValueError: if split point is too close to either edge (< 0.1s margin).
    """
    trim = trims.get(clip_id, {})
    t_start = float(trim.get("start", 0.0))
    t_end = float(trim.get("end", 0.0))
    real_dur = float(durations.get(clip_id, 0.0))
    effective_end = t_end if t_end > t_start else (real_dur if real_dur > 0 else 999.0)
    abs_split = t_start + split_time  # split_time is relative to trim_start

    if abs_split <= t_start + 0.1:
        raise ValueError(
            f"Split point {split_time:.1f}s is too close to clip start."
        )
    if abs_split >= effective_end - 0.1:
        raise ValueError(
            f"Split point {split_time:.1f}s is too close to clip end."
        )

    idx = current_order.index(clip_id)
    source_data = dict(clip_map[clip_id])
    label_base = source_data.get("label", clip_id)

    clip_a_id = f"split_a::{clip_id}::{len(current_order)}"
    clip_b_id = f"split_b::{clip_id}::{len(current_order)}"

    new_map = dict(clip_map)
    new_map[clip_a_id] = {**source_data, "id": clip_a_id, "label": f"{label_base} [A]"}
    new_map[clip_b_id] = {**source_data, "id": clip_b_id, "label": f"{label_base} [B]"}
    new_map.pop(clip_id, None)

    new_trims = dict(trims)
    new_trims[clip_a_id] = {
        **trim,
        "start": t_start,
        "end": abs_split,
    }
    new_trims[clip_b_id] = {
        **trim,
        "start": abs_split,
        "end": t_end if t_end > 0 else 0.0,
    }
    new_trims.pop(clip_id, None)

    new_order = current_order[:idx] + [clip_a_id, clip_b_id] + current_order[idx + 1:]

    return new_order, new_trims, new_map


# ── Pre-render validation ─────────────────────────────────────────────────────

def validate_render_inputs(
    has_video: bool,
    has_files: bool,
    clip_order: list[str],
    trims: dict[str, dict],
) -> None:
    """Raise ValueError with a user-friendly message if render state is invalid.

    Checks:
    - At least one media source present
    - No zero-duration trim (trim_end > 0 and trim_end <= trim_start)
    - Source paths in trims dict actually exist on disk (when provided)
    """
    if not has_video and not has_files:
        raise ValueError(
            "No media uploaded. Upload at least one video file to render."
        )
    for clip_id in clip_order:
        trim = trims.get(clip_id, {})
        t_s = float(trim.get("start", 0.0))
        t_e = float(trim.get("end", 0.0))
        if t_e > 0 and t_e <= t_s:
            label = trim.get("label", clip_id.split("::")[-1])
            raise ValueError(
                f'Clip "{label}": trim out ({t_e:.1f}s) must be greater than '
                f'trim in ({t_s:.1f}s). Fix in the Inspector before rendering.'
            )
        src = trim.get("source_path", "")
        if src and not os.path.isfile(src):
            label = trim.get("label", clip_id.split("::")[-1])
            raise ValueError(
                f'Clip "{label}": source file no longer exists at {src}. '
                f'Re-upload the file to render.'
            )


# ── Canonical state sync ──────────────────────────────────────────────────────

def inflate_timeline_from_project(
    timeline: list[Any],  # list[TimelineClip]
    state: dict,
) -> None:
    """Populate editor session state keys from canonical project.timeline.

    Args:
        timeline: list of TimelineClip objects (from ProjectState.timeline)
        state:    mutable dict — in production this is st.session_state

    Only runs when timeline is non-empty. Idempotent: if called twice the
    second call replaces the first (correct behaviour on project switch).
    """
    if not timeline:
        return

    order: list[str] = []
    trims: dict[str, dict] = {}
    for clip in sorted(timeline, key=lambda c: c.order):
        clip_id = f"canonical::{clip.clip_id}"
        order.append(clip_id)
        trims[clip_id] = {
            "start": clip.trim_start or 0.0,
            "end": clip.trim_end or 0.0,
            "source_path": clip.source_path,
            "label": os.path.basename(clip.source_path),
            "clip_id": clip.clip_id,
        }

    state["editor_session_clip_order"] = order
    state["editor_session_trims"] = trims
    if order:
        state["editor_selected_clip"] = order[0]


def sync_session_state_to_project(
    state: dict,
    project: Any,  # ProjectState
    TimelineClip: Any,  # class — injected to avoid import coupling
) -> None:
    """Write live editor session state back into project.timeline.

    Args:
        state:         mutable dict (st.session_state in production)
        project:       ProjectState instance to update in-place
        TimelineClip:  the TimelineClip class (injected to avoid circular imports)

    Only syncs clips whose trim dict carries a 'source_path' key.  Clips
    that exist only as widget-level session IDs without a resolved file path
    are skipped — they will be written when the user renders.
    """
    trims = state.get("editor_session_trims") or {}
    order = state.get("editor_session_clip_order") or []
    canonical_clips: list = []
    for idx, clip_id in enumerate(order):
        trim = trims.get(clip_id, {})
        source_path = trim.get("source_path", "")
        if not source_path:
            # Try to recover source_path from the existing project timeline
            existing_id = trim.get("clip_id", "")
            if existing_id:
                for tc in project.timeline:
                    if tc.clip_id == existing_id:
                        source_path = tc.source_path
                        break
        if not source_path:
            continue
        canonical_clips.append(TimelineClip(
            clip_id=trim.get("clip_id") or clip_id,
            source_path=source_path,
            order=idx,
            trim_start=float(trim.get("start", 0.0)),
            trim_end=float(trim.get("end", 0.0)) or None,
        ))
    if canonical_clips:
        try:
            project.set_timeline(canonical_clips)
        except ValueError:
            pass  # Invalid ordering — leave existing timeline untouched


# ── Undo / redo stack ─────────────────────────────────────────────────────────

_MAX_HISTORY = 20


def push_edit_history(state: dict) -> None:
    """Push the current timeline state onto the undo stack.

    Args:
        state: mutable dict containing editor_session_clip_order,
               editor_session_trims, edit_history, edit_history_index.

    Keeps at most _MAX_HISTORY (20) entries to bound memory usage.
    """
    import copy as _copy
    order = list(state.get("editor_session_clip_order") or [])
    trims = _copy.deepcopy(state.get("editor_session_trims") or {})
    history: list = list(state.get("edit_history") or [])
    idx: int = int(state.get("edit_history_index", -1))

    # Truncate any redo branch
    if idx < len(history) - 1:
        history = history[: idx + 1]

    history.append({"clip_order": order, "trims": trims})

    # Cap at max entries
    if len(history) > _MAX_HISTORY:
        history = history[-_MAX_HISTORY:]

    state["edit_history"] = history
    state["edit_history_index"] = len(history) - 1
    state["save_status"] = "unsaved"


def undo_edit(state: dict) -> bool:
    """Restore the previous timeline state.  Returns True if undo was possible."""
    history: list = state.get("edit_history") or []
    idx: int = int(state.get("edit_history_index", -1))
    if idx <= 0 or not history:
        return False
    idx -= 1
    entry = history[idx]
    state["editor_session_clip_order"] = list(entry["clip_order"])
    state["editor_session_trims"] = dict(entry["trims"])
    state["edit_history_index"] = idx
    state["save_status"] = "unsaved"
    return True


def redo_edit(state: dict) -> bool:
    """Reapply the next timeline state.  Returns True if redo was possible."""
    history: list = state.get("edit_history") or []
    idx: int = int(state.get("edit_history_index", -1))
    if idx >= len(history) - 1 or not history:
        return False
    idx += 1
    entry = history[idx]
    state["editor_session_clip_order"] = list(entry["clip_order"])
    state["editor_session_trims"] = dict(entry["trims"])
    state["edit_history_index"] = idx
    state["save_status"] = "unsaved"
    return True


# ── Default session state values ─────────────────────────────────────────────

EDITOR_STATE_DEFAULTS: dict[str, Any] = {
    "edit_history": [],
    "edit_history_index": -1,
    "playhead_position": 0.0,
    "timeline_zoom": 1.0,
    "timeline_snap_enabled": True,
    "editor_clip_durations": {},
    "editor_clip_meta": {},
    "editor_thumbnail_cache": {},
    "save_status": "saved",
    "save_error": None,
}
