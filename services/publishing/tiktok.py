"""TikTok Content Posting API adapter (§3, §4, §46).

Official flow: POST https://open.tiktokapis.com/v2/post/publish/video/init/
(FILE_UPLOAD source) → chunked PUT to upload_url → POST
/v2/post/publish/status/fetch/ polling. Scheduling is official via
post_info.publish_time (unix seconds, +15 min to +10 days, UTC).

Honest limitations encoded: unaudited apps post with privacy_level
SELF_ONLY; no custom thumbnail or caption-file upload exists in the API.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from services.publishing.base import ProviderResponse
from services.publishing.http_client import HttpResponse
from services.publishing.models import PublishingJob, parse_scheduled_at
from services.publishing.real_base import RealProviderBase

API = "https://open.tiktokapis.com"
INIT_URL = f"{API}/v2/post/publish/video/init/"
STATUS_URL = f"{API}/v2/post/publish/status/fetch/"
USER_URL = f"{API}/v2/user/info/?fields=open_id"

SCHEDULE_MIN = timedelta(minutes=15)
SCHEDULE_MAX = timedelta(days=10)


class TikTokProvider(RealProviderBase):
    platform = "TikTok"
    provider_name = "tiktok"

    # ------------------------------------------------------------- auth
    def _ping(self) -> bool:
        response = self._request("GET", USER_URL, context="metadata")
        return isinstance(response, HttpResponse)

    # ----------------------------------------------------------- upload
    def _init(self, job: PublishingJob, scheduled_unix: int | None) -> ProviderResponse:
        post_info = {"title": (job.title or job.description or job.caption or "")[:2200],
                     "privacy_level": "SELF_ONLY"}  # unaudited apps: honest official default
        if scheduled_unix:
            post_info["publish_time"] = scheduled_unix
        size = os.path.getsize(job.asset_path) if os.path.isfile(job.asset_path) else 0
        response = self._request("POST", INIT_URL, json_body={
            "post_info": post_info,
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": size or 1, "total_chunk_count": 1},
        }, context="upload")
        if isinstance(response, ProviderResponse):
            return response
        data = response.body.get("data", {}) if isinstance(response.body, dict) else {}
        publish_id = data.get("publish_id", "")
        upload_url = data.get("upload_url", "")
        if not publish_id:
            return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                    message="TikTok returned no publish_id.")
        binary = self._asset_bytes(job)
        put = self._request("PUT", upload_url, headers={"Content-Range": f"bytes 0-{len(binary) - 1}/{len(binary)}"},
                            data=binary, context="upload")
        if isinstance(put, ProviderResponse):
            return put
        return ProviderResponse(provider_status="UPLOADING", external_id=publish_id,
                                message="TikTok accepted the upload (SELF_ONLY until app audit).")

    def upload(self, job: PublishingJob) -> ProviderResponse:
        if not self._token():
            return self._missing_token()
        if job.scheduled_at:
            return self._init_scheduled(job)
        return self._init(job, scheduled_unix=None)

    def _init_scheduled(self, job: PublishingJob) -> ProviderResponse:
        moment = parse_scheduled_at(job.scheduled_at)
        now = datetime.now(timezone.utc)
        if not (SCHEDULE_MIN <= moment - now <= SCHEDULE_MAX):
            return ProviderResponse(
                provider_status="FAILED", error_kind="invalid_metadata",
                message="TikTok scheduling officially supports +15 minutes to +10 days only.")
        return self._init(job, scheduled_unix=int(moment.timestamp()))

    # ------------------------------------------------------- processing
    def _fetch(self, publish_id: str) -> HttpResponse | ProviderResponse:
        return self._request("POST", STATUS_URL, json_body={"publish_id": publish_id},
                             context="metadata")

    def check_processing(self, job: PublishingJob) -> ProviderResponse:
        response = self._fetch(job.external_post_id)
        if isinstance(response, ProviderResponse):
            return response
        data = response.body.get("data", {}) if isinstance(response.body, dict) else {}
        state = data.get("status", "")
        if state in ("PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX"):
            return ProviderResponse(provider_status="PROCESSING", message=f"TikTok status: {state}.")
        if state == "PUBLISH_COMPLETE":
            return ProviderResponse(provider_status="READY", message="TikTok processing complete.")
        if state == "SCHEDULED":
            return ProviderResponse(provider_status="READY", message="TikTok accepted the schedule.")
        if state == "FAILED":
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message=f"TikTok publish failed: {data.get('fail_reason', 'unknown')}.")
        return ProviderResponse(provider_status="PROCESSING", message=f"TikTok status: {state or 'unknown'}.")

    # ---------------------------------------------------------- publish
    def publish(self, job: PublishingJob) -> ProviderResponse:
        """DIRECT_POST flows finalize during processing; confirm via status fetch."""
        response = self._fetch(job.external_post_id)
        if isinstance(response, ProviderResponse):
            return response
        data = response.body.get("data", {}) if isinstance(response.body, dict) else {}
        state = data.get("status", "")
        if state == "PUBLISH_COMPLETE":
            share = data.get("share_url") or (f"https://www.tiktok.com/@me/video/{job.external_post_id}")
            return ProviderResponse(provider_status="PUBLISHED", external_id=job.external_post_id,
                                    external_url=share,
                                    message="TikTok confirmed publication (PUBLISH_COMPLETE).")
        if state == "SCHEDULED":
            return ProviderResponse(provider_status="SCHEDULED", external_id=job.external_post_id,
                                    message="TikTok confirmed the scheduled post.")
        if state == "FAILED":
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message=f"TikTok publish failed: {data.get('fail_reason', 'unknown')}.")
        return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                message=f"TikTok post not confirmed yet (status {state or 'unknown'}).")

    def schedule(self, job: PublishingJob) -> ProviderResponse:
        # Scheduling happens at init time on TikTok; publish() confirms it.
        return self.publish(job)

    # ------------------------------------------------------------ status
    def get_status(self, external_id: str) -> ProviderResponse:
        response = self._fetch(external_id)
        if isinstance(response, ProviderResponse):
            return response
        data = response.body.get("data", {}) if isinstance(response.body, dict) else {}
        state = data.get("status", "")
        mapping = {"PUBLISH_COMPLETE": "PUBLISHED", "FAILED": "FAILED", "SCHEDULED": "SCHEDULED"}
        status = mapping.get(state, "PROCESSING")
        return ProviderResponse(provider_status=status, external_id=external_id,
                                external_url=data.get("share_url", ""),
                                message=f"TikTok status fetch: {state or 'unknown'}.")


__all__ = ["TikTokProvider"]
