"""Advanced caption styling: presets, custom styles, emphasis, safe zones.

Builds Advanced SubStation Alpha (.ass) content on top of the existing
caption timing model (segments with start/end/text). Timing helpers are
reused from advanced_video so captions stay synchronized with the timeline.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from advanced_video import format_ass_time

# ASS colours are &HAABBGGRR (alpha, blue, green, red)
_CAPTION_PRESETS: dict[str, dict] = {
    "Classic": dict(fontname="Arial", fontsize=58, primary="&H00FFFFFF", outline_c="&H00000000",
                    back="&H80000000", outline=2, shadow=1, alignment=2, margin_v=60, bold=-1, box=False),
    "Minimal": dict(fontname="Helvetica", fontsize=46, primary="&H00FFFFFF", outline_c="&H00000000",
                    back="&H00000000", outline=1, shadow=0, alignment=2, margin_v=48, bold=0, box=False),
    "Bold": dict(fontname="Impact", fontsize=68, primary="&H00FFFFFF", outline_c="&H00000000",
                 back="&H80000000", outline=4, shadow=2, alignment=2, margin_v=70, bold=-1, box=False),
    "Creator": dict(fontname="Montserrat", fontsize=64, primary="&H0000FFFF", outline_c="&H00000000",
                    back="&H96000000", outline=3, shadow=0, alignment=2, margin_v=120, bold=-1, box=True),
    "Karaoke": dict(fontname="Arial", fontsize=60, primary="&H00FFFFFF", outline_c="&H000000FF",
                    back="&H00000000", outline=3, shadow=0, alignment=2, margin_v=64, bold=-1, box=False),
    "Social": dict(fontname="Arial", fontsize=56, primary="&H0000F0FF", outline_c="&H00000000",
                   back="&HAA000000", outline=2, shadow=1, alignment=2, margin_v=140, bold=-1, box=True),
    "News": dict(fontname="Times New Roman", fontsize=50, primary="&H00FFFFFF", outline_c="&H00000000",
                 back="&HC8000000", outline=0, shadow=0, alignment=2, margin_v=52, bold=0, box=True),
}

CAPTION_PRESETS = tuple(_CAPTION_PRESETS)


@dataclass(frozen=True)
class CaptionStyle:
    """Resolved caption styling, creatable from a preset or fully custom."""

    fontname: str
    fontsize: int
    primary: str
    outline_c: str
    back: str
    outline: int
    shadow: int
    alignment: int  # ASS numpad alignment (2 = bottom centre)
    margin_v: int
    bold: int
    box: bool

    @staticmethod
    def from_preset(name: str, margin_v: int | None = None) -> "CaptionStyle":
        try:
            data = dict(_CAPTION_PRESETS[name])
        except KeyError as exc:
            raise ValueError(f"Unknown caption preset: {name}. Available: {', '.join(CAPTION_PRESETS)}") from exc
        if margin_v is not None:
            data["margin_v"] = int(margin_v)
        return CaptionStyle(**data)


def style_for_platform_safe_zone(preset: str, safe_zone_bottom: int) -> CaptionStyle:
    """Position captions above a platform's bottom safe zone (e.g. TikTok UI)."""
    if safe_zone_bottom < 0:
        raise ValueError("safe_zone_bottom cannot be negative")
    return CaptionStyle.from_preset(preset, margin_v=max(40, safe_zone_bottom))


def _escape_ass(text: str) -> str:
    return str(text).strip().replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _emphasize(text: str, emphasis_words: tuple[str, ...], emphasis_colour: str) -> str:
    """Wrap emphasis words in ASS colour override tags (word highlighting)."""
    if not emphasis_words:
        return text
    result = text
    for word in emphasis_words:
        word = word.strip()
        if not word:
            continue
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        result = pattern.sub(lambda m: f"{{\\c{emphasis_colour}}}{m.group(0)}{{\\r}}", result)
    return result


def build_ass(
    segments: list[dict],
    style: CaptionStyle,
    emphasis_words: tuple[str, ...] = (),
    emphasis_colour: str = "&H0000FFFF",
    resolution: tuple[int, int] = (1080, 1920),
) -> str:
    """Render caption segments into complete ASS content."""
    if style.margin_v < 0 or style.fontsize <= 0:
        raise ValueError("Caption style values must be non-negative.")
    width, height = resolution
    box_style = "3" if style.box else "1"  # BorderStyle 3 = opaque box behind text
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: GenForge,{style.fontname},{style.fontsize},{style.primary},{style.primary},{style.outline_c},{style.back},{style.bold},0,0,0,100,100,0,0,{box_style},{style.outline},{style.shadow},{style.alignment},60,60,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for segment in segments:
        start = float(segment.get("start", 0.0))
        end = max(float(segment.get("end", start)), start + 0.01)
        text = _escape_ass(segment.get("text", ""))
        if not text:
            continue
        text = _emphasize(text, tuple(emphasis_words), emphasis_colour)
        lines.append(
            f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},GenForge,,0,0,0,,{text}\n"
        )
    return "".join(lines)


def write_styled_ass(
    segments: list[dict],
    ass_path: str,
    preset: str = "Classic",
    emphasis_words: tuple[str, ...] = (),
    safe_zone_bottom: int | None = None,
) -> str:
    """Write styled captions to disk; timing stays exactly as supplied."""
    if not segments:
        raise ValueError("Caption segments are required.")
    style = (style_for_platform_safe_zone(preset, safe_zone_bottom)
             if safe_zone_bottom is not None else CaptionStyle.from_preset(preset))
    content = build_ass(segments, style, emphasis_words=emphasis_words)
    os.makedirs(os.path.dirname(ass_path) or ".", exist_ok=True)
    with open(ass_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return ass_path


def shift_segments(segments: list[dict], offset: float) -> list[dict]:
    """Timing adjustment helper: shift all captions by offset seconds."""
    shifted = []
    for segment in segments:
        start = float(segment.get("start", 0.0)) + offset
        end = float(segment.get("end", start)) + offset
        if start < 0:
            raise ValueError("Shift would move captions before the timeline start.")
        shifted.append({**segment, "start": round(start, 3), "end": round(end, 3)})
    return shifted


def subtitles_filter_arg(ass_path: str) -> str:
    """Escape an .ass path for the FFmpeg subtitles filter.

    Windows drive letters contain ':' which the filter parses as an option
    separator, so the path must be forward-slashed, colon-escaped and quoted
    (same escaping used by the existing SRT burn-in in advanced_editing).
    """
    escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
    return f"'{escaped}'"
