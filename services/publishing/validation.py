"""Pre-publish validation (§10, §29): never upload known-invalid media.

Validation runs BEFORE any upload attempt. It is honest and layered:

* ``problems``  → hard failures: the job must NOT be queued for upload.
* ``warnings``  → advisory notes that do not block publishing.
* ``requires_adaptation`` → the existing export pipeline can fix the asset
  (wrong aspect/codec/container), so the UI offers a re-export instead of
  letting a doomed upload burn quota.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from services.media_probe import probe_media
from services.platform_profiles import PLATFORM_PROFILES
from services.publishing.capabilities import capabilities_for
from services.publishing.models import ensure_future, parse_scheduled_at

# Official per-platform metadata ceilings (verified against official docs §2).
# ``None`` = no officially documented limit.
METADATA_LIMITS: dict[str, dict[str, int | None]] = {
    "YouTube": {"title": 100, "description": 5000, "hashtags": 15},
    "YouTube Shorts": {"title": 100, "description": 5000, "hashtags": 15},
    "Instagram Reels": {"title": None, "description": 2200, "hashtags": 30},
    "Square Feed": {"title": None, "description": 2200, "hashtags": 30},
    "TikTok": {"title": 2200, "description": 2200, "hashtags": None},
    "LinkedIn": {"title": 200, "description": 3000, "hashtags": None},
    "Webhook": {"title": None, "description": None, "hashtags": None},
}

# Containers/codecs every target platform accepts for direct upload.
ACCEPTED_CONTAINERS = {".mp4", ".mov"}
ACCEPTED_VIDEO_CODECS = {"h264", "hevc", "vp9"}

_HASHTAG_RE = re.compile(r"#\w+")


@dataclass
class ValidationReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_adaptation: bool = False
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {"ok": self.ok, "problems": list(self.problems),
                "warnings": list(self.warnings),
                "requires_adaptation": self.requires_adaptation,
                "recommendation": self.recommendation}


def _expected_ratio(platform: str) -> float | None:
    profile = PLATFORM_PROFILES.get(platform)
    if profile is None:
        return None
    num, den = profile.ratio.split(":")
    return int(num) / int(den)


def validate_asset(asset_path: str, platform: str) -> ValidationReport:
    """§10: check the file against platform requirements BEFORE upload."""
    report = ValidationReport(ok=True)
    if not asset_path:
        report.ok = False
        report.problems.append("No asset selected.")
        return report
    if asset_path.startswith(("http://", "https://")):
        # Hosted assets (e.g. Instagram's required video_url) cannot be probed
        # locally; the platform performs the final media validation.
        report.warnings.append("Remote asset URL — local probing skipped; platform will validate.")
        return report
    path = Path(asset_path)
    if not path.is_file():
        report.ok = False
        report.problems.append(f"Asset not found: {asset_path}")
        return report
    if path.suffix.lower() not in ACCEPTED_CONTAINERS:
        report.ok = False
        report.requires_adaptation = True
        report.problems.append(
            f"Container {path.suffix or '(none)'} is not accepted; re-export as MP4.")
        return report
    try:
        meta = probe_media(path)
    except (OSError, RuntimeError, ValueError) as exc:
        report.ok = False
        report.problems.append(f"Asset could not be probed: {exc}")
        return report

    if meta.width is None or meta.height is None or meta.duration <= 0:
        report.ok = False
        report.problems.append("Asset has no decodable video stream.")
        return report
    if meta.video_codec and meta.video_codec not in ACCEPTED_VIDEO_CODECS:
        report.ok = False
        report.requires_adaptation = True
        report.problems.append(
            f"Video codec {meta.video_codec!r} is not upload-safe; re-encode to H.264.")

    profile = PLATFORM_PROFILES.get(platform)
    if profile is None:
        report.warnings.append(
            f"No platform profile for {platform!r}; only basic checks were applied.")
        return report

    # Duration limits come from the shared platform profile (documented values).
    if meta.duration > profile.max_duration:
        report.ok = False
        report.requires_adaptation = True
        report.problems.append(
            f"Duration {meta.duration:.1f}s exceeds the {profile.max_duration:.0f}s "
            f"{platform} limit; trim the clip first.")
    if profile.min_duration and meta.duration < profile.min_duration:
        report.ok = False
        report.problems.append(
            f"Duration {meta.duration:.1f}s is below the {profile.min_duration:.0f}s "
            f"{platform} minimum.")

    # Aspect must match the profile within a small tolerance.
    expected = _expected_ratio(platform)
    actual = meta.width / meta.height
    if expected and abs(actual - expected) / expected > 0.02:
        report.ok = False
        report.requires_adaptation = True
        report.problems.append(
            f"Aspect {meta.width}x{meta.height} does not match the {profile.ratio} "
            f"{platform} profile; re-export via the platform export pipeline.")

    if meta.width < profile.width or meta.height < profile.height:
        report.warnings.append(
            f"Resolution {meta.width}x{meta.height} is below the recommended "
            f"{profile.width}x{profile.height}; quality may suffer.")
    return report


def _count_hashtags(payload: dict) -> int:
    explicit = payload.get("hashtags") or []
    if isinstance(explicit, str):
        explicit = [t.strip() for t in explicit.split(",") if t.strip()]
    text = " ".join(filter(None, [payload.get("title", ""), payload.get("description", ""),
                                  payload.get("caption", "")]))
    return len(explicit) + len(_HASHTAG_RE.findall(text))


def validate_metadata(payload: dict, platform: str) -> ValidationReport:
    """§11: metadata is user-editable, but must respect platform ceilings."""
    report = ValidationReport(ok=True)
    limits = METADATA_LIMITS.get(platform)
    if limits is None:
        report.problems.append(f"Unknown platform: {platform!r}")
        report.ok = False
        return report
    title = payload.get("title") or ""
    description = payload.get("description") or payload.get("caption") or ""
    checks = (("title", title), ("description", description))
    for name, value in checks:
        ceiling = limits.get(name)
        if ceiling and len(value) > ceiling:
            report.ok = False
            report.problems.append(
                f"{name.title()} is {len(value)} chars; {platform} allows {ceiling}.")
    ceiling = limits.get("hashtags")
    total = _count_hashtags(payload)
    if ceiling and total > ceiling:
        report.warnings.append(
            f"{total} hashtags exceed the {platform} guidance of {ceiling}; "
            "excess hashtags may be ignored by the platform.")
    if not title and not description and platform != "Webhook":
        report.warnings.append("No title or caption provided; post will publish without text.")
    return report


def validate_schedule(scheduled_at: str, platform: str) -> ValidationReport:
    """§13: timezone-aware, future, and only where officially supported."""
    report = ValidationReport(ok=True)
    if not scheduled_at:
        return report  # immediate publish — nothing to validate
    try:
        moment = parse_scheduled_at(scheduled_at)
        ensure_future(moment)
    except ValueError as exc:
        report.ok = False
        report.problems.append(str(exc))
        return report
    if not capabilities_for(platform).scheduling:
        report.ok = False
        report.problems.append(f"Platform scheduling unsupported for {platform}.")
    return report


def pre_publish_checklist(job) -> list[dict]:
    """§29 checklist shown to the user before anything is queued."""
    asset = validate_asset(job.asset_path, job.platform)
    metadata = validate_metadata(
        {"title": job.title, "description": job.description,
         "caption": job.caption, "hashtags": job.hashtags}, job.platform)
    schedule = validate_schedule(job.scheduled_at, job.platform)
    items = [
        {"label": "Asset exists and is upload-safe", "passed": asset.ok,
         "detail": "; ".join(asset.problems) or "OK",
         "requires_adaptation": asset.requires_adaptation},
        {"label": "Metadata respects platform limits", "passed": metadata.ok,
         "detail": "; ".join(metadata.problems) or "OK"},
        {"label": "Schedule valid (if set)", "passed": schedule.ok,
         "detail": "; ".join(schedule.problems) or "OK"},
    ]
    return items


__all__ = [
    "METADATA_LIMITS", "ACCEPTED_CONTAINERS", "ACCEPTED_VIDEO_CODECS",
    "ValidationReport", "validate_asset", "validate_metadata",
    "validate_schedule", "pre_publish_checklist",
]
