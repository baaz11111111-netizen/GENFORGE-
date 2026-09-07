"""Phase 11 — Publishing adapters: clean provider interface, truthful statuses.

Mandate rule: only real publishing where official APIs and credentials exist.
No provider here can fake a publication — a "published" status is only ever
returned after an explicit confirmation (HTTP 2xx from a live endpoint).
Providers without credentials or official API support report UNSUPPORTED or
UNAUTHENTICATED, never success.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, field_validator

STATUSES = ("published", "scheduled", "failed", "unsupported", "unauthenticated")

# Platforms whose official upload APIs require OAuth credentials GENFORGE does
# not bundle. They are listed honestly, never simulated.
OFFICIAL_API_REQUIRED = {
    "TikTok": "TikTok Content Posting API (OAuth client credentials required)",
    "Instagram Reels": "Instagram Graph API (Meta business account + access token required)",
    "YouTube Shorts": "YouTube Data API v3 (OAuth client credentials required)",
    "YouTube": "YouTube Data API v3 (OAuth client credentials required)",
    "Square Feed": "Instagram Graph API (Meta business account + access token required)",
}


class PublishRequest(BaseModel):
    """One requested publication against a real rendered asset."""

    platform: str
    asset_path: str
    title: str = ""
    description: str = ""
    scheduled_at: str = ""

    @field_validator("platform")
    @classmethod
    def _known_platform(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Platform is required.")
        return value.strip()

    @field_validator("asset_path")
    @classmethod
    def _asset_exists(cls, value: str) -> str:
        if not value or not os.path.isfile(value):
            raise ValueError(f"Publishable asset file not found: {value}")
        return str(os.path.abspath(value))


@dataclass
class PublishResult:
    """Truthful publication outcome. confirmation must never be fabricated."""

    provider: str
    status: str
    message: str
    external_id: str | None = None
    confirmed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"Unknown publish status '{self.status}'. Available: {', '.join(STATUSES)}")
        if self.status == "published" and not self.confirmed:
            raise ValueError("A 'published' status requires explicit confirmation; never fake success.")


class Publisher:
    """Provider interface: authenticate → upload → publish → schedule → status."""

    provider_name = "base"
    supported_platforms: tuple[str, ...] = ()

    def authenticate(self) -> bool:
        raise NotImplementedError

    def upload(self, request: PublishRequest) -> PublishResult:
        raise NotImplementedError

    def publish(self, request: PublishRequest) -> PublishResult:
        raise NotImplementedError

    def schedule(self, request: PublishRequest) -> PublishResult:
        raise NotImplementedError

    def status(self, external_id: str) -> PublishResult:
        raise NotImplementedError

    def supports(self, platform: str) -> bool:
        return platform in self.supported_platforms

    def _unsupported(self, request: PublishRequest) -> PublishResult:
        return PublishResult(
            provider=self.provider_name, status="unsupported",
            message=f"UNSUPPORTED: {self.provider_name} cannot publish to {request.platform}. "
                    f"{OFFICIAL_API_REQUIRED.get(request.platform, 'No official API integration available.')}",
        )


class WebhookPublisher(Publisher):
    """Publishes by POSTing the asset manifest to a live webhook (e.g. n8n).

    This is the only provider that can genuinely confirm delivery in the
    current environment: success is reported only on an HTTP 200/201 response.
    """

    provider_name = "webhook"
    supported_platforms = ("Webhook",)

    def __init__(self, endpoint: str = ""):
        self.endpoint = endpoint.strip()
        self._authenticated = False
        self._confirmed: dict[str, dict[str, Any]] = {}

    def configure(self, endpoint: str) -> None:
        self.endpoint = endpoint.strip()
        self._authenticated = False

    def authenticate(self) -> bool:
        """Authentication = a syntactically valid absolute HTTP(S) endpoint."""
        from urllib.parse import urlparse
        parsed = urlparse(self.endpoint)
        self._authenticated = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        return self._authenticated

    def _deliver(self, request: PublishRequest, mode: str) -> PublishResult:
        if not self.authenticate():
            return PublishResult(
                provider=self.provider_name, status="unauthenticated",
                message="UNAUTHENTICATED: configure a valid HTTP(S) webhook endpoint before publishing.",
            )
        payload = {
            "mode": mode,
            "platform": request.platform,
            "asset_path": request.asset_path,
            "title": request.title,
            "description": request.description,
            "scheduled_at": request.scheduled_at,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        data = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            self.endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=10) as response:
                confirmed = response.status in (200, 201)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return PublishResult(
                provider=self.provider_name, status="failed",
                message=f"Webhook delivery failed: {exc}",
            )
        if not confirmed:
            return PublishResult(provider=self.provider_name, status="failed",
                                 message="Webhook endpoint did not confirm delivery.")
        external_id = uuid4().hex
        self._confirmed[external_id] = {**payload, "status": "scheduled" if mode == "schedule" else "published"}
        return PublishResult(
            provider=self.provider_name,
            status="scheduled" if mode == "schedule" else "published",
            message="Delivery confirmed by webhook endpoint (HTTP 200/201).",
            external_id=external_id, confirmed=True,
        )

    def upload(self, request: PublishRequest) -> PublishResult:
        return self._deliver(request, "upload")

    def publish(self, request: PublishRequest) -> PublishResult:
        return self._deliver(request, "publish")

    def schedule(self, request: PublishRequest) -> PublishResult:
        if not request.scheduled_at:
            return PublishResult(provider=self.provider_name, status="failed",
                                 message="scheduled_at is required for scheduling.")
        return self._deliver(request, "schedule")

    def status(self, external_id: str) -> PublishResult:
        record = self._confirmed.get(external_id)
        if record is None:
            return PublishResult(provider=self.provider_name, status="failed",
                                 message=f"No confirmed publication found: {external_id}")
        return PublishResult(provider=self.provider_name, status=record["status"],
                             message="Status read from confirmed delivery record.",
                             external_id=external_id, confirmed=True, metadata=dict(record))


class PlatformPublisher(Publisher):
    """Adapter for social platforms that require official OAuth APIs.

    Without bundled credentials every operation reports UNSUPPORTED /
    UNAUTHENTICATED honestly. A pluggable ``transport`` allows a real API
    client to be supplied when credentials become available.
    """

    provider_name = "platform_api"
    supported_platforms = tuple(OFFICIAL_API_REQUIRED)

    def __init__(self, transport=None):
        # transport: callable(PublishRequest, mode) -> confirmed bool / external id.
        self.transport = transport
        self._records: dict[str, dict[str, Any]] = {}

    def authenticate(self) -> bool:
        return self.transport is not None

    def _attempt(self, request: PublishRequest, mode: str) -> PublishResult:
        if request.platform not in self.supported_platforms:
            return self._unsupported(request)
        if not self.authenticate():
            return PublishResult(
                provider=self.provider_name, status="unauthenticated",
                message=f"UNAUTHENTICATED: {OFFICIAL_API_REQUIRED[request.platform]}. "
                        "Publishing is disabled until valid credentials are configured.",
            )
        try:
            confirmation = self.transport(request, mode)
        except Exception as exc:
            return PublishResult(provider=self.provider_name, status="failed",
                                 message=f"Provider API call failed: {exc}")
        if not confirmation:
            return PublishResult(provider=self.provider_name, status="failed",
                                 message="Provider API did not confirm the publication.")
        external_id = str(confirmation if isinstance(confirmation, str) else uuid4().hex)
        self._records[external_id] = {"platform": request.platform, "mode": mode,
                                      "asset_path": request.asset_path}
        return PublishResult(
            provider=self.provider_name,
            status="scheduled" if mode == "schedule" else "published",
            message="Publication confirmed by the official platform API.",
            external_id=external_id, confirmed=True,
        )

    def upload(self, request: PublishRequest) -> PublishResult:
        return self._attempt(request, "upload")

    def publish(self, request: PublishRequest) -> PublishResult:
        return self._attempt(request, "publish")

    def schedule(self, request: PublishRequest) -> PublishResult:
        if not request.scheduled_at:
            return PublishResult(provider=self.provider_name, status="failed",
                                 message="scheduled_at is required for scheduling.")
        return self._attempt(request, "schedule")

    def status(self, external_id: str) -> PublishResult:
        record = self._records.get(external_id)
        if record is None:
            return PublishResult(provider=self.provider_name, status="failed",
                                 message=f"No confirmed publication found: {external_id}")
        return PublishResult(provider=self.provider_name,
                             status="scheduled" if record["mode"] == "schedule" else "published",
                             message="Status read from confirmed API record.",
                             external_id=external_id, confirmed=True, metadata=dict(record))


PUBLISHERS: dict[str, Publisher] = {
    "webhook": WebhookPublisher(),
    "platform_api": PlatformPublisher(),
}


def publisher_for(platform: str) -> Publisher:
    """Resolve the adapter responsible for a platform (webhook is opt-in only)."""
    if platform == "Webhook":
        return PUBLISHERS["webhook"]
    return PUBLISHERS["platform_api"]


def publish_campaign_assets(campaign: dict[str, Any], platforms: list[str] | None = None) -> list[dict[str, Any]]:
    """Publish the real rendered campaign clip per platform, honestly.

    Every result is recorded in the campaign's publish history. Slots without
    a rendered asset are reported unavailable — never simulated.
    """
    if not campaign or "assets" not in campaign:
        raise ValueError("A built campaign workspace is required.")
    clips = campaign["assets"].get("clips", [])
    rendered = next((clip for clip in clips if clip.get("status") == "rendered" and clip.get("path")), None)
    targets = platforms or campaign.get("brief", {}).get("platforms", [])
    history: list[dict[str, Any]] = []
    for platform in targets:
        entry: dict[str, Any] = {"platform": platform, "attempted_at": datetime.now(timezone.utc).isoformat()}
        if rendered is None or not os.path.isfile(rendered["path"]):
            entry.update({"status": "failed", "message":
                          "No rendered campaign clip exists; nothing was published."})
            history.append(entry)
            continue
        request = PublishRequest(platform=platform, asset_path=rendered["path"],
                                 title=campaign.get("brief", {}).get("topic", ""))
        result = publisher_for(platform).publish(request)
        entry.update({"status": result.status, "message": result.message,
                      "external_id": result.external_id, "confirmed": result.confirmed})
        history.append(entry)
    campaign.setdefault("publish_history", []).extend(history)
    return history


__all__ = [
    "STATUSES",
    "OFFICIAL_API_REQUIRED",
    "PublishRequest",
    "PublishResult",
    "Publisher",
    "WebhookPublisher",
    "PlatformPublisher",
    "PUBLISHERS",
    "publisher_for",
    "publish_campaign_assets",
]
