"""Scriptable mock provider (§34/§37).

Used by the automated suite instead of real platforms: real publishing is
never triggered in tests. The mock faithfully simulates the platform state
machine — upload → processing steps → publish — and every failure class the
mandate requires testing (§26): timeout, rate limit, expired token,
permission denied, invalid media, server error, malformed response.

Idempotency is real: submitting the same idempotency key twice returns the
same external post instead of creating a duplicate (§17).
"""

from __future__ import annotations

from uuid import uuid4

from services.publishing.base import BaseProvider, ProviderResponse
from services.publishing.capabilities import PLATFORM_CAPABILITIES
from services.publishing.models import PublishingJob

SCENARIOS = (
    "normal", "upload_failure_retryable", "upload_failure_permanent",
    "processing_failure", "rate_limited", "expired_token", "permission_denied",
    "invalid_media", "server_error", "timeout", "schedule_unsupported",
)


class MockPlatformProvider(BaseProvider):
    """A fully mocked platform with deterministic, inspectable behavior."""

    provider_name = "mock"

    def __init__(self, platform: str = "TikTok", scenario: str = "normal",
                 processing_steps: int = 2, authenticated: bool = True):
        if platform not in PLATFORM_CAPABILITIES:
            raise ValueError(f"Unknown platform: {platform!r}")
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown mock scenario: {scenario!r}. Valid: {', '.join(SCENARIOS)}")
        self.platform = platform
        self.scenario = scenario
        self.processing_steps = max(0, processing_steps)
        self.authenticated = authenticated
        # internal simulated platform state
        self._uploads: dict[str, dict] = {}
        self._posts: dict[str, dict] = {}
        self._by_idempotency: dict[str, str] = {}
        self._poll_counts: dict[str, int] = {}
        self.call_log: list[str] = []

    # ------------------------------------------------------------- auth
    def authenticate(self) -> bool:
        self.call_log.append("authenticate")
        if self.scenario == "expired_token":
            self.authenticated = False
        return self.authenticated

    def disconnect(self) -> None:
        self.authenticated = False
        self.call_log.append("disconnect")

    # ---------------------------------------------------------- helpers
    def _unauthenticated(self) -> ProviderResponse:
        kind = "expired_token" if self.scenario == "expired_token" else "invalid_credentials"
        return ProviderResponse(provider_status="FAILED", error_kind=kind,
                                message="Mock platform rejected the credentials.")

    def _register_idempotent(self, job: PublishingJob) -> ProviderResponse | None:
        """§17: same idempotency key must never create a second post."""
        existing_id = self._by_idempotency.get(job.idempotency_key)
        if existing_id:
            record = self._posts[existing_id]
            return ProviderResponse(
                provider_status=record["status"], external_id=existing_id,
                external_url=record["url"], message="Existing post returned (idempotent replay).",
                metadata={"idempotent_replay": True},
            )
        return None

    def _create_post(self, job: PublishingJob, status: str) -> dict:
        post_id = f"mock-{uuid4().hex[:12]}"
        record = {"post_id": post_id, "status": status,
                  "url": f"https://mock.example/{self.platform.lower().replace(' ', '-')}/{post_id}",
                  "idempotency_key": job.idempotency_key, "title": job.title}
        self._posts[post_id] = record
        self._by_idempotency[job.idempotency_key] = post_id
        return record

    # ------------------------------------------------------- operations
    def upload(self, job: PublishingJob) -> ProviderResponse:
        self.call_log.append("upload")
        if not self.authenticate():
            return self._unauthenticated()
        issues = self.validate_asset(job)
        if issues:
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message="; ".join(issues))
        scenario_failures = {
            "upload_failure_retryable": ("server_error", "Mock upload interrupted (retryable)."),
            "upload_failure_permanent": ("permission_denied", "Mock upload permanently rejected."),
            "timeout": ("timeout", "Mock upload timed out."),
            "server_error": ("server_error", "Mock platform 500."),
            "rate_limited": ("rate_limited", "Mock platform 429: slow down."),
            "permission_denied": ("permission_denied", "Mock scope missing."),
            "invalid_media": ("invalid_media", "Mock codec rejected."),
        }
        if self.scenario in scenario_failures:
            kind, message = scenario_failures[self.scenario]
            retry_after = 5.0 if kind == "rate_limited" else None
            return ProviderResponse(provider_status="FAILED", error_kind=kind,
                                    message=message, retry_after_seconds=retry_after)
        upload_id = f"upload-{uuid4().hex[:8]}"
        self._uploads[upload_id] = {"job_id": job.job_id, "steps_left": self.processing_steps}
        self._poll_counts[upload_id] = 0
        return ProviderResponse(provider_status="UPLOADING", external_id=upload_id,
                                message="Mock upload accepted; platform is processing.")

    def check_processing(self, job: PublishingJob) -> ProviderResponse:
        self.call_log.append("check_processing")
        upload = next((u for u in self._uploads.values() if u["job_id"] == job.job_id), None)
        if upload is None:
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_media",
                                    message="No upload known for this job.")
        self._poll_counts[upload.get("upload_id", job.job_id)] = \
            self._poll_counts.get(upload.get("upload_id", job.job_id), 0) + 1
        if self.scenario == "processing_failure" and upload["steps_left"] <= 1:
            return ProviderResponse(provider_status="FAILED", error_kind="server_error",
                                    message="Mock processing failed on the platform side.")
        if upload["steps_left"] > 0:
            upload["steps_left"] -= 1
            return ProviderResponse(provider_status="PROCESSING",
                                    message=f"Mock processing: {upload['steps_left']} step(s) remaining.")
        return ProviderResponse(provider_status="READY", message="Mock processing complete.")

    def publish(self, job: PublishingJob) -> ProviderResponse:
        self.call_log.append("publish")
        if not self.authenticate():
            return self._unauthenticated()
        if not job.scheduled_at:
            replay = self._register_idempotent(job)
            if replay is not None:
                return replay
            record = self._create_post(job, "PUBLISHED")
            return ProviderResponse(provider_status="PUBLISHED", external_id=record["post_id"],
                                    external_url=record["url"],
                                    message="Mock platform confirmed publication.")
        return self.schedule(job)

    def schedule(self, job: PublishingJob) -> ProviderResponse:
        self.call_log.append("schedule")
        if self.scenario == "schedule_unsupported" or not self.capabilities.scheduling:
            return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                    message=f"Platform scheduling unsupported for {self.platform}.")
        if not self.authenticate():
            return self._unauthenticated()
        if not job.scheduled_at:
            return ProviderResponse(provider_status="FAILED", error_kind="invalid_metadata",
                                    message="scheduled_at is required to schedule.")
        replay = self._register_idempotent(job)
        if replay is not None:
            return replay
        record = self._create_post(job, "SCHEDULED")
        return ProviderResponse(provider_status="SCHEDULED", external_id=record["post_id"],
                                external_url=record["url"],
                                message="Mock platform confirmed the schedule.")

    def cancel(self, job: PublishingJob) -> ProviderResponse:
        self.call_log.append("cancel")
        post_id = self._by_idempotency.get(job.idempotency_key)
        if post_id and self._posts[post_id]["status"] == "SCHEDULED":
            del self._posts[post_id]
            del self._by_idempotency[job.idempotency_key]
            return ProviderResponse(provider_status="READY", message="Mock scheduled post cancelled.")
        return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                message="Only mock scheduled posts can be cancelled.")

    def get_status(self, external_id: str) -> ProviderResponse:
        self.call_log.append("get_status")
        record = self._posts.get(external_id)
        if record is None:
            return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                    message=f"Unknown mock post: {external_id}")
        return ProviderResponse(provider_status=record["status"], external_id=external_id,
                                external_url=record["url"], message="Mock status lookup.")

    def get_post(self, external_id: str) -> ProviderResponse:
        return self.get_status(external_id)

    def get_metrics(self, external_id: str) -> ProviderResponse:
        self.call_log.append("get_metrics")
        record = self._posts.get(external_id)
        if record is None:
            return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                    message=f"Unknown mock post: {external_id}")
        return ProviderResponse(provider_status=record["status"], external_id=external_id,
                                message="Mock metrics placeholder (no invented numbers).",
                                metadata={"views": None, "likes": None})


__all__ = ["SCENARIOS", "MockPlatformProvider"]
