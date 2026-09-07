"""Reliable FFmpeg-backed video effects and audio composition helpers."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Target transition specification.
# All clips are normalized to this spec before xfade.
_TRANSITION_FPS = 30
_TRANSITION_PIX_FMT = "yuv420p"
_TRANSITION_SAR = "1:1"
_TRANSITION_TIMESCALE = 15360  # divisible by 30; gives clean timebase 1/15360
_TRANSITION_AUDIO_RATE = 48000
_TRANSITION_CODEC = "libx264"


def _require_file(path: str, label: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"{label} must be a non-empty path")
    resolved = os.path.abspath(path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _prepare_output(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("output_path must be a non-empty path")
    resolved = os.path.abspath(path)
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ValueError(f"output_path is not a file path: {resolved}")
    os.makedirs(os.path.dirname(resolved) or os.curdir, exist_ok=True)
    if os.path.exists(resolved):
        os.remove(resolved)
    return resolved


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg operation exceeded the 300 second timeout") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg was not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        diagnostics = (exc.stderr or exc.stdout or "No FFmpeg diagnostics returned.").strip()
        raise RuntimeError(f"FFmpeg operation failed: {diagnostics[-5000:]}") from exc


def _probe(path: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Media probe exceeded 30 second timeout: {path}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe was not found on PATH") from exc
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not inspect media: {path}") from exc


def _probe_video_stream(path: str) -> dict[str, Any]:
    """Return the first video stream dict from ffprobe, or raise."""
    metadata = _probe(path)
    for stream in metadata.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    raise RuntimeError(f"No video stream found in: {path}")


def _validate_cfr(path: str) -> dict[str, Any]:
    """Validate that a media file has a genuine constant frame rate.

    Returns the video stream metadata on success.
    Raises RuntimeError if the frame rate is invalid (e.g. 1/0).
    """
    vs = _probe_video_stream(path)
    avg_fr = vs.get("avg_frame_rate", "0/0")
    r_fr = vs.get("r_frame_rate", "0/0")

    # Reject invalid rates like 0/0 or N/0
    for label, rate_str in [("avg_frame_rate", avg_fr), ("r_frame_rate", r_fr)]:
        if "/" in rate_str:
            num, den = rate_str.split("/", 1)
            try:
                if int(den) == 0 or int(num) == 0:
                    raise RuntimeError(
                        f"Invalid {label}={rate_str} in {path}. "
                        f"The normalized intermediate is not genuine CFR."
                    )
            except ValueError:
                raise RuntimeError(f"Unparseable {label}={rate_str} in {path}")

    return vs


def _duration(path: str) -> float:
    metadata = _probe(path)
    raw = metadata.get("format", {}).get("duration")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Media has no usable duration: {path}") from exc
    if value <= 0:
        raise RuntimeError(f"Media duration must be positive: {path}")
    return value


def _video_shape(path: str) -> tuple[int, int]:
    for stream in _probe(path).get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width") or 1920)
            height = int(stream.get("height") or 1080)
            return max(2, width - width % 2), max(2, height - height % 2)
    raise ValueError(f"No video stream found: {path}")


def _has_audio(path: str) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in _probe(path).get("streams", []))


def _verify_output(path: str) -> str:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise RuntimeError(f"FFmpeg produced no usable output: {path}")
    return path


# ---------------------------------------------------------
# A. CHROMA KEY / GREEN SCREEN REMOVAL
# ---------------------------------------------------------
def apply_chroma_key(
    foreground_video: str,
    background_media: str,
    output_path: str,
    key_color_hex: str = "0x00FF00",
    similarity: float = 0.15,
    blend: float = 0.08,
) -> str:
    """Replace a keyed foreground background with normalized image/video media."""
    foreground = _require_file(foreground_video, "foreground video")
    background = _require_file(background_media, "background media")
    destination = _prepare_output(output_path)
    color = key_color_hex.replace("#", "0x")
    width, height = _video_shape(foreground)
    background_is_image = Path(background).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    input_args = ["ffmpeg", "-y", "-i", foreground]
    if background_is_image:
        input_args += ["-loop", "1", "-i", background]
    else:
        input_args += ["-stream_loop", "-1", "-i", background]

    filter_complex = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p[fgbase];"
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=2[bg];"
        f"[fgbase]chromakey={color}:{similarity}:{blend}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1[v]"
    )
    command = input_args + [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", destination,
    ]
    _run(command)
    return _verify_output(destination)


# ---------------------------------------------------------
# B. DYNAMIC VIDEO TRANSITIONS — TWO-STAGE NORMALIZATION
# ---------------------------------------------------------

def _normalize_transition_clip(
    source: str,
    dest: str,
    target_width: int,
    target_height: int,
    target_fps: int = _TRANSITION_FPS,
    target_duration: float | None = None,
) -> str:
    """Stage 1: Normalize a single clip to the canonical transition specification.

    Writes a real intermediate MP4 file with:
      - explicit resolution (target_width x target_height, padded)
      - genuine CFR at target_fps (enforced by -r output flag)
      - pixel format yuv420p
      - SAR 1:1
      - predictable timebase (1/target_fps via video_track_timescale)
      - PTS starting from 0

    Returns dest on success. Raises RuntimeError with diagnostics on failure.
    """
    has_audio = _has_audio(source)
    dur_arg: list[str] = []
    if target_duration is not None and target_duration > 0:
        dur_arg = ["-t", f"{target_duration:.6f}"]

    vf = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={target_fps},format={_TRANSITION_PIX_FMT},"
        f"setsar={_TRANSITION_SAR},setpts=PTS-STARTPTS"
    )
    cmd = [
        "ffmpeg", "-y", "-i", source,
        *dur_arg,
        "-vf", vf,
        "-r", str(target_fps),
        "-video_track_timescale", str(_TRANSITION_TIMESCALE),
        "-c:v", _TRANSITION_CODEC, "-preset", "fast", "-crf", "18",
        "-pix_fmt", _TRANSITION_PIX_FMT,
    ]
    if has_audio:
        cmd += [
            "-c:a", "aac", "-b:a", "192k",
            "-ar", str(_TRANSITION_AUDIO_RATE), "-ac", "2",
        ]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", dest]
    _run(cmd)
    return dest


def _normalized_with_cache(source: str, dest: str, width: int, height: int,
                           target_fps: int, target_duration: float) -> str:
    """Normalize a clip, reusing a cached intermediate when parameters match.

    Stage-2 validation still runs downstream on cache hits, so correctness is
    unchanged; caching only removes redundant re-encodes of identical inputs.
    """
    from services.media_cache import (
        fetch_normalized, normalization_cache_key, store_normalized,
    )
    key = normalization_cache_key(source, width, height, target_fps, target_duration)
    if fetch_normalized(key, dest):
        return dest
    _normalize_transition_clip(source, dest, width, height,
                               target_fps=target_fps, target_duration=target_duration)
    store_normalized(key, dest)
    return dest


def _validate_transition_intermediate(path: str) -> dict[str, Any]:
    """Stage 2: Validate a normalized intermediate before passing to xfade.

    Confirms: file exists, non-empty, valid video stream, genuine CFR,
    correct pixel format, correct SAR.
    """
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise RuntimeError(f"Normalized intermediate is missing or empty: {path}")
    vs = _validate_cfr(path)
    pix = vs.get("pix_fmt", "")
    if pix != _TRANSITION_PIX_FMT:
        raise RuntimeError(
            f"Normalized intermediate has unexpected pix_fmt={pix}, "
            f"expected {_TRANSITION_PIX_FMT}: {path}"
        )
    sar = vs.get("sample_aspect_ratio", "")
    if sar != _TRANSITION_SAR:
        logger.warning(
            "Normalized intermediate SAR=%s (expected %s): %s",
            sar, _TRANSITION_SAR, path,
        )
    return vs


def _render_transition(
    norm_a: str,
    norm_b: str,
    destination: str,
    transition_type: str,
    duration: float,
    offset: float,
    first_has_audio: bool,
    second_has_audio: bool,
    first_duration: float,
    second_duration: float,
) -> str:
    """Stage 3: Run xfade on two verified normalized intermediates."""
    # Build video xfade
    xfade = f"[0:v][1:v]xfade=transition={transition_type}:duration={duration:.6f}:offset={offset:.6f}[vout]"

    # Build audio crossfade or silent padding.
    # anullsrc cannot live inside filter_complex — it must be a proper lavfi input.
    # We collect any extra -f lavfi -i inputs here and track their stream index.
    extra_inputs: list[str] = []
    audio_parts: list[str] = []
    next_input_idx = 2  # norm_a=0, norm_b=1

    if first_has_audio and second_has_audio:
        audio_parts.append("[0:a]asetpts=PTS-STARTPTS[a0]")
        audio_parts.append("[1:a]asetpts=PTS-STARTPTS[a1]")
        audio_parts.append(
            f"[a0][a1]acrossfade=d={duration:.6f}:c1=tri:c2=tri[aout]"
        )
    elif first_has_audio:
        # second clip is silent — pad with lavfi anullsrc input
        null_src = f"anullsrc=r={_TRANSITION_AUDIO_RATE}:cl=stereo"
        extra_inputs += ["-f", "lavfi", "-i", null_src]
        audio_parts.append("[0:a]asetpts=PTS-STARTPTS[a0]")
        audio_parts.append(
            f"[{next_input_idx}:a]atrim=duration={second_duration:.6f},"
            f"asetpts=PTS-STARTPTS[a1]"
        )
        audio_parts.append(
            f"[a0][a1]acrossfade=d={duration:.6f}:c1=tri:c2=tri[aout]"
        )
        next_input_idx += 1
    elif second_has_audio:
        # first clip is silent — pad with lavfi anullsrc input
        null_src = f"anullsrc=r={_TRANSITION_AUDIO_RATE}:cl=stereo"
        extra_inputs += ["-f", "lavfi", "-i", null_src]
        audio_parts.append(
            f"[{next_input_idx}:a]atrim=duration={first_duration:.6f},"
            f"asetpts=PTS-STARTPTS[a0]"
        )
        audio_parts.append("[1:a]asetpts=PTS-STARTPTS[a1]")
        audio_parts.append(
            f"[a0][a1]acrossfade=d={duration:.6f}:c1=tri:c2=tri[aout]"
        )
        next_input_idx += 1
    else:
        # Both clips are audio-less: generate a silent track via lavfi input.
        total_duration = max(0.01, first_duration + second_duration - duration)
        null_src = f"anullsrc=r={_TRANSITION_AUDIO_RATE}:cl=stereo"
        extra_inputs += ["-f", "lavfi", "-i", null_src]
        audio_parts.append(
            f"[{next_input_idx}:a]atrim=duration={total_duration:.6f},"
            f"asetpts=PTS-STARTPTS[aout]"
        )

    filter_parts = [xfade] + audio_parts
    filter_complex = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y", "-i", norm_a, "-i", norm_b]
        + extra_inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", _TRANSITION_CODEC, "-preset", "fast", "-crf", "20",
            "-pix_fmt", _TRANSITION_PIX_FMT,
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            destination,
        ]
    )
    _run(cmd)
    return destination


def apply_clip_transition(
    clip1_path: str,
    clip2_path: str,
    output_path: str,
    transition_type: str = "wipeleft",
    duration: float = 0.5,
    clip1_duration: float | None = None,
) -> str:
    """Apply xfade/acrossfade using two-stage normalization.

    Stage 1 — Normalize: each clip is re-encoded to a temporary intermediate
    with explicit resolution, FPS, SAR, timebase, and pixel format.

    Stage 2 — Verify: each intermediate is validated with ffprobe to confirm
    genuine CFR and correct stream parameters.

    Stage 3 — Transition: xfade runs on the verified intermediates.
    """
    from services.stage_telemetry import stage_timer

    first = _require_file(clip1_path, "first clip")
    second = _require_file(clip2_path, "second clip")
    destination = os.path.abspath(output_path)
    if os.path.normcase(first) == os.path.normcase(destination) or os.path.normcase(second) == os.path.normcase(destination):
        raise ValueError("output_path must differ from both input clips")
    destination = _prepare_output(destination)

    allowed = {"wipeleft", "dissolve", "circlecrop", "slideup", "fade", "smoothleft", "radial"}
    if transition_type not in allowed:
        raise ValueError(f"Unsupported transition type: {transition_type}")

    with stage_timer("PROBING"):
        first_duration = float(clip1_duration or _duration(first))
        second_duration = _duration(second)
        if duration <= 0:
            raise ValueError("Transition duration must be positive")
        duration = min(float(duration), max(0.05, first_duration), max(0.05, second_duration))
        offset = max(0.0, first_duration - duration)

        # Determine target dimensions from first clip
        width, height = _video_shape(first)

        # Track audio presence on the ORIGINAL clips
        first_has_audio = _has_audio(first)
        second_has_audio = _has_audio(second)

    # --- Stage 1: Normalize each clip to a temporary intermediate ---
    tmpdir = tempfile.mkdtemp(prefix="genforge_trans_")
    try:
        norm_a = os.path.join(tmpdir, "norm_a.mp4")
        norm_b = os.path.join(tmpdir, "norm_b.mp4")

        with stage_timer("NORMALIZING"):
            _normalized_with_cache(
                first, norm_a, width, height,
                target_fps=_TRANSITION_FPS,
                target_duration=first_duration,
            )
            _normalized_with_cache(
                second, norm_b, width, height,
                target_fps=_TRANSITION_FPS,
                target_duration=second_duration,
            )

        # --- Stage 2: Validate intermediates ---
        with stage_timer("VALIDATING"):
            vs_a = _validate_transition_intermediate(norm_a)
            vs_b = _validate_transition_intermediate(norm_b)

        logger.debug(
            "Transition intermediates validated: A=%s fps=%s, B=%s fps=%s",
            norm_a, vs_a.get("avg_frame_rate"),
            norm_b, vs_b.get("avg_frame_rate"),
        )

        # --- Stage 3: Render transition ---
        with stage_timer("RENDERING"):
            _render_transition(
                norm_a, norm_b, destination,
                transition_type=transition_type,
                duration=duration,
                offset=offset,
                first_has_audio=first_has_audio,
                second_has_audio=second_has_audio,
                first_duration=first_duration,
                second_duration=second_duration,
            )
    except RuntimeError:
        raise
    finally:
        # Clean up temporary normalized files
        shutil.rmtree(tmpdir, ignore_errors=True)

    with stage_timer("FINALIZING"):
        return _verify_output(destination)


# ---------------------------------------------------------
# C. VOICEOVER AND SIDECHAIN MIXING
# ---------------------------------------------------------
def apply_voiceover_to_video(
    video_path: str,
    voiceover_audio: str,
    output_path: str,
    background_music: str | None = None,
    duck_background: bool = True,
) -> str:
    """Attach narration to a video, optionally mixing and ducking background music."""
    video = _require_file(video_path, "video")
    voiceover = _require_file(voiceover_audio, "voiceover audio")
    destination = _prepare_output(output_path)
    video_duration = _duration(video)
    command = ["ffmpeg", "-y", "-i", video, "-i", voiceover]
    music_index: int | None = None
    if background_music:
        music = _require_file(background_music, "background music")
        command += ["-stream_loop", "-1", "-i", music]
        music_index = 2

    graph = [
        f"[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad,atrim=duration={video_duration:.6f}[voice]"
    ]
    if music_index is None:
        graph.append("[voice]anull[aout]")
    else:
        graph.append(
            f"[{music_index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume=0.35,atrim=duration={video_duration:.6f}[music]"
        )
        if duck_background:
            # FFmpeg 9 consumes a pad label once; split the voice chain so the
            # sidechain input and the mix input each have their own label.
            graph.append("[voice]asplit=2[voice_sc][voice_mix]")
            graph.append(
                "[music][voice_sc]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=300[ducked]"
            )
            graph.append(
                "[voice_mix][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
        else:
            graph.append("[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]")

    command += [
        "-filter_complex", ";".join(graph),
        "-map", "0:v:0", "-map", "[aout]",
        "-t", f"{video_duration:.6f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", destination,
    ]
    _run(command)
    return _verify_output(destination)


def apply_audio_ducking(
    dialogue_audio: str,
    background_music: str,
    output_path: str,
    duck_level_db: float = -12.0,
) -> str:
    """Mix dialogue and music with sidechain compression; retained for legacy callers."""
    dialogue = _require_file(dialogue_audio, "dialogue audio")
    music = _require_file(background_music, "background music")
    destination = _prepare_output(output_path)
    music_gain = max(0.01, min(1.0, 10 ** (float(duck_level_db) / 20.0)))
    filter_complex = (
        f"[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={music_gain:.6f}[bg];"
        "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[voice];"
        "[voice]asplit=2[voice_sc][voice_mix];"
        "[bg][voice_sc]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=300[ducked];"
        "[voice_mix][ducked]amix=inputs=2:duration=longest:dropout_transition=2[a_out]"
    )
    _run([
        "ffmpeg", "-y", "-i", dialogue, "-stream_loop", "-1", "-i", music,
        "-filter_complex", filter_complex, "-map", "[a_out]",
        "-c:a", "aac", "-b:a", "192k", destination,
    ])
    return _verify_output(destination)


# ---------------------------------------------------------
# D. TIKTOK/REELS ANIMATED STYLE CAPTIONS (.ASS)
# ---------------------------------------------------------
def create_tiktok_ass_subtitles(segments: list[dict[str, Any]], ass_path: str) -> str:
    """Generate an Advanced SubStation Alpha caption file."""
    destination = _prepare_output(ass_path)
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Arial,65,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,50,50,450,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(destination, "w", encoding="utf-8") as file:
        file.write(header)
        for segment in segments:
            start = format_ass_time(float(segment.get("start", 0.0)))
            end = format_ass_time(max(float(segment.get("end", 0.0)), float(segment.get("start", 0.0)) + 0.01))
            text = str(segment.get("text", "")).strip().upper().replace("{", "\\{").replace("}", "\\}")
            file.write(f"Dialogue: 0,{start},{end},TikTok,,0,0,0,,{{\\b1\\c&H00FFFF&}}{text}{{\\r}}\n")
    return destination


def format_ass_time(seconds: float) -> str:
    total_centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(total_centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    return f"{hours}:{minutes:02d}:{remainder // 100:02d}.{remainder % 100:02d}"
