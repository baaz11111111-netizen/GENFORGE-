"""Shared platform adaptation profiles and export entry point."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from advanced_editing import resize_video_aspect
from services.media_probe import probe_media as _probe_media


def _duration(path: str) -> float:
    """Resolve media duration through the shared probe cache instead of the
    private production_features._duration helper."""
    return _probe_media(str(path)).duration


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    ratio: str
    width: int
    height: int
    max_duration: float
    caption_position: str
    safe_zone: tuple[int, int, int, int]
    thumbnail: tuple[int, int] = (1280, 720)
    text_placement: str = "center"
    min_duration: float = 0.0


PLATFORM_PROFILES = {
    "TikTok": PlatformProfile("TikTok", "9:16", 1080, 1920, 600, "bottom", (80, 220, 80, 320),
                              thumbnail=(1080, 1920), text_placement="upper_third", min_duration=1.0),
    "Instagram Reels": PlatformProfile("Instagram Reels", "9:16", 1080, 1920, 90, "bottom", (80, 220, 80, 320),
                                       thumbnail=(1080, 1920), text_placement="upper_third", min_duration=1.0),
    "YouTube Shorts": PlatformProfile("YouTube Shorts", "9:16", 1080, 1920, 60, "bottom", (80, 220, 80, 320),
                                      thumbnail=(1080, 1920), text_placement="upper_third", min_duration=1.0),
    "YouTube": PlatformProfile("YouTube", "16:9", 1920, 1080, 43200, "bottom", (120, 80, 120, 80),
                               thumbnail=(1280, 720), text_placement="center", min_duration=1.0),
    "Square Feed": PlatformProfile("Square Feed", "1:1", 1080, 1080, 120, "bottom", (80, 80, 80, 160),
                                   thumbnail=(1080, 1080), text_placement="center", min_duration=1.0),
}


def export_for_platform(input_path: str, output_path: str, platform: str) -> str:
    """Adapt media through the shared renderer using a named platform profile."""
    try:
        profile = PLATFORM_PROFILES[platform]
    except KeyError as exc:
        raise ValueError(f"Unknown platform profile: {platform}") from exc
    if not Path(input_path).is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}")
    return resize_video_aspect(input_path, output_path, profile.ratio)


def caption_safe_margin(platform: str) -> int:
    """Bottom margin (px) keeping captions out of the platform UI safe zone."""
    try:
        profile = PLATFORM_PROFILES[platform]
    except KeyError as exc:
        raise ValueError(f"Unknown platform profile: {platform}") from exc
    return profile.safe_zone[3]


def duration_advisory(input_path: str, platform: str) -> dict:
    """Honest duration fit check against the profile limits."""
    try:
        profile = PLATFORM_PROFILES[platform]
    except KeyError as exc:
        raise ValueError(f"Unknown platform profile: {platform}") from exc
    duration = _duration(input_path)
    problems = []
    if duration > profile.max_duration:
        problems.append(f"Duration {duration:.1f}s exceeds the {profile.max_duration:.0f}s {platform} limit.")
    if profile.min_duration and duration < profile.min_duration:
        problems.append(f"Duration {duration:.1f}s is below the {profile.min_duration:.0f}s {platform} minimum.")
    return {"platform": platform, "duration": round(duration, 3), "fits": not problems, "problems": problems}


def export_master_suite(input_path: str, output_dir: str, platforms: list[str] | None = None) -> dict:
    """MASTER VIDEO → one adapted export per platform via the shared renderer.

    Per-platform failures are reported honestly instead of aborting the suite.
    """
    if not Path(input_path).is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}")
    targets = platforms or list(PLATFORM_PROFILES)
    for platform in targets:
        if platform not in PLATFORM_PROFILES:
            raise ValueError(f"Unknown platform profile: {platform}")
    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_path))[0]
    outputs: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    advisories: dict[str, dict] = {}
    for platform in targets:
        profile = PLATFORM_PROFILES[platform]
        destination = os.path.join(output_dir, f"{base}_{profile.name.replace(' ', '_')}_{profile.ratio.replace(':', 'x')}.mp4")
        advisories[platform] = duration_advisory(input_path, platform)
        try:
            outputs[platform] = export_for_platform(input_path, destination, platform)
        except (OSError, RuntimeError, ValueError) as exc:
            outputs[platform] = None
            errors[platform] = str(exc)
    return {"outputs": outputs, "errors": errors, "advisories": advisories}
