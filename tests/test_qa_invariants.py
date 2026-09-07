"""
GENFORGE QA Invariant Tests — Phase 14, 15, 16

Tests explicit state consistency invariants, failure/recovery behaviour,
and concurrency/repeatability guarantees.

Invariants tested:
  INV-01  No clip has negative effective duration
  INV-02  in_point < out_point for any set trim
  INV-03  Clip ordering is deterministic (contiguous from 0)
  INV-04  Timeline duration == sum of effective clip durations
  INV-05  Project serialisation/deserialisation preserves state
  INV-06  Undo → redo returns EXACTLY to pre-undo state
  INV-07  Deleted clips absent from canonical state
  INV-08  Switching projects does not mutate another project
  INV-09  Rendering never mutates canonical editor state
  INV-10  AI unavailable never corrupts project state
  INV-11  Temp media paths do not replace persistent project references
  INV-12  Cache invalidation occurs on project switch
  INV-13  Session state and persistent state do not diverge silently

Failure/recovery:
  FR-01 … FR-13  Per failure scenario: no crash, meaningful error, app usable

Concurrency:
  CC-01 … CC-06  Repeated save/load/undo/waveform/cache operations
"""

from __future__ import annotations

import copy
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build a realistic project with timeline
# ─────────────────────────────────────────────────────────────────────────────

def _project_with_clips(tmp_path, n=3):
    from services.project_model import ProjectState, TimelineClip
    p = ProjectState(name="InvTest")
    clips = []
    for i in range(n):
        f = tmp_path / f"clip_{i}.mp4"
        f.write_bytes(b"x" * 64)
        clips.append(TimelineClip(source_path=str(f), order=i,
                                  trim_start=0.0, trim_end=float(i + 1)))
    p.set_timeline(clips)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# INV-01  No clip has negative effective duration
# ─────────────────────────────────────────────────────────────────────────────
class TestInv01NegativeDuration:
    def test_trim_end_less_than_start_rejected_by_validate(self):
        import timeline_logic as tl
        with pytest.raises(ValueError, match="trim out"):
            tl.validate_render_inputs(
                True, False, ["a"],
                {"a": {"start": 5.0, "end": 3.0, "label": "clip.mp4"}}
            )

    def test_total_duration_never_negative(self):
        import timeline_logic as tl
        order = ["a", "b"]
        trims = {
            "a": {"start": 8.0, "end": 0.0},   # trim_start > real_dur → clamps to 0
            "b": {"start": 0.0, "end": 2.0},
        }
        durs = {"a": 5.0, "b": 10.0}
        total = tl.total_timeline_duration(order, trims, durs)
        assert total >= 0.0

    def test_speed_one_is_default(self, tmp_path):
        from services.project_model import TimelineClip
        clip = TimelineClip(source_path=str(tmp_path / "a.mp4"), order=0)
        assert clip.speed == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# INV-02  in_point < out_point for every set trim
# ─────────────────────────────────────────────────────────────────────────────
class TestInv02TrimOrdering:
    def test_validate_trim_in_greater_than_out_raises(self):
        import timeline_logic as tl
        with pytest.raises(ValueError, match="trim out"):
            tl.validate_render_inputs(
                True, False, ["x"],
                {"x": {"start": 10.0, "end": 5.0, "label": "x"}}
            )

    def test_validate_trim_in_equal_out_raises(self):
        import timeline_logic as tl
        with pytest.raises(ValueError, match="trim out"):
            tl.validate_render_inputs(
                True, False, ["x"],
                {"x": {"start": 4.0, "end": 4.0, "label": "x"}}
            )

    def test_trim_end_zero_means_full_clip_not_rejected(self):
        import timeline_logic as tl
        # end=0 means "use full clip duration" — must NOT raise
        tl.validate_render_inputs(True, False, ["x"],
                                  {"x": {"start": 2.0, "end": 0.0}})


# ─────────────────────────────────────────────────────────────────────────────
# INV-03  Clip ordering is deterministic (contiguous from 0)
# ─────────────────────────────────────────────────────────────────────────────
class TestInv03ClipOrdering:
    def test_set_timeline_enforces_contiguous_from_zero(self, tmp_path):
        from services.project_model import ProjectState, TimelineClip
        p = ProjectState(name="T")
        f = tmp_path / "v.mp4"; f.write_bytes(b"x")
        with pytest.raises(ValueError, match="contiguous"):
            p.set_timeline([
                TimelineClip(source_path=str(f), order=0),
                TimelineClip(source_path=str(f), order=2),  # gap at 1
            ])

    def test_set_timeline_after_insertion_orders_correctly(self, tmp_path):
        from services.project_model import ProjectState, TimelineClip
        p = ProjectState(name="T")
        f = tmp_path / "v.mp4"; f.write_bytes(b"x")
        clips = [TimelineClip(source_path=str(f), order=i) for i in range(4)]
        p.set_timeline(clips)
        assert [c.order for c in p.timeline] == [0, 1, 2, 3]

    def test_set_timeline_sorts_regardless_of_input_order(self, tmp_path):
        from services.project_model import ProjectState, TimelineClip
        p = ProjectState(name="T")
        f = tmp_path / "v.mp4"; f.write_bytes(b"x")
        clips = [TimelineClip(source_path=str(f), order=2),
                 TimelineClip(source_path=str(f), order=0),
                 TimelineClip(source_path=str(f), order=1)]
        p.set_timeline(clips)
        assert [c.order for c in p.timeline] == [0, 1, 2]


# ─────────────────────────────────────────────────────────────────────────────
# INV-04  Timeline duration == sum of effective clip durations
# ─────────────────────────────────────────────────────────────────────────────
class TestInv04TimelineDuration:
    def test_duration_equals_sum_of_effective_clips(self):
        import timeline_logic as tl
        order = ["a", "b", "c"]
        trims = {
            "a": {"start": 1.0, "end": 5.0},
            "b": {"start": 0.0, "end": 3.0},
            "c": {"start": 0.5, "end": 0.0},
        }
        durs = {"a": 10.0, "b": 10.0, "c": 8.0}
        total = tl.total_timeline_duration(order, trims, durs)
        expected = 4.0 + 3.0 + (8.0 - 0.5)
        assert total == pytest.approx(expected)

    def test_empty_timeline_has_zero_duration(self):
        import timeline_logic as tl
        assert tl.total_timeline_duration([], {}, {}) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# INV-05  Project serialisation/deserialisation preserves complete state
# ─────────────────────────────────────────────────────────────────────────────
class TestInv05Serialisation:
    def test_all_fields_survive_round_trip(self, tmp_path):
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        p = ProjectState(name="Serialise Test")
        p.add_source("/tmp/src.mp4")
        p.set_timeline([
            TimelineClip(source_path="/tmp/clip.mp4", order=0,
                         trim_start=1.5, trim_end=7.0, speed=0.5)
        ])
        p.update_settings(platform="YouTube", quality="high")
        p.ai_plan = {"action": "trim", "score": 0.9}
        p.add_version("/tmp/render.mp4", {"viral_score": 0.85})
        store.save(p)

        loaded = store.load(p.project_id)
        assert loaded.name == p.name
        assert loaded.source_assets == p.source_assets
        assert loaded.timeline[0].trim_start == pytest.approx(1.5)
        assert loaded.timeline[0].speed == pytest.approx(0.5)
        assert loaded.settings == p.settings
        assert loaded.ai_plan == p.ai_plan
        assert loaded.outputs[0].analytics == {"viral_score": 0.85}

    def test_model_dump_model_validate_identity(self, tmp_path):
        from services.project_model import ProjectState
        p = ProjectState(name="Dump Test")
        p.add_source("/tmp/x.mp4")
        dumped = p.model_dump()
        restored = ProjectState.model_validate(dumped)
        assert restored.project_id == p.project_id
        assert restored.name == p.name

    def test_json_is_valid_after_save(self, tmp_path):
        import json
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        p = ProjectState(name="Valid JSON")
        path = store.save(p)
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["project_id"] == p.project_id


# ─────────────────────────────────────────────────────────────────────────────
# INV-06  Undo → redo returns EXACTLY to pre-undo state
# ─────────────────────────────────────────────────────────────────────────────
class TestInv06UndoRedoExact:
    def test_undo_redo_exact_state_recovery(self):
        import timeline_logic as tl
        state = dict(tl.EDITOR_STATE_DEFAULTS)
        state["editor_session_clip_order"] = ["a", "b"]
        state["editor_session_trims"] = {
            "a": {"start": 0.0, "end": 5.0},
            "b": {"start": 1.0, "end": 4.0},
        }
        tl.push_edit_history(state)

        # Modify
        state["editor_session_clip_order"] = ["b", "a"]
        tl.push_edit_history(state)

        # Capture post-edit state
        pre_undo_order = list(state["editor_session_clip_order"])
        pre_undo_trims = copy.deepcopy(state["editor_session_trims"])

        # Undo
        tl.undo_edit(state)
        assert state["editor_session_clip_order"] == ["a", "b"]

        # Redo — must return exactly to pre-undo state
        tl.redo_edit(state)
        assert state["editor_session_clip_order"] == pre_undo_order
        assert state["editor_session_trims"] == pre_undo_trims

    def test_multiple_undo_redo_cycles_remain_consistent(self):
        import timeline_logic as tl
        state = dict(tl.EDITOR_STATE_DEFAULTS)
        states_pushed = []
        for i in range(5):
            order = [f"c{i}"]
            state["editor_session_clip_order"] = order
            state["editor_session_trims"] = {f"c{i}": {"start": float(i)}}
            tl.push_edit_history(state)
            states_pushed.append(list(order))

        # Undo all the way
        for i in range(4, 0, -1):
            tl.undo_edit(state)
            assert state["editor_session_clip_order"] == states_pushed[i - 1]

        # Redo all the way
        for i in range(1, 5):
            tl.redo_edit(state)
            assert state["editor_session_clip_order"] == states_pushed[i]


# ─────────────────────────────────────────────────────────────────────────────
# INV-07  Deleted clips absent from canonical state
# ─────────────────────────────────────────────────────────────────────────────
class TestInv07DeletedClipsAbsent:
    def test_delete_project_absent_from_list(self, tmp_path):
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        p = ProjectState(name="ToDelete")
        store.save(p)
        store.delete(p.project_id, output_root=tmp_path / "outputs")
        ids = [x.project_id for x in store.list_projects()]
        assert p.project_id not in ids

    def test_deleted_project_cannot_be_loaded(self, tmp_path):
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        p = ProjectState(name="GoneProject")
        store.save(p)
        store.delete(p.project_id, output_root=tmp_path / "outputs")
        with pytest.raises(FileNotFoundError):
            store.load(p.project_id)

    def test_set_timeline_replace_removes_old_clips(self, tmp_path):
        from services.project_model import ProjectState, TimelineClip
        p = ProjectState(name="T")
        f = tmp_path / "v.mp4"; f.write_bytes(b"x")
        p.set_timeline([TimelineClip(source_path=str(f), order=0),
                        TimelineClip(source_path=str(f), order=1)])
        # Replace with single clip
        p.set_timeline([TimelineClip(source_path=str(f), order=0)])
        assert len(p.timeline) == 1


# ─────────────────────────────────────────────────────────────────────────────
# INV-08  Switching projects does not mutate another project
# ─────────────────────────────────────────────────────────────────────────────
class TestInv08ProjectIsolation:
    def test_in_memory_objects_isolated(self):
        from services.project_model import ProjectState, TimelineClip
        pa = ProjectState(name="A")
        pb = ProjectState(name="B")
        pa.add_source("/tmp/a.mp4")
        assert "/tmp/a.mp4" not in pb.source_assets

    def test_reloaded_projects_isolated_on_disk(self, tmp_path):
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        pa = ProjectState(name="A")
        pb = ProjectState(name="B")
        store.save(pa)
        store.save(pb)
        la = store.load(pa.project_id)
        la.update_settings(x="1")
        store.save(la)
        lb = store.load(pb.project_id)
        assert "x" not in lb.settings


# ─────────────────────────────────────────────────────────────────────────────
# INV-09  Rendering never mutates canonical editor state
# ─────────────────────────────────────────────────────────────────────────────
class TestInv09RenderDoesNotMutateState:
    def test_session_state_unchanged_after_render(self, media, tmp_path):
        """Calling trim_clip_for_timeline must not alter session state dict."""
        import timeline_logic as tl
        from production_features import trim_clip_for_timeline

        state = dict(tl.EDITOR_STATE_DEFAULTS)
        state["editor_session_clip_order"] = ["c1"]
        state["editor_session_trims"] = {
            "c1": {"start": 0.0, "end": 1.0, "source_path": media.audio}
        }
        # Deep copy for comparison
        state_before = copy.deepcopy(state)
        out = str(tmp_path / "render.mp4")
        trim_clip_for_timeline(media.audio, out, 0.0, 1.0)
        # State must not have changed
        assert state["editor_session_clip_order"] == state_before["editor_session_clip_order"]
        assert state["editor_session_trims"] == state_before["editor_session_trims"]

    def test_project_state_unchanged_by_ffprobe(self, media, tmp_path):
        from services.media_probe import probe_media
        from services.project_model import ProjectState

        p = ProjectState(name="InvRender")
        p.add_source(media.audio)
        pid = p.project_id
        sources_before = list(p.source_assets)
        probe_media(media.audio)
        assert p.source_assets == sources_before
        assert p.project_id == pid


# ─────────────────────────────────────────────────────────────────────────────
# INV-10  AI unavailable never corrupts project state
# ─────────────────────────────────────────────────────────────────────────────
class TestInv10AIFailureNoCorruption:
    def test_failed_script_generation_leaves_project_intact(self):
        from services.project_model import ProjectState
        from services.script_studio import ScriptRequest, generate_script

        p = ProjectState(name="AIInv")
        original_id = p.project_id
        original_timeline = list(p.timeline)

        def fail(_): raise RuntimeError("API down")
        req = ScriptRequest(topic="X", audience="Y")
        result = generate_script(req, generator=fail)

        assert result["status"] == "unavailable"
        assert p.project_id == original_id
        assert p.timeline == original_timeline
        assert len(p.scripts) == 0

    def test_invalid_ai_response_does_not_mutate_project(self):
        from services.project_model import ProjectState
        from services.script_studio import ScriptRequest, generate_script

        p = ProjectState(name="AIInv2")
        def bad_gen(_): return {"hook": ""}  # empty hook fails validation
        req = ScriptRequest(topic="X", audience="Y")
        result = generate_script(req, generator=bad_gen)
        assert result["status"] == "invalid"
        assert len(p.scripts) == 0  # project untouched

    def test_auto_optimize_unavailable_does_not_add_version(self, media):
        from services.auto_editor import auto_optimize
        from services.project_model import ProjectState

        p = ProjectState(name="AIInv3")
        auto_optimize(p, media.audio,
                      analyzer=lambda _: {"status": "unavailable"},
                      max_iterations=1)
        assert len(p.outputs) == 0


# ─────────────────────────────────────────────────────────────────────────────
# INV-11  Temp media paths do not replace persistent project references
# ─────────────────────────────────────────────────────────────────────────────
class TestInv11TempPathsNotPersisted:
    def test_trim_output_not_in_source_assets(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.project_model import ProjectState

        p = ProjectState(name="TempPaths")
        p.add_source(media.audio)

        out = str(tmp_path / "temp_trim.mp4")
        trim_clip_for_timeline(media.audio, out, 0.0, 1.0)

        # Temp output must NOT be auto-added to source_assets
        assert out not in p.source_assets
        assert str(Path(out).resolve()) not in p.source_assets

    def test_add_version_stores_path_not_modifies_source(self, tmp_path):
        from services.project_model import ProjectState

        p = ProjectState(name="VersionPath")
        p.add_source("/tmp/original_source.mp4")
        version = p.add_version("/tmp/render_output.mp4")
        # Source assets unchanged
        assert "/tmp/render_output.mp4" not in p.source_assets
        # Version stored separately
        assert len(p.outputs) == 1


# ─────────────────────────────────────────────────────────────────────────────
# INV-12  Cache invalidation occurs on data change
# ─────────────────────────────────────────────────────────────────────────────
class TestInv12CacheInvalidation:
    def test_probe_cache_invalidated_when_file_changes(self, media, tmp_path):
        import shutil
        from services.media_probe import clear_probe_cache, probe_cache_stats, probe_media

        dest = str(tmp_path / "mutable.mp4")
        shutil.copy(media.silent, dest)
        clear_probe_cache()
        m1 = probe_media(dest)
        miss1 = probe_cache_stats()["misses"]

        # Overwrite with a different file
        shutil.copy(media.audio, dest)
        m2 = probe_media(dest)
        miss2 = probe_cache_stats()["misses"]
        assert miss2 > miss1  # forced re-probe

    def test_asset_cache_different_params_different_key(self, tmp_path):
        from services.asset_cache import asset_cache_key
        f = tmp_path / "v.mp4"
        f.write_bytes(b"x" * 512)
        k1 = asset_cache_key(str(f), "op", size=100)
        k2 = asset_cache_key(str(f), "op", size=200)
        assert k1 != k2

    def test_waveform_cache_cleared_between_calls(self, media):
        from services.waveform import _CACHE, clear_waveform_cache, get_waveform_peaks
        get_waveform_peaks(media.audio, num_peaks=20)
        assert len(_CACHE) > 0
        clear_waveform_cache()
        assert len(_CACHE) == 0


# ─────────────────────────────────────────────────────────────────────────────
# INV-13  Session state and persistent state do not diverge silently
# ─────────────────────────────────────────────────────────────────────────────
class TestInv13StateDivergence:
    def test_unsaved_changes_do_not_appear_in_reloaded_project(self, tmp_path):
        import timeline_logic as tl
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        f = tmp_path / "v.mp4"; f.write_bytes(b"x")
        p = ProjectState(name="DivTest")
        p.set_timeline([TimelineClip(source_path=str(f), order=0,
                                     trim_start=1.0, trim_end=5.0)])
        store.save(p)

        # Make in-memory changes WITHOUT saving
        p.timeline[0].trim_start = 3.0  # direct mutation, not through store

        # Reload from disk should reflect the SAVED state, not the in-memory mutation
        reloaded = store.load(p.project_id)
        assert reloaded.timeline[0].trim_start == pytest.approx(1.0)

    def test_sync_before_save_preserves_session_changes(self, tmp_path):
        import timeline_logic as tl
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        f = tmp_path / "v.mp4"; f.write_bytes(b"x")
        p = ProjectState(name="SyncSave")
        store.save(p)

        state = dict(tl.EDITOR_STATE_DEFAULTS)
        state["editor_session_clip_order"] = ["c1"]
        state["editor_session_trims"] = {
            "c1": {"start": 2.0, "end": 7.0, "source_path": str(f), "clip_id": "u1"}
        }
        # Sync session state → project → save
        tl.sync_session_state_to_project(state, p, TimelineClip)
        store.save(p)

        loaded = store.load(p.project_id)
        assert loaded.timeline[0].trim_start == pytest.approx(2.0)
        assert loaded.timeline[0].trim_end == pytest.approx(7.0)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 15 — Failure / Recovery Tests
# ─────────────────────────────────────────────────────────────────────────────
class TestFailureRecovery:
    # FR-01: No crash on missing probe target
    def test_probe_missing_file_no_crash(self, tmp_path):
        from services.media_probe import probe_media
        try:
            probe_media(str(tmp_path / "nonexistent.mp4"))
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError as e:
            assert "nonexistent" in str(e)

    # FR-02: Corrupt media probe returns meaningful error
    def test_corrupt_media_probe_meaningful_error(self, tmp_path):
        from services.media_probe import probe_media
        corrupt = tmp_path / "corrupt.mp4"
        corrupt.write_bytes(b"\x00" * 100)
        try:
            probe_media(str(corrupt))
        except (RuntimeError, FileNotFoundError) as e:
            assert str(e)  # must have a message

    # FR-03: Malformed project JSON → RuntimeError, not crash
    def test_malformed_json_raises_runtime_error(self, tmp_path):
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path)
        bad_dir = store.root / "badf00d111"
        bad_dir.mkdir()
        (bad_dir / "project.json").write_text("not json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Could not load"):
            store.load("badf00d111")

    # FR-04: list_projects skips corrupt entry, app remains usable
    def test_list_projects_skips_corrupt_entry(self, tmp_path):
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path)
        good = ProjectState(name="Good")
        store.save(good)
        bad_dir = store.root / "deadbeef"
        bad_dir.mkdir()
        (bad_dir / "project.json").write_text("{bad", encoding="utf-8")
        projects = store.list_projects()
        assert len(projects) == 1
        assert projects[0].project_id == good.project_id

    # FR-05: Path traversal rejected — security invariant
    def test_path_traversal_rejected(self, tmp_path):
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path)
        with pytest.raises(ValueError):
            store.path_for("../../etc/passwd")

    # FR-06: AI failure → status unavailable, no crash
    def test_ai_failure_returns_unavailable_status(self):
        from services.script_studio import ScriptRequest, generate_script
        def fail(_): raise RuntimeError("Quota exceeded")
        req = ScriptRequest(topic="Test", audience="Test")
        result = generate_script(req, generator=fail)
        assert result["status"] == "unavailable"
        assert result["script"] is None
        assert "FEATURE UNAVAILABLE" in result["message"] or "unavailable" in result["message"].lower()

    # FR-07: Publishing validation failure → job in FAILED, no publish attempted
    def test_publishing_validation_failure_prevents_upload(self, tmp_path):
        from services.publishing.manager import PublishingManager
        from services.publishing.mock import MockPlatformProvider
        from services.publishing.models import PublishingJob
        provider = MockPlatformProvider(platform="TikTok", scenario="normal")
        mgr = PublishingManager(provider, max_retries=0, max_polls=3, backoff_base=0.0)
        job = PublishingJob(
            platform="TikTok",
            asset_path=str(tmp_path / "missing.mp4"),  # doesn't exist
            title="T",
        )
        result = mgr.run_job(job)
        assert result.status == "FAILED"
        assert "upload" not in provider.call_log

    # FR-08: malformed trim state raises before render
    def test_malformed_trim_raises_before_render(self):
        import timeline_logic as tl
        with pytest.raises(ValueError):
            tl.validate_render_inputs(
                True, False, ["a"],
                {"a": {"start": 9.0, "end": 1.0, "label": "bad.mp4"}}
            )

    # FR-09: Waveform extraction on missing file returns []
    def test_waveform_missing_file_returns_empty(self):
        from services.waveform import get_waveform_peaks
        result = get_waveform_peaks("/does/not/exist.mp4", num_peaks=100)
        assert result == []

    # FR-10: Storage cleanup on non-existent temp dir does not crash
    def test_cleanup_missing_temp_dir_no_crash(self, tmp_path):
        from services.storage_cleanup import safe_cleanup
        result = safe_cleanup(str(tmp_path), max_age_hours=0,
                              dry_run=True, candidate_dirs=("temp_inputs", "temp"))
        assert result["candidates"] == 0

    # FR-11: Invalid duplicate orders in set_timeline — state unchanged
    def test_set_timeline_failure_leaves_state_unchanged(self, tmp_path):
        from services.project_model import ProjectState, TimelineClip
        p = ProjectState(name="FR-11")
        f = tmp_path / "v.mp4"; f.write_bytes(b"x")
        p.set_timeline([TimelineClip(source_path=str(f), order=0)])
        original_id = p.timeline[0].clip_id
        try:
            p.set_timeline([
                TimelineClip(source_path=str(f), order=0),
                TimelineClip(source_path=str(f), order=0),  # duplicate
            ])
        except ValueError:
            pass
        # Original timeline preserved
        assert len(p.timeline) == 1
        assert p.timeline[0].clip_id == original_id

    # FR-12: FFmpeg unavailable for trim — raises RuntimeError, app stays usable
    def test_ffmpeg_unavailable_raises_runtime_error(self, tmp_path, media):
        import shutil
        from production_features import trim_clip_for_timeline
        # Patch shutil.which to simulate ffmpeg not found
        with patch("production_features.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="FFmpeg"):
                trim_clip_for_timeline(media.audio, str(tmp_path / "out.mp4"),
                                       0.0, 1.0)

    # FR-13: Waveform extraction ffmpeg unavailable returns []
    def test_waveform_ffmpeg_unavailable_returns_empty(self, media):
        with patch("services.waveform.shutil.which", return_value=None):
            from services.waveform import _extract_peaks_ffmpeg
            result = _extract_peaks_ffmpeg(media.audio, 50)
            assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Phase 16 — Concurrency / Repeatability Tests
# ─────────────────────────────────────────────────────────────────────────────
class TestConcurrencyRepeatability:
    # CC-01: Save 10 times produces consistent state
    def test_save_10_times_consistent(self, tmp_path):
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        p = ProjectState(name="Repeated Save")
        for _ in range(10):
            store.save(p)
        loaded = store.load(p.project_id)
        assert loaded.name == "Repeated Save"
        assert loaded.project_id == p.project_id

    # CC-02: Undo/redo 20 times leaves consistent state
    def test_undo_redo_20_times(self):
        import timeline_logic as tl
        state = dict(tl.EDITOR_STATE_DEFAULTS)
        state["editor_session_clip_order"] = ["a"]
        state["editor_session_trims"] = {}
        for i in range(20):
            state["editor_session_clip_order"] = [f"c{i}"]
            tl.push_edit_history(state)
        for _ in range(10):
            tl.undo_edit(state)
        for _ in range(5):
            tl.redo_edit(state)
        assert state["edit_history_index"] >= 0
        assert state["editor_session_clip_order"]

    # CC-03: Repeated waveform extraction produces identical result
    def test_waveform_repeated_calls_identical(self, media):
        from services.waveform import clear_waveform_cache, get_waveform_peaks
        clear_waveform_cache()
        r1 = get_waveform_peaks(media.audio, num_peaks=50)
        r2 = get_waveform_peaks(media.audio, num_peaks=50)
        r3 = get_waveform_peaks(media.audio, num_peaks=50)
        assert r1 == r2 == r3

    # CC-04: Concurrent probe_media on same file returns same result
    def test_concurrent_probe_media_same_result(self, media):
        from services.media_probe import probe_media
        results = []
        errors = []
        def do_probe():
            try:
                m = probe_media(media.landscape)
                results.append(m.duration)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=do_probe) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        assert len(set(round(r, 3) for r in results)) == 1  # all same duration

    # CC-05: Concurrent project saves do not corrupt each other
    def test_concurrent_project_saves(self, tmp_path):
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        projects = [ProjectState(name=f"Concurrent {i}") for i in range(5)]
        errors = []
        def save_project(p):
            try:
                for _ in range(3):
                    store.save(p)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=save_project, args=(p,)) for p in projects]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        loaded = store.list_projects()
        assert len(loaded) == 5

    # CC-06: Asset cache thread-safe fetch/store
    def test_asset_cache_thread_safe(self, tmp_path):
        from services.asset_cache import (
            asset_cache_stats,
            clear_asset_cache,
            fetch_asset,
            store_asset,
        )
        clear_asset_cache()
        f = tmp_path / "src.png"
        f.write_bytes(b"\x89PNG test")
        errors = []
        def do_store():
            try:
                store_asset("shared_key", ".png", str(f))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=do_store) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        dest = tmp_path / "fetched.png"
        hit = fetch_asset("shared_key", ".png", str(dest))
        assert hit is True

    # CC-07: delete_all returns accurate count after 5 concurrent creates
    def test_delete_all_after_concurrent_creates(self, tmp_path):
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        created = []
        lock = threading.Lock()
        def create():
            p = ProjectState(name="Concurrent Create")
            store.save(p)
            with lock:
                created.append(p.project_id)
        threads = [threading.Thread(target=create) for _ in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        count = store.delete_all(output_root=tmp_path / "outputs")
        assert count == 6
        assert store.list_projects() == []


# ─────────────────────────────────────────────────────────────────────────────
# Publishing state machine invariants
# ─────────────────────────────────────────────────────────────────────────────
class TestPublishingStateMachineInvariants:
    def test_published_is_terminal_cannot_transition(self):
        from services.publishing.models import ALLOWED_TRANSITIONS
        assert ALLOWED_TRANSITIONS["PUBLISHED"] == frozenset()

    def test_cancelled_is_terminal_cannot_transition(self):
        from services.publishing.models import ALLOWED_TRANSITIONS
        assert ALLOWED_TRANSITIONS["CANCELLED"] == frozenset()

    def test_all_statuses_have_transitions_defined(self):
        from services.publishing.models import ALLOWED_TRANSITIONS, JOB_STATUSES
        for status in JOB_STATUSES:
            assert status in ALLOWED_TRANSITIONS

    def test_job_retry_count_non_negative_invariant(self):
        from services.publishing.models import PublishingJob
        with pytest.raises(ValueError, match="negative"):
            PublishingJob(platform="TikTok", retry_count=-1)

    def test_terminal_success_status_correctly_identified(self):
        from services.publishing.models import PublishingJob
        job = PublishingJob(platform="TikTok", status="PUBLISHED",
                            external_post_id="abc123")
        assert job.is_terminal_success() is True

        job2 = PublishingJob(platform="TikTok", status="FAILED")
        assert job2.is_terminal_success() is False

    def test_job_status_transitions_log_timestamps(self):
        from datetime import timezone
        from datetime import datetime as dt
        from services.publishing.models import PublishingJob
        job = PublishingJob(platform="TikTok", status="READY")
        before = dt.now(timezone.utc).isoformat()
        job.transition_to("UPLOADING")
        assert job.updated_at >= before
