"""LinkedIn Posts + Videos API adapter (§3, §4, §46).

Official flow: POST /rest/videos?action=initializeUpload → PUT binary to the
signed upload URL → POST /rest/posts with content.media referencing the
video urn. Scheduling is official via scheduledPublishTime (epoch seconds).
The member urn (urn:li:person:…) is carried as external_account_id.
"""

from __future__ import annotations

from datetime import timezone

from services.publishing.base import ProviderResponse
from services.publishing.http_client import HttpResponse
from services.publishing.models import PublishingJob, parse_scheduled_at
from services.publishing.real_base import RealProviderBase

API = "https://api.linkedin.com"
USERINFO_URL = f"{API}/userinfo"
INIT_UPLOAD_URL = f"{API}/rest/videos?action=initializeUpload"
POSTS_URL = f"{API}/rest/posts"


class LinkedInProvider(RealProviderBase):
    platform = "LinkedIn"
    provider_name = "linkedin"

    # ------------------------------------------------------------- auth
    def _ping(self) -> bool:
        response = self._request("GET", USERINFO_URL, context="metadata")
        return isinstance(response, HttpResponse)

    def _member_urn(self) -> str:
        if self.external_account_id.startswith("urn:li:person:"):
            return self.external_account_id
        return f"urn:li:person:{self.external_account_id}" if self.external_account_id else ""

    # ----------------------------------------------------------- upload
    def upload(self, job: PublishingJob) -> ProviderResponse:
        if not self._token():
            return self._missing_token()
        owner = self._member_urn()
        if not owner:
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_credentials",
                                    message="LinkedIn publishing requires the member urn (person id).")
        response = self._request("POST", INIT_UPLOAD_URL,
                                 json_body={"initializeUploadRequest": {"owner": owner}},
                                 context="upload")
        if isinstance(response, ProviderResponse):
            return response
        value = response.body.get("value", {}) if isinstance(response.body, dict) else {}
        upload_url = value.get("uploadUrl", "")
        video_urn = value.get("video", "")
        if not upload_url or not video_urn:
            return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                    message="LinkedIn returned no upload URL or video urn.")
        binary = self._asset_bytes(job)
        put = self._request("PUT", upload_url,
                            headers={"Content-Type": "application/octet-stream"},
                            data=binary, context="upload")
        if isinstance(put, ProviderResponse):
            return put
        return ProviderResponse(provider_status="UPLOADING", external_id=video_urn,
                                message="LinkedIn accepted the video upload.")

    # ------------------------------------------------------- processing
    def check_processing(self, job: PublishingJob) -> ProviderResponse:
        encoded = job.external_post_id.replace(":", "%3A")
        response = self._request("GET", f"{API}/rest/videos/{encoded}?view=processing",
                                 context="metadata")
        if isinstance(response, ProviderResponse):
            return response
        body = response.body if isinstance(response.body, dict) else {}
        state = body.get("status", "")
        if state == "AVAILABLE":
            return ProviderResponse(provider_status="READY", message="LinkedIn video available.")
        if state == "FAILED":
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message="LinkedIn video processing failed.")
        return ProviderResponse(provider_status="PROCESSING",
                                message=f"LinkedIn video status: {state or 'unknown'}.")

    # ---------------------------------------------------------- publish
    def _create_post(self, job: PublishingJob, scheduled_epoch: int | None) -> ProviderResponse:
        body = {
            "author": self._member_urn(),
            "commentary": job.description or job.caption or job.title or "",
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED"},
            "content": {"media": {"id": job.external_post_id}},
            "lifecycleState": "PUBLISHED",
        }
        if scheduled_epoch:
            body["scheduledPublishTime"] = scheduled_epoch
            body["lifecycleState"] = "SCHEDULED"
        response = self._request("POST", POSTS_URL, json_body=body,
                                 headers=self._auth_headers({"LinkedIn-Version": "202401",
                                                             "X-Restli-Protocol-Version": "2.0.0"}),
                                 context="publish")
        if isinstance(response, ProviderResponse):
            return response
        post_urn = ""
        if isinstance(response.body, dict):
            post_urn = response.body.get("id", "")
        if not post_urn:
            header_id = response.headers.get("x-restli-id", "") if response.headers else ""
            post_urn = header_id
        if not post_urn:
            return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                    message="LinkedIn returned no post id.")
        encoded = post_urn.replace("urn:li:share:", "").replace("urn:li:ugcPost:", "")
        url = f"https://www.linkedin.com/feed/update/{post_urn}/"
        status = "SCHEDULED" if scheduled_epoch else "PUBLISHED"
        message = ("LinkedIn confirmed the scheduled post." if scheduled_epoch
                   else "LinkedIn confirmed publication.")
        return ProviderResponse(provider_status=status, external_id=post_urn,
                                external_url=url, message=message)

    def publish(self, job: PublishingJob) -> ProviderResponse:
        if job.scheduled_at:
            return self.schedule(job)
        return self._create_post(job, scheduled_epoch=None)

    def schedule(self, job: PublishingJob) -> ProviderResponse:
        moment = parse_scheduled_at(job.scheduled_at)
        epoch = int(moment.astimezone(timezone.utc).timestamp())
        return self._create_post(job, scheduled_epoch=epoch)

    # ------------------------------------------------------------ status
    def get_status(self, external_id: str) -> ProviderResponse:
        encoded = external_id.replace(":", "%3A")
        response = self._request("GET", f"{API}/rest/posts/{encoded}", context="metadata")
        if isinstance(response, ProviderResponse):
            return response
        body = response.body if isinstance(response.body, dict) else {}
        state = body.get("lifecycleState", "")
        mapping = {"PUBLISHED": "PUBLISHED", "SCHEDULED": "SCHEDULED", "PROCESSING": "PROCESSING"}
        status = mapping.get(state, "READY" if body else "FAILED")
        return ProviderResponse(provider_status=status, external_id=external_id,
                                external_url=f"https://www.linkedin.com/feed/update/{external_id}/",
                                message=f"LinkedIn post lifecycle: {state or 'unknown'}.")


__all__ = ["LinkedInProvider"]
