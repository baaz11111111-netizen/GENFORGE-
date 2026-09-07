"""Publishing pipeline manager (§14–§17, §22).

Runs the canonical pipeline for each job:

    READY → VALIDATE → AUTHENTICATE → UPLOAD → PROCESSING
          → CHECK STATUS → PUBLISH/SCHEDULE → CONFIRM → STORE RESULT

Hard rules baked in:

* Success is reported ONLY when the platform confirms it (§39).
* Retries happen ONLY for transient errors and with bounded exponential
  backoff (§15/§16) — never for invalid credentials/media/metadata.
* Idempotency: an existing external post is adopted instead of re-publishing
  (§17), so retries can never create duplicate posts.
* The queue is bounded, ordered, and reports honest states (§22).
"""

from __future__ import annotations

import time

from services.publishing.base import BaseProvider, ProviderResponse
from services.publishing.models import PublishingJob
from services.publishing.validation import validate_asset, validate_metadata, validate_schedule

QUEUE_STATES = ("queued", "waiting", "running", "completed", "failed", "cancelled")


class PublishingManager:
    """Drives jobs through the provider with bounded retries and polling."""

    def __init__(self, provider: BaseProvider, max_retries: int = 3, max_polls: int = 10,
                 backoff_base: float = 0.1, sleep_fn=time.sleep):
        if max_retries < 0 or max_polls < 1:
            raise ValueError("max_retries must be >= 0 and max_polls >= 1.")
        self.provider = provider
        self.max_retries = max_retries
        self.max_polls = max_polls
        self.backoff_base = backoff_base
        self._sleep = sleep_fn
        self.queue: list[dict] = []

    # --------------------------------------------------------- validation
    def validate_job(self, job: PublishingJob) -> list[str]:
        """All pre-flight checks; empty list means the job may proceed."""
        problems: list[str] = []
        for report in (validate_asset(job.asset_path, job.platform),
                       validate_metadata({"title": job.title, "description": job.description,
                                          "caption": job.caption, "hashtags": job.hashtags},
                                         job.platform),
                       validate_schedule(job.scheduled_at, job.platform)):
            problems.extend(report.problems)
        return problems

    # -------------------------------------------------------------- core
    def run_job(self, job: PublishingJob) -> PublishingJob:
        """§14 pipeline. Returns the job with its final honest status."""
        if job.status == "DRAFT":
            problems = self.validate_job(job)
            if problems:
                job.transition_to("FAILED", error="Pre-publish validation failed: " + "; ".join(problems))
                return job
            job.transition_to("READY")

        if job.status != "READY":
            return job  # already terminal or mid-flight elsewhere

        if not self.provider.authenticate():
            job.transition_to("FAILED", error="Authentication failed: credentials invalid or expired.")
            return job

        # §17: never re-publish what already exists upstream.
        if job.external_post_id:
            existing = self.provider.get_status(job.external_post_id)
            if existing.provider_status in ("PUBLISHED", "SCHEDULED"):
                job.transition_to(existing.provider_status,
                                  external_post_id=existing.external_id,
                                  external_url=existing.external_url or job.external_url)
                return job

        attempt = 0
        while True:
            done = self._single_attempt(job)
            if done:
                return job
            # Retryable failure left the job READY; honor the retry cap (§16).
            if attempt >= self.max_retries:
                job.transition_to("FAILED",
                                  error=f"Retry limit reached ({self.max_retries}); last error: {job.error}")
                return job
            attempt += 1
            job.retry_count += 1
            self._sleep(self.backoff_base * (2 ** attempt))

    def _single_attempt(self, job: PublishingJob) -> bool:
        """One upload→process→publish pass. True when no retry should follow."""
        response = self.provider.upload(job)
        if response.is_failure:
            return self._handle_failure(job, response, context="upload")
        if response.external_id:
            job.external_post_id = response.external_id  # polling/confirm address the upload
        if job.status == "READY":
            job.transition_to("UPLOADING")

        processed = self._poll_processing(job)
        if processed.is_failure:
            return self._handle_failure(job, processed, context="processing")
        if job.status == "UPLOADING":
            job.transition_to("PROCESSING")

        response = self.provider.publish(job)
        if response.is_failure:
            return self._handle_failure(job, response, context="publish")
        return self._confirm(job, response)

    def _poll_processing(self, job: PublishingJob) -> ProviderResponse:
        """§15: bounded polling — never forever."""
        last = ProviderResponse(provider_status="PROCESSING", message="not polled")
        for _ in range(self.max_polls):
            last = self.provider.check_processing(job)
            if last.provider_status in ("READY", "FAILED", "PUBLISHED", "SCHEDULED"):
                return last
            self._sleep(self.backoff_base)
        return ProviderResponse(provider_status="FAILED", error_kind="timeout",
                                message=f"Processing poll limit ({self.max_polls}) reached.")

    def _confirm(self, job: PublishingJob, response: ProviderResponse) -> bool:
        """CONFIRM step: trust only a platform-confirmed result (§39)."""
        target = response.provider_status  # PUBLISHED or SCHEDULED
        verification = self.provider.get_status(response.external_id)
        if verification.provider_status != target:
            job.transition_to("UNKNOWN", error=(
                f"Provider reported {target} but verification returned "
                f"{verification.provider_status}; status unconfirmed."))
            return True
        job.transition_to(target, external_post_id=response.external_id,
                          external_url=response.external_url)
        return True

    def _handle_failure(self, job: PublishingJob, response: ProviderResponse, context: str) -> bool:
        """§16: classify — retryables may retry, permanents fail immediately."""
        message = f"{context} failed: {response.message or response.error_kind or 'unknown error'}"
        job.transition_to("FAILED", error=message)
        if response.retryable:
            job.transition_to("READY")  # re-queued for the next attempt
            return False
        return True

    # -------------------------------------------------------------- queue
    def queue_job(self, job: PublishingJob) -> dict:
        """§22: validate BEFORE queueing; invalid jobs never enter the queue."""
        if any(entry["job_id"] == job.job_id for entry in self.queue):
            return next(e for e in self.queue if e["job_id"] == job.job_id)
        problems = self.validate_job(job) if job.status == "DRAFT" else []
        entry = {"job_id": job.job_id, "job": job, "reason": "; ".join(problems)}
        entry["state"] = "failed" if problems else "queued"
        if problems:  # only DRAFT jobs are validated, so this move is always legal
            job.transition_to("FAILED", error="Queue rejected: " + entry["reason"])
        self.queue.append(entry)
        return entry

    def cancel_queued(self, job_id: str) -> bool:
        for entry in self.queue:
            if entry["job_id"] == job_id and entry["state"] in ("queued", "waiting"):
                entry["state"] = "cancelled"
                if entry["job"].status in ("DRAFT", "READY", "FAILED"):
                    entry["job"].transition_to("CANCELLED")
                return True
        return False

    def run_queue(self) -> list[dict]:
        """Process queued jobs in order with bounded concurrency (1 lane)."""
        pending = [e for e in self.queue if e["state"] in ("queued", "waiting")]
        for index, entry in enumerate(pending):
            if entry["state"] == "cancelled":
                continue
            for other in pending[index + 1:]:
                if other["state"] == "queued":
                    other["state"] = "waiting"
            entry["state"] = "running"
            job = self.run_job(entry["job"])
            entry["state"] = "completed" if job.status in ("PUBLISHED", "SCHEDULED") else "failed"
            entry["reason"] = job.error or job.status
        return self.queue


__all__ = ["QUEUE_STATES", "PublishingManager"]
