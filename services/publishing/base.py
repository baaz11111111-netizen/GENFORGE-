"""Provider abstraction (§3) for the publishing state machine.

Every platform adapter implements BaseProvider. Responses are honest
ProviderResponse objects; errors are classified so the manager can retry
transient failures and NEVER retry invalid credentials/media (§16).

This module does not touch the legacy ``Publisher`` adapters in
services/publishing/__init__.py — those remain available unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from services.publishing.capabilities import PlatformCapabilities, capabilities_for
from services.publishing.models import PublishingJob

# Provider-side processing states (§15)
PROVIDER_STATES = ("UPLOADING", "PROCESSING", "READY", "FAILED", "PUBLISHED", "SCHEDULED")

# Error classification (§16): retryable vs. never-retry.
RETRYABLE_ERRORS = frozenset({
    "timeout", "connection_reset", "dns_failure", "server_error", "rate_limited",
})
NON_RETRYABLE_ERRORS = frozenset({
    "invalid_credentials", "expired_token", "invalid_media", "invalid_metadata",
    "permission_denied", "unsupported",
})


class ProviderError(Exception):
    """Provider failure with a machine-readable classification."""

    def __init__(self, kind: str, message: str, retry_after_seconds: float | None = None):
        if kind not in RETRYABLE_ERRORS and kind not in NON_RETRYABLE_ERRORS and kind != "unknown":
            raise ValueError(f"Unknown provider error kind: {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_ERRORS


@dataclass
class ProviderResponse:
    """One truthful provider answer. No fabricated success."""

    provider_status: str  # one of PROVIDER_STATES
    external_id: str = ""
    external_url: str = ""
    message: str = ""
    error_kind: str = ""
    retry_after_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provider_status not in PROVIDER_STATES:
            raise ValueError(
                f"Unknown provider status {self.provider_status!r}. Valid: {', '.join(PROVIDER_STATES)}"
            )
        if self.provider_status == "PUBLISHED" and not self.external_id:
            raise ValueError("A PUBLISHED provider response requires the platform's external id.")

    @property
    def is_failure(self) -> bool:
        return self.provider_status == "FAILED"

    @property
    def retryable(self) -> bool:
        return self.error_kind in RETRYABLE_ERRORS


class BaseProvider(ABC):
    """Common publishing interface (§3)."""

    provider_name: str = "base"
    platform: str = ""

    @property
    def capabilities(self) -> PlatformCapabilities:
        return capabilities_for(self.platform)

    @abstractmethod
    def authenticate(self) -> bool:
        """True when credentials are present and valid."""

    def validate_asset(self, job: PublishingJob) -> list[str]:
        """Platform-specific pre-upload asset checks. Empty list = valid."""
        return []

    @abstractmethod
    def upload(self, job: PublishingJob) -> ProviderResponse:
        """Start the upload. Must not claim publication."""

    def check_processing(self, job: PublishingJob) -> ProviderResponse:
        """Poll processing state (bounded by the manager, never forever)."""
        return ProviderResponse(provider_status="READY", message="Provider reports no processing stage.")

    @abstractmethod
    def publish(self, job: PublishingJob) -> ProviderResponse:
        """Finalize publication. Only PUBLISHED with a platform external id."""

    def schedule(self, job: PublishingJob) -> ProviderResponse:
        if not self.capabilities.scheduling:
            return ProviderResponse(
                provider_status="FAILED", error_kind="unsupported",
                message=f"Platform scheduling unsupported for {self.platform}.",
            )
        raise NotImplementedError

    def get_status(self, external_id: str) -> ProviderResponse:
        return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                message="Status lookup unsupported.")

    def get_post(self, external_id: str) -> ProviderResponse:
        """Idempotency helper (§17): does this post already exist upstream?"""
        return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                message="Post lookup unsupported.")

    def cancel(self, job: PublishingJob) -> ProviderResponse:
        return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                message="Cancellation unsupported.")

    def disconnect(self) -> None:
        """Drop local session state. Never logs or echoes credentials."""

    def get_metrics(self, external_id: str) -> ProviderResponse:
        """Future performance foundation (§33). Unsupported by default."""
        return ProviderResponse(provider_status="FAILED", error_kind="unsupported",
                                message="Metrics unsupported by this provider.")


__all__ = [
    "PROVIDER_STATES",
    "RETRYABLE_ERRORS",
    "NON_RETRYABLE_ERRORS",
    "ProviderError",
    "ProviderResponse",
    "BaseProvider",
]
