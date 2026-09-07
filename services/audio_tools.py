"""Advanced audio tools built on the existing FFmpeg audio pipeline.

These helpers compose with the canonical audio functions in advanced_video
(ducking, voiceover mixing) and production_features (LUFS mastering) instead
of creating a second audio renderer. Every operation renders real media and
reports honest errors.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import BaseModel, field_validator

from production_features import _ensure_output, _probe, _require_file, _run_ffmpeg

FADE_CURVES = ("tri", "qsin", "esin", "hsin", "log", "ipar", "qua", "cub", "squ", "cbr", "par", "exp", "iqsin", "ihsin", "dese", "desi", "losi", "nofade")

EQ_PRESETS: dict[str, str] = {
    "Voice Presence": "equalizer=f=3000:t=q:w=1.2:g=4,equalizer=f=200:t=q:w=1:g=-2",
    "Warm": "equalizer=f=250:t=q:w=1:g=3,equalizer=f=6000:t=q:w=1:g=-2",
    "Bright": "equalizer=f=8000:t=q:w=1:g=4",
    "Bass Boost": "equalizer=f=80:t=q:w=0.8:g=6",
    "Telephone": "highpass=f=500,lowpass=f=3000",
    "Podcast": "highpass=f=80,equalizer=f=3000:t=q:w=1.2:g=3,equalizer=f=10000:t=q:w=1:g=-1",
}


class AudioTrack(BaseModel):
    """One mixable track in a session (file + per-track controls)."""

    path: str
    volume_db: float = 0.0
    muted: bool = False
    solo: bool = False

    @field_validator("volume_db")
    @classmethod
    def _gain_bounds(cls, value: float) -> float:
        if not -60.0 <= value <= 24.0:
            raise ValueError("Track gain must be between -60 dB and +24 dB.")
        return float(value)


@dataclass(frozen=True)
class FadeSpec:
    """Fade-in/out pair; durations in seconds, curve from FADE_CURVES."""

    fade_in: float = 0.0
    fade_out: float = 0.0
    curve: str = "tri"


def _require_audio(path: str, label: str) -> str:
    resolved = _require_file(path, label)
    if not any(stream.get("codec_type") == "audio" for stream in _probe(resolved).get("streams", [])):
        raise ValueError(f"{label} has no audio stream: {resolved}")
    return resolved


def render_waveform_png(input_path: str, output_path: str, width: int = 1200, height: int = 240, color: str = "#00E5FF") -> str:
    """Render a waveform overview image for timeline visualization."""
    source = _require_audio(input_path, "Waveform source")
    destination = _ensure_output(output_path)
    if width <= 0 or height <= 0:
        raise ValueError("Waveform width and height must be positive.")
    if not color.startswith("#") or len(color) not in (4, 7):
        raise ValueError("Waveform color must be #RGB or #RRGGBB HEX.")
    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", source,
        "-filter_complex", f"[0:a]showwavespic=s={width}x{height}:colors={color}[wave]",
        "-map", "[wave]", "-frames:v", "1", destination,
    ]
    _run_ffmpeg(command)
    if not os.path.isfile(destination) or os.path.getsize(destination) == 0:
        raise RuntimeError("Waveform render produced an empty image.")
    return destination


def build_fade_filters(spec: FadeSpec, duration: float) -> str:
    """Compose afade filters for a clip of known duration."""
    if spec.curve not in FADE_CURVES:
        raise ValueError(f"Unknown fade curve '{spec.curve}'. Available: {', '.join(FADE_CURVES)}")
    if spec.fade_in < 0 or spec.fade_out < 0:
        raise ValueError("Fade durations cannot be negative.")
    if duration <= 0:
        raise ValueError("Duration must be positive to place fades.")
    if spec.fade_in + spec.fade_out > duration + 1e-6:
        raise ValueError("Combined fade durations exceed the clip duration.")
    parts = []
    if spec.fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={spec.fade_in:.3f}:curve={spec.curve}")
    if spec.fade_out > 0:
        parts.append(f"afade=t=out:st={max(0.0, duration - spec.fade_out):.3f}:d={spec.fade_out:.3f}:curve={spec.curve}")
    return ",".join(parts)


def apply_fades(input_path: str, output_path: str, spec: FadeSpec) -> str:
    """Render a copy of the media with fade-in/out curves applied."""
    source = _require_audio(input_path, "Fade input")
    destination = _ensure_output(output_path)
    duration = float(_probe(source)["format"]["duration"])
    chain = build_fade_filters(spec, duration)
    if not chain:
        raise ValueError("At least one fade (in or out) is required.")
    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", source,
        "-af", chain,
        "-map", "0:v?", "-map", "0:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", destination,
    ]
    _run_ffmpeg(command)
    return destination


def reduce_noise(input_path: str, output_path: str, noise_reduction_db: float = 12.0, noise_floor_db: float = -40.0) -> str:
    """Noise reduction via FFmpeg afftdn where the codec pipeline supports it."""
    source = _require_audio(input_path, "Noise reduction input")
    destination = _ensure_output(output_path)
    if not 1.0 <= noise_reduction_db <= 97.0:
        raise ValueError("noise_reduction_db must be between 1 and 97 dB.")
    if not -80.0 <= noise_floor_db <= -10.0:
        raise ValueError("noise_floor_db must be between -80 and -10 dB.")
    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", source,
        "-af", f"afftdn=nr={noise_reduction_db:.1f}:nf={noise_floor_db:.1f}",
        "-map", "0:v?", "-map", "0:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", destination,
    ]
    _run_ffmpeg(command)
    return destination


def enhance_voice(input_path: str, output_path: str) -> str:
    """Voice enhancement chain: rumble cut, presence lift, de-harsh, dynamics."""
    source = _require_audio(input_path, "Voice enhancement input")
    destination = _ensure_output(output_path)
    chain = (
        "highpass=f=80,lowpass=f=12000,"
        "equalizer=f=3000:t=q:w=1.2:g=3,"
        "equalizer=f=8000:t=q:w=1:g=-2,"
        "acompressor=threshold=-18dB:ratio=3:attack=20:release=250,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    )
    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", source,
        "-af", chain,
        "-map", "0:v?", "-map", "0:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", destination,
    ]
    _run_ffmpeg(command)
    return destination


def apply_dynamics(
    input_path: str,
    output_path: str,
    threshold_db: float = -18.0,
    ratio: float = 3.0,
    attack_ms: float = 20.0,
    release_ms: float = 250.0,
    limiter_ceiling_db: float = -1.0,
) -> str:
    """Compressor + limiter stage with explicit, validated controls."""
    source = _require_audio(input_path, "Dynamics input")
    destination = _ensure_output(output_path)
    if not -60.0 <= threshold_db <= 0.0:
        raise ValueError("threshold_db must be between -60 and 0 dB.")
    if not 1.0 <= ratio <= 20.0:
        raise ValueError("ratio must be between 1 and 20.")
    if not 0.1 <= attack_ms <= 2000.0 or not 1.0 <= release_ms <= 9000.0:
        raise ValueError("attack_ms must be 0.1–2000 and release_ms 1–9000.")
    if not -20.0 <= limiter_ceiling_db <= 0.0:
        raise ValueError("limiter_ceiling_db must be between -20 and 0 dB.")
    chain = (
        f"acompressor=threshold={threshold_db:.1f}dB:ratio={ratio:.2f}"
        f":attack={attack_ms:.1f}:release={release_ms:.1f},"
        f"alimiter=limit={10 ** (limiter_ceiling_db / 20):.6f}"
    )
    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", source,
        "-af", chain,
        "-map", "0:v?", "-map", "0:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", destination,
    ]
    _run_ffmpeg(command)
    return destination


def apply_eq_preset(input_path: str, output_path: str, preset: str) -> str:
    """Apply a named EQ preset (see EQ_PRESETS)."""
    source = _require_audio(input_path, "EQ input")
    destination = _ensure_output(output_path)
    try:
        chain = EQ_PRESETS[preset]
    except KeyError as exc:
        raise ValueError(f"Unknown EQ preset: {preset}. Available: {', '.join(EQ_PRESETS)}") from exc
    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", source,
        "-af", chain,
        "-map", "0:v?", "-map", "0:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", destination,
    ]
    _run_ffmpeg(command)
    return destination


def mix_tracks(tracks: Sequence[AudioTrack | dict[str, Any]], output_path: str) -> str:
    """Mix multiple tracks honouring per-track volume, mute and solo controls.

    When any track is soloed, only soloed tracks are audible; muted tracks are
    never mixed in. Reuses FFmpeg amix so levels stay compatible with the
    existing ducking/voiceover pipeline.
    """
    resolved = [t if isinstance(t, AudioTrack) else AudioTrack.model_validate(t) for t in tracks]
    if not resolved:
        raise ValueError("At least one track is required.")
    destination = _ensure_output(output_path)
    soloed = any(track.solo for track in resolved)
    audible: list[AudioTrack] = []
    for track in resolved:
        if track.muted:
            continue
        if soloed and not track.solo:
            continue
        audible.append(track)
    if not audible:
        raise ValueError("Mix has no audible tracks (all muted or solo-filtered).")

    command = ["ffmpeg", "-y", "-hide_banner"]
    filters = []
    for index, track in enumerate(audible):
        source = _require_audio(track.path, f"Track {index + 1}")
        command.extend(["-i", source])
        gain = 10 ** (track.volume_db / 20)
        filters.append(
            f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={gain:.6f}[t{index}]"
        )
    mix_inputs = "".join(f"[t{i}]" for i in range(len(audible)))
    filters.append(f"{mix_inputs}amix=inputs={len(audible)}:duration=longest:normalize=0[aout]")
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", destination,
    ])
    _run_ffmpeg(command)
    if not os.path.isfile(destination) or os.path.getsize(destination) == 0:
        raise RuntimeError("Track mix produced an empty output.")
    return destination


def ducking_controls(threshold: float = 0.03, ratio: float = 8.0, attack_ms: float = 15.0, release_ms: float = 300.0) -> dict[str, float]:
    """Validate improved ducking parameters for the canonical sidechain compressor.

    Returns the normalized control set consumed by advanced_video.apply_audio_ducking
    callers (same semantics as the existing ducking pipeline).
    """
    if not 0.001 <= threshold <= 1.0:
        raise ValueError("Ducking threshold must be between 0.001 and 1.0.")
    if not 1.0 <= ratio <= 40.0:
        raise ValueError("Ducking ratio must be between 1 and 40.")
    if not 1.0 <= attack_ms <= 1000.0 or not 50.0 <= release_ms <= 5000.0:
        raise ValueError("Ducking attack must be 1–1000 ms and release 50–5000 ms.")
    return {"threshold": threshold, "ratio": ratio, "attack_ms": attack_ms, "release_ms": release_ms}


__all__ = [
    "FADE_CURVES",
    "EQ_PRESETS",
    "AudioTrack",
    "FadeSpec",
    "render_waveform_png",
    "build_fade_filters",
    "apply_fades",
    "reduce_noise",
    "enhance_voice",
    "apply_dynamics",
    "apply_eq_preset",
    "mix_tracks",
    "ducking_controls",
]
