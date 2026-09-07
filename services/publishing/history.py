"""Publication history + job persistence (§18, §19, §41).

Storage layout (project-scoped, no tokens — those live in publishing_state/):

    projects/<project_id>/publishing/jobs.json
    projects/<project_id>/publishing/history.json

§40 rule enforced structurally: records that reached a terminal state
(PUBLISHED / SCHEDULED / FAILED / CANCELLED / UNSUPPORTED) are never
rewritten — refreshes only ADD history entries for live posts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from services.publishing.models import PublishingJob

TERMINAL_STATUSES = frozenset({"PUBLISHED", "SCHEDULED", "FAILED", "CANCELLED", "UNSUPPORTED"})


def publishing_dir(project_id: str) -> str:
    if not project_id or "/" in project_id or "\\" in project_id or project_id in (".", ".."):
        raise ValueError("Project id is required for publishing storage.")
    return os.path.join("projects", project_id, "publishing")


class PublishingStore:
    """JSON-file persistence for jobs and version-pinned history."""

    def __init__(self, project_id: str, base_dir: str | None = None):
        self.project_id = project_id
        self.directory = base_dir or publishing_dir(project_id)

    # ------------------------------------------------------------- files
    def _path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def _load(self, name: str) -> dict | list:
        path = self._path(name)
        if not os.path.isfile(path):
            return {} if name == "jobs.json" else []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {} if name == "jobs.json" else []

    def _save(self, name: str, payload) -> None:
        os.makedirs(self.directory, exist_ok=True)
        with open(self._path(name), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    # -------------------------------------------------------------- jobs
    def save_job(self, job: PublishingJob) -> None:
        jobs = self._load("jobs.json")
        existing = jobs.get(job.job_id)
        if existing and existing.get("status") in TERMINAL_STATUSES and job.status not in TERMINAL_STATUSES:
            return  # §40: never rewrite a terminal record with mid-flight state
        jobs[job.job_id] = job.model_dump()
        self._save("jobs.json", jobs)

    def load_jobs(self) -> list[PublishingJob]:
        jobs = self._load("jobs.json")
        records = [PublishingJob(**record) for record in jobs.values()]
        return sorted(records, key=lambda job: job.created_at)

    def get_job(self, job_id: str) -> PublishingJob | None:
        record = self._load("jobs.json").get(job_id)
        return PublishingJob(**record) if record else None

    # ----------------------------------------------------------- history
    def append_history(self, job: PublishingJob, event: str) -> dict:
        """Append-only publication record. Never mutates existing entries."""
        entry = {
            "job_id": job.job_id,
            "platform": job.platform,
            "status": job.status,
            "event": event,
            "external_post_id": job.external_post_id,
            "external_url": job.external_url,
            "version_id": job.version_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        history = self._load("history.json")
        history.append(entry)
        self._save("history.json", history)
        return entry

    def load_history(self) -> list[dict]:
        return list(self._load("history.json"))

    def record_result(self, job: PublishingJob) -> None:
        """Persist a terminal job + its history entry in one honest step."""
        self.save_job(job)
        if job.status in TERMINAL_STATUSES:
            self.append_history(job, event="terminal")

    # --------------------------------------------------- status refresh
    def refresh_status(self, job: PublishingJob, provider) -> PublishingJob:
        """Poll the platform for live status; append history, never rewrite (§40)."""
        if not job.external_post_id:
            return job
        response = provider.get_status(job.external_post_id)
        if response.is_failure:
            return job  # keep the recorded state; platform gave no better answer
        self.append_history(job, event=f"status_refresh:{response.provider_status}")
        if job.status == "SCHEDULED" and response.provider_status == "PUBLISHED":
            job.transition_to("PUBLISHED", external_post_id=response.external_id,
                              external_url=response.external_url or job.external_url)
            self.save_job(job)
        return job

    # ----------------------------------------------------------- metrics
    def metrics_candidates(self) -> list[dict]:
        """§32: stored external ids/urls for future performance fetching."""
        return [{"job_id": job.job_id, "platform": job.platform,
                 "external_post_id": job.external_post_id, "external_url": job.external_url}
                for job in self.load_jobs()
                if job.status == "PUBLISHED" and job.external_post_id]


__all__ = ["TERMINAL_STATUSES", "publishing_dir", "PublishingStore"]
