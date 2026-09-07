"""Platform capability matrix (§5).

Truthful per-platform capability flags derived from the CURRENT official
APIs. The UI uses this to hide unsupported controls; the manager uses it to
reject unsupported operations before any network call.

Sources verified against official documentation:
* YouTube Data API v3 — videos.insert (resumable), publishAt scheduling,
  thumbnails.set, captions.insert, processingStatus in the status part.
* Instagram Graph API (Meta) — container → media_publish two-step flow for
  Reels; NO official scheduling endpoint and NO caption/thumbnail upload.
* TikTok Content Posting API — /v2/post/publish/video/init/ direct post with
  publish_time scheduling and /v2/post/publish/status/fetch/ status polling;
  no thumbnail or caption-file upload.
* LinkedIn Posts API — video initializeUpload + Posts, scheduledPublishTime
  supported; no caption-file or thumbnail upload through the public API.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformCapabilities:
    """What one platform officially supports through its current API."""

    platform: str
    video_upload: bool
    image_upload: bool
    short_form: bool
    scheduling: bool
    immediate_publish: bool
    captions: bool
    title: bool
    description: bool
    hashtags: bool
    thumbnail: bool
    cover_image: bool
    privacy: bool
    comments_settings: bool
    processing_status: bool
    publication_status: bool
    metrics: bool = False
    notes: str = ""

    def as_dict(self) -> dict[str, bool | str]:
        return {key: getattr(self, key) for key in (
            "video_upload", "image_upload", "short_form", "scheduling",
            "immediate_publish", "captions", "title", "description", "hashtags",
            "thumbnail", "cover_image", "privacy", "comments_settings",
            "processing_status", "publication_status", "metrics",
        )}


PLATFORM_CAPABILITIES: dict[str, PlatformCapabilities] = {
    "YouTube": PlatformCapabilities(
        platform="YouTube", video_upload=True, image_upload=False, short_form=True,
        scheduling=True, immediate_publish=True, captions=True, title=True,
        description=True, hashtags=True, thumbnail=True, cover_image=False,
        privacy=True, comments_settings=True, processing_status=True,
        publication_status=True, metrics=True,
        notes="YouTube Data API v3: videos.insert + publishAt (schedule requires privacyStatus=private).",
    ),
    "YouTube Shorts": PlatformCapabilities(
        platform="YouTube Shorts", video_upload=True, image_upload=False, short_form=True,
        scheduling=True, immediate_publish=True, captions=True, title=True,
        description=True, hashtags=True, thumbnail=True, cover_image=False,
        privacy=True, comments_settings=True, processing_status=True,
        publication_status=True, metrics=True,
        notes="Same API as YouTube; Shorts detection is by duration/aspect.",
    ),
    "Instagram Reels": PlatformCapabilities(
        platform="Instagram Reels", video_upload=True, image_upload=False, short_form=True,
        scheduling=False, immediate_publish=True, captions=False, title=False,
        description=True, hashtags=True, thumbnail=False, cover_image=False,
        privacy=False, comments_settings=False, processing_status=True,
        publication_status=True, metrics=True,
        notes="Instagram Graph API: container → media_publish. No official scheduling, caption-file, or thumbnail API.",
    ),
    "Square Feed": PlatformCapabilities(
        platform="Square Feed", video_upload=True, image_upload=True, short_form=False,
        scheduling=False, immediate_publish=True, captions=False, title=False,
        description=True, hashtags=True, thumbnail=False, cover_image=False,
        privacy=False, comments_settings=False, processing_status=True,
        publication_status=True, metrics=True,
        notes="Instagram Graph API image/video containers; same limitations as Reels.",
    ),
    "TikTok": PlatformCapabilities(
        platform="TikTok", video_upload=True, image_upload=False, short_form=True,
        scheduling=True, immediate_publish=True, captions=False, title=True,
        description=False, hashtags=True, thumbnail=False, cover_image=False,
        privacy=True, comments_settings=True, processing_status=True,
        publication_status=True, metrics=False,
        notes="Content Posting API direct post; publish_time scheduling (+15min..+10 days); SELF_ONLY posts while unaudited.",
    ),
    "LinkedIn": PlatformCapabilities(
        platform="LinkedIn", video_upload=True, image_upload=True, short_form=False,
        scheduling=True, immediate_publish=True, captions=False, title=True,
        description=True, hashtags=True, thumbnail=False, cover_image=False,
        privacy=True, comments_settings=True, processing_status=True,
        publication_status=True, metrics=False,
        notes="LinkedIn Posts API + video initializeUpload; scheduledPublishTime supported.",
    ),
    "Webhook": PlatformCapabilities(
        platform="Webhook", video_upload=True, image_upload=True, short_form=True,
        scheduling=True, immediate_publish=True, captions=True, title=True,
        description=True, hashtags=True, thumbnail=True, cover_image=True,
        privacy=False, comments_settings=False, processing_status=False,
        publication_status=True, metrics=False,
        notes="n8n/webhook dispatch: delivery confirmation only — not a platform publication (§23).",
    ),
}


def capabilities_for(platform: str) -> PlatformCapabilities:
    try:
        return PLATFORM_CAPABILITIES[platform]
    except KeyError as exc:
        raise ValueError(f"Unknown platform: {platform!r}") from exc


def supports(platform: str, capability: str) -> bool:
    caps = capabilities_for(platform)
    if not hasattr(caps, capability):
        raise ValueError(f"Unknown capability: {capability!r}")
    return bool(getattr(caps, capability))


__all__ = ["PlatformCapabilities", "PLATFORM_CAPABILITIES", "capabilities_for", "supports"]
