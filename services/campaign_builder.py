"""Phase 10 — Campaign builder: a campaign workspace on top of existing services.

Composes the real GENFORGE pipeline (Script Studio, Highlights, Thumbnail
Studio, platform profiles) instead of re-implementing any of it. Strategy
artefacts (pillars, calendar, hashtags, CTAs) are deterministic and clearly
labelled; generated assets only ever reference files that actually exist.
Missing dependencies produce honest "unavailable" entries — never fake assets.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from services.platform_profiles import PLATFORM_PROFILES, export_for_platform
from services.script_studio import ScriptRequest, generate_script, save_script_version

GOALS = ("awareness", "engagement", "education", "conversion", "community")

_GOAL_KEYWORDS = {
    "awareness": ("aware", "reach", "brand", "discover", "visibility", "growth"),
    "engagement": ("engage", "engagement", "interact", "comments", "shares", "viral"),
    "education": ("educat", "teach", "learn", "tutorial", "how-to", "how to", "explain"),
    "conversion": ("convert", "conversion", "sales", "sell", "leads", "buy", "purchase"),
    "community": ("community", "loyal", "fans", "audience building", "membership"),
}

_GOAL_PILLARS = {
    "awareness": (
        ("Origin Story", "Why {brand} exists and the problem {topic} solves"),
        ("Behind the Scenes", "How {brand} builds and ships {topic}"),
        ("Bold Claim", "The single biggest misconception about {topic}"),
    ),
    "engagement": (
        ("Hot Take", "A polarising opinion about {topic} that starts conversations"),
        ("Challenge", "Invite the audience to try {topic} and react"),
        ("Poll & Reply", "Ask the audience what they want from {brand} next"),
    ),
    "education": (
        ("Quick Tip", "One actionable {topic} tip in under a minute"),
        ("Step by Step", "A compact walkthrough of {topic} from start to finish"),
        ("Myth vs Fact", "Correct a common mistake people make with {topic}"),
    ),
    "conversion": (
        ("Problem Agitate Solve", "Show the pain {topic} removes and prove it"),
        ("Social Proof", "Real results and testimonials around {topic}"),
        ("Offer Spotlight", "What {brand} is offering right now and why act today"),
    ),
    "community": (
        ("Member Spotlight", "Celebrate someone using {topic}"),
        ("Inside Look", "Exclusive updates from {brand} for insiders"),
        ("Ask Me Anything", "Direct Q&A about {topic} with the team"),
    ),
}

_GOAL_CTAS = {
    "awareness": "Follow for more and share with someone who needs this.",
    "engagement": "Comment your take below and tag a friend.",
    "education": "Save this for later and follow for the next tip.",
    "conversion": "Tap the link in bio and start today.",
    "community": "Join the community and tell us what to build next.",
}

# Map platform profile names to Script Studio platform vocabulary.
_SCRIPT_PLATFORM_MAP = {
    "TikTok": "TikTok",
    "Instagram Reels": "Instagram Reels",
    "YouTube Shorts": "YouTube Shorts",
    "YouTube": "YouTube",
    "Square Feed": "Square/Social",
}


class CampaignBrief(BaseModel):
    """Validated inputs for one campaign workspace."""

    brand: str
    goal: str
    audience: str
    platforms: list[str]
    posts_per_week: int = Field(default=3, ge=1, le=30)
    topic: str
    horizon_weeks: int = Field(default=4, ge=1, le=12)

    @field_validator("brand", "goal", "audience", "topic")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Brand, goal, audience and topic are required.")
        return value.strip()

    @field_validator("platforms")
    @classmethod
    def _known_platforms(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one platform is required.")
        cleaned: list[str] = []
        for platform in value:
            if platform not in PLATFORM_PROFILES:
                raise ValueError(
                    f"Unknown platform '{platform}'. Available: {', '.join(PLATFORM_PROFILES)}"
                )
            if platform not in cleaned:
                cleaned.append(platform)
        return cleaned


def classify_goal(goal: str) -> str:
    """Deterministic goal classification; falls back to 'awareness'."""
    lowered = (goal or "").lower()
    for name, keywords in _GOAL_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return name
    return "awareness"


def build_pillars(brief: CampaignBrief) -> list[dict[str, str]]:
    """Three deterministic content pillars for the classified goal."""
    classified = classify_goal(brief.goal)
    pillars = []
    for name, template in _GOAL_PILLARS[classified]:
        pillars.append({
            "name": name,
            "angle": template.format(brand=brief.brand, topic=brief.topic),
            "goal": classified,
        })
    return pillars


def build_calendar(
    brief: CampaignBrief,
    pillars: list[dict[str, str]],
    start_date: date | None = None,
) -> list[dict[str, Any]]:
    """Deterministic posting calendar: platforms and pillars rotate round-robin."""
    if not pillars:
        raise ValueError("Content pillars are required to build a calendar.")
    first = start_date or date.today()
    slots = brief.posts_per_week * brief.horizon_weeks
    per_week_gap = 7.0 / brief.posts_per_week
    calendar = []
    for index in range(slots):
        platform = brief.platforms[index % len(brief.platforms)]
        pillar = pillars[index % len(pillars)]
        slot_date = first + timedelta(days=round(index * per_week_gap))
        calendar.append({
            "slot_index": index,
            "date": slot_date.isoformat(),
            "platform": platform,
            "pillar": pillar["name"],
            "content_topic": f"{pillar['name']}: {brief.topic}",
            "script_ref": None,
            "status": "planned",
        })
    return calendar


def _hashtag_token(text: str) -> str:
    """Turn free text into one CamelCase-safe hashtag token (may be empty)."""
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    return "".join(word if word[0].isupper() else word.capitalize() for word in words)


def build_hashtags(brief: CampaignBrief, limit: int = 10) -> list[str]:
    """Deterministic hashtag set derived from the brief — never fabricated AI output."""
    if limit < 3:
        raise ValueError("limit must be at least 3.")
    tokens: list[str] = []
    for source in (brief.brand, brief.topic, classify_goal(brief.goal), brief.audience):
        token = _hashtag_token(source)
        if token and token not in tokens:
            tokens.append(token)
    for platform in brief.platforms:
        token = _hashtag_token(platform)
        if token and token not in tokens:
            tokens.append(token)
    return [f"#{token}" for token in tokens[:limit]]


def build_cta(brief: CampaignBrief) -> str:
    """Deterministic goal-based call to action."""
    return _GOAL_CTAS[classify_goal(brief.goal)]


def _caption_text(brief: CampaignBrief, entry: dict[str, Any], hashtags: list[str], cta: str) -> str:
    tag_block = " ".join(hashtags[:5])
    return f"{entry['content_topic']} — {brief.brand}. {cta} {tag_block}".strip()


def _default_clip_builder(video_path: str, output_dir: str, platforms: list[str]) -> dict[str, Any]:
    """Real pipeline: highlight detection → canonical trim → platform variants."""
    from services.highlights import detect_highlights, render_highlight
    try:
        highlights = detect_highlights(video_path, count=1)
        master = render_highlight(highlights[0], output_dir)
        versions: dict[str, str] = {"master": master}
        version_errors: dict[str, str] = {}
        for platform in platforms:
            destination = os.path.join(
                output_dir, f"campaign_clip_{platform.replace(' ', '_').lower()}.mp4"
            )
            try:
                versions[platform] = export_for_platform(master, destination, platform)
            except (OSError, RuntimeError, ValueError) as exc:
                version_errors[platform] = str(exc)
        return {"status": "rendered", "path": master, "platform_versions": versions,
                "version_errors": version_errors,
                "highlight": {"start": highlights[0].start, "end": highlights[0].end,
                              "score": highlights[0].score, "reason": highlights[0].reason}}
    except Exception as exc:
        return {"status": "unavailable", "path": None, "message": f"Clip build unavailable: {exc}"}


def _default_thumbnail_builder(video_path: str, output_dir: str, titles: list[str]) -> dict[str, Any]:
    """Real pipeline: Thumbnail Studio variants (honestly unavailable without OpenCV)."""
    from services.thumbnail_studio import generate_thumbnail_variants
    try:
        variants = generate_thumbnail_variants(video_path, output_dir, titles=titles)
        return {"status": "rendered", "variants": variants}
    except Exception as exc:
        return {"status": "unavailable", "variants": [], "message": f"Thumbnail build unavailable: {exc}"}


def build_campaign(
    project,
    brief: CampaignBrief,
    video_source: str | None = None,
    output_dir: str | None = None,
    start_date: date | None = None,
    script_generator: Callable[[str], dict] | None = None,
    clip_builder: Callable[[str, str, list[str]], dict] | None = None,
    thumbnail_builder: Callable[[str, str, list[str]], dict] | None = None,
    webhook_url: str = "",
) -> dict[str, Any]:
    """Build the campaign workspace and store it on the project.

    Scripts flow through Script Studio, clips through the Highlights pipeline,
    thumbnails through Thumbnail Studio, and platform variants through the
    shared renderer. Every stored asset references a real generated file; any
    unavailable dependency is recorded honestly instead of faked.
    """
    workspace_dir = output_dir or os.path.join("outputs", project.project_id, "campaign")
    os.makedirs(workspace_dir, exist_ok=True)

    pillars = build_pillars(brief)
    calendar = build_calendar(brief, pillars, start_date=start_date)
    hashtags = build_hashtags(brief)
    cta = build_cta(brief)

    # --- Scripts: one per pillar, stored as real project script versions ---
    script_assets: list[dict[str, Any]] = []
    script_ref_by_pillar: dict[str, str] = {}
    for pillar in pillars:
        script_platform = _SCRIPT_PLATFORM_MAP.get(brief.platforms[0], "YouTube")
        request = ScriptRequest(
            topic=f"{pillar['angle']} for {brief.brand}",
            audience=brief.audience,
            platform=script_platform,
            goal=brief.goal,
        )
        result = generate_script(request, generator=script_generator)
        if result["status"] == "generated":
            version = save_script_version(project, result["script"], label=f"Campaign: {pillar['name']}")
            script_assets.append({"pillar": pillar["name"], "status": "generated",
                                  "script_id": version["script_id"]})
            script_ref_by_pillar[pillar["name"]] = version["script_id"]
        else:
            script_assets.append({"pillar": pillar["name"], "status": "unavailable",
                                  "script_id": None, "message": result["message"]})
    for entry in calendar:
        entry["script_ref"] = script_ref_by_pillar.get(entry["pillar"])

    # --- Short clip + platform variants (only when a real source exists) ---
    clip_assets: list[dict[str, Any]] = []
    produce_clip = clip_builder or _default_clip_builder
    if video_source and os.path.isfile(video_source):
        project.add_source(video_source)
        clip_result = produce_clip(video_source, workspace_dir, brief.platforms)
        if clip_result["status"] == "rendered" and clip_result.get("path"):
            project.add_version(clip_result["path"],
                                analytics={"campaign": True, "highlight": clip_result.get("highlight")})
        clip_assets.append(clip_result)
    else:
        clip_assets.append({"status": "unavailable", "path": None,
                            "message": "No campaign source video supplied; no clip was rendered."})

    # --- Captions: deterministic copy per calendar slot (referencing real scripts) ---
    captions = []
    for entry in calendar:
        captions.append({
            "slot_index": entry["slot_index"],
            "platform": entry["platform"],
            "text": _caption_text(brief, entry, hashtags, cta),
            "hashtags": hashtags[:5],
            "cta": cta,
            "script_ref": entry["script_ref"],
        })

    # --- Thumbnails: only from the actually rendered clip ---
    thumbnail_assets: list[dict[str, Any]] = []
    produce_thumbs = thumbnail_builder or _default_thumbnail_builder
    rendered_clip = next((c for c in clip_assets if c.get("status") == "rendered" and c.get("path")), None)
    if rendered_clip:
        thumb_result = produce_thumbs(rendered_clip["path"], workspace_dir, [brief.topic])
        if thumb_result["status"] == "rendered" and thumb_result.get("variants"):
            from services.thumbnail_studio import add_thumbnails_to_project
            stored = add_thumbnails_to_project(project, thumb_result["variants"])
            thumb_result = dict(thumb_result, thumbnail_ids=[entry["thumbnail_id"] for entry in stored[-len(thumb_result["variants"]):]])
        thumbnail_assets.append(thumb_result)
    else:
        thumbnail_assets.append({"status": "unavailable", "variants": [],
                                 "message": "Thumbnails require a rendered campaign clip."})

    # --- Honest overall status ---
    generated_scripts = sum(1 for item in script_assets if item["status"] == "generated")
    rendered_groups = bool(rendered_clip)
    ready = generated_scripts == len(pillars) and rendered_groups and \
        all(item.get("status") == "rendered" for item in thumbnail_assets)
    anything = generated_scripts > 0 or rendered_groups
    status = "ready" if ready else ("partial" if anything else "unavailable")

    campaign = {
        "campaign_id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brief": brief.model_dump(),
        "pillars": pillars,
        "calendar": calendar,
        "hashtags": hashtags,
        "cta": cta,
        "assets": {
            "scripts": script_assets,
            "clips": clip_assets,
            "captions": captions,
            "thumbnails": thumbnail_assets,
        },
        "status": status,
    }

    # --- Optional dispatch through the existing n8n architecture ---
    if webhook_url and webhook_url.strip():
        from campaign_agent import trigger_n8n_webhook
        payload = {
            "name": f"Campaign: {brief.brand} — {brief.topic}",
            "platforms": brief.platforms,
            "calendar_size": len(calendar),
            "assets": {
                "clip": rendered_clip.get("path") if rendered_clip else None,
                "scripts": [item["script_id"] for item in script_assets if item["script_id"]],
            },
        }
        try:
            campaign["webhook_dispatched"] = trigger_n8n_webhook(webhook_url.strip(), payload)
        except ValueError as exc:
            campaign["webhook_dispatched"] = False
            campaign["webhook_error"] = str(exc)

    project.campaign = campaign
    return campaign


__all__ = [
    "GOALS",
    "CampaignBrief",
    "classify_goal",
    "build_pillars",
    "build_calendar",
    "build_hashtags",
    "build_cta",
    "build_campaign",
]
