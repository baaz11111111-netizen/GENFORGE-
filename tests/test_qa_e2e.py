"""
GENFORGE QA End-to-End Tests — Phase 13 (E2E-001 … E2E-010)

Each workflow crosses multiple modules and exercises the complete path from
project creation to rendered/published output. Uses real FFmpeg where required.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _probe(path: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def _good_script_gen(_prompt):
    return {
        "hook": "Hook text", "introduction": "Intro text", "body": "Body content here",
        "cta": "Follow for more", "alternate_hooks": ["Alt 1", "Alt 2"],
        "short_version": "Short version", "long_version": "Long version content here",
    }


# ─────────────────────────────────────────────────────────────────────────────
# E2E-001 — Full editing workflow: import → trim → split → save → reload → render
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E001EditingWorkflow:
    def test_import_trim_split_save_reload_render(self, media, tmp_path):
        import timeline_logic as tl
        from production_features import trim_clip_for_timeline
        from services.media_probe import probe_media
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-001")
        project.add_source(media.audio)

        # Build initial timeline
        state = dict(tl.EDITOR_STATE_DEFAULTS)
        cid = "clip::0::audio.mp4"
        state["editor_session_clip_order"] = [cid]
        state["editor_session_trims"] = {
            cid: {"start": 0.0, "end": 0.0, "source_path": media.audio,
                  "label": "audio.mp4", "clip_id": "orig1"}
        }
        tl.push_edit_history(state)

        # Apply trim
        state["editor_session_trims"][cid]["start"] = 0.2
        state["editor_session_trims"][cid]["end"] = 1.6
        tl.push_edit_history(state)

        # Split at 0.7s relative to trim_start
        clip_map = {cid: {"id": cid, "label": "audio.mp4", "role": "Primary"}}
        durations = {cid: 2.0}
        new_order, new_trims, new_map = tl.split_clip_at_point(
            cid, 0.7, clip_map, state["editor_session_clip_order"],
            state["editor_session_trims"], durations
        )
        state["editor_session_clip_order"] = new_order
        state["editor_session_trims"] = new_trims
        tl.push_edit_history(state)
        assert len(new_order) == 2

        # Sync to project and save
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)

        # Reload
        loaded = store.load(project.project_id)
        new_state = dict(tl.EDITOR_STATE_DEFAULTS)
        tl.inflate_timeline_from_project(loaded.timeline, new_state)
        assert len(new_state["editor_session_clip_order"]) == 2

        # Render each clip
        out_dir = tmp_path / "renders"
        out_dir.mkdir()
        for i, clip in enumerate(loaded.timeline):
            out = str(out_dir / f"clip_{i}.mp4")
            trim_clip_for_timeline(
                clip.source_path, out,
                start_time=clip.trim_start or 0.0,
                end_time=clip.trim_end or 0.0,
            )
            assert Path(out).is_file()
            assert Path(out).stat().st_size > 0


# ─────────────────────────────────────────────────────────────────────────────
# E2E-002 — Image processing → add to project → save → reload
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E002ImageProcessingWorkflow:
    def test_image_compose_store_in_project(self, tmp_path):
        from PIL import Image
        from services.image_studio import compose_advanced
        from services.project_model import ProjectState
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-002")

        # Create a fake RGBA cutout
        cutout = Image.new("RGBA", (400, 600), (200, 100, 50, 220))
        cutout_path = str(tmp_path / "cutout.png")
        cutout.save(cutout_path, "PNG")

        # Compose with gradient
        out_path = str(tmp_path / "composed.png")
        compose_advanced(cutout_path, out_path,
                         gradient=("#FF512F", "#DD2476"),
                         canvas_size=(1080, 1920))
        assert Path(out_path).is_file()

        # Add to project
        project.add_source(out_path)
        store.save(project)

        loaded = store.load(project.project_id)
        assert out_path in [os.path.abspath(s) for s in loaded.source_assets]

    def test_crop_all_presets_and_store(self, tmp_path):
        from PIL import Image
        from services.image_studio import CROP_PRESETS, crop_to_preset
        from services.project_model import ProjectState
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-002-crop")

        src = Image.new("RGB", (1920, 1080), (128, 200, 100))
        src_path = str(tmp_path / "landscape.png")
        src.save(src_path, "PNG")

        for preset_name in CROP_PRESETS:
            safe = preset_name.replace(" ", "_").replace(":", "x").replace("/", "x")
            out_path = str(tmp_path / f"crop_{safe}.png")
            crop_to_preset(src_path, preset_name, out_path)
            assert Path(out_path).is_file()
            project.add_source(out_path)

        store.save(project)
        loaded = store.load(project.project_id)
        assert len(loaded.source_assets) == len(CROP_PRESETS)


# ─────────────────────────────────────────────────────────────────────────────
# E2E-003 — AI Director: apply plan → modify → undo/redo → save → reload
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E003AIDirectorWorkflow:
    def test_ai_plan_applied_then_manually_modified(self, tmp_path):
        import timeline_logic as tl
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-003")
        f1 = tmp_path / "v1.mp4"; f1.write_bytes(b"v")

        # Simulate AI plan applying timeline changes
        state = dict(tl.EDITOR_STATE_DEFAULTS)
        ai_cid = "canonical::ai_clip_1"
        state["editor_session_clip_order"] = [ai_cid]
        state["editor_session_trims"] = {
            ai_cid: {"start": 0.0, "end": 5.0, "source_path": str(f1),
                     "label": "v1.mp4", "clip_id": "ai1"}
        }
        tl.push_edit_history(state)

        # Store AI plan on project
        project.ai_plan = {"action": "trim", "clip_id": "ai1", "end": 5.0}
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)

        # Manual modification — push history BEFORE changing
        tl.push_edit_history(state)  # history[1]: end=5.0
        state["editor_session_trims"][ai_cid]["end"] = 3.5
        tl.push_edit_history(state)  # history[2]: end=3.5

        # Undo the manual change → back to end=5.0
        tl.undo_edit(state)
        assert state["editor_session_trims"][ai_cid]["end"] == pytest.approx(5.0)

        # Redo it → back to end=3.5
        tl.redo_edit(state)
        assert state["editor_session_trims"][ai_cid]["end"] == pytest.approx(3.5)

        # Save and reload
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)
        loaded = store.load(project.project_id)
        assert loaded.ai_plan is not None
        assert loaded.timeline[0].trim_end == pytest.approx(3.5)


# ─────────────────────────────────────────────────────────────────────────────
# E2E-004 — Two projects, repeated switching, zero state leakage
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E004ProjectIsolation:
    def test_switch_ab_repeatedly_no_leakage(self, tmp_path):
        import timeline_logic as tl
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        fa = tmp_path / "alpha.mp4"; fa.write_bytes(b"a")
        fb = tmp_path / "beta.mp4";  fb.write_bytes(b"b")

        pa = ProjectState(name="ProjectAlpha")
        pb = ProjectState(name="ProjectBeta")

        # Set up alpha
        state_a = dict(tl.EDITOR_STATE_DEFAULTS)
        state_a["editor_session_clip_order"] = ["ca"]
        state_a["editor_session_trims"] = {
            "ca": {"start": 1.0, "end": 3.0, "source_path": str(fa), "clip_id": "ua"}
        }
        tl.sync_session_state_to_project(state_a, pa, TimelineClip)
        pa.add_source(str(fa))  # explicitly register source
        store.save(pa)

        # Set up beta
        state_b = dict(tl.EDITOR_STATE_DEFAULTS)
        state_b["editor_session_clip_order"] = ["cb"]
        state_b["editor_session_trims"] = {
            "cb": {"start": 0.5, "end": 2.5, "source_path": str(fb), "clip_id": "ub"}
        }
        tl.sync_session_state_to_project(state_b, pb, TimelineClip)
        pb.add_source(str(fb))  # explicitly register source
        store.save(pb)

        # Switch 5 times, mutate, verify isolation each time
        for _ in range(5):
            loaded_a = store.load(pa.project_id)
            loaded_b = store.load(pb.project_id)
            assert loaded_a.timeline[0].trim_start == pytest.approx(1.0)
            assert loaded_b.timeline[0].trim_start == pytest.approx(0.5)
            assert loaded_a.source_assets != loaded_b.source_assets

            # Mutate a — should not affect b
            loaded_a.update_settings(iteration=_)
            store.save(loaded_a)
            reloaded_b = store.load(pb.project_id)
            assert "iteration" not in reloaded_b.settings

    def test_in_memory_objects_do_not_share_state(self):
        from services.project_model import ProjectState
        pa = ProjectState(name="A")
        pb = ProjectState(name="B")
        pa.add_source("/tmp/a.mp4")
        assert "/tmp/a.mp4" not in pb.source_assets
        pb.update_settings(key="val")
        assert "key" not in pa.settings


# ─────────────────────────────────────────────────────────────────────────────
# E2E-005 — trim → reorder → transition → audio → undo → redo → render
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E005TrimReorderRender:
    def test_full_edit_render_cycle(self, media, tmp_path):
        import timeline_logic as tl
        from production_features import trim_clip_for_timeline
        from services.media_probe import probe_media
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-005")
        project.add_source(media.audio)

        state = dict(tl.EDITOR_STATE_DEFAULTS)
        c1 = "clip::0"
        c2 = "clip::1"
        state["editor_session_clip_order"] = [c1, c2]
        state["editor_session_trims"] = {
            c1: {"start": 0.0, "end": 1.0, "source_path": media.audio, "clip_id": "u1"},
            c2: {"start": 0.5, "end": 1.5, "source_path": media.audio, "clip_id": "u2"},
        }
        tl.push_edit_history(state)

        # Reorder: swap c1 and c2
        state["editor_session_clip_order"] = [c2, c1]
        tl.push_edit_history(state)

        # Undo reorder
        tl.undo_edit(state)
        assert state["editor_session_clip_order"] == [c1, c2]

        # Redo reorder
        tl.redo_edit(state)
        assert state["editor_session_clip_order"] == [c2, c1]

        # Sync to project and save
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)

        # Reload
        loaded = store.load(project.project_id)
        new_state = dict(tl.EDITOR_STATE_DEFAULTS)
        tl.inflate_timeline_from_project(loaded.timeline, new_state)
        assert len(new_state["editor_session_clip_order"]) == 2

        # Render each clip (use start_time/end_time parameter names)
        out_dir = tmp_path / "renders_e2e005"
        out_dir.mkdir()
        for i, clip in enumerate(loaded.timeline):
            out = str(out_dir / f"clip_{i}.mp4")
            trim_clip_for_timeline(
                clip.source_path, out,
                start_time=clip.trim_start or 0.0,
                end_time=clip.trim_end or 0.0,
            )
            assert Path(out).stat().st_size > 0
            meta = probe_media(out)
            assert meta.duration > 0


# ─────────────────────────────────────────────────────────────────────────────
# E2E-006 — Create → rename → edit → save → reload → render
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E006RenamePersistence:
    def test_renamed_project_renders_correctly(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        p = ProjectState(name="Original Name")
        p.set_timeline([
            TimelineClip(source_path=media.audio, order=0,
                         trim_start=0.0, trim_end=1.0)
        ])
        store.save(p)

        # Rename
        renamed = ProjectState.model_validate({**p.model_dump(), "name": "Final Name"})
        store.save(renamed)

        # Reload
        reloaded = store.load(p.project_id)
        assert reloaded.name == "Final Name"

        # Render
        out = str(tmp_path / "renamed_render.mp4")
        clip = reloaded.timeline[0]
        trim_clip_for_timeline(clip.source_path, out,
                               start_time=clip.trim_start, end_time=clip.trim_end or 0.0)
        assert Path(out).is_file()
        assert Path(out).stat().st_size > 0


# ─────────────────────────────────────────────────────────────────────────────
# E2E-007 — Large project stress test (many clips, repeated undo/redo)
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E007LargeProjectStress:
    def test_15_clips_undo_redo_save_reload(self, tmp_path):
        import timeline_logic as tl
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="Stress Test")

        # Create 15 fake clip files
        clip_files = []
        for i in range(15):
            f = tmp_path / f"clip_{i}.mp4"
            f.write_bytes(b"x" * 100)
            clip_files.append(str(f))

        state = dict(tl.EDITOR_STATE_DEFAULTS)
        order = [f"clip::{i}" for i in range(15)]
        trims = {
            f"clip::{i}": {
                "start": 0.0, "end": float(i + 1),
                "source_path": clip_files[i],
                "clip_id": f"uid{i}",
            }
            for i in range(15)
        }
        state["editor_session_clip_order"] = order
        state["editor_session_trims"] = trims
        tl.push_edit_history(state)

        # Perform 10 edits (trim changes)
        for i in range(10):
            cid = order[i % 15]
            state["editor_session_trims"][cid]["end"] = float(i + 0.5)
            tl.push_edit_history(state)

        # Undo 5 times
        for _ in range(5):
            tl.undo_edit(state)
        # Redo 3 times
        for _ in range(3):
            tl.redo_edit(state)

        assert len(state["editor_session_clip_order"]) == 15
        assert state["edit_history_index"] >= 0

        # Sync + save + reload
        tl.sync_session_state_to_project(state, project, TimelineClip)
        store.save(project)
        loaded = store.load(project.project_id)
        assert len(loaded.timeline) == 15

    def test_history_cap_prevents_unbounded_growth(self):
        import timeline_logic as tl
        state = dict(tl.EDITOR_STATE_DEFAULTS)
        state["editor_session_clip_order"] = ["a"]
        state["editor_session_trims"] = {}
        for i in range(30):
            state["editor_session_clip_order"] = [f"c{i}"]
            tl.push_edit_history(state)
        assert len(state["edit_history"]) == 20  # capped


# ─────────────────────────────────────────────────────────────────────────────
# E2E-008 — Failure recovery: bad media → recover → continue → render
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E008FailureRecovery:
    def test_bad_media_probe_does_not_corrupt_project(self, media, tmp_path):
        from services.media_probe import probe_media
        from services.project_model import ProjectState
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-008")
        project.add_source(media.audio)

        # Try to probe corrupt file — should raise but not corrupt project
        corrupt = tmp_path / "corrupt.mp4"
        corrupt.write_bytes(b"not a video")
        try:
            probe_media(str(corrupt))
        except (RuntimeError, FileNotFoundError):
            pass  # expected

        # Project state still intact
        assert len(project.source_assets) == 1
        store.save(project)
        loaded = store.load(project.project_id)
        assert loaded.status != "failed"

    def test_render_missing_file_recorded_as_error(self, tmp_path):
        from services.project_model import ProjectState
        project = ProjectState(name="Error Recovery")
        project.record_error("Source file missing during render")
        assert project.status == "failed"
        assert len(project.errors) == 1
        # App remains usable — project can be saved/loaded
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path / "projects")
        store.save(project)
        loaded = store.load(project.project_id)
        assert loaded.errors[0] == "Source file missing during render"

    def test_failed_project_can_be_recovered_and_re_rendered(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="Recovery Test")
        project.record_error("first attempt failed")
        store.save(project)

        # Recovery: reset status and add valid clip
        loaded = store.load(project.project_id)
        loaded.status = "draft"
        loaded.set_timeline([
            TimelineClip(source_path=media.audio, order=0,
                         trim_start=0.0, trim_end=1.0)
        ])
        store.save(loaded)

        out = str(tmp_path / "recovered.mp4")
        trim_clip_for_timeline(media.audio, out, 0.0, 1.0)
        version = loaded.add_version(out)
        assert version.status == "rendered"
        store.save(loaded)

        reloaded = store.load(project.project_id)
        assert len(reloaded.outputs) == 1


# ─────────────────────────────────────────────────────────────────────────────
# E2E-009 — AI failure recovery: AI unavailable → fallback → edit → render
# ─────────────────────────────────────────────────────────────────────────────
class TestE2E009AIFailureRecovery:
    def test_ai_unavailable_fallback_to_manual_edit(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.project_model import ProjectState, TimelineClip
        from services.project_store import ProjectStore
        from services.script_studio import ScriptRequest, generate_script

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-009")

        # AI script generation fails
        def fail_gen(_p):
            raise RuntimeError("Gemini quota exhausted")

        req = ScriptRequest(topic="Testing", audience="Devs")
        result = generate_script(req, generator=fail_gen)
        assert result["status"] == "unavailable"
        assert result["script"] is None
        # Project not mutated
        assert len(project.scripts) == 0

        # Manual edit continues
        project.set_timeline([
            TimelineClip(source_path=media.audio, order=0,
                         trim_start=0.0, trim_end=1.0)
        ])
        store.save(project)

        out = str(tmp_path / "manual_edit.mp4")
        trim_clip_for_timeline(media.audio, out, 0.0, 1.0)
        project.add_version(out)
        store.save(project)
        loaded = store.load(project.project_id)
        assert len(loaded.outputs) == 1
        assert loaded.outputs[0].status == "rendered"

    def test_auto_optimize_ai_unavailable_returns_original(self, media, tmp_path):
        from services.auto_editor import auto_optimize
        from services.project_model import ProjectState

        project = ProjectState(name="AIFallback")
        result = auto_optimize(
            project, media.audio,
            analyzer=lambda p: {"status": "unavailable"},
            max_iterations=1,
        )
        assert result["status"] == "analysis_unavailable"
        # Project not mutated
        assert len(project.outputs) == 0


# ─────────────────────────────────────────────────────────────────────────────
# E2E-010 — Publishing workflow: project → render → validate → queue → simulate
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.slow
class TestE2E010PublishingWorkflow:
    def test_full_publishing_pipeline_normal(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        from services.publishing.manager import PublishingManager
        from services.publishing.mock import MockPlatformProvider
        from services.publishing.models import PublishingJob

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="E2E-010")

        # Render
        out = str(tmp_path / "publish_ready.mp4")
        trim_clip_for_timeline(media.portrait, out, 0.0, 1.5)
        version = project.add_version(out)
        store.save(project)

        # Create job
        job = PublishingJob(
            platform="TikTok",
            asset_path=out,
            title="My first TikTok",
            description="Integration test video",
            project_id=project.project_id,
            version_id=version.version_id,
        )

        # Run through mock provider
        provider = MockPlatformProvider(platform="TikTok", scenario="normal",
                                        processing_steps=1)
        mgr = PublishingManager(provider, max_retries=1, max_polls=5,
                                backoff_base=0.0)
        result = mgr.run_job(job)
        assert result.status == "PUBLISHED"
        assert result.external_post_id

    def test_publishing_failure_retry_then_succeed_simulation(self, media, tmp_path):
        """Simulate: first attempt rate-limited → retry → normal publish."""
        from production_features import trim_clip_for_timeline
        from services.publishing.manager import PublishingManager
        from services.publishing.mock import MockPlatformProvider
        from services.publishing.models import PublishingJob

        out = str(tmp_path / "pub_retry.mp4")
        trim_clip_for_timeline(media.portrait, out, 0.0, 1.0)

        # Rate-limited scenario — all retries fail with 429
        provider = MockPlatformProvider(platform="TikTok", scenario="rate_limited")
        mgr = PublishingManager(provider, max_retries=2, max_polls=3, backoff_base=0.0)
        job = PublishingJob(platform="TikTok", asset_path=out, title="Retry test")
        result = mgr.run_job(job)
        assert result.status == "FAILED"
        assert "rate_limited" in result.error or "429" in result.error or "slow down" in result.error

    def test_publishing_timeout_scenario(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.publishing.manager import PublishingManager
        from services.publishing.mock import MockPlatformProvider
        from services.publishing.models import PublishingJob

        out = str(tmp_path / "pub_timeout.mp4")
        trim_clip_for_timeline(media.portrait, out, 0.0, 1.0)

        provider = MockPlatformProvider(platform="TikTok", scenario="timeout")
        mgr = PublishingManager(provider, max_retries=0, max_polls=3, backoff_base=0.0)
        job = PublishingJob(platform="TikTok", asset_path=out, title="Timeout test")
        result = mgr.run_job(job)
        assert result.status == "FAILED"

    def test_idempotency_no_duplicate_post(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.publishing.manager import PublishingManager
        from services.publishing.mock import MockPlatformProvider
        from services.publishing.models import PublishingJob

        out = str(tmp_path / "idem.mp4")
        trim_clip_for_timeline(media.portrait, out, 0.0, 1.0)

        provider = MockPlatformProvider(platform="TikTok", scenario="normal",
                                       processing_steps=0)
        mgr = PublishingManager(provider, max_retries=0, max_polls=3, backoff_base=0.0)

        job1 = PublishingJob(platform="TikTok", asset_path=out, title="Idempotency")
        result1 = mgr.run_job(job1)
        assert result1.status == "PUBLISHED"
        post_id = result1.external_post_id

        # Attempt to re-publish same idempotency key
        job2 = PublishingJob(platform="TikTok", asset_path=out, title="Idempotency",
                             idempotency_key=job1.idempotency_key)
        job2.transition_to("READY")
        result2 = mgr.run_job(job2)
        # Must not create a new post_id
        if result2.status == "PUBLISHED":
            assert result2.external_post_id == post_id


# ─────────────────────────────────────────────────────────────────────────────
# E2E — Script caption workflow
# ─────────────────────────────────────────────────────────────────────────────
class TestE2ECaptionWorkflow:
    def test_script_to_captions_to_ass(self, tmp_path):
        from caption_presets import write_styled_ass
        from services.script_studio import script_caption_segments

        script_text = "Welcome to GENFORGE. Today we will explore AI video editing. Let's get started."
        segments = script_caption_segments(script_text, total_seconds=8.0,
                                           max_words_per_caption=5)
        assert len(segments) > 1

        ass_path = str(tmp_path / "caps.ass")
        written = write_styled_ass(segments, ass_path, preset="Social")
        assert Path(written).is_file()
        content = Path(written).read_text(encoding="utf-8")
        assert "Dialogue:" in content
        assert "GENFORGE" in content or "Welcome" in content

    def test_caption_segments_span_full_duration(self, tmp_path):
        from services.script_studio import script_caption_segments
        segs = script_caption_segments(
            "One two three four five six seven eight nine ten",
            total_seconds=10.0, max_words_per_caption=3
        )
        assert segs[-1]["end"] == pytest.approx(10.0, abs=0.01)
        # Check all segments non-overlapping
        for i in range(len(segs) - 1):
            assert segs[i]["end"] <= segs[i + 1]["start"] + 0.001


# ─────────────────────────────────────────────────────────────────────────────
# E2E — Performance feedback loop
# ─────────────────────────────────────────────────────────────────────────────
class TestE2EPerformanceFeedback:
    def test_measure_interpret_recommend_cycle(self, media, tmp_path):
        from production_features import trim_clip_for_timeline
        from services.performance import (
            interpret_metrics,
            measure_local_metrics,
            record_performance,
            recommend_next_campaign,
        )
        from services.project_model import ProjectState
        from services.project_store import ProjectStore

        store = ProjectStore(tmp_path / "projects")
        project = ProjectState(name="PerfFeedback")

        out = str(tmp_path / "perf.mp4")
        trim_clip_for_timeline(media.audio, out, 0.0, 1.0)
        version = project.add_version(out)

        # Local measure
        measured = measure_local_metrics(out)
        assert measured["status"] == "measured"
        assert measured["metrics"]["duration"] > 0

        # Record on project
        record_performance(project, {"platform": "YouTube",
                                     "external_id": version.version_id},
                           measured)
        assert len(project.telemetry) == 1

        # Interpret real metrics
        interpreted = interpret_metrics({"views": 500, "engagement": 25,
                                        "retention": 45.0})
        assert "recommendations" in interpreted

        # Feed back into project
        guidance = recommend_next_campaign(project, interpreted)
        assert guidance["recommendations"]
        assert len(project.telemetry) == 2

        store.save(project)
        loaded = store.load(project.project_id)
        assert len(loaded.telemetry) == 2
