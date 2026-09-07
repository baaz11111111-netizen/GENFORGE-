"""Phase 8 — Platform adaptation regression tests."""
import json
import subprocess
from pathlib import Path

import pytest

from caption_presets import style_for_platform_safe_zone
from services.platform_profiles import (
    PLATFORM_PROFILES,
    caption_safe_margin,
    duration_advisory,
    export_for_platform,
    export_master_suite,
)


def _make_video(path: Path, duration=2.0, size="320x240"):
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path),
    ], check=True, capture_output=True)
    return path


def _dimensions(path: str) -> tuple[int, int]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    return stream["width"], stream["height"]


class TestProfileDefinitions:
    def test_all_required_platforms_defined(self):
        for name in ("TikTok", "Instagram Reels", "YouTube Shorts", "YouTube", "Square Feed"):
            assert name in PLATFORM_PROFILES

    def test_profiles_carry_full_metadata(self):
        for name, profile in PLATFORM_PROFILES.items():
            assert profile.width > 0 and profile.height > 0
            assert profile.max_duration > 0
            assert len(profile.safe_zone) == 4 and all(v >= 0 for v in profile.safe_zone)
            assert profile.thumbnail[0] > 0 and profile.thumbnail[1] > 0
            assert profile.text_placement in ("center", "upper_third", "bottom")
            assert profile.ratio in ("9:16", "1:1", "16:9")

    def test_shorts_profiles_are_vertical_and_bounded(self):
        for name in ("TikTok", "Instagram Reels", "YouTube Shorts"):
            assert PLATFORM_PROFILES[name].ratio == "9:16"
        assert PLATFORM_PROFILES["YouTube Shorts"].max_duration <= 60
        assert PLATFORM_PROFILES["Instagram Reels"].max_duration <= 90


class TestSafeZonesAndCaptions:
    def test_caption_margin_matches_safe_zone(self):
        for name in PLATFORM_PROFILES:
            assert caption_safe_margin(name) == PLATFORM_PROFILES[name].safe_zone[3]

    def test_caption_style_integrates_with_safe_zone(self):
        margin = caption_safe_margin("TikTok")
        style = style_for_platform_safe_zone("Classic", safe_zone_bottom=margin)
        assert style.margin_v == margin

    def test_unknown_platform_rejected(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            caption_safe_margin("MySpace")
        with pytest.raises(ValueError, match="Unknown platform"):
            duration_advisory(__file__, "MySpace")


class TestDurationAdvisory:
    def test_short_clip_fits_shorts(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        advisory = duration_advisory(str(video), "YouTube Shorts")
        assert advisory["fits"] is True and advisory["problems"] == []

    def test_over_limit_reported_honestly(self, tmp_path, monkeypatch):
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        strict = dict(PLATFORM_PROFILES)
        base = PLATFORM_PROFILES["YouTube Shorts"]
        from services.platform_profiles import PlatformProfile
        strict["YouTube Shorts"] = PlatformProfile(
            base.name, base.ratio, base.width, base.height, 1.0,
            base.caption_position, base.safe_zone,
        )
        import services.platform_profiles as module
        monkeypatch.setattr(module, "PLATFORM_PROFILES", strict)
        advisory = module.duration_advisory(str(video), "YouTube Shorts")
        assert advisory["fits"] is False
        assert any("exceeds" in problem for problem in advisory["problems"])


class TestExport:
    def test_single_platform_export_matches_profile_size(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        out = export_for_platform(str(video), str(tmp_path / "tiktok.mp4"), "TikTok")
        assert _dimensions(out) == (1080, 1920)

    def test_master_suite_renders_all_requested_platforms(self, tmp_path):
        video = _make_video(tmp_path / "master.mp4")
        suite = export_master_suite(str(video), str(tmp_path / "suite"),
                                    platforms=["TikTok", "YouTube", "Square Feed"])
        assert suite["errors"] == {}
        assert _dimensions(suite["outputs"]["TikTok"]) == (1080, 1920)
        assert _dimensions(suite["outputs"]["YouTube"]) == (1920, 1080)
        assert _dimensions(suite["outputs"]["Square Feed"]) == (1080, 1080)
        for platform in ("TikTok", "YouTube", "Square Feed"):
            assert suite["advisories"][platform]["fits"] is True

    def test_master_suite_rejects_unknown_platform(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        with pytest.raises(ValueError, match="Unknown platform"):
            export_master_suite(str(video), str(tmp_path / "suite"), platforms=["MySpace"])

    def test_missing_input_rejected(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            export_master_suite(str(tmp_path / "missing.mp4"), str(tmp_path / "suite"))
