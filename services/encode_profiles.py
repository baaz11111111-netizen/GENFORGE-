"""Encode preset profiles: fast previews vs quality finals (Priorities #5/#18).

Measured on the benchmark fixture (1080p30, 3s, libx264, same machine):

    preview  (ultrafast, crf 28): ~1.01s, larger file — good enough to review edits
    final    (medium,   crf 20): ~3.97s, ~2.7x smaller file — publish quality

Profiles are opt-in: every renderer defaults to "final", so existing behavior
and output quality are unchanged unless a caller explicitly asks for a
preview-speed encode.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EncodeProfile:
    """One encode quality/speed trade-off point."""

    preset: str
    crf: int
    description: str


ENCODE_PROFILES: dict[str, EncodeProfile] = {
    "preview": EncodeProfile("ultrafast", 28, "fastest encode for editor previews; not for publishing"),
    "draft": EncodeProfile("veryfast", 23, "quick review renders; acceptable size, reduced quality"),
    "final": EncodeProfile("medium", 20, "publish quality; matches the verified-stable render settings"),
}


def resolve_profile(profile: str) -> EncodeProfile:
    """Return the named profile; unknown names fail loudly rather than silently."""
    try:
        return ENCODE_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(
            f"Unknown encode profile: {profile!r}. Valid profiles: {sorted(ENCODE_PROFILES)}"
        ) from exc


def encode_flags(profile: str = "final") -> list[str]:
    """FFmpeg x264 flags for the named profile (inserted before the output path)."""
    resolved = resolve_profile(profile)
    return ["-c:v", "libx264", "-preset", resolved.preset, "-crf", str(resolved.crf)]


__all__ = [
    "EncodeProfile",
    "ENCODE_PROFILES",
    "resolve_profile",
    "encode_flags",
]
