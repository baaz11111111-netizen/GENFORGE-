import os
import shutil
import subprocess
import json

import pytest

pytestmark = pytest.mark.slow

from advanced_video import apply_clip_transition


def test_transition_normalizes_resolution_and_fps(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    output = tmp_path / "transition.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(first)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(second)],
        check=True, capture_output=True,
    )
    apply_clip_transition(str(first), str(second), str(output), duration=0.25)
    assert output.exists() and output.stat().st_size > 0


@pytest.mark.slow
@pytest.mark.parametrize("first_rate,second_rate", [(24, 30), (30, 24), (24, 60), (60, 30)])
@pytest.mark.parametrize("first_size,second_size", [("1280x720", "1920x1080"), ("1920x1080", "720x1280")])
@pytest.mark.parametrize("first_audio,second_audio", [(True, True), (True, False), (False, True), (False, False)])
def test_transition_matrix_outputs_probeable_media(
    tmp_path, first_rate, second_rate, first_size, second_size, first_audio, second_audio
):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe unavailable")

    def make_clip(path, size, rate, with_audio):
        command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}"]
        if with_audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
        command += ["-t", "0.6", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if with_audio:
            command += ["-c:a", "aac"]
        else:
            command += ["-an"]
        command.append(str(path))
        subprocess.run(command, check=True, capture_output=True)

    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    output = tmp_path / "transition.mp4"
    make_clip(first, first_size, first_rate, first_audio)
    make_clip(second, second_size, second_rate, second_audio)
    apply_clip_transition(str(first), str(second), str(output), duration=0.2)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    assert video["width"] == int(first_size.split("x")[0])
    assert video["height"] == int(first_size.split("x")[1])
    assert video["pix_fmt"] == "yuv420p"
    assert video["r_frame_rate"] == "30/1"
    assert any(stream["codec_type"] == "audio" for stream in streams)


# ===========================================================================
# Deep validation tests (mandate Sections 11-14)
# ===========================================================================

def _make_clip(path, size="640x360", rate=30, duration=2.0, with_audio=True):
    """Helper: create a synthetic test clip."""
    command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}"]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    command += ["-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac"]
    else:
        command += ["-an"]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True)


def _probe_output(path):
    """Helper: return full ffprobe JSON for a media file."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(r.stdout)


def _extract_frame_md5(video_path, time_seconds):
    """Extract a single frame at time_seconds and return its MD5 hash."""
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(time_seconds), "-i", str(video_path),
            "-frames:v", "1", "-f", "md5", "-",
        ],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


class TestDeepValidation:
    """Mandate Section 11: every test verifies deep output properties."""

    def test_deep_output_validation(self, tmp_path):
        """Verify avg_frame_rate, r_frame_rate, timebase, duration, SAR, audio."""
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"
        _make_clip(first, "1280x720", 24, 2.0, True)
        _make_clip(second, "720x1280", 30, 2.0, False)
        apply_clip_transition(str(first), str(second), str(output), duration=0.5)

        data = _probe_output(output)
        vs = next(s for s in data["streams"] if s["codec_type"] == "video")

        # FPS must be valid 30/1
        assert vs["r_frame_rate"] == "30/1"
        assert vs["avg_frame_rate"] == "30/1"
        # Must not be 0/0 or N/0
        assert "/0" not in vs.get("r_frame_rate", "")
        assert "/0" not in vs.get("avg_frame_rate", "")
        # Pixel format
        assert vs["pix_fmt"] == "yuv420p"
        # SAR
        assert vs.get("sample_aspect_ratio") in ("1:1", None)
        # Duration must be positive and roughly correct (2 + 2 - 0.5 = 3.5 ± 0.5)
        dur = float(data["format"]["duration"])
        assert 2.5 <= dur <= 4.5, f"Unexpected duration: {dur}"
        # Audio stream must exist
        assert any(s["codec_type"] == "audio" for s in data["streams"])

    def test_output_not_identical_to_source(self, tmp_path):
        """Output must differ from both source clips (not just a copy)."""
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"
        _make_clip(first, "640x360", 30, 2.0, True)
        _make_clip(second, "640x360", 30, 2.0, True)
        apply_clip_transition(str(first), str(second), str(output), duration=0.5)

        # Output file size must differ from both inputs
        out_size = output.stat().st_size
        assert out_size != first.stat().st_size
        assert out_size != second.stat().st_size


class TestTransitionProof:
    """Mandate Section 12: prove that the transition actually occurs."""

    def test_transition_actually_occurs_not_concatenation(self, tmp_path):
        """Extract frames around the transition point and verify they differ
        from both source clips. A simple concatenation would show a hard cut;
        a real xfade shows blended frames during the transition window."""
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"

        # Use distinctly different clips: red testsrc2 vs green testsrc2
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:size=320x240:rate=30",
            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(first),
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:size=320x240:rate=30",
            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(second),
        ], check=True, capture_output=True)

        apply_clip_transition(str(first), str(second), str(output),
                              transition_type="fade", duration=0.5)

        # The transition starts at offset = first_dur - trans_dur = 2.0 - 0.5 = 1.5
        # During transition (1.5 to 2.0), frames should be blends of red+blue (purple-ish)
        # After transition (2.0+), frames should be pure blue

        # Extract frame hash during transition (at 1.75s)
        mid_transition = _extract_frame_md5(output, 1.75)
        # Extract frame hash after transition (at 2.5s)
        after_transition = _extract_frame_md5(output, 2.5)
        # Extract frame hash before transition (at 0.5s)
        before_transition = _extract_frame_md5(output, 0.5)

        # All three hashes must differ — proving frames change during transition
        assert before_transition != after_transition, (
            "Pre-transition and post-transition frames are identical; "
            "transition may not have occurred."
        )
        assert mid_transition != before_transition, (
            "Mid-transition frame is identical to pre-transition; "
            "transition may not have occurred."
        )
        assert mid_transition != after_transition, (
            "Mid-transition frame is identical to post-transition; "
            "transition may not have occurred."
        )


class TestAllTransitionTypes:
    """Mandate Section 9: all transition types must work."""

    @pytest.mark.parametrize("ttype", [
        "fade", "dissolve", "wipeleft", "slideup", "circlecrop", "smoothleft", "radial",
    ])
    def test_all_transition_types(self, tmp_path, ttype):
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"
        _make_clip(first, "640x360", 30, 1.5, True)
        _make_clip(second, "640x360", 30, 1.5, True)
        result = apply_clip_transition(str(first), str(second), str(output),
                                       transition_type=ttype, duration=0.3)
        assert output.exists() and output.stat().st_size > 0
        data = _probe_output(result)
        vs = next(s for s in data["streams"] if s["codec_type"] == "video")
        assert vs["r_frame_rate"] == "30/1"


class TestSameMediaProperties:
    """Mandate Section 10 Test 13: same media properties → transition works."""

    def test_same_media_properties(self, tmp_path):
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"
        _make_clip(first, "1280x720", 30, 2.0, True)
        _make_clip(second, "1280x720", 30, 2.0, True)
        apply_clip_transition(str(first), str(second), str(output), duration=0.5)
        data = _probe_output(output)
        vs = next(s for s in data["streams"] if s["codec_type"] == "video")
        assert vs["width"] == 1280
        assert vs["height"] == 720
        assert vs["r_frame_rate"] == "30/1"


class TestCFRValidation:
    """Mandate Section 6: normalized intermediates must be genuine CFR."""

    def test_no_invalid_frame_rate_in_output(self, tmp_path):
        """Output must never report 0/0 or N/0 frame rate."""
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"
        # Use a 24fps source (non-30fps) to force normalization
        _make_clip(first, "640x360", 24, 2.0, True)
        _make_clip(second, "640x360", 60, 2.0, False)
        apply_clip_transition(str(first), str(second), str(output), duration=0.3)

        data = _probe_output(output)
        vs = next(s for s in data["streams"] if s["codec_type"] == "video")
        for key in ("r_frame_rate", "avg_frame_rate"):
            rate = vs.get(key, "0/0")
            if "/" in rate:
                num, den = rate.split("/", 1)
                assert int(den) != 0, f"{key}={rate} has zero denominator"
                assert int(num) != 0, f"{key}={rate} has zero numerator"


class TestTemporalFileManagement:
    """Mandate Section 14: temporary files must be isolated and cleaned."""

    def test_temp_files_are_cleaned(self, tmp_path):
        """After a successful transition, no genforge_trans_ temp dirs created
        by *this* test should remain.

        Snapshot pre-existing dirs first so that stale dirs from previous
        aborted test runs (e.g. process kills, timeouts) do not cause a false
        failure — we only care about dirs created within this test.
        """
        import tempfile
        temp_root = tempfile.gettempdir()

        # Snapshot dirs that already exist before we run anything.
        pre_existing = set(
            d for d in os.listdir(temp_root)
            if d.startswith("genforge_trans_")
        )

        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"
        _make_clip(first, "640x360", 30, 1.5, True)
        _make_clip(second, "640x360", 30, 1.5, True)
        apply_clip_transition(str(first), str(second), str(output), duration=0.3)

        # Only dirs that were created during this test should be absent now.
        after = set(
            d for d in os.listdir(temp_root)
            if d.startswith("genforge_trans_")
        )
        new_remaining = after - pre_existing
        assert len(new_remaining) == 0, (
            f"Temp directories created by this test were not cleaned: {new_remaining}"
        )


class TestVFRSource:
    """Mandate Section 10 TEST 14: VFR source must be normalized to CFR."""

    def test_vfr_source_normalized_to_cfr(self, tmp_path):
        """Build a VFR clip by concatenating 24fps and 60fps segments,
        then verify the transition output is genuine CFR at 30fps."""
        seg1 = tmp_path / "seg24.mp4"
        seg2 = tmp_path / "seg60.mp4"
        concat_list = tmp_path / "concat.txt"
        vfr_clip = tmp_path / "vfr.mp4"
        second = tmp_path / "second.mp4"
        output = tmp_path / "out.mp4"

        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg1),
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=60",
            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg2),
        ], check=True, capture_output=True)
        concat_list.write_text(f"file '{seg1}'\nfile '{seg2}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vfr_clip),
        ], check=True, capture_output=True)
        _make_clip(second, "640x360", 30, 1.5, True)

        apply_clip_transition(str(vfr_clip), str(second), str(output), duration=0.3)

        data = _probe_output(output)
        vs = next(s for s in data["streams"] if s["codec_type"] == "video")
        assert vs["r_frame_rate"] == "30/1"
        assert vs["avg_frame_rate"] == "30/1"
        # Duration must be sane: vfr_clip (~2s) + second (1.5s) - 0.3s
        dur = float(data["format"]["duration"])
        assert 2.5 <= dur <= 4.0, f"Unexpected duration: {dur}"


class TestErrorHandling:
    """Mandate Section 15: useful error messages."""

    def test_rejects_missing_clip(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            apply_clip_transition("nonexistent.mp4", "also_missing.mp4",
                                  str(tmp_path / "out.mp4"))

    def test_rejects_unsupported_transition_type(self, tmp_path):
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        _make_clip(first, "640x360", 30, 1.5, True)
        _make_clip(second, "640x360", 30, 1.5, True)
        with pytest.raises(ValueError, match="Unsupported transition"):
            apply_clip_transition(str(first), str(second),
                                  str(tmp_path / "out.mp4"),
                                  transition_type="nonexistent")

    def test_rejects_output_same_as_input(self, tmp_path):
        first = tmp_path / "first.mp4"
        second = tmp_path / "second.mp4"
        _make_clip(first, "640x360", 30, 1.5, True)
        _make_clip(second, "640x360", 30, 1.5, True)
        with pytest.raises(ValueError, match="output_path must differ"):
            apply_clip_transition(str(first), str(second), str(first))
