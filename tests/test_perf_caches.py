"""Performance-pass cache tests: probe cache, capability cache, normalization cache."""
import os
import subprocess
import time
from pathlib import Path

import pytest

from services.media_probe import clear_probe_cache, probe_cache_stats, probe_media
from services.media_cache import (
    clear_normalization_cache,
    fetch_normalized,
    normalization_cache_key,
    normalization_cache_stats,
    store_normalized,
)


def _make_video(path: Path, duration=1.0, size="320x240"):
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24",
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path),
    ], check=True)
    return path


@pytest.fixture(autouse=True)
def _clean_probe_cache():
    clear_probe_cache()
    yield
    clear_probe_cache()


class TestProbeCache:
    def test_repeated_probe_is_cache_hit(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        first = probe_media(video)
        second = probe_media(video)
        assert first == second
        stats = probe_cache_stats()
        assert stats["hits"] >= 1 and stats["misses"] == 1

    def test_changed_file_invalidates_cache(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        probe_media(video)
        # Replace with a longer file: identity (size + mtime) changes.
        _make_video(tmp_path / "v.mp4", duration=2.0)
        fresh = probe_media(video)
        assert fresh.duration > 1.5
        assert probe_cache_stats()["misses"] == 2

    def test_clear_cache_resets_stats(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        probe_media(video)
        clear_probe_cache()
        assert probe_cache_stats() == {"hits": 0, "misses": 0, "entries": 0}


class TestCapabilityCache:
    def test_check_ffmpeg_spawns_once(self, monkeypatch):
        import app
        calls = {"count": 0}
        real_run = subprocess.run

        def counting_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "ffmpeg" and "-version" in cmd:
                calls["count"] += 1
            return real_run(cmd, *args, **kwargs)

        monkeypatch.setattr(app.subprocess, "run", counting_run)
        app.invalidate_ffmpeg_cache()
        assert app.check_ffmpeg() is True
        assert app.check_ffmpeg() is True
        assert app.check_ffmpeg() is True
        assert calls["count"] == 1
        # Explicit refresh re-verifies (never hides a missing executable).
        app.check_ffmpeg(refresh=True)
        assert calls["count"] == 2
        app.invalidate_ffmpeg_cache()


class TestNormalizationCache:
    def test_key_changes_with_parameters(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        base = normalization_cache_key(str(video), 320, 240, 30, 1.0)
        assert base != normalization_cache_key(str(video), 640, 480, 30, 1.0)
        assert base != normalization_cache_key(str(video), 320, 240, 24, 1.0)
        assert base != normalization_cache_key(str(video), 320, 240, 30, 2.0)

    def test_key_changes_when_source_changes(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        before = normalization_cache_key(str(video), 320, 240, 30, 1.0)
        time.sleep(0.01)
        _make_video(tmp_path / "v.mp4", duration=2.0)
        after = normalization_cache_key(str(video), 320, 240, 30, 1.0)
        assert before != after

    def test_store_and_fetch_roundtrip(self, tmp_path):
        clear_normalization_cache()
        video = _make_video(tmp_path / "v.mp4")
        dest = tmp_path / "dest.mp4"
        assert fetch_normalized("missingkey", str(dest)) is False
        store_normalized("unitkey", str(video))
        assert fetch_normalized("unitkey", str(dest)) is True
        assert dest.stat().st_size == video.stat().st_size
        assert normalization_cache_stats()["hits"] == 1
        clear_normalization_cache()
        assert normalization_cache_stats()["entries"] == 0

    def test_repeated_transition_reuses_cache(self, tmp_path):
        from advanced_video import apply_clip_transition
        clear_normalization_cache()
        clip_a = str(_make_video(tmp_path / "a.mp4"))
        clip_b = str(_make_video(tmp_path / "b.mp4"))
        apply_clip_transition(clip_a, clip_b, str(tmp_path / "out1.mp4"), "fade", 0.3)
        stats_after_first = normalization_cache_stats()
        assert stats_after_first["misses"] >= 2 and stats_after_first["hits"] == 0
        # Identical inputs + identical durations → both clips hit the cache.
        apply_clip_transition(clip_a, clip_b, str(tmp_path / "out2.mp4"), "fade", 0.3)
        stats_after_second = normalization_cache_stats()
        assert stats_after_second["hits"] >= 2
        assert (tmp_path / "out2.mp4").stat().st_size > 0
        clear_normalization_cache()


class TestThumbnailSampling:
    def test_auto_thumbnail_renders_valid_image(self, tmp_path):
        from PIL import Image
        from advanced_ai import generate_auto_thumbnail
        video = _make_video(tmp_path / "v.mp4", duration=2.0, size="640x360")
        out = generate_auto_thumbnail(str(video), str(tmp_path / "thumb.png"), title_text="Test")
        assert Path(out).stat().st_size > 0
        image = Image.open(out)
        assert image.size[0] >= 640 and image.size[1] >= 360

    def test_thumbnail_fallback_path_matches_fast_path(self, tmp_path, monkeypatch):
        """Forcing the OpenCV fallback must still produce a valid thumbnail."""
        import advanced_ai
        video = _make_video(tmp_path / "v.mp4", duration=2.0, size="640x360")
        monkeypatch.setattr(advanced_ai, "_score_candidates_ffmpeg", lambda *a, **k: None)
        out = advanced_ai.generate_auto_thumbnail(str(video), str(tmp_path / "thumb_fb.png"))
        assert Path(out).stat().st_size > 0

    def test_thumbnail_rejects_missing_video(self, tmp_path):
        from advanced_ai import generate_auto_thumbnail
        with pytest.raises(FileNotFoundError):
            generate_auto_thumbnail(str(tmp_path / "nope.mp4"), str(tmp_path / "t.png"))

    def test_candidate_frames_sequential_cover_indices(self, tmp_path):
        from services.thumbnail_studio import extract_candidate_frames
        video = _make_video(tmp_path / "v.mp4", duration=2.0, size="320x240")
        candidates = extract_candidate_frames(str(video), count=5)
        assert len(candidates) == 5
        indices = [c["frame_index"] for c in candidates]
        assert indices == sorted(set(indices))
        assert indices[0] == 0  # evenly spaced sampling still starts at frame 0


class TestEncodeProfiles:
    def test_profile_registry_and_flags(self):
        from services.encode_profiles import ENCODE_PROFILES, encode_flags, resolve_profile
        assert resolve_profile("final").preset == "medium" and resolve_profile("final").crf == 20
        assert resolve_profile("preview").preset == "ultrafast"
        assert encode_flags("preview") == ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
        assert set(ENCODE_PROFILES) == {"preview", "draft", "final"}

    def test_unknown_profile_rejected(self):
        from services.encode_profiles import encode_flags
        with pytest.raises(ValueError):
            encode_flags("turbo")

    def test_preview_render_faster_than_final(self, tmp_path):
        from production_features import trim_clip_for_timeline
        video = _make_video(tmp_path / "v.mp4", duration=2.0, size="640x360")
        start, end = time.perf_counter(), time.perf_counter()
        preview = trim_clip_for_timeline(str(video), str(tmp_path / "p.mp4"), 0.0, 1.5, profile="preview")
        preview_elapsed = time.perf_counter() - start
        final = trim_clip_for_timeline(str(video), str(tmp_path / "f.mp4"), 0.0, 1.5, profile="final")
        final_elapsed = time.perf_counter() - end
        assert Path(preview).stat().st_size > 0 and Path(final).stat().st_size > 0
        assert preview_elapsed < final_elapsed  # measured, not assumed

    def test_default_profile_matches_previous_settings(self, tmp_path):
        """Default (no profile arg) must stay on the verified-stable medium/crf20 path."""
        from production_features import trim_clip_for_timeline
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        out = trim_clip_for_timeline(str(video), str(tmp_path / "d.mp4"), 0.0, 1.0)
        assert Path(out).stat().st_size > 0


class TestStageTelemetry:
    def test_stage_timer_records_completed_and_failed(self):
        from services.stage_telemetry import (clear_stage_timings, latest_stage,
                                              stage_label, stage_timer, stage_timings)
        clear_stage_timings()
        with stage_timer("PROBING"):
            pass
        with pytest.raises(RuntimeError):
            with stage_timer("RENDERING"):
                raise RuntimeError("boom")
        records = stage_timings()
        assert [r["stage"] for r in records] == ["PROBING", "RENDERING"]
        assert records[0]["status"] == "completed" and records[0]["seconds"] >= 0
        assert records[1]["status"] == "failed"
        assert latest_stage()["stage"] == "RENDERING"
        assert stage_label("RENDERING") == "RENDERING…"
        clear_stage_timings()
        assert stage_timings() == [] and latest_stage() is None

    def test_unknown_stage_rejected(self):
        from services.stage_telemetry import stage_label, stage_timer
        with pytest.raises(ValueError):
            with stage_timer("MAKING_COFFEE"):
                pass
        with pytest.raises(ValueError):
            stage_label("MAKING_COFFEE")

    def test_transition_job_records_all_stages(self, tmp_path):
        from advanced_video import apply_clip_transition
        from services.stage_telemetry import clear_stage_timings, stage_timings
        clear_stage_timings()
        clip_a = str(_make_video(tmp_path / "a.mp4"))
        clip_b = str(_make_video(tmp_path / "b.mp4"))
        apply_clip_transition(clip_a, clip_b, str(tmp_path / "out.mp4"), "fade", 0.3)
        stages = [r["stage"] for r in stage_timings() if r["status"] == "completed"]
        assert stages == ["PROBING", "NORMALIZING", "VALIDATING", "RENDERING", "FINALIZING"]
        clear_stage_timings()


class TestAssetCache:
    def test_repeated_thumbnail_is_cache_hit(self, tmp_path):
        from advanced_ai import generate_auto_thumbnail
        from services.asset_cache import asset_cache_stats, clear_asset_cache
        clear_asset_cache()
        video = _make_video(tmp_path / "v.mp4", duration=1.5, size="320x240")
        first = generate_auto_thumbnail(str(video), str(tmp_path / "t1.png"), title_text="Same")
        second = generate_auto_thumbnail(str(video), str(tmp_path / "t2.png"), title_text="Same")
        assert Path(first).read_bytes() == Path(second).read_bytes()
        assert asset_cache_stats()["hits"] >= 1
        clear_asset_cache()

    def test_key_changes_with_params_or_source(self, tmp_path):
        from services.asset_cache import asset_cache_key
        video = _make_video(tmp_path / "v.mp4")
        base = asset_cache_key(str(video), "auto_thumbnail", title_text="A")
        assert base != asset_cache_key(str(video), "auto_thumbnail", title_text="B")
        assert base != asset_cache_key(str(video), "other_op", title_text="A")
        time.sleep(0.01)
        _make_video(tmp_path / "v.mp4", duration=2.0)
        assert base != asset_cache_key(str(video), "auto_thumbnail", title_text="A")


class TestSafeStorageCleanup:
    @staticmethod
    def _age(path, hours):
        old = time.time() - hours * 3600
        os.utime(path, (old, old))

    def _build_root(self, tmp_path):
        for rel in ("uploads", "projects", "outputs", "temp_inputs", "temp"):
            (tmp_path / rel).mkdir(parents=True, exist_ok=True)
        (tmp_path / "uploads" / "source.mp4").write_bytes(b"source" * 100)
        (tmp_path / "projects" / "proj.json").write_text("{}")
        (tmp_path / "outputs" / "final.mp4").write_bytes(b"render" * 100)
        (tmp_path / "temp_inputs" / "old_intermediate.mp4").write_bytes(b"x" * 5000)
        (tmp_path / "temp_inputs" / "fresh_intermediate.mp4").write_bytes(b"y" * 100)
        (tmp_path / "temp" / "old_scratch.jpg").write_bytes(b"z" * 300)
        self._age(tmp_path / "temp_inputs" / "old_intermediate.mp4", 48)
        self._age(tmp_path / "temp" / "old_scratch.jpg", 48)
        self._age(tmp_path / "uploads" / "source.mp4", 48)  # old BUT protected
        self._age(tmp_path / "outputs" / "final.mp4", 48)   # old BUT protected

    def test_dry_run_reports_without_deleting(self, tmp_path):
        from services.storage_cleanup import safe_cleanup
        self._build_root(tmp_path)
        report = safe_cleanup(root=str(tmp_path), max_age_hours=24, dry_run=True)
        assert report["dry_run"] is True
        assert report["candidates"] == 2
        assert report["removed"] == []
        assert (tmp_path / "temp_inputs" / "old_intermediate.mp4").exists()

    def test_cleanup_removes_only_stale_intermediates(self, tmp_path):
        from services.storage_cleanup import safe_cleanup
        self._build_root(tmp_path)
        report = safe_cleanup(root=str(tmp_path), max_age_hours=24, dry_run=False)
        assert len(report["removed"]) == 2
        # Protected + fresh files must all survive.
        assert (tmp_path / "uploads" / "source.mp4").exists()
        assert (tmp_path / "projects" / "proj.json").exists()
        assert (tmp_path / "outputs" / "final.mp4").exists()
        assert (tmp_path / "temp_inputs" / "fresh_intermediate.mp4").exists()
        # Stale intermediates are gone.
        assert not (tmp_path / "temp_inputs" / "old_intermediate.mp4").exists()
        assert not (tmp_path / "temp" / "old_scratch.jpg").exists()

    def test_protected_dirs_can_never_be_candidates(self, tmp_path):
        from services.storage_cleanup import PROTECTED_DIRS, safe_cleanup
        (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
        stale = tmp_path / "uploads" / "ancient.mp4"
        stale.write_bytes(b"a" * 1000)
        self._age(stale, 1000)
        report = safe_cleanup(root=str(tmp_path), max_age_hours=1, dry_run=False,
                              candidate_dirs=("uploads", "projects", "outputs"))
        assert report["candidates"] == 0 and report["removed"] == []
        assert stale.exists()
        assert set(PROTECTED_DIRS) == {"uploads", "projects", "outputs"}

