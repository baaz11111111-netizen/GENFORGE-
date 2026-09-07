"""Provider registry (§3): one factory for mock + real adapters."""

from __future__ import annotations

from services.publishing.accounts import TokenStore
from services.publishing.base import BaseProvider
from services.publishing.instagram import InstagramProvider
from services.publishing.linkedin import LinkedInProvider
from services.publishing.mock import MockPlatformProvider
from services.publishing.tiktok import TikTokProvider
from services.publishing.youtube import YouTubeProvider


def real_provider_for(platform: str, token_reference: str = "", token_store: TokenStore | None = None,
                      transport=None, external_account_id: str = "") -> BaseProvider:
    """Official adapters only (§4). Unknown platforms are rejected, never invented."""
    kwargs = {"token_reference": token_reference, "token_store": token_store,
              "transport": transport, "external_account_id": external_account_id}
    if platform == "YouTube":
        return YouTubeProvider(**kwargs)
    if platform == "YouTube Shorts":
        return YouTubeProvider(shorts=True, **kwargs)
    if platform == "Instagram Reels":
        return InstagramProvider(**kwargs)
    if platform == "Square Feed":
        return InstagramProvider(square_feed=True, **kwargs)
    if platform == "TikTok":
        return TikTokProvider(**kwargs)
    if platform == "LinkedIn":
        return LinkedInProvider(**kwargs)
    if platform == "Webhook":
        raise ValueError("Webhook publishing uses the legacy WebhookPublisher, not a platform adapter.")
    raise ValueError(f"No official adapter exists for platform {platform!r}.")


def provider_for(platform: str, mode: str = "mock", **kwargs) -> BaseProvider:
    """mode='mock' for tests/demos, mode='real' for official adapters."""
    if mode == "mock":
        return MockPlatformProvider(platform=platform,
                                    scenario=kwargs.get("scenario", "normal"))
    if mode == "real":
        return real_provider_for(platform, **{k: v for k, v in kwargs.items()
                                              if k in ("token_reference", "token_store",
                                                       "transport", "external_account_id")})
    raise ValueError(f"Unknown provider mode: {mode!r}")


__all__ = ["real_provider_for", "provider_for"]
