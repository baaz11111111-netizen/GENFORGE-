"""Phase 2 — Advanced caption presets regression tests."""
import subprocess
from pathlib import Path

import pytest

from caption_presets import (
    CAPTION_PRESETS,
    CaptionStyle,
    build_ass,
    shift_segments,
    style_for_platform_safe_zone,
    subtitles_filter_arg,
    write_styled_ass,
)

SEGMENTS = [
    {"start": 0.0, "end": 1.2, "text": "This is the HOOK moment"},
    {"start": 1.2, "end": 2.4, "text": "Follow for more"},
]


class TestPresets:
    def test_all_required_presets_exist(self):
        for name in ("Classic", "Minimal", "Bold", "Creator", "Karaoke", "Social", "News"):
            assert name in CAPTION_PRESETS

    def test_every_preset_builds_valid_ass(self):
        for name in CAPTION_PRESETS:
            style = CaptionStyle.from_preset(name)
            content = build_ass(SEGMENTS, style)
            assert "[Script Info]" in content and "[V4+ Styles]" in content and "[Events]" in content
            assert content.count("Dialogue:") == len(SEGMENTS)
            assert "Style: GenForge," in content

    def test_unknown_preset_rejected(self):
        with pytest.raises(ValueError, match="Unknown caption preset"):
            CaptionStyle.from_preset("DoesNotExist")


class TestStyling:
    def test_emphasis_words_get_colour_tags(self):
        style = CaptionStyle.from_preset("Bold")
        content = build_ass(SEGMENTS, style, emphasis_words=("HOOK",))
        assert "{\\c&H0000FFFF}HOOK{\\r}" in content

    def test_box_preset_uses_opaque_border_style(self):
        content = build_ass(SEGMENTS, CaptionStyle.from_preset("News"))
        style_line = next(l for l in content.splitlines() if l.startswith("Style:"))
        fields = style_line.split(",")
        assert fields[15] == "3"  # BorderStyle 3 = box

    def test_safe_zone_raises_margin(self):
        style = style_for_platform_safe_zone("Classic", safe_zone_bottom=320)
        assert style.margin_v == 320
        default = CaptionStyle.from_preset("Classic")
        assert style.margin_v > default.margin_v

    def test_negative_safe_zone_rejected(self):
        with pytest.raises(ValueError):
            style_for_platform_safe_zone("Classic", -5)


class TestTiming:
    def test_write_styled_ass_file(self, tmp_path):
        out = tmp_path / "captions.ass"
        result = write_styled_ass(SEGMENTS, str(out), preset="Creator", emphasis_words=("more",))
        content = Path(result).read_text(encoding="utf-8")
        assert "0:00:00.00,0:00:01.20" in content
        assert "{\\c&H0000FFFF}more{\\r}" in content

    def test_empty_segments_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            write_styled_ass([], str(tmp_path / "x.ass"))

    def test_shift_segments_adjusts_timing(self):
        shifted = shift_segments(SEGMENTS, 0.5)
        assert shifted[0]["start"] == 0.5 and shifted[0]["end"] == 1.7

    def test_shift_rejects_negative_result(self):
        with pytest.raises(ValueError):
            shift_segments(SEGMENTS, -1.0)


class TestBurnIn:
    def test_styled_captions_burn_into_video(self, tmp_path):
        """Styled ASS must actually render into a video via FFmpeg subtitles filter."""
        video = tmp_path / "base.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
            "-t", "2.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(video),
        ], check=True, capture_output=True)
        ass = write_styled_ass(SEGMENTS, str(tmp_path / "cap.ass"), preset="Bold")
        out = tmp_path / "captioned.mp4"
        result = subprocess.run([
            "ffmpeg", "-y", "-i", str(video),
            "-vf", f"subtitles={subtitles_filter_arg(ass)}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out),
        ], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-400:]
        assert out.is_file() and out.stat().st_size > 0


def test_subtitles_filter_arg_escapes_windows_path():
    assert subtitles_filter_arg("C:\\Users\\x\\cap.ass") == "'C\\:/Users/x/cap.ass'"
