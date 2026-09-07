"""Production finishing and editorial utilities for GENFORGE.

The module intentionally owns capabilities that are not covered by the existing
single-clip enhancement agents: multi-clip timeline assembly, broadcast-style
loudness mastering, and visual review contact sheets.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Sequence


_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def _require_file(path: str, label: str) -> str:
    if not path or not isinstance(path, str):
        raise ValueError(f"{label} must be a non-empty file path.")
    resolved = os.path.abspath(path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _ensure_output(path: str) -> str:
    if not path or not isinstance(path, str):
        raise ValueError("output_path must be a non-empty file path.")
    resolved = os.path.abspath(path)
    os.makedirs(os.path.dirname(resolved) or os.curdir, exist_ok=True)
    return resolved


def _run_ffmpeg(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg was not found on PATH. Install FFmpeg and restart the terminal.")
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg operation exceeded 600 second timeout") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "No FFmpeg diagnostics returned.").strip()
        raise RuntimeError(f"FFmpeg failed with exit code {exc.returncode}: {detail[-4000:]}") from exc
    return result


def _probe(path: str) -> Dict[str, object]:
    resolved = _require_file(path, "Media input")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe was not found on PATH. Install FFmpeg and restart the terminal.")
    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", resolved
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=30,
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise RuntimeError(f"Could not inspect media '{resolved}': {detail[-2000:]}") from exc


def _duration(path: str) -> float:
    metadata = _probe(path)
    raw_duration = metadata.get("format", {}).get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Media has no usable duration: {path}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"Media duration must be positive: {path}")
    return duration


def normalize_audio_lufs(
    input_path: str,
    output_path: str,
    target_lufs: float = -16.0,
    true_peak_db: float = -1.5,
    loudness_range: float = 11.0,
) -> str:
    """Master a media file to an integrated loudness target with FFmpeg loudnorm.

    Uses a measured two-pass loudnorm render when possible and falls back to a
    deterministic single-pass render if FFmpeg does not return valid measurements.
    Video is stream-copied, so this is suitable for fast finishing of existing renders.
    """
    input_file = _require_file(input_path, "Audio mastering input")
    output_file = _ensure_output(output_path)
    if os.path.normcase(input_file) == os.path.normcase(output_file):
        raise ValueError("output_path must differ from input_path.")
    if not any(stream.get("codec_type") == "audio" for stream in _probe(input_file).get("streams", [])):
        raise ValueError("Audio mastering requires an input with an audio stream.")
    if not -70.0 <= target_lufs <= -5.0:
        raise ValueError("target_lufs must be between -70 and -5 LUFS.")
    if not -10.0 <= true_peak_db <= 0.0:
        raise ValueError("true_peak_db must be between -10 and 0 dBTP.")
    if loudness_range <= 0:
        raise ValueError("loudness_range must be positive.")

    analysis = [
        "ffmpeg", "-hide_banner", "-i", input_file,
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak_db}:LRA={loudness_range}:print_format=json",
        "-f", "null", "-",
    ]
    measured: Optional[Dict[str, object]] = None
    try:
        analysis_result = _run_ffmpeg(analysis)
        diagnostic_text = analysis_result.stderr or ""
        json_start = diagnostic_text.rfind("{\n")
        if json_start >= 0:
            measured = json.loads(diagnostic_text[json_start:])
    except (RuntimeError, json.JSONDecodeError):
        measured = None

    loudnorm = (
        f"loudnorm=I={target_lufs}:TP={true_peak_db}:LRA={loudness_range}"
    )
    if measured:
        required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        if all(key in measured for key in required):
            loudnorm += ":" + ":".join(
                f"{key}={measured[key]}" for key in required
            ) + ":linear=true:print_format=summary"

    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", input_file,
        "-af", loudnorm,
        "-map", "0:v?", "-map", "0:a?",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", output_file,
    ]
    _run_ffmpeg(command)
    if not os.path.isfile(output_file) or os.path.getsize(output_file) == 0:
        raise RuntimeError("FFmpeg completed but produced an empty mastered file.")
    return output_file


def trim_clip_for_timeline(input_path: str, output_path: str, start_time: float = 0.0,
                           end_time: float = 0.0, profile: str = "final") -> str:
    """Render one timeline clip with optional in/out points before concatenation.

    ``profile`` selects the encode preset (see services.encode_profiles);
    "final" preserves the verified-stable medium/crf20 render.
    """
    from services.encode_profiles import encode_flags
    source = _require_file(input_path, "Timeline clip")
    destination = _ensure_output(output_path)
    if start_time < 0 or end_time < 0:
        raise ValueError("Timeline trim values cannot be negative.")
    duration = _duration(source)
    effective_end = duration if end_time <= 0 else min(end_time, duration)
    if effective_end <= start_time:
        raise ValueError(f"Timeline trim end must be after trim start: {input_path}")
    if start_time == 0 and effective_end >= duration - 0.001:
        return source
    has_audio = any(stream.get("codec_type") == "audio" for stream in _probe(source).get("streams", []))
    command = [
        "ffmpeg", "-y", "-hide_banner", "-ss", f"{start_time:.6f}",
        "-i", source, "-t", f"{effective_end - start_time:.6f}",
        *encode_flags(profile),
        "-pix_fmt", "yuv420p",
    ]
    command += ["-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]
    command += ["-movflags", "+faststart", destination]
    _run_ffmpeg(command)
    if not os.path.isfile(destination) or os.path.getsize(destination) == 0:
        raise RuntimeError("Timeline trim produced an empty output.")
    return destination


def assemble_timeline(

    clip_paths: Sequence[str],
    output_path: str,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> str:
    """Assemble any number of video clips into one normalized editorial timeline.

    Inputs may have different dimensions, frame rates, codecs, or audio presence.
    Missing audio is replaced with silence so the concat filter remains stable.
    Transitions remain owned by the existing two-clip transition helper.
    """
    if not clip_paths:
        raise ValueError("At least one video clip is required.")
    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError("width, height, and fps must be positive.")
    inputs = [_require_file(path, "Timeline clip") for path in clip_paths]
    for path in inputs:
        if os.path.splitext(path)[1].lower() not in _VIDEO_EXTENSIONS:
            raise ValueError(f"Unsupported timeline clip type: {path}")
    output_file = _ensure_output(output_path)

    command: List[str] = ["ffmpeg", "-y", "-hide_banner"]
    metadata: List[Dict[str, object]] = []
    for path in inputs:
        metadata.append(_probe(path))
        command.extend(["-i", path])

    filters: List[str] = []
    for index, media in enumerate(metadata):
        streams = media.get("streams", [])
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        duration = _duration(inputs[index])
        filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},"
            f"format=yuv420p,setpts=PTS-STARTPTS[v{index}]"
        )

        if has_audio:
            filters.append(
                f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
        else:
            filters.append(
                f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )

    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(inputs)))
    filters.append(f"{concat_inputs}concat=n={len(inputs)}:v=1:a=1[vout][aout]")
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", output_file,
    ])
    _run_ffmpeg(command)
    if not os.path.isfile(output_file) or os.path.getsize(output_file) == 0:
        raise RuntimeError("FFmpeg completed but produced an empty timeline.")
    return output_file


def generate_contact_sheet(
    video_path: str,
    output_path: str,
    columns: int = 4,
    rows: int = 3,
    thumbnail_width: int = 320,
) -> str:
    """Create a labeled visual review sheet from evenly sampled video frames."""
    input_file = _require_file(video_path, "Contact-sheet video")
    output_file = _ensure_output(output_path)
    if columns <= 0 or rows <= 0 or thumbnail_width <= 0:
        raise ValueError("columns, rows, and thumbnail_width must be positive.")
    duration = _duration(input_file)
    frame_count = columns * rows
    interval = max(duration / frame_count, 0.05)
    tile_width = thumbnail_width
    tile_height = max(2, int(round(thumbnail_width * 9 / 16)))
    tile_filter = (
        f"fps=1/{interval:.6f},"
        f"scale={tile_width}:{tile_height}:force_original_aspect_ratio=decrease,"
        f"pad={tile_width}:{tile_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,tile={columns}x{rows}:padding=8:margin=8"
    )

    command = [
        "ffmpeg", "-y", "-hide_banner", "-i", input_file,
        "-vf", tile_filter, "-frames:v", "1", "-q:v", "2", output_file,
    ]
    _run_ffmpeg(command)
    if not os.path.isfile(output_file) or os.path.getsize(output_file) == 0:
        raise RuntimeError("FFmpeg completed but produced an empty contact sheet.")
    return output_file


__all__ = ["assemble_timeline", "generate_contact_sheet", "normalize_audio_lufs", "trim_clip_for_timeline"]
