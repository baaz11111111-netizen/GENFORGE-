"""Canonical timeline keyframes and motion control.

Keyframes live inside the existing ``TimelineClip.transform`` field under the
``keyframes`` (visual) and ``volume_keyframes`` (audio) keys, so they flow
through ProjectState, versioning, and ``ai_context`` exactly like every other
timeline attribute. Rendering translates keyframes into FFmpeg filter
expressions (zoompan / rotate / colorchannelmixer / volume) — no separate
animation system is created.

Supported properties: position_x, position_y, scale, rotation, opacity.
Values are interpolated between keyframes (linear with optional easing) and
clamped outside the first/last keyframe.
"""

from __future__ import annotations

import math
import os
from typing import Any, Literal, Sequence

from pydantic import BaseModel, field_validator

from production_features import _duration, _ensure_output, _probe, _require_file, _run_ffmpeg

VISUAL_PROPERTIES = ("position_x", "position_y", "scale", "rotation", "opacity")
EASINGS = ("linear", "ease_in", "ease_out", "ease_in_out")

_BOUNDS = {
    "position_x": (-2.0, 2.0),
    "position_y": (-2.0, 2.0),
    "scale": (0.05, 16.0),
    "rotation": (-36000.0, 36000.0),
    "opacity": (0.0, 1.0),
}


class Keyframe(BaseModel):
    """One animated value at one point in clip-local time (seconds)."""

    time: float
    property: Literal["position_x", "position_y", "scale", "rotation", "opacity", "volume"]
    value: float
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "linear"

    @field_validator("time")
    @classmethod
    def _non_negative_time(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Keyframe time cannot be negative.")
        return float(value)

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Keyframe value must be finite.")
        return float(value)


def validate_keyframes(keyframes: Sequence[Keyframe | dict[str, Any]]) -> list[Keyframe]:
    """Coerce and validate a keyframe list; raises ValueError on bad data."""
    resolved = [kf if isinstance(kf, Keyframe) else Keyframe.model_validate(kf) for kf in keyframes]
    for keyframe in resolved:
        low, high = _BOUNDS.get(keyframe.property, (-1e9, 1e9))
        if not low <= keyframe.value <= high:
            raise ValueError(
                f"Keyframe value {keyframe.value} out of range [{low}, {high}] "
                f"for property '{keyframe.property}'."
            )
    resolved.sort(key=lambda kf: kf.time)
    per_property: dict[str, list[float]] = {}
    for keyframe in resolved:
        times = per_property.setdefault(keyframe.property, [])
        if keyframe.time in times:
            raise ValueError("Keyframe times must be unique for one property.")
        times.append(keyframe.time)
    return resolved


def set_clip_keyframes(clip, keyframes: Sequence[Keyframe | dict[str, Any]], property_name: str | None = None):
    """Store visual keyframes on a TimelineClip.transform (canonical storage).

    When ``property_name`` is given, only that property's keyframes are
    replaced; other animated properties are preserved.
    """
    validated = validate_keyframes(keyframes)
    if not validated:
        raise ValueError("At least one keyframe is required.")
    if property_name and not all(kf.property == property_name for kf in validated):
        raise ValueError(f"All keyframes must target property '{property_name}'.")
    transform = dict(clip.transform or {})
    existing = [kf for kf in _existing_visual(transform) if property_name and kf.property != property_name]
    transform["keyframes"] = [kf.model_dump() for kf in (existing + validated)]
    clip.transform = transform
    return clip


def set_clip_volume_keyframes(clip, keyframes: Sequence[Keyframe | dict[str, Any]]):
    """Store volume automation keyframes (values are linear gain 0.0–4.0)."""
    coerced = []
    for kf in keyframes:
        if isinstance(kf, Keyframe):
            item = kf
        else:
            item = Keyframe.model_validate({**kf, "property": kf.get("property", "volume")})
        if item.property != "volume":
            raise ValueError("Volume keyframes must target property 'volume'.")
        if not 0.0 <= item.value <= 4.0:
            raise ValueError("Volume keyframe gain must be between 0.0 and 4.0.")
        coerced.append(item)
    validated = validate_keyframes(coerced)
    if not validated:
        raise ValueError("At least one volume keyframe is required.")
    transform = dict(clip.transform or {})
    transform["volume_keyframes"] = [kf.model_dump() for kf in validated]
    clip.transform = transform
    return clip


def _existing_visual(transform: dict[str, Any]) -> list[Keyframe]:
    return [Keyframe.model_validate(kf) for kf in transform.get("keyframes", [])]


def _ease(fraction: float, easing: str) -> float:
    if easing == "ease_in":
        return fraction * fraction
    if easing == "ease_out":
        return 1.0 - (1.0 - fraction) ** 2
    if easing == "ease_in_out":
        return fraction * fraction * (3.0 - 2.0 * fraction)
    return fraction


def value_at(keyframes: Sequence[Keyframe], time: float) -> float:
    """Interpolated value at ``time``; clamped outside the keyframe range."""
    ordered = sorted(keyframes, key=lambda kf: kf.time)
    if not ordered:
        raise ValueError("Cannot interpolate without keyframes.")
    if time <= ordered[0].time:
        return ordered[0].value
    if time >= ordered[-1].time:
        return ordered[-1].value
    for previous, nxt in zip(ordered, ordered[1:]):
        if previous.time <= time <= nxt.time:
            span = nxt.time - previous.time
            fraction = 0.0 if span <= 0 else (time - previous.time) / span
            return previous.value + (nxt.value - previous.value) * _ease(fraction, nxt.easing)
    return ordered[-1].value  # pragma: no cover - guarded above


def _fmt(number: float) -> str:
    return f"{number:.6f}".rstrip("0").rstrip(".") or "0"


def piecewise_expression(keyframes: Sequence[Keyframe], variable: str = "t") -> str:
    """FFmpeg expression evaluating the interpolation curve.

    ``variable`` is the time expression available to the target filter:
    ``t`` for rotate/volume/colorchannelmixer, ``(on/FPS)`` for zoompan which
    does not expose a time variable.
    """
    ordered = sorted(keyframes, key=lambda kf: kf.time)
    if not ordered:
        raise ValueError("Cannot build an expression without keyframes.")
    if len(ordered) == 1:
        return _fmt(ordered[0].value)
    expr = _fmt(ordered[-1].value)
    for previous, nxt in reversed(list(zip(ordered, ordered[1:]))):
        span = nxt.time - previous.time
        if span <= 0:
            continue
        slope = (nxt.value - previous.value) / span
        linear = f"{_fmt(previous.value)}+{_fmt(slope)}*(({variable})-{_fmt(previous.time)})"
        expr = f"if(lte({variable},{_fmt(nxt.time)}),{linear},{expr})"
    expr = f"if(lt({variable},{_fmt(ordered[0].time)}),{_fmt(ordered[0].value)},{expr})"
    return expr


def _visual_groups(keyframes: Sequence[Keyframe]) -> dict[str, list[Keyframe]]:
    groups: dict[str, list[Keyframe]] = {}
    for keyframe in keyframes:
        groups.setdefault(keyframe.property, []).append(keyframe)
    return groups


def build_keyframe_video_filters(
    keyframes: Sequence[Keyframe],
    width: int,
    height: int,
    fps: int = 30,
) -> list[str]:
    """Translate visual keyframes into concrete FFmpeg video filters."""
    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError("width, height and fps must be positive.")
    groups = _visual_groups(validate_keyframes(keyframes))
    if "volume" in groups:
        raise ValueError("Volume keyframes are audio properties; use the audio filter chain.")
    filters: list[str] = []

    scale_kfs = groups.get("scale", [])
    pos_x = groups.get("position_x", [])
    pos_y = groups.get("position_y", [])
    if scale_kfs or pos_x or pos_y:
        zoom_var = f"on/{fps}"
        zoom = piecewise_expression(scale_kfs, zoom_var) if scale_kfs else "1"
        # zoompan pans relative to the zoomed canvas; position values are
        # normalized (0..1 centre-based), mapped onto the overscan area.
        x_expr = piecewise_expression(pos_x, zoom_var) if pos_x else "0.5"
        y_expr = piecewise_expression(pos_y, zoom_var) if pos_y else "0.5"
        x_offset = f"(iw-iw/zoom)*min(max({x_expr},0),1)"
        y_offset = f"(ih-ih/zoom)*min(max({y_expr},0),1)"
        filters.append(
            f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
            f"crop={width * 2}:{height * 2},"
            f"zoompan=z='{zoom}':x='{x_offset}':y='{y_offset}'"
            f":d=1:s={width}x{height}:fps={fps}"
        )

    rotation_kfs = groups.get("rotation", [])
    if rotation_kfs:
        radians = f"({piecewise_expression(rotation_kfs)})*{math.pi:.10f}/180"
        filters.append(f"rotate={radians}:c=black@0:ow=iw:oh=ih")

    opacity_kfs = groups.get("opacity", [])
    if opacity_kfs:
        filters.append(
            f"format=rgba,colorchannelmixer=aa='{piecewise_expression(opacity_kfs)}'"
        )
    return filters


def build_keyframe_audio_filters(keyframes: Sequence[Keyframe]) -> list[str]:
    """Translate volume keyframes into FFmpeg audio filters."""
    validated = [kf for kf in validate_keyframes(keyframes) if kf.property == "volume"]
    if not validated:
        return []
    return [f"volume=volume='{piecewise_expression(validated)}':eval=frame"]


def apply_clip_keyframes(
    clip,
    input_path: str,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
) -> str:
    """Render one timeline clip with its stored keyframes via FFmpeg."""
    source = _require_file(input_path, "Keyframed clip")
    destination = _ensure_output(output_path)
    transform = clip.transform or {}
    visual = [Keyframe.model_validate(kf) for kf in transform.get("keyframes", [])]
    volume = [Keyframe.model_validate(kf) for kf in transform.get("volume_keyframes", [])]
    if not visual and not volume:
        raise ValueError("Clip has no keyframes; nothing to render in the keyframe pass.")
    duration = _duration(source)
    for keyframe in visual + volume:
        if keyframe.time > duration + 0.5:
            raise ValueError(f"Keyframe at {keyframe.time}s is beyond the clip duration {duration:.2f}s.")
    has_audio = any(stream.get("codec_type") == "audio" for stream in _probe(source).get("streams", []))

    video_filters = build_keyframe_video_filters(visual, width, height, fps)
    video_filters.append("format=yuv420p")
    audio_filters = build_keyframe_audio_filters(volume)

    command = ["ffmpeg", "-y", "-hide_banner", "-i", source, "-vf", ",".join(video_filters)]
    if has_audio:
        chain = ",".join(["aresample=48000", *audio_filters]) if audio_filters else "aresample=48000"
        command += ["-af", chain, "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-an"]
    command += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart", destination,
    ]
    _run_ffmpeg(command)
    if not os.path.isfile(destination) or os.path.getsize(destination) == 0:
        raise RuntimeError("Keyframe render produced an empty output.")
    return destination


__all__ = [
    "VISUAL_PROPERTIES",
    "EASINGS",
    "Keyframe",
    "validate_keyframes",
    "set_clip_keyframes",
    "set_clip_volume_keyframes",
    "value_at",
    "piecewise_expression",
    "build_keyframe_video_filters",
    "build_keyframe_audio_filters",
    "apply_clip_keyframes",
]
