"""Phase 3 — canonical timeline keyframe regression tests."""
import json
import subprocess
from pathlib import Path

import pytest

from services.keyframes import (
    Keyframe,
    apply_clip_keyframes,
    build_keyframe_audio_filters,
    build_keyframe_video_filters,
    piecewise_expression,
    set_clip_keyframes,
    set_clip_volume_keyframes,
    validate_keyframes,
    value_at,
)
from services.project_model import ProjectState, TimelineClip


def _make_video(path: Path, duration=2.0, with_audio=True):
    command = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=24",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    command += [
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
    ]
    if with_audio:
        command += ["-c:a", "aac"]
    else:
        command += ["-an"]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True)
    return path


SCALE_CURVE = [
    {"time": 0.0, "property": "scale", "value": 1.0},
    {"time": 3.0, "property": "scale", "value": 1.2},
    {"time": 6.0, "property": "scale", "value": 1.0},
]


class TestValidation:
    def test_mandate_scale_curve_validates(self):
        keyframes = validate_keyframes(SCALE_CURVE)
        assert [kf.value for kf in keyframes] == [1.0, 1.2, 1.0]

    def test_negative_time_rejected(self):
        with pytest.raises(Exception):
            validate_keyframes([{"time": -0.5, "property": "scale", "value": 1.0}])

    def test_out_of_range_opacity_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            validate_keyframes([{"time": 0.0, "property": "opacity", "value": 1.5}])

    def test_duplicate_times_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            validate_keyframes([
                {"time": 1.0, "property": "scale", "value": 1.0},
                {"time": 1.0, "property": "scale", "value": 1.5},
            ])


class TestInterpolation:
    def test_midpoint_linear_interpolation(self):
        keyframes = validate_keyframes(SCALE_CURVE)
        assert value_at(keyframes, 1.5) == pytest.approx(1.1)
        assert value_at(keyframes, 4.5) == pytest.approx(1.1)

    def test_clamped_outside_range(self):
        keyframes = validate_keyframes(SCALE_CURVE)
        assert value_at(keyframes, -5.0) == 1.0
        assert value_at(keyframes, 99.0) == 1.0

    def test_ease_in_slower_start_than_linear(self):
        curve = [
            Keyframe(time=0.0, property="scale", value=0.0),
            Keyframe(time=1.0, property="scale", value=1.0, easing="ease_in"),
        ]
        assert value_at(curve, 0.5) == pytest.approx(0.25)

    def test_ease_out_faster_start(self):
        curve = [
            Keyframe(time=0.0, property="scale", value=0.0),
            Keyframe(time=1.0, property="scale", value=1.0, easing="ease_out"),
        ]
        assert value_at(curve, 0.5) == pytest.approx(0.75)


class TestCanonicalStorage:
    def test_set_clip_keyframes_stores_in_transform(self):
        clip = TimelineClip(source_path="x.mp4", order=0)
        set_clip_keyframes(clip, SCALE_CURVE)
        assert clip.transform["keyframes"][1]["value"] == 1.2

    def test_replacing_one_property_preserves_others(self):
        clip = TimelineClip(source_path="x.mp4", order=0)
        set_clip_keyframes(clip, SCALE_CURVE)
        set_clip_keyframes(
            clip,
            [{"time": 0.0, "property": "opacity", "value": 0.5}],
            property_name="opacity",
        )
        properties = {kf["property"] for kf in clip.transform["keyframes"]}
        assert properties == {"scale", "opacity"}

    def test_volume_keyframes_reject_wrong_property(self):
        clip = TimelineClip(source_path="x.mp4", order=0)
        with pytest.raises(ValueError, match="volume"):
            set_clip_volume_keyframes(clip, [{"time": 0.0, "property": "scale", "value": 1.0}])

    def test_volume_keyframes_reject_excessive_gain(self):
        clip = TimelineClip(source_path="x.mp4", order=0)
        with pytest.raises(ValueError, match="4.0"):
            set_clip_volume_keyframes(clip, [{"time": 0.0, "property": "volume", "value": 9.0}])

    def test_keyframes_survive_project_roundtrip(self):
        project = ProjectState()
        clip = TimelineClip(source_path="x.mp4", order=0)
        set_clip_keyframes(clip, SCALE_CURVE)
        project.set_timeline([clip])
        restored = ProjectState.model_validate(json.loads(project.model_dump_json()))
        assert restored.timeline[0].transform["keyframes"][2]["time"] == 6.0


class TestFilterTranslation:
    def test_scale_keyframes_become_zoompan(self):
        filters = build_keyframe_video_filters(validate_keyframes(SCALE_CURVE), 320, 240, fps=24)
        assert len(filters) == 1 and "zoompan" in filters[0]

    def test_rotation_and_opacity_filters(self):
        keyframes = validate_keyframes([
            {"time": 0.0, "property": "rotation", "value": 0.0},
            {"time": 1.0, "property": "rotation", "value": 45.0},
            {"time": 0.0, "property": "opacity", "value": 1.0},
            {"time": 1.0, "property": "opacity", "value": 0.2},
        ])
        filters = build_keyframe_video_filters(keyframes, 320, 240)
        assert any(f.startswith("rotate=") for f in filters)
        assert any("colorchannelmixer" in f for f in filters)

    def test_volume_keyframes_become_volume_filter(self):
        keyframes = validate_keyframes([
            {"time": 0.0, "property": "volume", "value": 1.0},
            {"time": 2.0, "property": "volume", "value": 0.0},
        ])
        filters = build_keyframe_audio_filters(keyframes)
        assert filters and "volume=volume='" in filters[0] and "eval=frame" in filters[0]

    def test_expression_is_piecewise(self):
        expr = piecewise_expression(validate_keyframes(SCALE_CURVE))
        assert expr.startswith("if(") and expr.count("if(") == 3

    def test_video_filters_reject_volume_keyframes(self):
        keyframes = validate_keyframes([{"time": 0.0, "property": "volume", "value": 1.0}])
        with pytest.raises(ValueError, match="audio"):
            build_keyframe_video_filters(keyframes, 320, 240)


class TestKeyframeRender:
    def test_scale_keyframes_render_real_video(self, tmp_path):
        video = _make_video(tmp_path / "clip.mp4")
        clip = TimelineClip(source_path=str(video), order=0)
        set_clip_keyframes(clip, [
            {"time": 0.0, "property": "scale", "value": 1.0},
            {"time": 2.0, "property": "scale", "value": 1.4},
        ])
        out = apply_clip_keyframes(clip, str(video), str(tmp_path / "rendered.mp4"), 320, 240, fps=24)
        assert Path(out).stat().st_size > 0

    def test_volume_automation_renders_audible_change(self, tmp_path):
        video = _make_video(tmp_path / "clip.mp4", duration=2.0)
        clip = TimelineClip(source_path=str(video), order=0)
        set_clip_volume_keyframes(clip, [
            {"time": 0.0, "property": "volume", "value": 1.0},
            {"time": 2.0, "property": "volume", "value": 0.0},
        ])
        out = apply_clip_keyframes(clip, str(video), str(tmp_path / "ducked.mp4"), 320, 240, fps=24)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=codec_type", "-of", "csv", out],
            capture_output=True, text=True, check=True,
        )
        assert "audio" in probe.stdout

    def test_clip_without_keyframes_rejected(self, tmp_path):
        video = _make_video(tmp_path / "clip.mp4", with_audio=False)
        clip = TimelineClip(source_path=str(video), order=0)
        with pytest.raises(ValueError, match="no keyframes"):
            apply_clip_keyframes(clip, str(video), str(tmp_path / "out.mp4"))

    def test_keyframe_beyond_duration_rejected(self, tmp_path):
        video = _make_video(tmp_path / "clip.mp4", duration=1.0, with_audio=False)
        clip = TimelineClip(source_path=str(video), order=0)
        set_clip_keyframes(clip, [
            {"time": 0.0, "property": "scale", "value": 1.0},
            {"time": 30.0, "property": "scale", "value": 1.5},
        ])
        with pytest.raises(ValueError, match="beyond the clip duration"):
            apply_clip_keyframes(clip, str(video), str(tmp_path / "out.mp4"))
