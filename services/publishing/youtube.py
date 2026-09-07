"""YouTube Data API v3 adapter (§3, §4, §46).

Official flow used: videos.insert (multipart) with privacyStatus=private →
processingDetails polling → PATCH status to public (publish) or publishAt
(scheduling; publishAt officially requires privacyStatus=private). Metrics
come from part=statistics. Thumbnails/captions are officially supported by
the API (capability matrix) but are not part of the core pipeline yet.
"""

from __future__ import annotations

import json
import uuid

from services.publishing.base import ProviderResponse
from services.publishing.http_client import HttpResponse
from services.publishing.models import PublishingJob
from services.publishing.real_base import RealProviderBase

API = "https://www.googleapis.com"
UPLOAD_URL = f"{API}/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status"
VIDEOS_URL = f"{API}/youtube/v3/videos"


class YouTubeProvider(RealProviderBase):
    platform = "YouTube"
    provider_name = "youtube"

    def __init__(self, shorts: bool = False, **kwargs):
        super().__init__(**kwargs)
        if shorts:
            self.platform = "YouTube Shorts"

    # ------------------------------------------------------------- auth
    def _ping(self) -> bool:
        response = self._request("GET", f"{API}/oauth2/v3/userinfo", context="metadata")
        return isinstance(response, HttpResponse)

    # ----------------------------------------------------------- upload
    def upload(self, job: PublishingJob) -> ProviderResponse:
        if not self._token():
            return self._missing_token()
        metadata = {
            "snippet": {"title": job.title or "GENFORGE upload",
                        "description": job.description or job.caption,
                        "tags": list(job.hashtags)},
            "status": {"privacyStatus": "private"},
        }
        if job.scheduled_at:
            metadata["status"]["publishAt"] = job.scheduled_at
        boundary = uuid.uuid4().hex
        payload = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\nContent-Type: video/mp4\r\n\r\n"
        ).encode("utf-8") + self._asset_bytes(job) + f"\r\n--{boundary}--".encode("utf-8")
        headers = self._auth_headers({"Content-Type": f'multipart/related; boundary="{boundary}"'})
        response = self._request("POST", UPLOAD_URL, headers=headers, data=payload, context="upload")
        if isinstance(response, ProviderResponse):
            return response
        video_id = response.body.get("id", "") if isinstance(response.body, dict) else ""
        if not video_id:
            return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                    message="YouTube returned no video id.")
        return ProviderResponse(provider_status="UPLOADING", external_id=video_id,
                                message="YouTube accepted the upload; processing next.")

    # ------------------------------------------------------- processing
    def check_processing(self, job: PublishingJob) -> ProviderResponse:
        response = self._request(
            "GET", f"{VIDEOS_URL}?part=processingDetails&id={job.external_post_id or 'pending'}",
            context="metadata")
        if isinstance(response, ProviderResponse):
            return response
        items = response.body.get("items", []) if isinstance(response.body, dict) else []
        if not items:
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message="YouTube has no record of this video id.")
        state = items[0].get("processingDetails", {}).get("processingStatus", "")
        if state == "succeeded":
            return ProviderResponse(provider_status="READY", message="YouTube processing complete.")
        if state == "failed":
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message="YouTube processing failed for this video.")
        return ProviderResponse(provider_status="PROCESSING", message=f"YouTube status: {state or 'unknown'}.")

    # ---------------------------------------------------------- publish
    def publish(self, job: PublishingJob) -> ProviderResponse:
        if job.scheduled_at:
            return self.schedule(job)
        response = self._request(
            "PATCH", f"{VIDEOS_URL}?part=status&id={job.external_post_id}",
            json_body={"id": job.external_post_id, "status": {"privacyStatus": "public"}},
            context="publish")
        if isinstance(response, ProviderResponse):
            return response
        video_id = response.body.get("id", job.external_post_id) if isinstance(response.body, dict) else job.external_post_id
        return ProviderResponse(provider_status="PUBLISHED", external_id=video_id,
                                external_url=f"https://www.youtube.com/watch?v={video_id}",
                                message="YouTube confirmed publication (privacyStatus=public).")

    def schedule(self, job: PublishingJob) -> ProviderResponse:
        response = self._request(
            "PATCH", f"{VIDEOS_URL}?part=status&id={job.external_post_id}",
            json_body={"id": job.external_post_id,
                       "status": {"privacyStatus": "private", "publishAt": job.scheduled_at}},
            context="schedule")
        if isinstance(response, ProviderResponse):
            return response
        video_id = response.body.get("id", job.external_post_id) if isinstance(response.body, dict) else job.external_post_id
        return ProviderResponse(provider_status="SCHEDULED", external_id=video_id,
                                external_url=f"https://www.youtube.com/watch?v={video_id}",
                                message="YouTube confirmed the publishAt schedule.")

    # ------------------------------------------------------------ status
    def get_status(self, external_id: str) -> ProviderResponse:
        response = self._request(
            "GET", f"{VIDEOS_URL}?part=status,processingDetails&id={external_id}", context="metadata")
        if isinstance(response, ProviderResponse):
            return response
        items = response.body.get("items", []) if isinstance(response.body, dict) else []
        if not items:
            return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                    message="YouTube has no record of this video id.")
        privacy = items[0].get("status", {}).get("privacyStatus", "")
        processing = items[0].get("processingDetails", {}).get("processingStatus", "")
        if privacy == "public":
            status = "PUBLISHED"
        elif items[0].get("status", {}).get("publishAt"):
            status = "SCHEDULED"
        elif processing in ("processing", "uploaded"):
            status = "PROCESSING"
        elif processing == "failed":
            status = "FAILED"
        else:
            status = "READY"
        return ProviderResponse(provider_status=status, external_id=external_id,
                                external_url=f"https://www.youtube.com/watch?v={external_id}",
                                message=f"YouTube privacy={privacy or '?'} processing={processing or '?'}.")

    def get_metrics(self, external_id: str) -> ProviderResponse:
        response = self._request("GET", f"{VIDEOS_URL}?part=statistics&id={external_id}",
                                 context="metadata")
        if isinstance(response, ProviderResponse):
            return response
        items = response.body.get("items", []) if isinstance(response.body, dict) else []
        if not items:
            return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                    message="YouTube has no record of this video id.")
        stats = items[0].get("statistics", {})
        return ProviderResponse(provider_status="PUBLISHED", external_id=external_id,
                                message="YouTube statistics fetched.",
                                metadata={"views": stats.get("viewCount"),
                                          "likes": stats.get("likeCount")})


__all__ = ["YouTubeProvider"]
