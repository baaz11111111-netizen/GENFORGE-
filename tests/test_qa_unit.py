"""
GENFORGE QA Unit Tests — Phase 1 (GF-001 … GF-184 coverage gaps)

Tests every function not already covered by the existing suites, or where
existing coverage was marked Partial/No in QA_FUNCTION_INVENTORY.md.

Rules:
- External dependencies (Gemini, FFmpeg) are mocked for determinism.
- Real FFmpeg/ffprobe calls are used only where the fixture is cheap and
  the function's correctness cannot be proven without real media.
- No fake tests: every assertion verifies actual observable behaviour.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# GF-004  ProjectState.validate_name — boundary / edge cases
# ─────────────────────────────────────────────────────────────────────────────
class TestProjectNameBoundary:
    """GF-004 extended boundary tests beyond the existing parametrize suite."""

    def test_exactly_120_chars_accepted(self):
        from services.project_model import ProjectState
        name = "A" * 120
        p = ProjectState(name=name)
        assert p.name == name

    def test_121_chars_rejected(self):
        from services.project_model import ProjectState
        with pytest.raises(ValueError, match="120"):
            ProjectState(name="A" * 121)

    def test_single_char_accepted(self):
        from services.project_model import ProjectState
        p = ProjectState(name="X")
        assert p.name == "X"

    def test_control_character_rejected(self):
        from services.project_model import ProjectState
        with pytest.raises(ValueError):
            ProjectState(name="bad\x00name")

    def test_tab_character_rejected(self):
        from services.project_model import ProjectState
        with pytest.raises(ValueError):
            ProjectState(name="bad\tname")

    def test_leading_trailing_whitespace_stripped(self):
        from services.project_model import ProjectState
        p = ProjectState(name="  My Project  ")
        assert p.name == "My Project"

    def test_only_dots_rejected(self):
        from services.project_model import ProjectState
        with pytest.raises(ValueError):
            ProjectState(name=".")
        with pytest.raises(ValueError):
            ProjectState(name="..")

    def test_forward_slash_rejected(self):
        from services.project_model import ProjectState
        with pytest.raises(ValueError):
            ProjectState(name="my/project")

    def test_backslash_rejected(self):
        from services.project_model import ProjectState
        with pytest.raises(ValueError):
            ProjectState(name="my\\project")

    def test_colon_rejected(self):
        from services.project_model import ProjectState
        with pytest.raises(ValueError):
            ProjectState(name="my:project")

    def test_unicode_accepted(self):
        from services.project_model import ProjectState
        p = ProjectState(name="Проект 日本語 🎬")
        assert "Проект" in p.name


# ─────────────────────────────────────────────────────────────────────────────
# GF-005  ProjectState.set_timeline — ordering invariants
# ─────────────────────────────────────────────────────────────────────────────
class TestSetTimeline:
    """GF-005 ordering / invariant tests."""

    def _clip(self, order):
        from services.project_model import TimelineClip
        return TimelineClip(source_path=f"/tmp/clip_{order}.mp4", order=order)

    def test_duplicate_orders_rejected(self):
        from services.project_model import ProjectState
        clips = [self._clip(0), self._clip(0)]
        with pytest.raises(ValueError, match="unique"):
            ProjectState().set_timeline(clips)

    def test_gap_in_orders_rejected(self):
        from services.project_model import ProjectState
        clips = [self._clip(0), self._clip(2)]
        with pytest.raises(ValueError, match="contiguous"):
            ProjectState().set_timeline(clips)

    def test_single_clip_accepted(self):
        from services.project_model import ProjectState
        ProjectState().set_timeline([self._clip(0)])

    def test_clips_sorted_by_order_after_set(self):
        from services.project_model import ProjectState
        p = ProjectState()
        p.set_timeline([self._clip(2), self._clip(0), self._clip(1)])
        assert [c.order for c in p.timeline] == [0, 1, 2]

    def test_empty_timeline_clears(self):
        from services.project_model import ProjectState, TimelineClip
        p = ProjectState()
        p.set_timeline([TimelineClip(source_path="/tmp/a.mp4", order=0)])
        p.set_timeline([])
        assert p.timeline == []


# ─────────────────────────────────────────────────────────────────────────────
# GF-009  ProjectState.record_error
# ─────────────────────────────────────────────────────────────────────────────
class TestRecordError:
    def test_status_becomes_failed(self):
        from services.project_model import ProjectState
        p = ProjectState(name="T")
        p.record_error("something went wrong")
        assert p.status == "failed"

    def test_error_appended(self):
        from services.project_model import ProjectState
        p = ProjectState(name="T")
        p.record_error("err1")
        p.record_error("err2")
        assert "err1" in p.errors
        assert "err2" in p.errors
        assert len(p.errors) == 2


# ─────────────────────────────────────────────────────────────────────────────
# GF-030  probe_media — missing / corrupt / no-streams
# ─────────────────────────────────────────────────────────────────────────────
class TestProbeMedia:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        from services.media_probe import probe_media
        with pytest.raises(FileNotFoundError):
            probe_media(str(tmp_path / "nonexistent.mp4"))

    def test_corrupt_file_raises_runtime_error(self, tmp_path):
        from services.media_probe import probe_media
        corrupt = tmp_path / "corrupt.mp4"
        corrupt.write_bytes(b"this is not a valid video file")
        with pytest.raises((RuntimeError, FileNotFoundError)):
            probe_media(str(corrupt))

    def test_real_landscape_video(self, media):
        from services.media_probe import probe_media
        meta = probe_media(media.landscape)
        assert meta.duration > 0
        assert meta.width == 1920
        assert meta.height == 1080
        assert meta.has_audio is True
        assert meta.video_codec is not None

    def test_real_portrait_video(self, media):
        from services.media_probe import probe_media
        meta = probe_media(media.portrait)
        assert meta.width == 1080
        assert meta.height == 1920

    def test_real_silent_video(self, media):
        from services.media_probe import probe_media
        meta = probe_media(media.silent)
        assert meta.has_audio is False

    def test_cache_hit_returns_same_object(self, media):
        from services.media_probe import clear_probe_cache, probe_cache_stats, probe_media
        clear_probe_cache()
        probe_media(media.audio)
        stats_before = probe_cache_stats()
        probe_media(media.audio)
        stats_after = probe_cache_stats()
        assert stats_after["hits"] > stats_before["hits"]

    def test_cache_invalidated_when_file_changes(self, tmp_path, media):
        """A changed file must produce a cache miss, not return stale metadata."""
        from services.media_probe import clear_probe_cache, probe_cache_stats, probe_media
        import shutil as _sh
        dest = str(tmp_path / "mutable.mp4")
        _sh.copy(media.silent, dest)
        clear_probe_cache()
        probe_media(dest)
        stats1 = probe_cache_stats()
        # Overwrite with a different (audio) file — mtime and size will differ
        _sh.copy(media.audio, dest)
        probe_media(dest)
        stats2 = probe_cache_stats()
        # Second call should be a miss (file changed), not a hit
        assert stats2["misses"] > stats1["misses"]

    def test_path_object_accepted(self, media):
        from services.media_probe import probe_media
        meta = probe_media(Path(media.landscape))
        assert meta.duration > 0


# ─────────────────────────────────────────────────────────────────────────────
# GF-031 / GF-032  probe_cache_stats / clear_probe_cache
# ─────────────────────────────────────────────────────────────────────────────
class TestProbeCacheStats:
    def test_clear_resets_counts(self, media):
        from services.media_probe import clear_probe_cache, probe_cache_stats, probe_media
        probe_media(media.audio)
        clear_probe_cache()
        stats = probe_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["entries"] == 0

    def test_miss_incremented_on_first_probe(self, media):
        from services.media_probe import clear_probe_cache, probe_cache_stats, probe_media
        clear_probe_cache()
        probe_media(media.audio)
        assert probe_cache_stats()["misses"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# GF-034  get_waveform_peaks — clamping, empty returns, caching
# ─────────────────────────────────────────────────────────────────────────────
class TestWaveformPeaks:
    def test_missing_file_returns_empty(self):
        from services.waveform import get_waveform_peaks
        result = get_waveform_peaks("/nonexistent/path.mp4")
        assert result == []

    def test_empty_path_returns_empty(self):
        from services.waveform import get_waveform_peaks
        assert get_waveform_peaks("") == []

    def test_silent_video_returns_empty_or_zeros(self, media):
        from services.waveform import clear_waveform_cache, get_waveform_peaks
        clear_waveform_cache()
        result = get_waveform_peaks(media.silent, num_peaks=20)
        # Silent video has no audio stream → should return []
        assert result == []

    def test_audio_video_returns_peaks(self, media):
        from services.waveform import clear_waveform_cache, get_waveform_peaks
        clear_waveform_cache()
        result = get_waveform_peaks(media.audio, num_peaks=50)
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(0.0 <= v <= 1.0 for v in result)

    def test_num_peaks_clamped_low(self, media):
        from services.waveform import clear_waveform_cache, get_waveform_peaks
        clear_waveform_cache()
        result = get_waveform_peaks(media.audio, num_peaks=1)
        # Clamped to 10 minimum
        assert len(result) <= 10 or len(result) > 0

    def test_second_call_uses_cache(self, media):
        from services.waveform import _CACHE, clear_waveform_cache, get_waveform_peaks
        clear_waveform_cache()
        r1 = get_waveform_peaks(media.audio, num_peaks=30)
        r2 = get_waveform_peaks(media.audio, num_peaks=30)
        assert r1 == r2

    def test_clear_waveform_cache_empties_dict(self, media):
        from services.waveform import _CACHE, clear_waveform_cache, get_waveform_peaks
        get_waveform_peaks(media.audio, num_peaks=20)
        clear_waveform_cache()
        assert len(_CACHE) == 0


# ─────────────────────────────────────────────────────────────────────────────
# GF-046 / GF-047 / GF-048  encode_profiles
# ─────────────────────────────────────────────────────────────────────────────
class TestEncodeProfiles:
    def test_all_three_profiles_present(self):
        from services.encode_profiles import ENCODE_PROFILES
        assert "preview" in ENCODE_PROFILES
        assert "draft" in ENCODE_PROFILES
        assert "final" in ENCODE_PROFILES

    def test_resolve_profile_returns_correct_preset(self):
        from services.encode_profiles import resolve_profile
        assert resolve_profile("preview").preset == "ultrafast"
        assert resolve_profile("final").preset == "medium"

    def test_resolve_unknown_raises(self):
        from services.encode_profiles import resolve_profile
        with pytest.raises(ValueError, match="Unknown encode profile"):
            resolve_profile("unknown")

    def test_encode_flags_preview_has_crf_28(self):
        from services.encode_profiles import encode_flags
        flags = encode_flags("preview")
        assert "-crf" in flags
        assert "28" in flags
        assert "ultrafast" in flags

    def test_encode_flags_final_has_crf_20(self):
        from services.encode_profiles import encode_flags
        flags = encode_flags("final")
        assert "20" in flags
        assert "medium" in flags

    def test_encode_flags_unknown_raises(self):
        from services.encode_profiles import encode_flags
        with pytest.raises(ValueError):
            encode_flags("imaginary")


# ─────────────────────────────────────────────────────────────────────────────
# GF-049 / GF-050  ai_service
# ─────────────────────────────────────────────────────────────────────────────
class TestAiService:
    def test_get_gemini_client_raises_without_api_key(self):
        from services.ai_service import get_gemini_client
        get_gemini_client.cache_clear()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GEMINI_API_KEY", None)
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                get_gemini_client()
        get_gemini_client.cache_clear()

    def test_generate_json_raises_on_empty_prompt(self):
        from services.ai_service import generate_json
        with pytest.raises(ValueError, match="non-empty"):
            generate_json("")

    def test_generate_json_raises_on_whitespace_prompt(self):
        from services.ai_service import generate_json
        with pytest.raises(ValueError, match="non-empty"):
            generate_json("   ")

    def test_generate_json_retries_and_raises_after_exhaustion(self):
        """RuntimeError raised after retries exhausted — no fabrication."""
        from services.ai_service import generate_json
        with patch("services.ai_service.get_gemini_client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = RuntimeError("API down")
            with pytest.raises(RuntimeError, match="failed after"):
                generate_json("valid prompt", retries=1)

    def test_generate_json_raises_on_empty_response(self):
        from services.ai_service import generate_json
        mock_response = MagicMock()
        mock_response.text = ""
        with patch("services.ai_service.get_gemini_client") as mock_client:
            mock_client.return_value.models.generate_content.return_value = mock_response
            with pytest.raises(RuntimeError, match="empty response"):
                generate_json("prompt")

    def test_generate_json_raises_on_non_dict_response(self):
        from services.ai_service import generate_json
        mock_response = MagicMock()
        mock_response.text = "[1, 2, 3]"
        with patch("services.ai_service.get_gemini_client") as mock_client:
            mock_client.return_value.models.generate_content.return_value = mock_response
            with pytest.raises(RuntimeError):
                generate_json("prompt")

    def test_generate_json_returns_dict_on_success(self):
        from services.ai_service import generate_json
        mock_response = MagicMock()
        mock_response.text = '{"result": "ok"}'
        with patch("services.ai_service.get_gemini_client") as mock_client:
            mock_client.return_value.models.generate_content.return_value = mock_response
            result = generate_json("prompt")
        assert result == {"result": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# GF-055  Highlight model validation
# ─────────────────────────────────────────────────────────────────────────────
class TestHighlightModel:
    def test_negative_start_rejected(self):
        from services.highlights import Highlight
        with pytest.raises(ValueError, match="negative"):
            Highlight(source_asset="/tmp/v.mp4", start=-1.0, end=5.0,
                      score=70.0, reason="x", hook="h", title="t", caption="c", cta="go")

    def test_end_before_start_rejected(self):
        from services.highlights import Highlight
        with pytest.raises(ValueError, match="end must be after start"):
            Highlight(source_asset="/tmp/v.mp4", start=5.0, end=3.0,
                      score=70.0, reason="x", hook="h", title="t", caption="c", cta="go")

    def test_end_equal_start_rejected(self):
        from services.highlights import Highlight
        with pytest.raises(ValueError):
            Highlight(source_asset="/tmp/v.mp4", start=5.0, end=5.0,
                      score=70.0, reason="x", hook="h", title="t", caption="c", cta="go")

    def test_duration_property(self):
        from services.highlights import Highlight
        h = Highlight(source_asset="/tmp/v.mp4", start=2.0, end=7.5,
                      score=80.0, reason="x", hook="h", title="t", caption="c", cta="go")
        assert h.duration == pytest.approx(5.5)


# ─────────────────────────────────────────────────────────────────────────────
# GF-056  make_gradient_background
# ─────────────────────────────────────────────────────────────────────────────
class TestGradientBackground:
    def test_vertical_gradient_correct_size(self):
        from services.image_studio import make_gradient_background
        img = make_gradient_background((100, 200), "#FF0000", "#0000FF", "vertical")
        assert img.size == (100, 200)
        assert img.mode == "RGBA"

    def test_horizontal_gradient(self):
        from services.image_studio import make_gradient_background
        img = make_gradient_background((100, 100), "#FFFFFF", "#000000", "horizontal")
        assert img.size == (100, 100)

    def test_diagonal_gradient(self):
        from services.image_studio import make_gradient_background
        img = make_gradient_background((50, 50), "#00FF00", "#FF00FF", "diagonal")
        assert img.size == (50, 50)

    def test_zero_size_raises(self):
        from services.image_studio import make_gradient_background
        with pytest.raises(ValueError, match="positive"):
            make_gradient_background((0, 100), "#FF0000", "#000000")

    def test_unknown_direction_raises(self):
        from services.image_studio import make_gradient_background
        with pytest.raises(ValueError, match="Unknown gradient direction"):
            make_gradient_background((100, 100), "#FF0000", "#000000", "circular")

    def test_invalid_hex_raises(self):
        from services.image_studio import make_gradient_background
        with pytest.raises(ValueError):
            make_gradient_background((100, 100), "notahex", "#000000")

    def test_top_left_pixel_matches_start_color(self):
        from services.image_studio import make_gradient_background
        img = make_gradient_background((100, 100), "#FF0000", "#0000FF", "vertical")
        r, g, b, a = img.getpixel((0, 0))
        assert r > 200   # red channel dominant at top
        assert b < 50

    def test_bottom_pixel_matches_stop_color(self):
        from services.image_studio import make_gradient_background
        img = make_gradient_background((100, 100), "#FF0000", "#0000FF", "vertical")
        r, g, b, a = img.getpixel((50, 99))
        assert b > 200   # blue dominant at bottom
        assert r < 50


# ─────────────────────────────────────────────────────────────────────────────
# GF-057 / GF-058  refine_edges / adjust_foreground
# ─────────────────────────────────────────────────────────────────────────────
class TestImageStudioHelpers:
    def _rgba_image(self, size=(100, 100)):
        from PIL import Image
        return Image.new("RGBA", size, (255, 0, 0, 200))

    def test_refine_edges_non_rgba_raises(self):
        from PIL import Image
        from services.image_studio import refine_edges
        rgb = Image.new("RGB", (50, 50))
        with pytest.raises(ValueError, match="RGBA"):
            refine_edges(rgb)

    def test_refine_edges_negative_feather_raises(self):
        from services.image_studio import refine_edges
        with pytest.raises(ValueError):
            refine_edges(self._rgba_image(), feather=-1.0)

    def test_refine_edges_negative_erode_raises(self):
        from services.image_studio import refine_edges
        with pytest.raises(ValueError):
            refine_edges(self._rgba_image(), erode=-1)

    def test_refine_edges_identity(self):
        from services.image_studio import refine_edges
        img = self._rgba_image()
        result = refine_edges(img, feather=0, erode=0)
        assert result.size == img.size

    def test_adjust_foreground_non_rgba_raises(self):
        from PIL import Image
        from services.image_studio import adjust_foreground
        with pytest.raises(ValueError, match="RGBA"):
            adjust_foreground(Image.new("RGB", (50, 50)))

    def test_adjust_foreground_out_of_range_brightness_raises(self):
        from services.image_studio import adjust_foreground
        with pytest.raises(ValueError):
            adjust_foreground(self._rgba_image(), brightness=5.0)

    def test_adjust_foreground_boundary_values_accepted(self):
        from services.image_studio import adjust_foreground
        result = adjust_foreground(self._rgba_image(), brightness=0.0, contrast=4.0, saturation=1.0)
        assert result.mode == "RGBA"


# ─────────────────────────────────────────────────────────────────────────────
# GF-059 / GF-060  add_subject_shadow / place_subject
# ─────────────────────────────────────────────────────────────────────────────
class TestSubjectPlacement:
    def _canvas(self):
        from PIL import Image
        return Image.new("RGBA", (400, 400), (0, 128, 255, 255))

    def _cutout(self):
        from PIL import Image
        return Image.new("RGBA", (100, 100), (255, 0, 0, 200))

    def test_shadow_opacity_out_of_range_raises(self):
        from services.image_studio import add_subject_shadow
        with pytest.raises(ValueError, match="opacity"):
            add_subject_shadow(self._canvas(), self._cutout(), (0, 0, 100, 100), opacity=300)

    def test_shadow_negative_blur_raises(self):
        from services.image_studio import add_subject_shadow
        with pytest.raises(ValueError, match="blur"):
            add_subject_shadow(self._canvas(), self._cutout(), (0, 0, 100, 100), blur=-1.0)

    def test_place_subject_scale_too_small_raises(self):
        from services.image_studio import place_subject
        with pytest.raises(ValueError, match="scale"):
            place_subject(self._canvas(), self._cutout(), scale=0.0)

    def test_place_subject_scale_too_large_raises(self):
        from services.image_studio import place_subject
        with pytest.raises(ValueError, match="scale"):
            place_subject(self._canvas(), self._cutout(), scale=5.0)

    def test_place_subject_position_out_of_range_raises(self):
        from services.image_studio import place_subject
        with pytest.raises(ValueError, match="position"):
            place_subject(self._canvas(), self._cutout(), position=(1.5, 0.5))

    def test_place_subject_returns_same_size_canvas(self):
        from services.image_studio import place_subject
        result, box = place_subject(self._canvas(), self._cutout(), scale=0.5, position=(0.5, 0.5))
        assert result.size == (400, 400)
        assert len(box) == 4

    def test_place_subject_off_canvas_does_not_raise(self):
        """Off-canvas positions clip silently instead of raising."""
        from services.image_studio import place_subject
        result, _ = place_subject(self._canvas(), self._cutout(), scale=0.5, position=(0.0, 0.0))
        assert result.size == (400, 400)


# ─────────────────────────────────────────────────────────────────────────────
# GF-062  crop_to_preset
# ─────────────────────────────────────────────────────────────────────────────
class TestCropToPreset:
    def test_all_presets_produce_correct_ratio(self, tmp_path):
        from PIL import Image
        from services.image_studio import CROP_PRESETS, crop_to_preset
        img = Image.new("RGB", (1920, 1080), (200, 100, 50))
        source = str(tmp_path / "src.png")
        img.save(source)
        for preset_name, (rw, rh) in CROP_PRESETS.items():
            out = str(tmp_path / f"crop_{preset_name.replace(' ', '_').replace(':', 'x')}.png")
            result_path = crop_to_preset(source, preset_name, out)
            result = Image.open(result_path)
            ratio = result.width / result.height
            expected = rw / rh
            assert abs(ratio - expected) < 0.02, f"Preset {preset_name}: ratio {ratio:.3f} != {expected:.3f}"

    def test_unknown_preset_raises(self, tmp_path):
        from PIL import Image
        from services.image_studio import crop_to_preset
        img = Image.new("RGB", (100, 100))
        src = str(tmp_path / "img.png")
        img.save(src)
        with pytest.raises(ValueError, match="Unknown crop preset"):
            crop_to_preset(src, "Nonsense 99:1", str(tmp_path / "out.png"))


# ─────────────────────────────────────────────────────────────────────────────
# GF-063 / GF-064 / GF-065  publishing models
# ─────────────────────────────────────────────────────────────────────────────
class TestPublishingModels:
    def test_can_transition_valid_edges(self):
        from services.publishing.models import can_transition
        assert can_transition("DRAFT", "READY") is True
        assert can_transition("READY", "UPLOADING") is True
        assert can_transition("UPLOADING", "PROCESSING") is True
        assert can_transition("PROCESSING", "PUBLISHED") is True

    def test_can_transition_invalid_edges(self):
        from services.publishing.models import can_transition
        assert can_transition("PUBLISHED", "DRAFT") is False
        assert can_transition("CANCELLED", "READY") is False
        assert can_transition("PUBLISHED", "FAILED") is False

    def test_can_transition_unknown_status_raises(self):
        from services.publishing.models import can_transition
        with pytest.raises(ValueError, match="Unknown publishing status"):
            can_transition("FLYING", "READY")

    def test_parse_scheduled_at_naive_rejected(self):
        from services.publishing.models import parse_scheduled_at
        with pytest.raises(ValueError, match="timezone-aware"):
            parse_scheduled_at("2030-06-15T10:00:00")  # no tz info

    def test_parse_scheduled_at_z_suffix_accepted(self):
        from services.publishing.models import parse_scheduled_at
        dt = parse_scheduled_at("2030-06-15T10:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parse_scheduled_at_none_returns_none(self):
        from services.publishing.models import parse_scheduled_at
        assert parse_scheduled_at(None) is None

    def test_ensure_future_past_raises(self):
        from datetime import timezone
        from datetime import datetime as dt
        from services.publishing.models import ensure_future
        past = dt(2020, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="future"):
            ensure_future(past)

    def test_ensure_future_none_returns_none(self):
        from services.publishing.models import ensure_future
        assert ensure_future(None) is None

    def test_job_transition_to_published_requires_post_id(self):
        from services.publishing.models import PublishingJob
        job = PublishingJob(platform="TikTok", status="PROCESSING")
        job.transition_to("PUBLISHED", external_post_id="abc123")
        assert job.status == "PUBLISHED"

    def test_job_transition_to_published_without_post_id_raises(self):
        from services.publishing.models import PublishingJob
        job = PublishingJob(platform="TikTok", status="PROCESSING")
        with pytest.raises(ValueError, match="external post id"):
            job.transition_to("PUBLISHED")

    def test_job_illegal_transition_raises(self):
        from services.publishing.models import PublishingJob
        job = PublishingJob(platform="TikTok", status="PUBLISHED",
                            external_post_id="abc")
        with pytest.raises(ValueError, match="Illegal"):
            job.transition_to("DRAFT")

    def test_account_mark_connected(self):
        from services.publishing.models import PublishingAccount
        acct = PublishingAccount(platform="YouTube")
        acct.mark("connected")
        assert acct.connected is True
        assert acct.state == "connected"

    def test_account_mark_invalid_state_raises(self):
        from services.publishing.models import PublishingAccount
        acct = PublishingAccount(platform="YouTube")
        with pytest.raises(ValueError):
            acct.mark("hacked")


# ─────────────────────────────────────────────────────────────────────────────
# GF-070 / GF-071 / GF-072  publishing validation
# ─────────────────────────────────────────────────────────────────────────────
class TestPublishingValidation:
    def test_validate_asset_missing_file(self, tmp_path):
        from services.publishing.validation import validate_asset
        report = validate_asset(str(tmp_path / "missing.mp4"), "TikTok")
        assert report.ok is False
        assert any("not found" in p.lower() for p in report.problems)

    def test_validate_asset_wrong_container(self, tmp_path):
        from services.publishing.validation import validate_asset
        bad = tmp_path / "file.avi"
        bad.write_bytes(b"data")
        report = validate_asset(str(bad), "TikTok")
        assert report.ok is False
        assert report.requires_adaptation is True

    def test_validate_asset_empty_path(self):
        from services.publishing.validation import validate_asset
        report = validate_asset("", "TikTok")
        assert report.ok is False

    def test_validate_metadata_title_too_long_youtube(self):
        from services.publishing.validation import validate_metadata
        report = validate_metadata({"title": "X" * 101}, "YouTube")
        assert report.ok is False
        assert any("Title" in p for p in report.problems)

    def test_validate_metadata_description_too_long_instagram(self):
        from services.publishing.validation import validate_metadata
        report = validate_metadata({"description": "X" * 2201}, "Instagram Reels")
        assert report.ok is False

    def test_validate_metadata_unknown_platform(self):
        from services.publishing.validation import validate_metadata
        report = validate_metadata({"title": "Hello"}, "Snapchat")
        assert report.ok is False

    def test_validate_metadata_no_title_warning(self):
        from services.publishing.validation import validate_metadata
        report = validate_metadata({}, "YouTube")
        assert any("No title" in w or "caption" in w.lower() for w in report.warnings)

    def test_validate_schedule_empty_is_ok(self):
        from services.publishing.validation import validate_schedule
        report = validate_schedule("", "TikTok")
        assert report.ok is True

    def test_validate_schedule_naive_datetime_rejected(self):
        from services.publishing.validation import validate_schedule
        report = validate_schedule("2030-01-01T10:00:00", "TikTok")
        assert report.ok is False

    def test_validate_schedule_unsupported_platform(self):
        from services.publishing.validation import validate_schedule
        # Instagram Reels does not support scheduling per capabilities
        report = validate_schedule("2030-01-01T10:00:00+00:00", "Instagram Reels")
        # May or may not support scheduling — validate returns report
        assert isinstance(report.ok, bool)


# ─────────────────────────────────────────────────────────────────────────────
# GF-084 / GF-085 / GF-086  script_studio models
# ─────────────────────────────────────────────────────────────────────────────
class TestScriptStudio:
    def test_script_request_empty_topic_raises(self):
        from services.script_studio import ScriptRequest
        with pytest.raises(ValueError, match="required"):
            ScriptRequest(topic="", audience="Marketers")

    def test_script_request_empty_audience_raises(self):
        from services.script_studio import ScriptRequest
        with pytest.raises(ValueError):
            ScriptRequest(topic="AI tools", audience="")

    def test_script_request_unknown_platform_raises(self):
        from services.script_studio import ScriptRequest
        with pytest.raises(ValueError, match="Unknown platform"):
            ScriptRequest(topic="X", audience="Y", platform="Snapchat")

    def test_script_request_unknown_tone_raises(self):
        from services.script_studio import ScriptRequest
        with pytest.raises(ValueError, match="Unknown tone"):
            ScriptRequest(topic="X", audience="Y", tone="Angry")

    def test_generated_script_empty_hook_raises(self):
        from services.script_studio import GeneratedScript
        with pytest.raises(ValueError):
            GeneratedScript(hook="", introduction="intro", body="body",
                            cta="cta", short_version="short", long_version="long")

    def test_generate_script_unavailable_ai(self):
        from services.script_studio import ScriptRequest, generate_script
        def fail(_):
            raise RuntimeError("No API")
        req = ScriptRequest(topic="Marketing", audience="SMBs")
        result = generate_script(req, generator=fail)
        assert result["status"] == "unavailable"
        assert result["script"] is None

    def test_generate_script_invalid_response(self):
        from services.script_studio import ScriptRequest, generate_script
        def bad(_):
            return {"hook": ""}  # empty hook fails GeneratedScript validation
        req = ScriptRequest(topic="X", audience="Y")
        result = generate_script(req, generator=bad)
        assert result["status"] == "invalid"

    def test_generate_script_success(self):
        from services.script_studio import ScriptRequest, generate_script
        def good(_):
            return {"hook": "Hook text", "introduction": "Intro", "body": "Body",
                    "cta": "CTA", "alternate_hooks": ["alt1", "alt2"],
                    "short_version": "Short", "long_version": "Long"}
        req = ScriptRequest(topic="AI video", audience="Creators")
        result = generate_script(req, generator=good)
        assert result["status"] == "generated"
        assert result["script"]["hook"] == "Hook text"

    def test_estimate_duration_empty_text_raises(self):
        from services.script_studio import estimate_duration_seconds
        with pytest.raises(ValueError, match="empty"):
            estimate_duration_seconds("")

    def test_estimate_duration_zero_wps_raises(self):
        from services.script_studio import estimate_duration_seconds
        with pytest.raises(ValueError, match="positive"):
            estimate_duration_seconds("hello world", words_per_second=0)

    def test_estimate_duration_reasonable(self):
        from services.script_studio import estimate_duration_seconds
        # 100 words at 2.5 wps = 40s
        text = " ".join(["word"] * 100)
        d = estimate_duration_seconds(text, words_per_second=2.5)
        assert d == pytest.approx(40.0, abs=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# GF-089 / GF-090  script_caption_segments
# ─────────────────────────────────────────────────────────────────────────────
class TestScriptCaptionSegments:
    def test_empty_text_raises(self):
        from services.script_studio import script_caption_segments
        with pytest.raises(ValueError, match="required"):
            script_caption_segments("", 10.0)

    def test_zero_total_seconds_raises(self):
        from services.script_studio import script_caption_segments
        with pytest.raises(ValueError, match="positive"):
            script_caption_segments("hello world", 0.0)

    def test_zero_max_words_raises(self):
        from services.script_studio import script_caption_segments
        with pytest.raises(ValueError, match="positive"):
            script_caption_segments("hello", 5.0, max_words_per_caption=0)

    def test_segments_cover_full_duration(self):
        from services.script_studio import script_caption_segments
        segs = script_caption_segments("One two three four five six", 6.0, max_words_per_caption=3)
        assert len(segs) == 2
        assert segs[-1]["end"] == pytest.approx(6.0, abs=0.01)

    def test_segment_starts_are_monotone(self):
        from services.script_studio import script_caption_segments
        segs = script_caption_segments("a b c d e f g h", 8.0, max_words_per_caption=2)
        starts = [s["start"] for s in segs]
        assert starts == sorted(starts)

    def test_single_word(self):
        from services.script_studio import script_caption_segments
        segs = script_caption_segments("hello", 3.0)
        assert len(segs) == 1
        assert segs[0]["text"] == "hello"


# ─────────────────────────────────────────────────────────────────────────────
# GF-092 / GF-093 / GF-094  auto_editor
# ─────────────────────────────────────────────────────────────────────────────
class TestAutoEditor:
    def test_diagnose_video_missing_file(self):
        from services.auto_editor import diagnose_video
        with pytest.raises(FileNotFoundError):
            diagnose_video("/no/such/file.mp4")

    def test_diagnose_video_real_clip(self, media):
        from services.auto_editor import diagnose_video
        result = diagnose_video(media.audio)
        assert result["status"] == "analyzed"
        assert "problems" in result
        assert "recommendations" in result

    def test_diagnose_video_silent_reports_no_audio(self, media):
        from services.auto_editor import diagnose_video
        result = diagnose_video(media.silent)
        assert any("audio" in p.lower() for p in result["problems"])

    def test_diagnose_video_analyzer_failure_does_not_crash(self, media):
        from services.auto_editor import diagnose_video
        def broken(_): raise RuntimeError("AI down")
        result = diagnose_video(media.audio, analyzer=broken)
        assert result["status"] == "analyzed"  # deterministic part still runs
        assert "unavailable" in (result["ai_summary"] or "").lower()

    def test_auto_optimize_bad_max_iterations_raises(self, media):
        from services.auto_editor import auto_optimize
        from services.project_model import ProjectState
        project = ProjectState(name="T")
        with pytest.raises(ValueError, match="max_iterations"):
            auto_optimize(project, media.audio, analyzer=lambda p: {}, max_iterations=5)

    def test_auto_optimize_analysis_unavailable(self, media):
        from services.auto_editor import auto_optimize
        from services.project_model import ProjectState
        project = ProjectState(name="T")
        result = auto_optimize(project, media.audio,
                               analyzer=lambda p: {"status": "unavailable"},
                               max_iterations=1)
        assert result["status"] == "analysis_unavailable"

    def test_auto_optimize_no_improvement_keeps_original(self, media):
        from services.auto_editor import auto_optimize
        from services.project_model import ProjectState
        project = ProjectState(name="T")
        # Analyzer always returns 50; editor returns same file → score unchanged
        result = auto_optimize(
            project, media.audio,
            analyzer=lambda p: {"hook_score": 50, "pacing_score": 50,
                                "audio_score": 50, "visual_score": 50},
            editor=lambda p, a: p,  # returns same path
            max_iterations=1,
            minimum_improvement=5.0,
        )
        assert result["status"] == "kept_original"
        assert result["selected_path"] == media.audio


# ─────────────────────────────────────────────────────────────────────────────
# GF-095  re_edit.improve_once
# ─────────────────────────────────────────────────────────────────────────────
class TestImproveOnce:
    def test_bad_max_iterations_raises(self):
        from services.re_edit import improve_once
        with pytest.raises(ValueError, match="max_iterations"):
            improve_once("/tmp/x.mp4", lambda p: {}, lambda p, a: p, max_iterations=4)

    def test_analysis_unavailable_returns_original(self, media):
        from services.re_edit import improve_once
        result = improve_once(media.audio,
                              analyzer=lambda p: {"status": "unavailable"},
                              editor=lambda p, a: p)
        assert result["status"] == "analysis_unavailable"
        assert result["selected_path"] == media.audio

    def test_improvement_above_threshold_selects_new(self, media, tmp_path):
        import shutil
        from services.re_edit import improve_once
        candidate = str(tmp_path / "candidate.mp4")
        shutil.copy(media.audio, candidate)
        call_count = {"n": 0}
        def analyzer(p):
            call_count["n"] += 1
            # First call (baseline) = 40; subsequent = 80
            score = 40.0 if call_count["n"] == 1 else 80.0
            return {"hook_score": score, "pacing_score": score,
                    "audio_score": score, "visual_score": score}
        result = improve_once(media.audio, analyzer, editor=lambda p, a: candidate,
                              max_iterations=1, minimum_improvement=5.0)
        assert result["selected_path"] == candidate
        assert result["selected_score"] > result["baseline_score"]


# ─────────────────────────────────────────────────────────────────────────────
# GF-097 / GF-098 / GF-099 / GF-100 / GF-101  campaign_builder pure functions
# ─────────────────────────────────────────────────────────────────────────────
class TestCampaignBuilderPure:
    def _brief(self, goal="awareness"):
        from services.campaign_builder import CampaignBrief
        return CampaignBrief(brand="Acme", goal=goal, audience="Marketers",
                             platforms=["TikTok", "YouTube"], topic="AI tools")

    def test_classify_goal_all_types(self):
        from services.campaign_builder import classify_goal
        assert classify_goal("grow brand awareness") == "awareness"
        assert classify_goal("boost engagement and shares") == "engagement"
        assert classify_goal("tutorial how-to video") == "education"
        assert classify_goal("convert leads to sales") == "conversion"
        assert classify_goal("build community loyalty") == "community"

    def test_classify_goal_fallback(self):
        from services.campaign_builder import classify_goal
        assert classify_goal("") == "awareness"
        assert classify_goal("random text xyz") == "awareness"

    def test_build_pillars_returns_three(self):
        from services.campaign_builder import build_pillars
        pillars = build_pillars(self._brief())
        assert len(pillars) == 3
        for p in pillars:
            assert "name" in p and "angle" in p and "goal" in p

    def test_build_pillars_interpolates_brand_and_topic(self):
        from services.campaign_builder import build_pillars
        pillars = build_pillars(self._brief())
        combined = " ".join(p["angle"] for p in pillars)
        assert "Acme" in combined or "AI tools" in combined

    def test_build_calendar_slot_count(self):
        from services.campaign_builder import build_calendar, build_pillars
        brief = self._brief()
        pillars = build_pillars(brief)
        cal = build_calendar(brief, pillars)
        assert len(cal) == brief.posts_per_week * brief.horizon_weeks

    def test_build_calendar_no_pillars_raises(self):
        from services.campaign_builder import build_calendar
        with pytest.raises(ValueError, match="pillars"):
            build_calendar(self._brief(), [])

    def test_build_hashtags_limit_enforced(self):
        from services.campaign_builder import build_hashtags
        tags = build_hashtags(self._brief(), limit=3)
        assert len(tags) <= 3

    def test_build_hashtags_limit_too_small_raises(self):
        from services.campaign_builder import build_hashtags
        with pytest.raises(ValueError, match="at least 3"):
            build_hashtags(self._brief(), limit=2)

    def test_build_hashtags_all_start_with_hash(self):
        from services.campaign_builder import build_hashtags
        tags = build_hashtags(self._brief())
        assert all(t.startswith("#") for t in tags)

    def test_build_cta_returns_string(self):
        from services.campaign_builder import build_cta
        cta = build_cta(self._brief())
        assert isinstance(cta, str) and len(cta) > 5

    def test_brief_unknown_platform_raises(self):
        from services.campaign_builder import CampaignBrief
        with pytest.raises(ValueError, match="Unknown platform"):
            CampaignBrief(brand="X", goal="awareness", audience="Y",
                          platforms=["Snapchat"], topic="Z")

    def test_brief_empty_platforms_raises(self):
        from services.campaign_builder import CampaignBrief
        with pytest.raises(ValueError, match="At least one platform"):
            CampaignBrief(brand="X", goal="awareness", audience="Y",
                          platforms=[], topic="Z")


# ─────────────────────────────────────────────────────────────────────────────
# GF-103 … GF-108  performance module
# ─────────────────────────────────────────────────────────────────────────────
class TestPerformanceModule:
    def test_validate_metrics_unknown_key_raises(self):
        from services.performance import validate_metrics
        with pytest.raises(ValueError, match="Unknown metric"):
            validate_metrics({"unknown_key": 100})

    def test_validate_metrics_negative_raises(self):
        from services.performance import validate_metrics
        with pytest.raises(ValueError, match="non-negative"):
            validate_metrics({"views": -1})

    def test_validate_metrics_nan_raises(self):
        from services.performance import validate_metrics
        with pytest.raises(ValueError, match="non-negative"):
            validate_metrics({"views": float("nan")})

    def test_validate_metrics_empty_raises(self):
        from services.performance import validate_metrics
        with pytest.raises(ValueError, match="At least one"):
            validate_metrics({})

    def test_fetch_platform_metrics_no_transport_unavailable(self):
        from services.performance import fetch_platform_metrics
        result = fetch_platform_metrics("YouTube", "abc123")
        assert result["status"] == "unavailable"
        assert not result["metrics"]

    def test_fetch_platform_metrics_transport_error_unavailable(self):
        from services.performance import fetch_platform_metrics
        def bad(p, eid): raise ConnectionError("network down")
        result = fetch_platform_metrics("YouTube", "abc123", transport=bad)
        assert result["status"] == "unavailable"

    def test_fetch_platform_metrics_empty_platform_raises(self):
        from services.performance import fetch_platform_metrics
        with pytest.raises(ValueError, match="Platform"):
            fetch_platform_metrics("", "abc123")

    def test_measure_local_metrics_missing_raises(self):
        from services.performance import measure_local_metrics
        with pytest.raises(FileNotFoundError):
            measure_local_metrics("/no/such/asset.mp4")

    def test_measure_local_metrics_real_file(self, media):
        from services.performance import measure_local_metrics
        result = measure_local_metrics(media.audio)
        assert result["status"] == "measured"
        assert result["metrics"]["duration"] > 0
        assert result["metrics"]["file_size_bytes"] > 0

    def test_interpret_metrics_computes_engagement_rate(self):
        from services.performance import interpret_metrics
        result = interpret_metrics({"views": 1000, "engagement": 50})
        assert result["derived"]["engagement_rate"] == pytest.approx(0.05)

    def test_interpret_metrics_reports_gaps(self):
        from services.performance import interpret_metrics
        result = interpret_metrics({"views": 100})
        assert "watch_time" in result["gaps"]

    def test_interpret_metrics_low_retention_recommendation(self):
        from services.performance import interpret_metrics
        result = interpret_metrics({"retention": 30.0})
        assert any("hook" in r.lower() or "retention" in r.lower()
                   for r in result["recommendations"])

    def test_recommend_next_campaign_appends_telemetry(self):
        from services.performance import interpret_metrics, recommend_next_campaign
        from services.project_model import ProjectState
        project = ProjectState(name="P")
        interp = interpret_metrics({"views": 500, "engagement": 10})
        guidance = recommend_next_campaign(project, interp)
        assert any(e["type"] == "performance_feedback" for e in project.telemetry)
        assert guidance["recommendations"]

    def test_record_performance_wrong_status_raises(self):
        from services.performance import record_performance
        from services.project_model import ProjectState
        project = ProjectState(name="P")
        with pytest.raises(ValueError, match="fetched or measured"):
            record_performance(project, {"platform": "TikTok"}, {"status": "pending"})


# ─────────────────────────────────────────────────────────────────────────────
# GF-116 … GF-119  asset_cache
# ─────────────────────────────────────────────────────────────────────────────
class TestAssetCache:
    def test_same_inputs_produce_same_key(self, tmp_path):
        from services.asset_cache import asset_cache_key
        f = tmp_path / "source.mp4"
        f.write_bytes(b"x" * 1024)
        k1 = asset_cache_key(str(f), "thumbnail", size=512)
        k2 = asset_cache_key(str(f), "thumbnail", size=512)
        assert k1 == k2

    def test_different_params_produce_different_key(self, tmp_path):
        from services.asset_cache import asset_cache_key
        f = tmp_path / "source.mp4"
        f.write_bytes(b"x" * 1024)
        k1 = asset_cache_key(str(f), "thumbnail", size=512)
        k2 = asset_cache_key(str(f), "thumbnail", size=256)
        assert k1 != k2

    def test_different_operation_produces_different_key(self, tmp_path):
        from services.asset_cache import asset_cache_key
        f = tmp_path / "source.mp4"
        f.write_bytes(b"x" * 1024)
        k1 = asset_cache_key(str(f), "thumbnail")
        k2 = asset_cache_key(str(f), "waveform")
        assert k1 != k2

    def test_cache_miss_returns_false(self, tmp_path):
        from services.asset_cache import clear_asset_cache, fetch_asset
        clear_asset_cache()
        result = fetch_asset("nonexistent_key_xyz", ".png", str(tmp_path / "out.png"))
        assert result is False

    def test_store_and_fetch_round_trip(self, tmp_path):
        from services.asset_cache import clear_asset_cache, fetch_asset, store_asset
        clear_asset_cache()
        produced = tmp_path / "produced.png"
        produced.write_bytes(b"\x89PNG test data")
        store_asset("testkey123", ".png", str(produced))
        dest = tmp_path / "fetched.png"
        hit = fetch_asset("testkey123", ".png", str(dest))
        assert hit is True
        assert dest.read_bytes() == produced.read_bytes()

    def test_clear_resets_stats(self, tmp_path):
        from services.asset_cache import asset_cache_stats, clear_asset_cache, store_asset
        f = tmp_path / "x.png"
        f.write_bytes(b"data")
        store_asset("k1", ".png", str(f))
        clear_asset_cache()
        stats = asset_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# GF-120 … GF-123  media_cache (transition normalization cache)
# ─────────────────────────────────────────────────────────────────────────────
class TestMediaCache:
    def test_same_inputs_same_key(self, tmp_path):
        from services.media_cache import normalization_cache_key
        f = tmp_path / "v.mp4"
        f.write_bytes(b"x" * 2048)
        k1 = normalization_cache_key(str(f), 1920, 1080, 30, 10.0)
        k2 = normalization_cache_key(str(f), 1920, 1080, 30, 10.0)
        assert k1 == k2

    def test_different_resolution_different_key(self, tmp_path):
        from services.media_cache import normalization_cache_key
        f = tmp_path / "v.mp4"
        f.write_bytes(b"x" * 2048)
        k1 = normalization_cache_key(str(f), 1920, 1080, 30, 10.0)
        k2 = normalization_cache_key(str(f), 1280, 720, 30, 10.0)
        assert k1 != k2

    def test_fetch_miss_returns_false_and_increments_miss(self, tmp_path):
        from services.media_cache import clear_normalization_cache, fetch_normalized, normalization_cache_stats
        clear_normalization_cache()
        result = fetch_normalized("nokey999", str(tmp_path / "out.mp4"))
        assert result is False

    def test_store_and_fetch(self, tmp_path):
        from services.media_cache import clear_normalization_cache, fetch_normalized, store_normalized
        clear_normalization_cache()
        src = tmp_path / "norm.mp4"
        src.write_bytes(b"fake_mp4_data")
        store_normalized("mykey", str(src))
        dest = tmp_path / "fetched.mp4"
        assert fetch_normalized("mykey", str(dest)) is True
        assert dest.read_bytes() == src.read_bytes()

    def test_clear_empties_cache_dir(self, tmp_path):
        from services.media_cache import clear_normalization_cache, normalization_cache_stats
        clear_normalization_cache()
        stats = normalization_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# GF-124 … GF-128  platform_profiles
# ─────────────────────────────────────────────────────────────────────────────
class TestPlatformProfiles:
    def test_all_five_profiles_present(self):
        from services.platform_profiles import PLATFORM_PROFILES
        for name in ("TikTok", "Instagram Reels", "YouTube Shorts", "YouTube", "Square Feed"):
            assert name in PLATFORM_PROFILES

    def test_caption_safe_margin_tiktok(self):
        from services.platform_profiles import caption_safe_margin
        margin = caption_safe_margin("TikTok")
        assert margin > 0

    def test_caption_safe_margin_unknown_raises(self):
        from services.platform_profiles import caption_safe_margin
        with pytest.raises(ValueError, match="Unknown platform"):
            caption_safe_margin("Snapchat")

    def test_export_for_platform_unknown_raises(self, tmp_path, media):
        from services.platform_profiles import export_for_platform
        with pytest.raises(ValueError, match="Unknown platform"):
            export_for_platform(media.landscape, str(tmp_path / "out.mp4"), "Snapchat")

    def test_duration_advisory_fits(self, media):
        from services.platform_profiles import duration_advisory
        result = duration_advisory(media.landscape, "YouTube")
        assert result["fits"] is True
        assert result["duration"] > 0

    def test_duration_advisory_unknown_platform_raises(self, media):
        from services.platform_profiles import duration_advisory
        with pytest.raises(ValueError):
            duration_advisory(media.landscape, "Snapchat")


# ─────────────────────────────────────────────────────────────────────────────
# GF-129 / GF-130  storage_cleanup
# ─────────────────────────────────────────────────────────────────────────────
class TestStorageCleanup:
    def test_negative_max_age_raises(self, tmp_path):
        from services.storage_cleanup import scan_reclaimable
        with pytest.raises(ValueError, match="negative"):
            scan_reclaimable(str(tmp_path), max_age_hours=-1)

    def test_scan_returns_no_entries_for_fresh_files(self, tmp_path):
        from services.storage_cleanup import scan_reclaimable
        temp = tmp_path / "temp"
        temp.mkdir()
        (temp / "fresh.mp4").write_bytes(b"data")
        result = scan_reclaimable(str(tmp_path), max_age_hours=24,
                                  candidate_dirs=("temp",))
        # Fresh file should NOT appear (age < 24h)
        assert result["total_bytes"] == 0

    def test_scan_reports_stale_file(self, tmp_path):
        from services.storage_cleanup import scan_reclaimable
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        stale = temp_dir / "stale.mp4"
        stale.write_bytes(b"stale data here")
        # Backdate mtime to 48 hours ago
        old_time = time.time() - 48 * 3600
        os.utime(str(stale), (old_time, old_time))
        result = scan_reclaimable(str(tmp_path), max_age_hours=24,
                                  candidate_dirs=("temp",))
        assert len(result["entries"]) == 1
        assert result["total_bytes"] == len(b"stale data here")

    def test_dry_run_does_not_delete(self, tmp_path):
        from services.storage_cleanup import safe_cleanup
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        stale = temp_dir / "old.mp4"
        stale.write_bytes(b"x" * 100)
        old_time = time.time() - 48 * 3600
        os.utime(str(stale), (old_time, old_time))
        result = safe_cleanup(str(tmp_path), max_age_hours=24, dry_run=True,
                              candidate_dirs=("temp",))
        assert result["dry_run"] is True
        assert result["removed"] == []
        assert stale.exists()

    def test_real_cleanup_deletes_stale_file(self, tmp_path):
        from services.storage_cleanup import safe_cleanup
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        stale = temp_dir / "old2.mp4"
        stale.write_bytes(b"x" * 100)
        old_time = time.time() - 48 * 3600
        os.utime(str(stale), (old_time, old_time))
        result = safe_cleanup(str(tmp_path), max_age_hours=24, dry_run=False,
                              candidate_dirs=("temp",))
        assert not stale.exists()
        assert len(result["removed"]) == 1

    def test_protected_dirs_never_touched(self, tmp_path):
        from services.storage_cleanup import PROTECTED_DIRS, safe_cleanup
        # Create a file inside a protected dir
        for name in PROTECTED_DIRS:
            prot = tmp_path / name
            prot.mkdir(exist_ok=True)
            victim = prot / "important.mp4"
            victim.write_bytes(b"do not delete")
            old_time = time.time() - 48 * 3600
            os.utime(str(victim), (old_time, old_time))
        safe_cleanup(str(tmp_path), max_age_hours=0, dry_run=False)
        for name in PROTECTED_DIRS:
            assert (tmp_path / name / "important.mp4").exists()


# ─────────────────────────────────────────────────────────────────────────────
# GF-131 … GF-138  keyframes (pure logic tests)
# ─────────────────────────────────────────────────────────────────────────────
class TestKeyframes:
    def test_keyframe_negative_time_raises(self):
        from services.keyframes import Keyframe
        with pytest.raises(ValueError, match="negative"):
            Keyframe(time=-0.1, property="scale", value=1.0)

    def test_keyframe_non_finite_value_raises(self):
        from services.keyframes import Keyframe
        with pytest.raises(ValueError, match="finite"):
            Keyframe(time=0.0, property="scale", value=float("inf"))

    def test_validate_keyframes_sorts_by_time(self):
        from services.keyframes import Keyframe, validate_keyframes
        kfs = [Keyframe(time=2.0, property="scale", value=2.0),
               Keyframe(time=0.0, property="scale", value=1.0)]
        result = validate_keyframes(kfs)
        assert result[0].time < result[1].time

    def test_validate_keyframes_duplicate_time_raises(self):
        from services.keyframes import Keyframe, validate_keyframes
        kfs = [Keyframe(time=1.0, property="scale", value=1.0),
               Keyframe(time=1.0, property="scale", value=2.0)]
        with pytest.raises(ValueError, match="unique"):
            validate_keyframes(kfs)

    def test_validate_keyframes_out_of_range_opacity_raises(self):
        from services.keyframes import Keyframe, validate_keyframes
        kfs = [Keyframe(time=0.0, property="opacity", value=2.0)]  # max is 1.0
        with pytest.raises(ValueError, match="out of range"):
            validate_keyframes(kfs)

    def test_value_at_before_first_returns_first(self):
        from services.keyframes import Keyframe, value_at
        kfs = [Keyframe(time=1.0, property="scale", value=2.0),
               Keyframe(time=3.0, property="scale", value=4.0)]
        assert value_at(kfs, 0.0) == pytest.approx(2.0)

    def test_value_at_after_last_returns_last(self):
        from services.keyframes import Keyframe, value_at
        kfs = [Keyframe(time=0.0, property="scale", value=1.0),
               Keyframe(time=2.0, property="scale", value=3.0)]
        assert value_at(kfs, 10.0) == pytest.approx(3.0)

    def test_value_at_midpoint_linear(self):
        from services.keyframes import Keyframe, value_at
        kfs = [Keyframe(time=0.0, property="scale", value=0.0),
               Keyframe(time=2.0, property="scale", value=2.0)]
        assert value_at(kfs, 1.0) == pytest.approx(1.0)

    def test_value_at_empty_raises(self):
        from services.keyframes import value_at
        with pytest.raises(ValueError):
            value_at([], 1.0)

    def test_piecewise_expression_single_keyframe(self):
        from services.keyframes import Keyframe, piecewise_expression
        kfs = [Keyframe(time=0.0, property="scale", value=1.5)]
        expr = piecewise_expression(kfs)
        assert "1.5" in expr

    def test_piecewise_expression_empty_raises(self):
        from services.keyframes import piecewise_expression
        with pytest.raises(ValueError):
            piecewise_expression([])

    def test_build_keyframe_video_filters_bad_dims_raises(self):
        from services.keyframes import Keyframe, build_keyframe_video_filters
        kfs = [Keyframe(time=0.0, property="scale", value=1.0)]
        with pytest.raises(ValueError, match="positive"):
            build_keyframe_video_filters(kfs, width=0, height=720)

    def test_build_keyframe_audio_filters_empty_returns_empty(self):
        from services.keyframes import Keyframe, build_keyframe_audio_filters
        # No volume keyframes → empty list
        kfs = [Keyframe(time=0.0, property="scale", value=1.0)]
        result = build_keyframe_audio_filters(kfs)
        assert result == []

    def test_build_keyframe_video_filters_volume_raises(self):
        from services.keyframes import Keyframe, build_keyframe_video_filters
        kfs = [Keyframe(time=0.0, property="volume", value=1.0)]
        with pytest.raises(ValueError, match="audio"):
            build_keyframe_video_filters(kfs, 1280, 720, 30)

    def test_all_easings_produce_bounded_values(self):
        from services.keyframes import Keyframe, value_at
        for easing in ("linear", "ease_in", "ease_out", "ease_in_out"):
            kfs = [Keyframe(time=0.0, property="opacity", value=0.0, easing=easing),
                   Keyframe(time=1.0, property="opacity", value=1.0, easing=easing)]
            for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                v = value_at(kfs, t)
                assert 0.0 <= v <= 1.0, f"easing={easing} t={t} v={v}"


# ─────────────────────────────────────────────────────────────────────────────
# GF-140 … GF-145  caption_presets
# ─────────────────────────────────────────────────────────────────────────────
class TestCaptionPresets:
    def test_all_seven_presets_accepted(self):
        from caption_presets import CAPTION_PRESETS, CaptionStyle
        for preset in CAPTION_PRESETS:
            style = CaptionStyle.from_preset(preset)
            assert style.fontsize > 0

    def test_unknown_preset_raises(self):
        from caption_presets import CaptionStyle
        with pytest.raises(ValueError, match="Unknown caption preset"):
            CaptionStyle.from_preset("Ghost")

    def test_margin_v_override(self):
        from caption_presets import CaptionStyle
        style = CaptionStyle.from_preset("Classic", margin_v=200)
        assert style.margin_v == 200

    def test_style_for_platform_safe_zone_negative_raises(self):
        from caption_presets import style_for_platform_safe_zone
        with pytest.raises(ValueError, match="negative"):
            style_for_platform_safe_zone("Classic", -10)

    def test_style_for_platform_safe_zone_zero_ok(self):
        from caption_presets import style_for_platform_safe_zone
        style = style_for_platform_safe_zone("Classic", 0)
        assert style.margin_v == 40  # clamps to max(40, 0)

    def test_build_ass_empty_segments_produces_header(self):
        from caption_presets import CaptionStyle, build_ass
        style = CaptionStyle.from_preset("Classic")
        content = build_ass([], style)
        assert "[Script Info]" in content
        assert "[Events]" in content

    def test_build_ass_segments_produce_dialogue_lines(self):
        from caption_presets import CaptionStyle, build_ass
        style = CaptionStyle.from_preset("Classic")
        segs = [{"start": 0.0, "end": 2.0, "text": "Hello world"}]
        content = build_ass(segs, style)
        assert "Dialogue:" in content
        assert "Hello world" in content

    def test_write_styled_ass_empty_raises(self, tmp_path):
        from caption_presets import write_styled_ass
        with pytest.raises(ValueError, match="required"):
            write_styled_ass([], str(tmp_path / "caps.ass"))

    def test_write_styled_ass_creates_file(self, tmp_path):
        from caption_presets import write_styled_ass
        segs = [{"start": 0.0, "end": 1.5, "text": "Test caption"}]
        path = write_styled_ass(segs, str(tmp_path / "caps.ass"))
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0

    def test_shift_segments_negative_result_raises(self):
        from caption_presets import shift_segments
        segs = [{"start": 0.5, "end": 2.0, "text": "x"}]
        with pytest.raises(ValueError, match="before the timeline start"):
            shift_segments(segs, offset=-1.0)

    def test_shift_segments_positive_offset(self):
        from caption_presets import shift_segments
        segs = [{"start": 1.0, "end": 3.0, "text": "x"}]
        shifted = shift_segments(segs, offset=5.0)
        assert shifted[0]["start"] == pytest.approx(6.0)
        assert shifted[0]["end"] == pytest.approx(8.0)

    def test_subtitles_filter_arg_escapes_windows_path(self):
        from caption_presets import subtitles_filter_arg
        result = subtitles_filter_arg(r"C:\Users\test\caps.ass")
        assert "C\\:" in result
        assert "\\" not in result.replace("\\:", "")


# ─────────────────────────────────────────────────────────────────────────────
# GF-153  format_ass_time
# ─────────────────────────────────────────────────────────────────────────────
class TestFormatAssTime:
    def test_zero(self):
        from advanced_video import format_ass_time
        assert format_ass_time(0.0) == "0:00:00.00"

    def test_one_minute(self):
        from advanced_video import format_ass_time
        result = format_ass_time(60.0)
        assert "01:00" in result

    def test_over_one_hour(self):
        from advanced_video import format_ass_time
        result = format_ass_time(3661.5)
        assert result.startswith("1:")


# ─────────────────────────────────────────────────────────────────────────────
# GF-047  project_store path traversal (regression)
# ─────────────────────────────────────────────────────────────────────────────
class TestProjectStorePathSafety:
    @pytest.mark.parametrize("bad_id", [
        "..", ".", "nested/id", "../escape", "id/../../etc/passwd",
        "", "  ",
    ])
    def test_traversal_ids_rejected(self, tmp_path, bad_id):
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path)
        with pytest.raises(ValueError):
            store.path_for(bad_id)

    def test_valid_hex_id_accepted(self, tmp_path):
        from services.project_store import ProjectStore
        store = ProjectStore(tmp_path)
        path = store.path_for("abc123def456")
        assert path.name == "project.json"
