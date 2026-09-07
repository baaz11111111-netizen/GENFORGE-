"""Campaign integration + batch publishing (§20, §21).

Batch publishing ALWAYS shows a preview first: every candidate gets a
READY / WARNING / ERROR verdict from the same validation used for single
jobs, and ERROR items can never enter the queue. Campaign assets are pulled
from the real campaign dict / project versions — never from static JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.publishing.manager import PublishingManager
from services.publishing.models import PublishingJob
from services.publishing.validation import validate_asset, validate_metadata, validate_schedule

VERDICTS = ("READY", "WARNING", "ERROR")


@dataclass
class BatchItem:
    platform: str
    asset_path: str
    verdict: str
    reasons: list[str] = field(default_factory=list)
    project_id: str = ""
    version_id: str = ""
    scheduled_at: str = ""
    job: PublishingJob | None = None


def _classify(platform: str, asset_path: str, scheduled_at: str = "",
              title: str = "", description: str = "", hashtags: list | None = None) -> tuple[str, list[str]]:
    """Map validation reports onto the READY / WARNING / ERROR verdict (§21)."""
    reasons: list[str] = []
    asset = validate_asset(asset_path, platform)
    metadata = validate_metadata({"title": title, "description": description, "hashtags": hashtags or []}, platform)
    schedule = validate_schedule(scheduled_at, platform)
    problems = asset.problems + metadata.problems + schedule.problems
    warnings = asset.warnings + metadata.warnings
    if asset.requires_adaptation:
        reasons.append("Asset requires adaptation before upload.")
    reasons.extend(problems)
    reasons.extend(warnings)
    if problems or asset.requires_adaptation:
        return "ERROR", reasons
    if warnings:
        return "WARNING", reasons
    return "READY", reasons


def build_batch_item(platform: str, asset_path: str, project=None, scheduled_at: str = "",
                     title: str = "", description: str = "", hashtags: list | None = None) -> BatchItem:
    """One preview row. Pass the ProjectState to version-pin the future job."""
    verdict, reasons = _classify(platform, asset_path, scheduled_at, title, description, hashtags)
    project_id = getattr(project, "project_id", "") if project is not None else ""
    version_id = ""
    if project is not None and getattr(project, "outputs", None):
        rendered = [v for v in project.outputs if v.status == "rendered"]
        if rendered:
            version_id = rendered[-1].version_id
    return BatchItem(platform=platform, asset_path=asset_path, verdict=verdict, reasons=reasons,
                     project_id=project_id, version_id=version_id, scheduled_at=scheduled_at)


def pairs_for_campaign(campaign: dict, platforms: list[str]) -> list[tuple[str, str]]:
    """§20: pull REAL asset paths out of a campaign result (never static JSON)."""
    assets = (campaign or {}).get("assets", {}) or {}
    video = assets.get("promo_video") or ""
    image = assets.get("hero_image") or ""
    pairs = []
    for platform in platforms:
        if video and video != "Bundle (Video + Image)":
            pairs.append((platform, video))
        elif image:
            pairs.append((platform, image))  # validation will judge fitness honestly
    return pairs


def pairs_for_project(project, platforms: list[str]) -> list[tuple[str, str]]:
    """Latest rendered project version feeds every requested platform."""
    rendered = [v for v in getattr(project, "outputs", []) if v.status == "rendered"]
    if not rendered:
        return []
    latest = rendered[-1].output_path
    return [(platform, latest) for platform in platforms]


def build_batch(pairs: list[tuple[str, str]], project=None, scheduled_at: str = "",
                title: str = "", description: str = "", hashtags: list | None = None) -> list[BatchItem]:
    return [build_batch_item(platform, asset, project=project, scheduled_at=scheduled_at,
                             title=title, description=description, hashtags=hashtags)
            for platform, asset in pairs]


def queue_batch(manager: PublishingManager, items: list[BatchItem], *,
                confirmed: bool = False, title: str = "", description: str = "",
                hashtags: list | None = None) -> dict:
    """Queue non-ERROR items. Requires explicit confirmation (§30/§31)."""
    if not confirmed:
        raise ValueError("Batch queueing requires explicit user confirmation.")
    summary = {"READY": 0, "WARNING": 0, "ERROR": 0, "queued": 0, "rejected": 0}
    for item in items:
        summary[item.verdict] = summary.get(item.verdict, 0) + 1
        if item.verdict == "ERROR":
            summary["rejected"] += 1
            continue
        job = PublishingJob(platform=item.platform, asset_path=item.asset_path,
                            project_id=item.project_id, version_id=item.version_id,
                            scheduled_at=item.scheduled_at, title=title,
                            description=description, hashtags=list(hashtags or []))
        entry = manager.queue_job(job)
        item.job = job
        if entry["state"] == "failed":
            summary["rejected"] += 1
        else:
            summary["queued"] += 1
    return summary


__all__ = ["VERDICTS", "BatchItem", "build_batch_item", "pairs_for_campaign",
           "pairs_for_project", "build_batch", "queue_batch"]
