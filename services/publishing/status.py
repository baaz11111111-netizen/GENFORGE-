"""
Publishing status abstraction for GENFORGE.

Provides clear status information about publishing mode, platform connectivity,
and capabilities to ensure users understand whether they're publishing to real
platforms or using mock/simulation mode.
"""

from typing import Literal, Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class PlatformStatus:
    """Status information for a single platform."""
    platform_id: str
    name: str
    is_connected: bool
    is_mock: bool
    status_message: str
    capabilities: List[str]


def get_publishing_mode() -> Literal["real", "mock"]:
    """
    Determine if the application is in real or mock publishing mode.
    
    Returns:
        "real" if configured for actual platform publishing
        "mock" if using simulation/test mode
    """
    # Check for real API credentials or webhook URLs
    # This is a simplified check - in production you'd check actual config
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Check if any real platform credentials are configured
    has_real_credentials = any([
        os.getenv("YOUTUBE_CLIENT_ID"),
        os.getenv("TIKTOK_API_KEY"),
        os.getenv("INSTAGRAM_ACCESS_TOKEN"),
        os.getenv("LINKEDIN_ACCESS_TOKEN"),
        os.getenv("N8N_WEBHOOK_URL"),
    ])
    
    return "real" if has_real_credentials else "mock"


def is_mock_mode() -> bool:
    """Check if currently in mock/simulation mode."""
    return get_publishing_mode() == "mock"


def get_mock_warning() -> str:
    """Get a user-friendly warning message for mock mode."""
    return (
        "⚠️ **Mock Publishing Mode Active** — "
        "Posts will be simulated but not actually published to platforms. "
        "Configure API credentials in `.env` to enable real publishing."
    )


def get_platform_status(platform_id: str) -> PlatformStatus:
    """
    Get detailed status for a specific platform.
    
    Args:
        platform_id: Platform identifier (youtube, tiktok, instagram, linkedin, n8n)
    
    Returns:
        PlatformStatus object with connection and capability info
    """
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Platform configuration mapping
    platform_configs = {
        "youtube": {
            "name": "YouTube",
            "env_key": "YOUTUBE_CLIENT_ID",
            "capabilities": ["Video Upload", "Shorts", "Community Posts", "Scheduling"],
        },
        "tiktok": {
            "name": "TikTok",
            "env_key": "TIKTOK_API_KEY",
            "capabilities": ["Video Upload", "Captions", "Hashtags"],
        },
        "instagram": {
            "name": "Instagram",
            "env_key": "INSTAGRAM_ACCESS_TOKEN",
            "capabilities": ["Posts", "Stories", "Reels", "Carousel"],
        },
        "linkedin": {
            "name": "LinkedIn",
            "env_key": "LINKEDIN_ACCESS_TOKEN",
            "capabilities": ["Posts", "Articles", "Video", "Images"],
        },
        "n8n": {
            "name": "n8n Webhook",
            "env_key": "N8N_WEBHOOK_URL",
            "capabilities": ["Custom Workflows", "Multi-Platform", "Automation"],
        },
    }
    
    config = platform_configs.get(platform_id, {
        "name": platform_id.title(),
        "env_key": None,
        "capabilities": [],
    })
    
    is_connected = bool(os.getenv(config.get("env_key", "")))
    is_mock = not is_connected
    
    if is_connected:
        status_msg = "✓ Connected"
    else:
        status_msg = "⚠ Not Configured (Mock Mode)"
    
    return PlatformStatus(
        platform_id=platform_id,
        name=config["name"],
        is_connected=is_connected,
        is_mock=is_mock,
        status_message=status_msg,
        capabilities=config.get("capabilities", []),
    )


def get_platform_capabilities_with_status() -> Dict[str, PlatformStatus]:
    """
    Get status and capabilities for all supported platforms.
    
    Returns:
        Dictionary mapping platform_id to PlatformStatus
    """
    platforms = ["youtube", "tiktok", "instagram", "linkedin", "n8n"]
    return {pid: get_platform_status(pid) for pid in platforms}


def format_platform_status_badge(status: PlatformStatus) -> Tuple[str, str]:
    """
    Format a platform status as (label, variant) for use with badge() component.
    
    Returns:
        Tuple of (label_text, badge_variant) where variant is "ok", "warn", or "err"
    """
    if status.is_connected:
        return ("CONNECTED", "ok")
    else:
        return ("MOCK MODE", "warn")


def get_post_confirmation_message(platform_id: str, is_mock: bool) -> str:
    """
    Get appropriate confirmation message after posting.
    
    Args:
        platform_id: Platform where post was sent
        is_mock: Whether this was a mock/simulated post
    
    Returns:
        User-friendly confirmation message
    """
    platform_name = get_platform_status(platform_id).name
    
    if is_mock:
        return (
            f"✓ **Mock post created for {platform_name}** — "
            f"This was a simulation. The post was not actually published. "
            f"Configure {platform_name} API credentials to enable real publishing."
        )
    else:
        return (
            f"✓ **Successfully published to {platform_name}** — "
            f"Your content is now live on the platform."
        )


# Backward compatibility aliases
def get_publishing_status_summary() -> str:
    """Get a summary of current publishing status for display."""
    mode = get_publishing_mode()
    if mode == "mock":
        return get_mock_warning()
    else:
        connected = [s for s in get_platform_capabilities_with_status().values() if s.is_connected]
        return f"✓ **Real Publishing Active** — {len(connected)} platform(s) connected"
