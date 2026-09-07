"""Publishing domain models: canonical job + account records, honest statuses.

The job status vocabulary and transition map form the publishing state
machine. A job can only move along explicitly allowed edges, so e.g. a
FAILED upload can never be silently rewritten into PUBLISHED (§39).

Scheduling is timezone-aware: naive timestamps are rejected; nothing is
silently converted between timezones (§13).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

JOB_STATUSES: tuple[str, ...] = (
    "DRAFT", "READY", "UPLOADING", "PROCESSING", "SCHEDULED",
    "PUBLISHED", "FAILED", "CANCELLED", "UNSUPPORTED", "UNKNOWN",
)

# Allowed state-machine edges. Terminal success states are frozen: history
# must never be rewritten after publication (§40).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"READY", "FAILED", "CANCELLED", "UNSUPPORTED"}),
    "READY": frozenset({"UPLOADING", "SCHEDULED", "PUBLISHED", "FAILED", "CANCELLED", "UNSUPPORTED"}),
    "UPLOADING": frozenset({"PROCESSING", "SCHEDULED", "PUBLISHED", "FAILED", "UNKNOWN"}),
    "PROCESSING": frozenset({"PUBLISHED", "SCHEDULED", "FAILED", "UNKNOWN"}),
    "SCHEDULED": frozenset({"PUBLISHED", "FAILED", "CANCELLED", "UNKNOWN"}),
    "UNKNOWN": frozenset({"PUBLISHED", "SCHEDULED", "PROCESSING", "FAILED", "CANCELLED"}),
    "PUBLISHED": frozenset(),   # frozen — confirmed publications never change
    "FAILED": frozenset({"READY", "CANCELLED"}),  # retry re-queues via READY
    "CANCELLED": frozenset(),
    "UNSUPPORTED": frozenset(),
}

TERMINAL_SUCCESS = frozenset({"PUBLISHED", "SCHEDULED"})

ACCOUNT_STATES: tuple[str, ...] = ("connected", "disconnected", "expired", "needs_reauthorization")


def can_transition(current: str, target: str) -> bool:
    """True when the state machine allows moving current → target."""
    if current not in ALLOWED_TRANSITIONS:
        raise ValueError(f"Unknown publishing status: {current!r}")
    return target in ALLOWED_TRANSITIONS[current]


def parse_scheduled_at(value: str | datetime | None) -> datetime | None:
    """Parse a schedule timestamp; naive values are rejected, never assumed."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid scheduled_at timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(
            "scheduled_at must be timezone-aware (include an explicit UTC offset); "
            "GENFORGE never silently assumes a timezone."
        )
    return parsed


def ensure_future(moment: datetime | None, now: datetime | None = None) -> datetime | None:
    """Validate that a schedule lies in the future (bounded, honest check)."""
    if moment is None:
        return None
    reference = now or datetime.now(timezone.utc)
    if moment <= reference:
        raise ValueError("scheduled_at must be in the future.")
    return moment


class PublishingJob(BaseModel):
    """One canonical publishing job, bound to a specific project version."""

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: str = ""
    version_id: str = ""
    asset_path: str = ""
    platform: str
    account_id: str = ""
    status: str = "DRAFT"
    title: str = ""
    description: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    scheduled_at: str = ""
    external_post_id: str = ""
    external_url: str = ""
    idempotency_key: str = Field(default_factory=lambda: uuid4().hex)
    error: str = ""
    retry_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("platform")
    @classmethod
    def _platform_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Publishing job requires a platform.")
        return value.strip()

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in JOB_STATUSES:
            raise ValueError(f"Unknown publishing status: {value!r}. Valid: {', '.join(JOB_STATUSES)}")
        return value

    @field_validator("retry_count")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("retry_count cannot be negative.")
        return value

    @model_validator(mode="after")
    def _schedule_timezone_aware(self) -> "PublishingJob":
        parse_scheduled_at(self.scheduled_at or None)
        return self

    def transition_to(self, target: str, error: str = "",
                      external_post_id: str = "", external_url: str = "") -> None:
        """Move along the state machine; illegal moves raise loudly."""
        if not can_transition(self.status, target):
            raise ValueError(
                f"Illegal publishing transition {self.status} → {target} for job {self.job_id}."
            )
        self.status = target
        if error:
            self.error = error
        if target == "PUBLISHED" and not external_post_id:
            raise ValueError("PUBLISHED requires an external post id from the platform.")
        if external_post_id:
            self.external_post_id = external_post_id
        if external_url:
            self.external_url = external_url
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def is_terminal_success(self) -> bool:
        return self.status in TERMINAL_SUCCESS


class PublishingAccount(BaseModel):
    """A connected platform account. Holds a token REFERENCE only — never the secret."""

    account_id: str = Field(default_factory=lambda: uuid4().hex)
    platform: str
    display_name: str = ""
    external_account_id: str = ""
    connected: bool = False
    state: str = "disconnected"
    capabilities: dict[str, Any] = Field(default_factory=dict)
    token_reference: str = ""  # env var name or secret-store key — never the token itself
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("state")
    @classmethod
    def _known_state(cls, value: str) -> str:
        if value not in ACCOUNT_STATES:
            raise ValueError(f"Unknown account state: {value!r}. Valid: {', '.join(ACCOUNT_STATES)}")
        return value

    @field_validator("platform")
    @classmethod
    def _platform_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Account requires a platform.")
        return value.strip()

    def mark(self, state: str) -> None:
        if state not in ACCOUNT_STATES:
            raise ValueError(f"Unknown account state: {state!r}")
        self.state = state
        self.connected = state == "connected"
        self.updated_at = datetime.now(timezone.utc).isoformat()


__all__ = [
    "JOB_STATUSES",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_SUCCESS",
    "ACCOUNT_STATES",
    "can_transition",
    "parse_scheduled_at",
    "ensure_future",
    "PublishingJob",
    "PublishingAccount",
]
