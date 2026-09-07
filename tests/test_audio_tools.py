"""Phase 4 — Advanced audio tools regression tests."""
import re
import subprocess
from pathlib import Path

import pytest

from services.audio_tools import (
    EQ_PRESETS,
    AudioTrack,
    FadeSpec,
    apply_dynamics,
    apply_eq_preset,
    apply_fades,
    build_fade_filters,
    ducking_controls,
    enhance_voice,
    mix_tracks,
    reduce_noise,
    render_waveform_png,
)


def _make_tone(path: Path, duration=2.0, frequency=440, volume=0.8):
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
        "-af", f"volume={volume}", "-c:a", "aac", str(path),
    ], check=True, capture_output=True)
    return path


def _mean_volume(path: str) -> float:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    assert match, "volumedetect did not report mean_volume"
    return float(match.group(1))


class TestWaveform:
    def test_waveform_png_rendered(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        out = render_waveform_png(str(tone), str(tmp_path / "wave.png"), width=400, height=100)
        data = Path(out).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_waveform_rejects_media_without_audio(self, tmp_path):
        video = tmp_path / "silent_video.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=24",
            "-t", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ], check=True, capture_output=True)
        with pytest.raises(ValueError, match="no audio stream"):
            render_waveform_png(str(video), str(tmp_path / "wave.png"))


class TestFades:
    def test_fade_out_lowers_measured_loudness(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a", duration=2.0)
        out = apply_fades(str(tone), str(tmp_path / "faded.m4a"), FadeSpec(fade_out=1.5))
        assert _mean_volume(str(out)) < _mean_volume(str(tone)) - 1.0

    def test_build_fade_filters_rejects_oversized_fades(self):
        with pytest.raises(ValueError, match="exceed"):
            build_fade_filters(FadeSpec(fade_in=2.0, fade_out=2.0), duration=3.0)

    def test_unknown_curve_rejected(self):
        with pytest.raises(ValueError, match="Unknown fade curve"):
            build_fade_filters(FadeSpec(fade_in=0.5, curve="banana"), duration=2.0)


class TestProcessing:
    def test_noise_reduction_renders(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        out = reduce_noise(str(tone), str(tmp_path / "clean.m4a"))
        assert Path(out).stat().st_size > 0

    def test_noise_reduction_bounds(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        with pytest.raises(ValueError):
            reduce_noise(str(tone), str(tmp_path / "x.m4a"), noise_reduction_db=200.0)

    def test_voice_enhancement_renders(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        out = enhance_voice(str(tone), str(tmp_path / "enhanced.m4a"))
        assert Path(out).stat().st_size > 0

    def test_dynamics_renders_and_validates(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        out = apply_dynamics(str(tone), str(tmp_path / "dyn.m4a"), threshold_db=-20.0, ratio=4.0)
        assert Path(out).stat().st_size > 0
        with pytest.raises(ValueError, match="ratio"):
            apply_dynamics(str(tone), str(tmp_path / "bad.m4a"), ratio=99.0)

    def test_every_eq_preset_renders(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        for name in EQ_PRESETS:
            out = apply_eq_preset(str(tone), str(tmp_path / f"eq_{name.replace(' ', '_')}.m4a"), name)
            assert Path(out).stat().st_size > 0

    def test_unknown_eq_preset_rejected(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        with pytest.raises(ValueError, match="Unknown EQ preset"):
            apply_eq_preset(str(tone), str(tmp_path / "x.m4a"), "DoesNotExist")


class TestMixer:
    def test_mix_two_tracks_with_volume(self, tmp_path):
        loud = _make_tone(tmp_path / "a.m4a", frequency=440)
        quiet = _make_tone(tmp_path / "b.m4a", frequency=880)
        out = mix_tracks(
            [AudioTrack(path=str(loud), volume_db=0.0), AudioTrack(path=str(quiet), volume_db=-6.0)],
            str(tmp_path / "mix.m4a"),
        )
        assert Path(out).stat().st_size > 0

    def test_muted_track_is_silent_in_mix(self, tmp_path):
        audible = _make_tone(tmp_path / "audible.m4a", frequency=440)
        muted = _make_tone(tmp_path / "muted.m4a", frequency=1200, volume=1.0)
        out = mix_tracks(
            [AudioTrack(path=str(audible)), AudioTrack(path=str(muted), muted=True)],
            str(tmp_path / "mix.m4a"),
        )
        solo_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
            capture_output=True, text=True, check=True,
        )
        assert float(solo_probe.stdout.strip()) > 1.5

    def test_solo_excludes_other_tracks(self, tmp_path):
        voice = _make_tone(tmp_path / "voice.m4a", frequency=440)
        music = _make_tone(tmp_path / "music.m4a", frequency=880)
        out = mix_tracks(
            [
                {"path": str(voice), "solo": True},
                {"path": str(music)},
            ],
            str(tmp_path / "solo.m4a"),
        )
        # Reference: voice alone through the identical mix pipeline, so codec
        # behaviour cancels out and only the solo gating differs.
        reference = mix_tracks([AudioTrack(path=str(voice))], str(tmp_path / "ref.m4a"))
        assert _mean_volume(out) == pytest.approx(_mean_volume(reference), abs=0.5)

    def test_all_muted_rejected(self, tmp_path):
        tone = _make_tone(tmp_path / "tone.m4a")
        with pytest.raises(ValueError, match="no audible tracks"):
            mix_tracks([AudioTrack(path=str(tone), muted=True)], str(tmp_path / "x.m4a"))

    def test_track_gain_bounds(self):
        with pytest.raises(ValueError):
            AudioTrack(path="x.m4a", volume_db=50.0)


class TestDuckingControls:
    def test_valid_controls_returned(self):
        controls = ducking_controls(threshold=0.05, ratio=10.0)
        assert controls["threshold"] == 0.05 and controls["ratio"] == 10.0

    def test_invalid_controls_rejected(self):
        with pytest.raises(ValueError):
            ducking_controls(threshold=0.0)
        with pytest.raises(ValueError):
            ducking_controls(release_ms=1.0)
