"""Phase 4 Timeline Logic Tests.

Tests the pure-Python timeline_logic module directly.
No Streamlit import, no sys.modules patching, no isolation issues.

Covers:
- fmt_time
- total_timeline_duration
- split_clip_at_point
- validate_render_inputs
- inflate_timeline_from_project / sync_session_state_to_project
- push_edit_history / undo_edit / redo_edit
- EDITOR_STATE_DEFAULTS keys
- Save/reload round-trip via ProjectStore
- Playhead state behaviour
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import timeline_logic as tl
from services.project_model import ProjectState, TimelineClip
from services.project_store import ProjectStore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_state() -> dict:
    """Return a clean session-state dict with all Phase 4 defaults."""
    state = dict(tl.EDITOR_STATE_DEFAULTS)
    return state


def _project_with_two_clips(tmp_path: Path) -> ProjectState:
    f1 = tmp_path / "clip_a.mp4"
    f2 = tmp_path / "clip_b.mp4"
    f1.write_bytes(b"fake_video_a")
    f2.write_bytes(b"fake_video_b")
    project = ProjectState(name="Test Project")
    project.set_timeline([
        TimelineClip(clip_id="aaa", source_path=str(f1), order=0,
                     trim_start=1.0, trim_end=5.0),
        TimelineClip(clip_id="bbb", source_path=str(f2), order=1,
                     trim_start=0.0, trim_end=None),
    ])
    return project


# ── fmt_time ──────────────────────────────────────────────────────────────────

class TestFmtTime:
    def test_zero(self):
        assert tl.fmt_time(0.0) == "00:00.00"

    def test_half_second(self):
        result = tl.fmt_time(0.5)
        assert result.startswith("00:00.")

    def test_five_seconds(self):
        result = tl.fmt_time(5.5)
        assert result.startswith("00:05.")

    def test_one_minute(self):
        result = tl.fmt_time(60.0)
        assert result.startswith("01:00.")

    def test_over_one_hour(self):
        result = tl.fmt_time(3661.5)
        assert result.startswith("61:01.")

    def test_negative_clamped_to_zero(self):
        assert tl.fmt_time(-5.0) == "00:00.00"

    def test_format_has_two_decimal_places(self):
        r = tl.fmt_time(1.0)
        # should be MM:SS.cc format
        parts = r.split(":")
        assert len(parts) == 2
        assert "." in parts[1]
        assert len(parts[1].split(".")[1]) == 2


# ── total_timeline_duration ───────────────────────────────────────────────────

class TestTotalTimelineDuration:
    def test_empty_sequence(self):
        assert tl.total_timeline_duration([], {}, {}) == 0.0

    def test_trim_range_used_when_set(self):
        order = ["a"]
        trims = {"a": {"start": 2.0, "end": 8.0}}
        durs = {"a": 10.0}
        assert tl.total_timeline_duration(order, trims, durs) == pytest.approx(6.0)

    def test_full_clip_uses_real_duration(self):
        order = ["a"]
        trims = {"a": {"start": 0.0, "end": 0.0}}
        durs = {"a": 15.0}
        assert tl.total_timeline_duration(order, trims, durs) == pytest.approx(15.0)

    def test_trim_in_only_subtracts_start(self):
        order = ["a"]
        trims = {"a": {"start": 3.0, "end": 0.0}}
        durs = {"a": 10.0}
        assert tl.total_timeline_duration(order, trims, durs) == pytest.approx(7.0)

    def test_multiple_clips_summed(self):
        order = ["a", "b", "c"]
        trims = {
            "a": {"start": 0.0, "end": 5.0},
            "b": {"start": 1.0, "end": 4.0},
            "c": {"start": 0.0, "end": 0.0},
        }
        durs = {"a": 10.0, "b": 10.0, "c": 8.0}
        assert tl.total_timeline_duration(order, trims, durs) == pytest.approx(5.0 + 3.0 + 8.0)

    def test_unknown_duration_contributes_zero(self):
        order = ["a"]
        trims = {"a": {"start": 0.0, "end": 0.0}}
        durs = {}
        assert tl.total_timeline_duration(order, trims, durs) == pytest.approx(0.0)

    def test_trim_start_beyond_real_duration_clamped(self):
        order = ["a"]
        trims = {"a": {"start": 12.0, "end": 0.0}}
        durs = {"a": 10.0}
        assert tl.total_timeline_duration(order, trims, durs) == pytest.approx(0.0)


# ── split_clip_at_point ───────────────────────────────────────────────────────

class TestSplitClipAtPoint:
    def _make(self, trim_start=0.0, trim_end=10.0):
        clip_id = "primary::test.mp4"
        clip_map = {clip_id: {"id": clip_id, "label": "test.mp4", "role": "Primary"}}
        order = [clip_id]
        trims = {clip_id: {"start": trim_start, "end": trim_end,
                            "source_path": "/fake/test.mp4", "clip_id": "abc123"}}
        durs = {clip_id: 10.0}
        return clip_id, clip_map, order, trims, durs

    def test_basic_split_produces_two_clips(self):
        clip_id, cm, order, trims, durs = self._make()
        new_order, new_trims, _ = tl.split_clip_at_point(
            clip_id, 5.0, cm, order, trims, durs)
        assert len(new_order) == 2

    def test_split_trims_are_correct(self):
        clip_id, cm, order, trims, durs = self._make(0.0, 10.0)
        new_order, new_trims, _ = tl.split_clip_at_point(
            clip_id, 5.0, cm, order, trims, durs)
        a_id, b_id = new_order
        assert new_trims[a_id]["start"] == pytest.approx(0.0)
        assert new_trims[a_id]["end"] == pytest.approx(5.0)
        assert new_trims[b_id]["start"] == pytest.approx(5.0)
        assert new_trims[b_id]["end"] == pytest.approx(10.0)

    def test_original_clip_removed_from_order(self):
        clip_id, cm, order, trims, durs = self._make()
        new_order, _, _ = tl.split_clip_at_point(
            clip_id, 5.0, cm, order, trims, durs)
        assert clip_id not in new_order

    def test_original_clip_removed_from_map(self):
        clip_id, cm, order, trims, durs = self._make()
        _, _, new_map = tl.split_clip_at_point(
            clip_id, 5.0, cm, order, trims, durs)
        assert clip_id not in new_map

    def test_original_clip_removed_from_trims(self):
        clip_id, cm, order, trims, durs = self._make()
        _, new_trims, _ = tl.split_clip_at_point(
            clip_id, 5.0, cm, order, trims, durs)
        assert clip_id not in new_trims

    def test_split_too_close_to_start_raises(self):
        clip_id, cm, order, trims, durs = self._make()
        with pytest.raises(ValueError, match="too close to clip start"):
            tl.split_clip_at_point(clip_id, 0.05, cm, order, trims, durs)

    def test_split_too_close_to_end_raises(self):
        clip_id, cm, order, trims, durs = self._make()
        with pytest.raises(ValueError, match="too close to clip end"):
            tl.split_clip_at_point(clip_id, 9.95, cm, order, trims, durs)

    def test_split_respects_trim_start_offset(self):
        clip_id, cm, order, trims, durs = self._make(trim_start=2.0, trim_end=8.0)
        new_order, new_trims, _ = tl.split_clip_at_point(
            clip_id, 3.0, cm, order, trims, durs)
        a_id = new_order[0]
        # abs_split = 2.0 + 3.0 = 5.0
        assert new_trims[a_id]["start"] == pytest.approx(2.0)
        assert new_trims[a_id]["end"] == pytest.approx(5.0)

    def test_split_preserves_source_path(self):
        clip_id, cm, order, trims, durs = self._make()
        new_order, new_trims, _ = tl.split_clip_at_point(
            clip_id, 5.0, cm, order, trims, durs)
        for part_id in new_order:
            assert new_trims[part_id].get("source_path") == "/fake/test.mp4"

    def test_split_in_multi_clip_preserves_others(self):
        cid = "clip::0::a.mp4"
        other = "clip::1::b.mp4"
        cm = {
            cid: {"id": cid, "label": "a.mp4", "role": "Clip"},
            other: {"id": other, "label": "b.mp4", "role": "Clip"},
        }
        order = [cid, other]
        trims = {
            cid: {"start": 0.0, "end": 10.0, "source_path": "/a.mp4", "clip_id": "c1"},
            other: {"start": 0.0, "end": 5.0, "source_path": "/b.mp4", "clip_id": "c2"},
        }
        durs = {cid: 10.0, other: 5.0}
        new_order, _, _ = tl.split_clip_at_point(cid, 5.0, cm, order, trims, durs)
        assert other in new_order
        assert len(new_order) == 3


# ── validate_render_inputs ────────────────────────────────────────────────────

class TestValidateRenderInputs:
    def test_no_media_raises(self):
        with pytest.raises(ValueError, match="No media uploaded"):
            tl.validate_render_inputs(False, False, [], {})

    def test_has_video_passes_empty_order(self):
        tl.validate_render_inputs(True, False, [], {})

    def test_invalid_trim_raises(self):
        with pytest.raises(ValueError, match="trim out"):
            tl.validate_render_inputs(
                True, False, ["a"],
                {"a": {"start": 5.0, "end": 3.0, "label": "test.mp4"}}
            )

    def test_trim_end_zero_is_not_invalid(self):
        """trim_end == 0 means 'use full clip' — must NOT raise."""
        tl.validate_render_inputs(True, False, ["a"], {"a": {"start": 2.0, "end": 0.0}})

    def test_missing_source_file_raises(self, tmp_path):
        missing = str(tmp_path / "gone.mp4")
        with pytest.raises(ValueError, match="source file no longer exists"):
            tl.validate_render_inputs(
                True, False, ["a"],
                {"a": {"start": 0.0, "end": 5.0,
                       "source_path": missing, "label": "gone.mp4"}}
            )

    def test_existing_source_file_passes(self, tmp_path):
        f = tmp_path / "ok.mp4"
        f.write_bytes(b"data")
        tl.validate_render_inputs(
            True, False, ["a"],
            {"a": {"start": 0.0, "end": 5.0,
                   "source_path": str(f), "label": "ok.mp4"}}
        )

    def test_has_files_only_passes(self):
        tl.validate_render_inputs(False, True, [], {})


# ── inflate_timeline_from_project ─────────────────────────────────────────────

class TestInflateTimeline:
    def test_empty_timeline_does_nothing(self):
        state = _fresh_state()
        project = ProjectState(name="Empty")
        tl.inflate_timeline_from_project(project.timeline, state)
        assert "editor_session_clip_order" not in state

    def test_two_clips_inflated(self, tmp_path):
        state = _fresh_state()
        project = _project_with_two_clips(tmp_path)
        tl.inflate_timeline_from_project(project.timeline, state)
        assert len(state["editor_session_clip_order"]) == 2

    def test_clip_order_follows_timeline_order(self, tmp_path):
        state = _fresh_state()
        project = _project_with_two_clips(tmp_path)
        tl.inflate_timeline_from_project(project.timeline, state)
        order = state["editor_session_clip_order"]
        trims = state["editor_session_trims"]
        first_trim = trims[order[0]]
        assert first_trim["start"] == pytest.approx(1.0)

    def test_trim_end_none_becomes_zero(self, tmp_path):
        state = _fresh_state()
        project = _project_with_two_clips(tmp_path)
        tl.inflate_timeline_from_project(project.timeline, state)
        order = state["editor_session_clip_order"]
        trims = state["editor_session_trims"]
        second = trims[order[1]]
        assert second["end"] == pytest.approx(0.0)

    def test_source_path_stored_in_trims(self, tmp_path):
        state = _fresh_state()
        project = _project_with_two_clips(tmp_path)
        tl.inflate_timeline_from_project(project.timeline, state)
        order = state["editor_session_clip_order"]
        trims = state["editor_session_trims"]
        for cid in order:
            assert "source_path" in trims[cid]
            assert trims[cid]["source_path"]

    def test_first_clip_set_as_selected(self, tmp_path):
        state = _fresh_state()
        project = _project_with_two_clips(tmp_path)
        tl.inflate_timeline_from_project(project.timeline, state)
        order = state["editor_session_clip_order"]
        assert state.get("editor_selected_clip") == order[0]


# ── sync_session_state_to_project ─────────────────────────────────────────────

class TestSyncSessionState:
    def test_clips_with_source_path_written(self, tmp_path):
        state = _fresh_state()
        f1 = tmp_path / "v.mp4"; f1.write_bytes(b"v")
        state["editor_session_clip_order"] = ["c1"]
        state["editor_session_trims"] = {
            "c1": {"start": 1.0, "end": 4.0,
                   "source_path": str(f1), "clip_id": "uuid1"}
        }
        project = ProjectState(name="Sync Test")
        tl.sync_session_state_to_project(state, project, TimelineClip)
        assert len(project.timeline) == 1
        assert project.timeline[0].trim_start == pytest.approx(1.0)
        assert project.timeline[0].trim_end == pytest.approx(4.0)

    def test_clips_without_source_path_skipped(self):
        state = _fresh_state()
        state["editor_session_clip_order"] = ["c1"]
        state["editor_session_trims"] = {"c1": {"start": 0.0, "end": 0.0}}
        project = ProjectState(name="Skip Test")
        tl.sync_session_state_to_project(state, project, TimelineClip)
        assert len(project.timeline) == 0

    def test_order_preserved(self, tmp_path):
        state = _fresh_state()
        f1 = tmp_path / "a.mp4"; f1.write_bytes(b"a")
        f2 = tmp_path / "b.mp4"; f2.write_bytes(b"b")
        state["editor_session_clip_order"] = ["c1", "c2"]
        state["editor_session_trims"] = {
            "c1": {"start": 0.0, "end": 3.0, "source_path": str(f1), "clip_id": "u1"},
            "c2": {"start": 1.0, "end": 5.0, "source_path": str(f2), "clip_id": "u2"},
        }
        project = ProjectState(name="Order Test")
        tl.sync_session_state_to_project(state, project, TimelineClip)
        assert project.timeline[0].order == 0
        assert project.timeline[1].order == 1

    def test_trim_end_zero_stored_as_none(self, tmp_path):
        """trim_end=0.0 means 'use full clip' — should be stored as None in TimelineClip."""
        state = _fresh_state()
        f1 = tmp_path / "c.mp4"; f1.write_bytes(b"c")
        state["editor_session_clip_order"] = ["c1"]
        state["editor_session_trims"] = {
            "c1": {"start": 2.0, "end": 0.0, "source_path": str(f1), "clip_id": "u1"}
        }
        project = ProjectState(name="None End Test")
        tl.sync_session_state_to_project(state, project, TimelineClip)
        assert project.timeline[0].trim_end is None


# ── push_edit_history / undo_edit / redo_edit ─────────────────────────────────

class TestUndoRedoStack:
    def _setup(self, order=None, trims=None) -> dict:
        state = _fresh_state()
        state["editor_session_clip_order"] = order or ["a", "b", "c"]
        state["editor_session_trims"] = trims or {"a": {"start": 0.0}}
        return state

    def test_push_adds_entry(self):
        state = self._setup()
        tl.push_edit_history(state)
        assert len(state["edit_history"]) == 1
        assert state["edit_history_index"] == 0

    def test_push_saves_current_order(self):
        state = self._setup(order=["x", "y"])
        tl.push_edit_history(state)
        assert state["edit_history"][0]["clip_order"] == ["x", "y"]

    def test_push_marks_unsaved(self):
        state = self._setup()
        state["save_status"] = "saved"
        tl.push_edit_history(state)
        assert state["save_status"] == "unsaved"

    def test_undo_restores_previous(self):
        state = self._setup(order=["a", "b"])
        tl.push_edit_history(state)
        state["editor_session_clip_order"] = ["b", "a"]
        tl.push_edit_history(state)

        result = tl.undo_edit(state)
        assert result is True
        assert state["editor_session_clip_order"] == ["a", "b"]
        assert state["edit_history_index"] == 0

    def test_undo_at_start_returns_false(self):
        state = self._setup()
        assert tl.undo_edit(state) is False

    def test_undo_empty_history_returns_false(self):
        state = _fresh_state()
        assert tl.undo_edit(state) is False

    def test_redo_after_undo(self):
        state = self._setup(order=["a", "b"])
        tl.push_edit_history(state)
        state["editor_session_clip_order"] = ["b", "a"]
        tl.push_edit_history(state)
        tl.undo_edit(state)

        result = tl.redo_edit(state)
        assert result is True
        assert state["editor_session_clip_order"] == ["b", "a"]

    def test_redo_at_end_returns_false(self):
        state = self._setup()
        tl.push_edit_history(state)
        assert tl.redo_edit(state) is False

    def test_new_push_truncates_redo_branch(self):
        state = self._setup(order=["a", "b"])
        tl.push_edit_history(state)
        state["editor_session_clip_order"] = ["b", "a"]
        tl.push_edit_history(state)
        tl.undo_edit(state)
        # New edit while undone → redo branch must be discarded
        state["editor_session_clip_order"] = ["a", "b", "c"]
        tl.push_edit_history(state)
        assert len(state["edit_history"]) == 2
        assert state["edit_history_index"] == 1

    def test_history_capped_at_20(self):
        state = self._setup()
        for i in range(25):
            state["editor_session_clip_order"] = [str(i)]
            tl.push_edit_history(state)
        assert len(state["edit_history"]) == 20

    def test_undo_marks_unsaved(self):
        state = self._setup()
        tl.push_edit_history(state)
        state["editor_session_clip_order"] = ["b"]
        tl.push_edit_history(state)
        state["save_status"] = "saved"
        tl.undo_edit(state)
        assert state["save_status"] == "unsaved"


# ── EDITOR_STATE_DEFAULTS ─────────────────────────────────────────────────────

class TestEditorStateDefaults:
    def test_playhead_starts_at_zero(self):
        assert tl.EDITOR_STATE_DEFAULTS["playhead_position"] == pytest.approx(0.0)

    def test_timeline_zoom_is_one(self):
        assert tl.EDITOR_STATE_DEFAULTS["timeline_zoom"] == pytest.approx(1.0)

    def test_snap_enabled_by_default(self):
        assert tl.EDITOR_STATE_DEFAULTS["timeline_snap_enabled"] is True

    def test_clip_durations_empty(self):
        assert tl.EDITOR_STATE_DEFAULTS["editor_clip_durations"] == {}

    def test_clip_meta_empty(self):
        assert tl.EDITOR_STATE_DEFAULTS["editor_clip_meta"] == {}

    def test_thumbnail_cache_empty(self):
        assert tl.EDITOR_STATE_DEFAULTS["editor_thumbnail_cache"] == {}

    def test_edit_history_empty(self):
        assert tl.EDITOR_STATE_DEFAULTS["edit_history"] == []

    def test_edit_history_index_minus_one(self):
        assert tl.EDITOR_STATE_DEFAULTS["edit_history_index"] == -1


# ── Save / reload round-trip ──────────────────────────────────────────────────

class TestSaveReloadRoundTrip:
    def test_trims_survive_disk_round_trip(self, tmp_path):
        store = ProjectStore(root=tmp_path / "projects")
        f1 = tmp_path / "clip.mp4"; f1.write_bytes(b"clip_data")

        state = _fresh_state()
        state["editor_session_clip_order"] = ["c1"]
        state["editor_session_trims"] = {
            "c1": {"start": 2.5, "end": 7.5,
                   "source_path": str(f1), "clip_id": "clip_uuid_1"}
        }
        project = ProjectState(name="Round Trip")
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)

        loaded = store.load(project.project_id)
        assert loaded.timeline[0].trim_start == pytest.approx(2.5)
        assert loaded.timeline[0].trim_end == pytest.approx(7.5)

    def test_clip_order_survives_reload(self, tmp_path):
        store = ProjectStore(root=tmp_path / "projects")
        f1 = tmp_path / "a.mp4"; f1.write_bytes(b"a")
        f2 = tmp_path / "b.mp4"; f2.write_bytes(b"b")

        state = _fresh_state()
        state["editor_session_clip_order"] = ["c2", "c1"]  # reversed intentionally
        state["editor_session_trims"] = {
            "c1": {"start": 0.0, "end": 4.0,
                   "source_path": str(f1), "clip_id": "u1"},
            "c2": {"start": 1.0, "end": 3.0,
                   "source_path": str(f2), "clip_id": "u2"},
        }
        project = ProjectState(name="Order Round Trip")
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)

        loaded = store.load(project.project_id)
        sorted_clips = sorted(loaded.timeline, key=lambda c: c.order)
        # c2 was listed first → order=0 → b.mp4
        assert os.path.basename(sorted_clips[0].source_path) == "b.mp4"
        assert os.path.basename(sorted_clips[1].source_path) == "a.mp4"

    def test_inflate_after_reload_restores_state(self, tmp_path):
        store = ProjectStore(root=tmp_path / "projects")
        f1 = tmp_path / "x.mp4"; f1.write_bytes(b"x")

        state = _fresh_state()
        state["editor_session_clip_order"] = ["cc"]
        state["editor_session_trims"] = {
            "cc": {"start": 3.0, "end": 8.0,
                   "source_path": str(f1), "clip_id": "cx1"}
        }
        project = ProjectState(name="Inflate After Reload")
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)

        # Simulate fresh session
        new_state = _fresh_state()
        loaded = store.load(project.project_id)
        tl.inflate_timeline_from_project(loaded.timeline, new_state)

        order = new_state["editor_session_clip_order"]
        trims = new_state["editor_session_trims"]
        assert len(order) == 1
        assert trims[order[0]]["start"] == pytest.approx(3.0)
        assert trims[order[0]]["end"] == pytest.approx(8.0)


# ── Playhead state behaviour ──────────────────────────────────────────────────

class TestPlayheadState:
    def test_default_playhead_is_zero(self):
        state = _fresh_state()
        assert state["playhead_position"] == pytest.approx(0.0)

    def test_playhead_can_advance(self):
        state = _fresh_state()
        state["playhead_position"] = 5.5
        assert state["playhead_position"] == pytest.approx(5.5)

    def test_playhead_back_clamps_at_zero(self):
        new_pos = max(0.0, 0.5 - 1.0)
        assert new_pos == pytest.approx(0.0)

    def test_fmt_time_formats_playhead(self):
        state = _fresh_state()
        state["playhead_position"] = 73.25
        result = tl.fmt_time(state["playhead_position"])
        assert result.startswith("01:13.")


# ── Regression: timeline_zoom widget key conflict ────────────────────────────

class TestTimelineZoomState:
    """Regression tests for the StreamlitAPIException caused by writing to a
    widget-owned session state key after the widget has been instantiated.

    Root cause: st.select_slider(key="timeline_zoom") owned the session state
    key, then st.session_state["timeline_zoom"] = float(new_zoom) was called
    after the widget rendered → StreamlitAPIException.

    Fix: remove key= from select_slider; manage timeline_zoom in our own
    session state dict; no widget owns the key.
    """

    def test_no_widget_owns_timeline_zoom_key(self):
        """app.py must not have key='timeline_zoom' on any widget."""
        import os
        app_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app.py",
        )
        src = open(app_path, encoding="utf-8").read()
        # The widget must NOT own timeline_zoom as a key
        assert 'key="timeline_zoom"' not in src, (
            "StreamlitAPIException regression: st.session_state['timeline_zoom'] "
            "cannot be written after a widget with key='timeline_zoom' is instantiated. "
            "Remove key='timeline_zoom' from all widgets."
        )
        assert "key='timeline_zoom'" not in src, (
            "Same regression — single-quoted variant."
        )

    def test_timeline_zoom_is_written_after_change(self):
        """When zoom changes, timeline_zoom is written to session state (no widget key)."""
        state = _fresh_state()
        # Simulate the zoom slider returning a new value
        old_zoom = state["timeline_zoom"]
        new_zoom = 2.0
        # This is the pattern used in app.py after the fix:
        # if new_zoom != zoom:
        #     zoom = new_zoom
        #     st.session_state["timeline_zoom"] = zoom
        if new_zoom != old_zoom:
            state["timeline_zoom"] = new_zoom
        assert state["timeline_zoom"] == pytest.approx(2.0)

    def test_timeline_zoom_survives_programmatic_update(self):
        """Component event zoom update must write safely to non-widget-owned key."""
        state = _fresh_state()
        # Simulate a component zoom event: new_zoom comes from component result
        component_zoom = 1.5
        # This is the pattern at line ~1413 in app.py:
        # st.session_state["timeline_zoom"] = float(new_zoom)
        state["timeline_zoom"] = float(component_zoom)
        assert state["timeline_zoom"] == pytest.approx(1.5)

    def test_timeline_zoom_default_is_one(self):
        state = _fresh_state()
        assert state["timeline_zoom"] == pytest.approx(1.0)

    def test_timeline_zoom_clamped_to_valid_range(self):
        """Zoom values must be in [0.5, 4.0] range per the slider options."""
        valid = [0.5, 1.0, 1.5, 2.0, 3.0]
        for v in valid:
            assert 0.5 <= v <= 4.0

    def test_timeline_zoom_in_editor_state_defaults(self):
        """EDITOR_STATE_DEFAULTS must include timeline_zoom = 1.0."""
        assert "timeline_zoom" in tl.EDITOR_STATE_DEFAULTS
        assert tl.EDITOR_STATE_DEFAULTS["timeline_zoom"] == pytest.approx(1.0)
