"""Phase 11 — Publishing adapter regression tests (truthfulness guarantees)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from services.publishing import (
    OFFICIAL_API_REQUIRED,
    PlatformPublisher,
    PublishRequest,
    PublishResult,
    WebhookPublisher,
    publish_campaign_assets,
    publisher_for,
)


def _asset(tmp_path: Path) -> str:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom")
    return str(path)


class _Handler(BaseHTTPRequestHandler):
    received: list[dict] = []
    reply_status = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _Handler.received.append(json.loads(self.rfile.read(length)))
        self.send_response(_Handler.reply_status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def local_webhook():
    _Handler.received = []
    _Handler.reply_status = 200
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/publish"
    server.shutdown()


class TestGuards:
    def test_missing_asset_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            PublishRequest(platform="TikTok", asset_path=str(tmp_path / "missing.mp4"))

    def test_blank_platform_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            PublishRequest(platform="  ", asset_path=_asset(tmp_path))

    def test_published_without_confirmation_is_impossible(self):
        with pytest.raises(ValueError, match="requires explicit confirmation"):
            PublishResult(provider="x", status="published", message="fake", confirmed=False)

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError, match="Unknown publish status"):
            PublishResult(provider="x", status="went_great", message="m")


class TestWebhookPublisher:
    def test_unauthenticated_without_endpoint(self, tmp_path):
        publisher = WebhookPublisher()
        request = PublishRequest(platform="Webhook", asset_path=_asset(tmp_path))
        result = publisher.publish(request)
        assert result.status == "unauthenticated" and result.confirmed is False

    def test_confirmed_publish_against_live_endpoint(self, tmp_path, local_webhook):
        publisher = WebhookPublisher(local_webhook)
        assert publisher.authenticate() is True
        request = PublishRequest(platform="Webhook", asset_path=_asset(tmp_path), title="Launch")
        result = publisher.publish(request)
        assert result.status == "published" and result.confirmed is True
        assert result.external_id
        assert _Handler.received[0]["mode"] == "publish"
        assert _Handler.received[0]["title"] == "Launch"

        lookup = publisher.status(result.external_id)
        assert lookup.status == "published" and lookup.confirmed is True

    def test_non_confirming_endpoint_is_not_success(self, tmp_path, local_webhook):
        _Handler.reply_status = 500
        publisher = WebhookPublisher(local_webhook)
        result = publisher.publish(PublishRequest(platform="Webhook", asset_path=_asset(tmp_path)))
        assert result.status == "failed" and result.confirmed is False

    def test_schedule_requires_timestamp(self, tmp_path, local_webhook):
        publisher = WebhookPublisher(local_webhook)
        result = publisher.schedule(PublishRequest(platform="Webhook", asset_path=_asset(tmp_path)))
        assert result.status == "failed"
        with_time = publisher.schedule(PublishRequest(
            platform="Webhook", asset_path=_asset(tmp_path), scheduled_at="2026-09-01T09:00:00Z"))
        assert with_time.status == "scheduled" and with_time.confirmed is True

    def test_status_of_unknown_publication_fails(self):
        assert WebhookPublisher("http://example.com").status("missing").status == "failed"


class TestPlatformPublisher:
    def test_no_credentials_means_unauthenticated(self, tmp_path):
        publisher = PlatformPublisher()
        request = PublishRequest(platform="TikTok", asset_path=_asset(tmp_path))
        result = publisher.publish(request)
        assert result.status == "unauthenticated"
        assert "UNAUTHENTICATED" in result.message
        assert "OAuth" in result.message or "credentials" in result.message
        assert result.confirmed is False

    def test_unknown_platform_is_unsupported(self, tmp_path):
        publisher = PlatformPublisher()
        request = PublishRequest(platform="MySpace", asset_path=_asset(tmp_path))
        result = publisher.publish(request)
        assert result.status == "unsupported" and result.message.startswith("UNSUPPORTED")

    def test_real_transport_confirmation(self, tmp_path):
        publisher = PlatformPublisher(transport=lambda req, mode: "yt-12345")
        request = PublishRequest(platform="YouTube", asset_path=_asset(tmp_path))
        result = publisher.publish(request)
        assert result.status == "published" and result.external_id == "yt-12345"
        assert publisher.status("yt-12345").confirmed is True

    def test_transport_rejection_is_failure(self, tmp_path):
        publisher = PlatformPublisher(transport=lambda req, mode: False)
        result = publisher.publish(PublishRequest(platform="TikTok", asset_path=_asset(tmp_path)))
        assert result.status == "failed" and result.confirmed is False

    def test_transport_exception_is_failure(self, tmp_path):
        def broken(req, mode):
            raise ConnectionError("API down")
        publisher = PlatformPublisher(transport=broken)
        result = publisher.publish(PublishRequest(platform="YouTube", asset_path=_asset(tmp_path)))
        assert result.status == "failed" and "API down" in result.message

    def test_all_documented_platforms_require_official_apis(self):
        assert set(OFFICIAL_API_REQUIRED) == {"TikTok", "Instagram Reels", "YouTube Shorts", "YouTube", "Square Feed"}


class TestCampaignDispatch:
    def _campaign(self, clip_path: str | None) -> dict:
        clip_entry = ({"status": "rendered", "path": clip_path} if clip_path
                      else {"status": "unavailable", "path": None})
        return {"brief": {"platforms": ["TikTok", "YouTube"], "topic": "Launch"},
                "assets": {"clips": [clip_entry]}}

    def test_no_rendered_clip_publishes_nothing(self):
        campaign = self._campaign(None)
        history = publish_campaign_assets(campaign)
        assert len(history) == 2
        assert all(entry["status"] == "failed" for entry in history)
        assert campaign["publish_history"] == history

    def test_rendered_clip_reports_honest_per_platform_status(self, tmp_path):
        campaign = self._campaign(_asset(tmp_path))
        history = publish_campaign_assets(campaign)
        assert len(history) == 2
        # No credentials configured → unauthenticated, never "published".
        assert all(entry["status"] == "unauthenticated" and entry["confirmed"] is False for entry in history)

    def test_explicit_platform_list_overrides_brief(self, tmp_path):
        campaign = self._campaign(_asset(tmp_path))
        history = publish_campaign_assets(campaign, platforms=["MySpace"])
        assert history[0]["status"] == "unsupported"

    def test_requires_campaign_workspace(self):
        with pytest.raises(ValueError):
            publish_campaign_assets({})

    def test_publisher_routing(self):
        assert publisher_for("Webhook").provider_name == "webhook"
        assert publisher_for("TikTok").provider_name == "platform_api"
