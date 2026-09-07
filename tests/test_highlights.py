"""Phase 1 — AI Highlights generator regression tests."""
import json
import subprocess
from pathlib import Path

import pytest

from services.highlights import (
    Highlight,
    adjust_highlight,
    detect_highlights,
    render_highlight,
    render_highlight_versions,
)


def _make_video(path: Path, duration=8.0, loud_from=4.0):
    """8s clip: quiet sine until loud_from, then loud."""
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-af", f"volume=enable='lt(t,{loud_from})':volume=0.01,volume=enable='gte(t,{loud_from})':volume=1.0",
        "-c:a", "aac", str(path),
    ], check=True, capture_output=True)
    return path


def _make_silent_video(path: Path, duration=6.0):
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=24",
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path),
    ], check=True, capture_output=True)
    return path


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(out.stdout)


class TestHighlightModel:
    def test_requires_end_after_start(self):
        with pytest.raises(ValueError):
            Highlight(source_asset="x.mp4", start=5.0, end=5.0, score=1.0,
                      reason="r", hook="h", title="t", caption="c", cta="a")

    def test_rejects_negative_timestamps(self):
        with pytest.raises(ValueError):
            Highlight(source_asset="x.mp4", start=-1.0, end=2.0, score=1.0,
                      reason="r", hook="h", title="t", caption="c", cta="a")

    def test_adjust_highlight_edits_times(self):
        h = Highlight(source_asset="x.mp4", start=1.0, end=5.0, score=1.0,
                      reason="r", hook="h", title="t", caption="c", cta="a")
        moved = adjust_highlight(h, start=2.0, end=6.0)
        assert moved.start == 2.0 and moved.end == 6.0
        assert h.start == 1.0  # original untouched


class TestDetection:
    def test_finds_loud_segment(self, tmp_path):
        video = _make_video(tmp_path / "long.mp4", duration=8.0, loud_from=4.0)
        found = detect_highlights(str(video), count=2, min_duration=2.0, max_duration=3.0, window=1.0)
        assert len(found) >= 1
        best = found[0]
        assert best.start >= 2.5, f"expected anchor in loud region, got {best.start}"
        assert "audio energy" in best.reason
        assert best.score > 0
        assert best.hook and best.title and best.cta  # honest heuristic copy present

    def test_no_audio_reports_honest_fallback(self, tmp_path):
        video = _make_silent_video(tmp_path / "silent.mp4", duration=6.0)
        found = detect_highlights(str(video), count=3, min_duration=2.0, max_duration=3.0)
        assert len(found) == 1
        assert "no audio" in found[0].reason
        assert found[0].start == 0.0

    def test_short_clip_returns_full_clip(self, tmp_path):
        video = _make_silent_video(tmp_path / "short.mp4", duration=1.5)
        found = detect_highlights(str(video), min_duration=4.0)
        assert len(found) == 1
        assert found[0].end <= 1.6


class TestRendering:
    @pytest.mark.slow
    def test_render_highlight_end_to_end(self, tmp_path):
        video = _make_video(tmp_path / "long.mp4", duration=8.0, loud_from=4.0)
        found = detect_highlights(str(video), count=1, min_duration=2.0, max_duration=3.0, window=1.0)
        out_dir = tmp_path / "exports"
        result = render_highlight(found[0], str(out_dir))
        assert Path(result).is_file() and Path(result).stat().st_size > 0
        meta = _probe(result)
        duration = float(meta["format"]["duration"])
        assert abs(duration - found[0].duration) < 0.5, f"trimmed duration {duration}"
        assert any(s["codec_type"] == "video" for s in meta["streams"])

    @pytest.mark.slow
    def test_render_platform_versions(self, tmp_path):
        video = _make_video(tmp_path / "long.mp4", duration=8.0, loud_from=4.0)
        found = detect_highlights(str(video), count=1, min_duration=2.0, max_duration=3.0, window=1.0)
        out_dir = tmp_path / "exports"
        versions = render_highlight_versions(found[0], str(out_dir), platforms=["TikTok"])
        assert "master" in versions and "TikTok" in versions
        meta = _probe(versions["TikTok"])
        vs = next(s for s in meta["streams"] if s["codec_type"] == "video")
        assert (vs["width"], vs["height"]) == (1080, 1920)

    def test_render_rejects_missing_source(self, tmp_path):
        h = Highlight(source_asset=str(tmp_path / "gone.mp4"), start=0.0, end=2.0, score=1.0,
                      reason="r", hook="h", title="t", caption="c", cta="a")
        with pytest.raises(FileNotFoundError):
            render_highlight(h, str(tmp_path))

    @pytest.mark.slow
    def test_unknown_platform_rejected(self, tmp_path):
        video = _make_video(tmp_path / "long.mp4", duration=8.0, loud_from=4.0)
        found = detect_highlights(str(video), count=1, min_duration=2.0, max_duration=3.0, window=1.0)
        with pytest.raises(ValueError):
            render_highlight_versions(found[0], str(tmp_path), platforms=["NotAPlatform"])
