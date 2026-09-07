"""Instagram Graph API adapter (§3, §4, §46).

Official two-step Content Publishing flow: create media container
(POST /{ig-user-id}/media with a PUBLIC video_url) → poll container
status_code → media_publish. Honest official limitations encoded here:

* No direct local-file upload: the platform requires a publicly hosted URL.
* No official scheduling for Reels/feed → schedule() stays unsupported.
* Business/Creator Instagram accounts connected to a Facebook Page required.
"""

from __future__ import annotations

from services.publishing.base import ProviderResponse
from services.publishing.http_client import HttpResponse
from services.publishing.models import PublishingJob
from services.publishing.real_base import RealProviderBase

API = "https://graph.facebook.com/v19.0"


class InstagramProvider(RealProviderBase):
    platform = "Instagram Reels"
    provider_name = "instagram"

    def __init__(self, square_feed: bool = False, **kwargs):
        super().__init__(**kwargs)
        if square_feed:
            self.platform = "Square Feed"

    # ------------------------------------------------------------- auth
    def _ping(self) -> bool:
        response = self._request("GET", f"{API}/me", context="metadata")
        return isinstance(response, HttpResponse)

    def _ig_user(self) -> str:
        return self.external_account_id

    # ----------------------------------------------------------- upload
    def upload(self, job: PublishingJob) -> ProviderResponse:
        if not self._token():
            return self._missing_token()
        if not self._ig_user():
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_credentials",
                                    message="Instagram publishing requires the IG user id (Business/Creator account).")
        asset = job.asset_path
        if not asset.startswith(("http://", "https://")):
            return ProviderResponse(
                provider_status="FAILED", error_kind="invalid_media",
                message="Instagram requires a publicly hosted video URL; host the asset first "
                        "(the Graph API does not accept direct file uploads).")
        params = {"media_type": "REELS" if self.platform == "Instagram Reels" else "MEDIA",
                  "video_url": asset}
        caption = job.description or job.caption or job.title
        if caption:
            params["caption"] = caption
        response = self._request("POST", f"{API}/{self._ig_user()}/media",
                                 json_body=params, context="upload")
        if isinstance(response, ProviderResponse):
            return response
        container_id = response.body.get("id", "") if isinstance(response.body, dict) else ""
        if not container_id:
            return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                    message="Instagram returned no container id.")
        return ProviderResponse(provider_status="UPLOADING", external_id=container_id,
                                message="Instagram container created; awaiting FINISHED status.")

    # ------------------------------------------------------- processing
    def check_processing(self, job: PublishingJob) -> ProviderResponse:
        response = self._request("GET",
                                 f"{API}/{job.external_post_id}?fields=status_code",
                                 context="metadata")
        if isinstance(response, ProviderResponse):
            return response
        state = response.body.get("status_code", "") if isinstance(response.body, dict) else ""
        if state == "FINISHED":
            return ProviderResponse(provider_status="READY", message="Instagram container finished.")
        if state in ("ERROR", "EXPIRED"):
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message=f"Instagram container state: {state}.")
        return ProviderResponse(provider_status="PROCESSING",
                                message=f"Instagram container state: {state or 'IN_PROGRESS'}.")

    # ---------------------------------------------------------- publish
    def publish(self, job: PublishingJob) -> ProviderResponse:
        if job.scheduled_at:
            return self.schedule(job)
        response = self._request("POST", f"{API}/{self._ig_user()}/media_publish",
                                 json_body={"creation_id": job.external_post_id}, context="publish")
        if isinstance(response, ProviderResponse):
            return response
        media_id = response.body.get("id", "") if isinstance(response.body, dict) else ""
        if not media_id:
            return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                    message="Instagram media_publish returned no media id.")
        return ProviderResponse(provider_status="PUBLISHED", external_id=media_id,
                                external_url=f"https://www.instagram.com/reel/{media_id}/",
                                message="Instagram confirmed publication via media_publish.")

    # ------------------------------------------------------------ status
    def get_status(self, external_id: str) -> ProviderResponse:
        response = self._request("GET",
                                 f"{API}/{external_id}?fields=id,media_type,permalink",
                                 context="metadata")
        if isinstance(response, ProviderResponse):
            return response
        body = response.body if isinstance(response.body, dict) else {}
        if not body.get("id"):
            return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                    message="Instagram has no record of this media id.")
        permalink = body.get("permalink", f"https://www.instagram.com/reel/{external_id}/")
        return ProviderResponse(provider_status="PUBLISHED", external_id=external_id,
                                external_url=permalink, message="Instagram media exists.")


__all__ = ["InstagramProvider"]
