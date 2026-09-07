"""Prompt-driven, timestamp-precise media effects for GENFORGE.

This module is deliberately additive. Existing prompt operations remain owned by
orchestrator.py; this router handles advanced operations that need explicit time
ranges and can be composed in one FFmpeg render.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


_TIME_TOKEN = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?"
_RANGE_RE = re.compile(
    rf"(?:(?P<start>{_TIME_TOKEN})\s*(?:to|[-–])\s*(?P<end>{_TIME_TOKEN})|"
    rf"between\s+(?P<between_start>{_TIME_TOKEN})\s+and\s+(?P<between_end>{_TIME_TOKEN}))",
    re.IGNORECASE,
)
_POINT_RE = re.compile(rf"\bat\s+(?:the\s+)?(?P<point>{_TIME_TOKEN})(?:-?second)?(?:\s+mark)?", re.IGNORECASE)
_PART_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_PART_RE = re.compile(r"\bpart\s*(?P<number>\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", re.IGNORECASE)


@dataclass(frozen=True)

class TimelineOperation:
    """One validated effect and its active interval in source seconds."""

    effect: str
    start_time: float
    end_time: float
    value: Optional[str] = None


class PromptTimelineError(ValueError):
    """Raised when a prompt cannot be safely converted into a timeline edit."""


def _parse_time(value: str) -> float:
    parts = value.strip().split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            minutes, seconds_part = parts
            seconds = int(minutes) * 60 + float(seconds_part)
        elif len(parts) == 3:
            hours, minutes, seconds_part = parts
            seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds_part)
        else:
            raise ValueError
    except ValueError as exc:
        raise PromptTimelineError(f"Invalid timestamp: {value}") from exc
    if seconds < 0:
        raise PromptTimelineError("Timestamps cannot be negative.")
    return seconds


def _ranges(prompt: str) -> List[Tuple[float, float]]:
    ranges = []
    for match in _RANGE_RE.finditer(prompt):
        start_token = match.group("start") or match.group("between_start")
        end_token = match.group("end") or match.group("between_end")
        start = _parse_time(start_token)
        end = _parse_time(end_token)
        if end <= start:
            raise PromptTimelineError(f"Timeline end must be after start: {match.group(0)}")
        ranges.append((start, end))
    return ranges


def _range_near(prompt: str, position: int) -> Optional[Tuple[float, float]]:
    candidates = list(_RANGE_RE.finditer(prompt))
    if not candidates:
        return None
    nearest = min(candidates, key=lambda match: abs(match.start() - position))
    if abs(nearest.start() - position) > 100:
        return None
    start_token = nearest.group("start") or nearest.group("between_start")
    end_token = nearest.group("end") or nearest.group("between_end")
    return _parse_time(start_token), _parse_time(end_token)


def _point_near(prompt: str, position: int) -> Optional[Tuple[float, float]]:
    candidates = list(_POINT_RE.finditer(prompt))
    if not candidates:
        return None
    nearest = min(candidates, key=lambda match: abs(match.start() - position))
    if abs(nearest.start() - position) > 100:
        return None
    point = _parse_time(nearest.group("point"))
    return point, point + 1.0


def parse_timeline_prompt(prompt: str) -> List[TimelineOperation]:
    """Parse supported advanced effects and explicit time ranges from natural language.

    Supported examples include ``glitch from 00:05 to 00:08``, ``black and white
    between 10 and 12``, ``blur from 1:00 to 1:03``, ``mirror 4-6``, ``vignette``,
    ``rotate 30 degrees from 2 to 4``, and ``mute audio from 7 to 9``.
    Effects without a range are rejected rather than silently applied globally.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise PromptTimelineError("prompt must be a non-empty string.")

    effect_patterns = {
        "glitch": r"\bglitch(?:ing|ed)?\b",
        "grayscale": r"\b(?:black\s*and\s*white|grayscale|greyscale|monochrome)\b",
        "blur": r"\bblur(?:red|ring)?\b",
        "sharpen": r"\bsharpen(?:ed|ing)?\b",
        "vignette": r"\bvignette\b",
        "mirror": r"\b(?:mirror|flip\s+horizontal|horizontal\s+flip)\b",
        "rotate": r"\brotate(?:d|ion)?\b",
        "invert": r"\binvert(?:ed|ing)?\b",
        "sepia": r"\bsepia\b",
        "pixelate": r"\b(?:pixelate|pixelated|mosaic)\b",
        "mute": r"\b(?:mute|silence)\s+(?:the\s+)?(?:audio|sound)\b",
        "fade": r"\bfade\b",
    }
    operations: List[TimelineOperation] = []
    lowered = prompt.lower()
    all_ranges = _ranges(prompt)
    if not all_ranges and not _POINT_RE.search(prompt):
        raise PromptTimelineError("Every advanced effect needs a range such as 'from 00:05 to 00:08'.")

    for effect, pattern in effect_patterns.items():
        for match in re.finditer(pattern, lowered):
            interval = _range_near(prompt, match.start())
            if interval is None:
                if effect == "fade":
                    interval = _point_near(prompt, match.start())
                if interval is None:
                    if len(all_ranges) == 1:
                        interval = all_ranges[0]
                    else:
                        raise PromptTimelineError(
                            f"Add an explicit time range near the '{effect}' instruction."
                        )
            value = None
            if effect == "rotate":
                angle_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:degree|degrees|deg)", lowered[match.start():])
                value = angle_match.group(1) if angle_match else "15"
            operations.append(TimelineOperation(effect, interval[0], interval[1], value))

    if not operations:
        raise PromptTimelineError(
            "No timestamped advanced effect found. Existing global prompt operations remain available."
        )
    return operations


def _part_number(value: str) -> int:
    token = value.strip().lower()
    return int(token) if token.isdigit() else _PART_WORDS[token]


def _part_targets(text: str, part_count: int) -> List[int]:
    targets = [_part_number(match.group("number")) for match in _PART_RE.finditer(text)]
    invalid = [number for number in targets if number < 1 or number > part_count]
    if invalid:
        raise PromptTimelineError(f"Prompt references unavailable part(s): {', '.join(map(str, invalid))}.")
    return sorted(set(number - 1 for number in targets))


def parse_multi_part_directives(
    prompt: str,
    part_count: int,
    selected_parts: Optional[Sequence[int]] = None,
) -> Dict[int, str]:
    """Route free-form natural-language instructions to zero-based part indexes."""
    if part_count <= 0:
        raise PromptTimelineError("part_count must be positive.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise PromptTimelineError("prompt must be a non-empty string.")

    part_token = r"part\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    explicit_re = re.compile(
        rf"(?P<header>{part_token}(?:\s*(?:,|and)\s*{part_token})*)\s*[:\-]\s*"
        rf"(?P<body>.*?)(?=(?:\s*;\s*|\s+)part\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*[:\-]|$)",
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(explicit_re.finditer(prompt))
    assignments: Dict[int, str] = {}
    if matches:
        for match in matches:
            body = match.group("body").strip(" ;,.")
            if not body:
                raise PromptTimelineError(f"Missing edit instruction for {match.group('header').strip()}.")
            for target in _part_targets(match.group("header"), part_count):
                assignments[target] = body
        return assignments

    named_targets = _part_targets(prompt, part_count)
    if named_targets:
        shared_body = _PART_RE.sub(" ", prompt)
        shared_body = re.sub(r"\b(?:on|for|and|parts?)\b", " ", shared_body, flags=re.IGNORECASE)
        shared_body = re.sub(r"\s+", " ", shared_body).strip(" ,;:.")
        if not shared_body:
            raise PromptTimelineError("Part names were found, but no edit instruction was provided.")
        return {target: shared_body for target in named_targets}

    targets = list(selected_parts) if selected_parts is not None else list(range(part_count))
    return {target: prompt.strip() for target in targets}


def parse_multi_part_prompt(
    prompt: str,
    part_count: int,
    selected_parts: Optional[Sequence[int]] = None,
) -> Dict[int, List[TimelineOperation]]:
    """Parse timestamped effects independently for each routed source part."""
    directives = parse_multi_part_directives(prompt, part_count, selected_parts)
    assignments: Dict[int, List[TimelineOperation]] = {}
    for target, body in directives.items():
        assignments[target] = parse_timeline_prompt(body)
    return assignments


def _require_file(path: str, label: str) -> str:

    if not path or not isinstance(path, str):
        raise ValueError(f"{label} must be a non-empty path.")
    resolved = os.path.abspath(path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _output_path(path: str) -> str:
    if not path or not isinstance(path, str):
        raise ValueError("output_path must be a non-empty path.")
    resolved = os.path.abspath(path)
    os.makedirs(os.path.dirname(resolved) or os.curdir, exist_ok=True)
    return resolved


def _run(command: Sequence[str]) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg was not found on PATH.")
    try:
        subprocess.run(
            list(command), capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=True, timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timestamped FFmpeg render exceeded 300 second timeout") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "No FFmpeg diagnostics returned.").strip()
        raise RuntimeError(f"Timestamped FFmpeg render failed: {detail[-4000:]}") from exc


def _enabled(start: float, end: float) -> str:
    return f"between(t,{start:.6f},{end:.6f})"


def _video_filter(operation: TimelineOperation) -> str:
    enabled = _enabled(operation.start_time, operation.end_time)
    effect = operation.effect
    if effect == "glitch":
        return f"rgbashift=rh=6:rv=-4:enable='{enabled}'"
    if effect == "grayscale":
        # eq=saturation=0 natively supports FFmpeg timeline evaluation ('enable')
        return f"eq=saturation=0:enable='{enabled}'"
    if effect == "blur":
        return f"gblur=sigma=12:enable='{enabled}'"
    if effect == "sharpen":
        return f"unsharp=5:5:1.5:5:5:0:enable='{enabled}'"
    if effect == "vignette":
        return f"vignette=PI/4:enable='{enabled}'"
    if effect == "mirror":
        return f"hflip=enable='{enabled}'"
    if effect == "rotate":
        angle = float(operation.value or "15")
        return f"rotate={angle}*PI/180:fillcolor=black:enable='{enabled}'"
    if effect == "invert":
        return f"negate=enable='{enabled}'"
    if effect == "sepia":
        return f"colorbalance=rs=0.393:gs=0.2:bs=-0.3:enable='{enabled}'"
    if effect == "pixelate":
        return f"boxblur=luma_radius=12:luma_power=2:enable='{enabled}'"
    if effect == "fade":
        duration = operation.end_time - operation.start_time
        return f"fade=t=in:st={operation.start_time:.6f}:d={duration:.6f}"
    return ""


def _audio_filter(operation: TimelineOperation) -> str:
    if operation.effect != "mute":
        return ""
    return f"volume=0:enable='{_enabled(operation.start_time, operation.end_time)}'"


def execute_timeline_prompt(
    input_path: str,
    prompt: str,
    output_path: str,
    operations: Optional[Sequence[TimelineOperation]] = None,
) -> str:
    """Render timestamped prompt operations with a validated FFmpeg filter graph."""
    input_file = _require_file(input_path, "Prompt input")
    output_file = _output_path(output_path)
    if os.path.normcase(input_file) == os.path.normcase(output_file):
        raise ValueError("output_path must differ from input_path.")
    parsed = list(operations) if operations is not None else parse_timeline_prompt(prompt)
    if not parsed:
        raise PromptTimelineError("At least one timeline operation is required.")
    for operation in parsed:
        if operation.start_time < 0 or operation.end_time <= operation.start_time:
            raise PromptTimelineError(f"Invalid operation interval: {operation}")

    video_filters = [
        value for value in (_video_filter(operation) for operation in parsed) if value
    ]
    audio_filters = [
        value for value in (_audio_filter(operation) for operation in parsed) if value
    ]

    command = [
        "ffmpeg", "-y", "-hide_banner",
        "-i", input_file,
    ]

    filter_graph: List[str] = []
    if video_filters:
        video_chain = "[0:v]fps=fps=30,setpts=PTS-STARTPTS[v_base];"
        video_chain += ";".join(
            f"[{('v_base' if index == 0 else f'v{index}')}]"
            f"{video_filter}[{'vout' if index == len(video_filters) - 1 else f'v{index + 1}'}]"
            for index, video_filter in enumerate(video_filters)
        )
        filter_graph.append(video_chain)
        video_map = "[vout]"
    else:
        video_map = "0:v?"

    if audio_filters:
        audio_chain = "[0:a]asetpts=PTS-STARTPTS[a_base];"
        audio_chain += ";".join(
            f"[{('a_base' if index == 0 else f'a{index}')}]"
            f"{audio_filter}[{'aout' if index == len(audio_filters) - 1 else f'a{index + 1}'}]"
            for index, audio_filter in enumerate(audio_filters)
        )
        filter_graph.append(audio_chain)
        audio_map = "[aout]"
    else:
        audio_map = "0:a?"

    if filter_graph:
        command.extend(["-filter_complex", ";".join(filter_graph)])

    command.extend(["-map", video_map, "-map", audio_map])
    command.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"])

    if audio_filters:
        command.extend(["-c:a", "aac", "-b:a", "192k", "-async", "1"])
    else:
        command.extend(["-c:a", "copy"])

    command.extend(["-movflags", "+faststart", output_file])
    _run(command)

    if not os.path.isfile(output_file) or os.path.getsize(output_file) == 0:
        raise RuntimeError("FFmpeg completed but produced an empty prompt render.")
    return output_file


def try_execute_timeline_prompt(
    input_path: str, prompt: str, output_path: str
) -> Tuple[bool, Optional[str], str]:
    """Convenience adapter for Streamlit routing without hiding errors."""
    try:
        operations = parse_timeline_prompt(prompt)
        return True, execute_timeline_prompt(input_path, prompt, output_path, operations), ""
    except (PromptTimelineError, FileNotFoundError, RuntimeError, ValueError) as exc:
        return False, None, str(exc)


__all__ = [
    "PromptTimelineError",
    "TimelineOperation",
    "execute_timeline_prompt",
    "parse_timeline_prompt",
    "parse_multi_part_directives",
    "parse_multi_part_prompt",
    "try_execute_timeline_prompt",

]