"""Phase 10 — real provider adapters against scripted transports (§37).

No network is touched: every platform response is scripted through
FakeTransport. Real-API smoke tests are deliberately NOT part of this suite.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services.publishing.accounts import TokenStore
from services.publishing.http_client import HttpResponse, TransportError
from services.publishing.instagram import InstagramProvider
from services.publishing.linkedin import LinkedInProvider
from services.publishing.manager import PublishingManager
from services.publishing.models import PublishingJob
from services.publishing.registry import provider_for, real_provider_for
from services.publishing.tiktok import TikTokProvider
from services.publishing.youtube import YouTubeProvider

FUTURE = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
HOSTED = "https://cdn.example/clip.mp4"

# Deterministic synthetic media from the conftest `media` fixture: the suite
# is self-contained on a clean checkout (no pre-existing temp/ files needed).
MEDIA: dict[str, str] = {}


@pytest.fixture(scope="session", autouse=True)
def _bind_synthetic_media(media):
    MEDIA.update(vars(media))


class FakeTransport:
    """Scripted platform: each entry is an HttpResponse or an Exception."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, headers=None, json_body=None, data=None, timeout=30.0):
        self.calls.append((method, url))
        if not self.responses:
            raise AssertionError(f"Unscripted {method} {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(body, headers=None):
    return HttpResponse(status=200, body=body, headers=headers or {})


def err(status, body=None, headers=None):
    return HttpResponse(status=status, body=body or {"error": {"message": f"HTTP {status}"}},
                        headers=headers or {})


@pytest.fixture()
def store(tmp_path):
    token_store = TokenStore(secrets_path=str(tmp_path / "secrets.json"))
    token_store.store("test:token", "SECRET-VALUE")
    return token_store


REF = "store:test:token"


def _job(**kwargs):
    base = {"platform": "YouTube", "asset_path": MEDIA["landscape"], "title": "Launch"}
    base.update(kwargs)
    return PublishingJob(**base)


def _manager(provider):
    return PublishingManager(provider, sleep_fn=lambda _s: None)


# ------------------------------------------------------------------ YouTube
class TestYouTubeAdapter:
    def _provider(self, store, responses):
        return YouTubeProvider(token_reference=REF, token_store=store,
                               transport=FakeTransport(responses))

    def test_happy_path_publishes_only_after_confirmation(self, store):
        provider = self._provider(store, [
            ok({"sub": "user-1"}),                                          # authenticate ping
            ok({"id": "vid1"}),                                             # upload
            ok({"items": [{"processingDetails": {"processingStatus": "succeeded"}}]}),
            ok({"id": "vid1"}),                                             # PATCH public
            ok({"items": [{"status": {"privacyStatus": "public"},
                            "processingDetails": {"processingStatus": "succeeded"}}]}),
        ])
        job = _job()
        result = _manager(provider).run_job(job)
        assert result.status == "PUBLISHED" and result.external_post_id == "vid1"
        assert result.external_url == "https://www.youtube.com/watch?v=vid1"

    def test_scheduling_uses_publish_at_with_private(self, store):
        provider = self._provider(store, [
            ok({"sub": "user-1"}),
            ok({"id": "vid2"}),
            ok({"items": [{"processingDetails": {"processingStatus": "succeeded"}}]}),
            ok({"id": "vid2"}),                                             # PATCH publishAt
            ok({"items": [{"status": {"privacyStatus": "private", "publishAt": FUTURE}}]}),
        ])
        job = _job(scheduled_at=FUTURE)
        result = _manager(provider).run_job(job)
        assert result.status == "SCHEDULED" and result.external_post_id == "vid2"

    def test_expired_token_never_retried(self, store):
        provider = self._provider(store, [err(401)])
        response = provider.upload(_job())
        assert response.error_kind == "expired_token" and not response.retryable

    def test_rate_limit_is_retryable_and_honors_retry_after(self, store):
        provider = self._provider(store, [err(429, headers={"Retry-After": "7"})])
        response = provider.upload(_job())
        assert response.error_kind == "rate_limited" and response.retryable
        assert response.retry_after_seconds == 7.0

    def test_permission_denied_classified(self, store):
        provider = self._provider(store, [err(403)])
        response = provider.upload(_job())
        assert response.error_kind == "permission_denied" and not response.retryable

    def test_network_timeout_classified(self, store):
        provider = self._provider(store, [TransportError("read timeout")])
        response = provider.upload(_job())
        assert response.error_kind == "timeout" and response.retryable

    def test_processing_failure_is_permanent(self, store):
        provider = self._provider(store, [
            ok({"items": [{"processingDetails": {"processingStatus": "failed"}}]}),
        ])
        job = _job(external_post_id="vidX", status="READY")
        response = provider.check_processing(job)
        assert response.provider_status == "FAILED" and response.error_kind == "invalid_media"

    def test_metrics_from_statistics(self, store):
        provider = self._provider(store, [ok({"items": [{"statistics": {"viewCount": "10", "likeCount": "2"}}]})])
        response = provider.get_metrics("vid1")
        assert response.metadata == {"views": "10", "likes": "2"}

    def test_no_token_means_invalid_credentials(self, store):
        provider = YouTubeProvider(token_reference="store:missing:key", token_store=store,
                                   transport=FakeTransport([]))
        response = provider.upload(_job())
        assert response.error_kind == "invalid_credentials"


# ---------------------------------------------------------------- Instagram
class TestInstagramAdapter:
    def test_local_file_is_honestly_rejected(self, store):
        provider = InstagramProvider(token_reference=REF, token_store=store,
                                     transport=FakeTransport([]), external_account_id="ig-1")
        response = provider.upload(_job(platform="Instagram Reels"))
        assert response.error_kind == "invalid_media" and "hosted" in response.message

    def test_two_step_flow_with_hosted_url(self, store):
        provider = InstagramProvider(token_reference=REF, token_store=store,
                                     transport=FakeTransport([
                                         ok({"id": "ig-user"}),             # authenticate ping
                                         ok({"id": "container1"}),          # create container
                                         ok({"status_code": "IN_PROGRESS"}),
                                         ok({"status_code": "FINISHED"}),
                                         ok({"id": "media1"}),              # media_publish
                                         ok({"id": "media1", "permalink": "https://instagram.example/reel/media1"}),
                                     ]), external_account_id="ig-1")
        job = _job(platform="Instagram Reels", asset_path=HOSTED)
        result = _manager(provider).run_job(job)
        assert result.status == "PUBLISHED" and result.external_post_id == "media1"

    def test_scheduling_officially_unsupported(self, store):
        provider = InstagramProvider(token_reference=REF, token_store=store,
                                     transport=FakeTransport([]), external_account_id="ig-1")
        response = provider.schedule(_job(platform="Instagram Reels", scheduled_at=FUTURE))
        assert response.error_kind == "unsupported" and "scheduling unsupported" in response.message

    def test_missing_ig_user_id_rejected(self, store):
        provider = InstagramProvider(token_reference=REF, token_store=store,
                                     transport=FakeTransport([]))
        response = provider.upload(_job(platform="Instagram Reels", asset_path=HOSTED))
        assert response.error_kind == "invalid_credentials"


# -------------------------------------------------------------------- TikTok
class TestTikTokAdapter:
    def _provider(self, store, responses):
        return TikTokProvider(token_reference=REF, token_store=store,
                              transport=FakeTransport(responses))

    def test_happy_path_confirms_publish_complete(self, store):
        provider = self._provider(store, [
            ok({"data": {"open_id": "tk-user"}}),                            # authenticate ping
            ok({"data": {"publish_id": "p1", "upload_url": "https://up.example"}}),  # init
            ok(""),                                                                  # PUT binary
            ok({"data": {"status": "PROCESSING_UPLOAD"}}),
            ok({"data": {"status": "PUBLISH_COMPLETE", "share_url": "https://tk.example/v/1"}}),
            ok({"data": {"status": "PUBLISH_COMPLETE", "share_url": "https://tk.example/v/1"}}),
            ok({"data": {"status": "PUBLISH_COMPLETE", "share_url": "https://tk.example/v/1"}}),
        ])
        job = _job(platform="TikTok", asset_path=MEDIA["portrait"])
        result = _manager(provider).run_job(job)
        assert result.status == "PUBLISHED" and result.external_post_id == "p1"
        assert result.external_url == "https://tk.example/v/1"

    def test_upload_message_is_honest_about_self_only(self, store):
        provider = self._provider(store, [
            ok({"data": {"publish_id": "p2", "upload_url": "https://up.example"}}),
            ok(""),
        ])
        response = provider.upload(_job(platform="TikTok", asset_path=MEDIA["portrait"]))
        assert "SELF_ONLY" in response.message  # unaudited apps: no invented reach

    def test_schedule_window_is_official_15min_to_10days(self, store):
        provider = self._provider(store, [])
        far = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        response = provider.upload(_job(platform="TikTok", asset_path=MEDIA["portrait"], scheduled_at=far))
        assert response.error_kind == "invalid_metadata" and "+15 minutes" in response.message

    def test_scheduled_flow_confirms_schedule(self, store):
        provider = self._provider(store, [
            ok({"data": {"open_id": "tk-user"}}),
            ok({"data": {"publish_id": "p3", "upload_url": "https://up.example"}}),
            ok(""),
            ok({"data": {"status": "SCHEDULED"}}),
            ok({"data": {"status": "SCHEDULED"}}),
            ok({"data": {"status": "SCHEDULED"}}),
        ])
        job = _job(platform="TikTok", asset_path=MEDIA["portrait"], scheduled_at=FUTURE)
        result = _manager(provider).run_job(job)
        assert result.status == "SCHEDULED" and result.external_post_id == "p3"

    def test_invalid_media_from_platform(self, store):
        provider = self._provider(store, [err(400, {"error": {"message": "video format invalid"}})])
        response = provider.upload(_job(platform="TikTok", asset_path=MEDIA["portrait"]))
        assert response.error_kind == "invalid_media" and not response.retryable


# ------------------------------------------------------------------ LinkedIn
class TestLinkedInAdapter:
    def _provider(self, store, responses, member="abc123"):
        return LinkedInProvider(token_reference=REF, token_store=store,
                                transport=FakeTransport(responses), external_account_id=member)

    def test_happy_path(self, store):
        provider = self._provider(store, [
            ok({"sub": "li-user"}),                                          # authenticate ping
            ok({"value": {"uploadUrl": "https://up.example", "video": "urn:li:video:9"}}),
            ok(""),                                                                  # PUT binary
            ok({"status": "AVAILABLE"}),
            ok({"id": "urn:li:share:55"}, headers={"x-restli-id": "urn:li:share:55"}),
            ok({"lifecycleState": "PUBLISHED"}),
        ])
        job = _job(platform="LinkedIn")
        result = _manager(provider).run_job(job)
        assert result.status == "PUBLISHED" and result.external_post_id == "urn:li:share:55"
        assert "linkedin.com" in result.external_url

    def test_schedule_uses_scheduled_publish_time(self, store):
        provider = self._provider(store, [
            ok({"sub": "li-user"}),
            ok({"value": {"uploadUrl": "https://up.example", "video": "urn:li:video:10"}}),
            ok(""),
            ok({"status": "AVAILABLE"}),
            ok({"id": "urn:li:share:56"}),
            ok({"lifecycleState": "SCHEDULED"}),
        ])
        job = _job(platform="LinkedIn", scheduled_at=FUTURE)
        result = _manager(provider).run_job(job)
        assert result.status == "SCHEDULED"
        create_call = provider.transport.calls[4]
        assert create_call[0] == "POST" and create_call[1].endswith("/rest/posts")

    def test_missing_member_urn_rejected(self, store):
        provider = self._provider(store, [], member="")
        response = provider.upload(_job(platform="LinkedIn"))
        assert response.error_kind == "invalid_credentials"

    def test_server_error_is_retryable(self, store):
        provider = self._provider(store, [err(503)])
        response = provider.upload(_job(platform="LinkedIn"))
        assert response.error_kind == "server_error" and response.retryable


# ------------------------------------------------------------------ registry
class TestRegistry:
    def test_mock_mode_default(self):
        provider = provider_for("TikTok")
        assert provider.provider_name == "mock"

    def test_real_mode_returns_official_adapters(self, store):
        mapping = {"YouTube": YouTubeProvider, "YouTube Shorts": YouTubeProvider,
                   "Instagram Reels": InstagramProvider, "Square Feed": InstagramProvider,
                   "TikTok": TikTokProvider, "LinkedIn": LinkedInProvider}
        for platform, cls in mapping.items():
            assert isinstance(provider_for(platform, mode="real", token_reference=REF,
                                           token_store=store), cls), platform

    def test_unknown_platform_rejected_never_invented(self):
        with pytest.raises(ValueError):
            real_provider_for("MySpace")
        with pytest.raises(ValueError):
            real_provider_for("Webhook")
        with pytest.raises(ValueError):
            provider_for("YouTube", mode="teleport")

    def test_shorts_variant_capability_matrix(self):
        provider = real_provider_for("YouTube Shorts")
        assert provider.platform == "YouTube Shorts" and provider.capabilities.scheduling
