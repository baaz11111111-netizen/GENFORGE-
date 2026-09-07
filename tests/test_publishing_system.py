"""Publishing system — Phases 1–11: models → pipeline → adapters → history."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from services.publishing.accounts import AccountStore, TokenStore, mask_token
from services.publishing.batch import (build_batch, build_batch_item, pairs_for_campaign,
                                       pairs_for_project, queue_batch)
from services.publishing.capabilities import PLATFORM_CAPABILITIES, capabilities_for, supports
from services.publishing.base import (NON_RETRYABLE_ERRORS, PROVIDER_STATES,
                                      ProviderError, ProviderResponse, RETRYABLE_ERRORS)
from services.publishing.manager import QUEUE_STATES, PublishingManager
from services.publishing.mock import MockPlatformProvider, SCENARIOS
from services.publishing.history import PublishingStore, publishing_dir
from services.publishing.n8n import (build_n8n_payload, notify_n8n, scrub_secrets,
                                     validate_webhook_url)
from services.publishing.models import (ALLOWED_TRANSITIONS, ACCOUNT_STATES,
                                        JOB_STATUSES, PublishingAccount, PublishingJob,
                                        can_transition, ensure_future, parse_scheduled_at)
from services.publishing.validation import (METADATA_LIMITS, pre_publish_checklist,
                                            validate_asset, validate_metadata,
                                            validate_schedule)

FUTURE = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

# Deterministic synthetic media from the conftest `media` fixture: the suite
# is self-contained on a clean checkout (no pre-existing temp/ files needed).
MEDIA: dict[str, str] = {}


@pytest.fixture(scope="session", autouse=True)
def _bind_synthetic_media(media):
    MEDIA.update(vars(media))


def _job(**kwargs) -> PublishingJob:
    base = {"platform": "TikTok", "asset_path": MEDIA["lowres"]}
    base.update(kwargs)
    return PublishingJob(**base)


class TestDomainModels:
    def test_job_defaults_to_draft(self):
        job = _job()
        assert job.status == "DRAFT" and job.retry_count == 0
        assert job.idempotency_key and job.job_id

    def test_status_vocabulary_complete(self):
        assert set(JOB_STATUSES) == {"DRAFT", "READY", "UPLOADING", "PROCESSING", "SCHEDULED",
                                     "PUBLISHED", "FAILED", "CANCELLED", "UNSUPPORTED", "UNKNOWN"}
        assert set(ALLOWED_TRANSITIONS) == set(JOB_STATUSES)

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError):
            _job(status="LIVE")

    def test_happy_path_transitions(self):
        job = _job()
        for target in ("READY", "UPLOADING", "PROCESSING"):
            job.transition_to(target)
        job.transition_to("PUBLISHED", external_post_id="ext-1", external_url="https://x/1")
        assert job.status == "PUBLISHED" and job.external_post_id == "ext-1"
        assert job.is_terminal_success()

    def test_published_requires_external_id(self):
        job = _job()
        job.transition_to("READY")
        job.transition_to("UPLOADING")
        with pytest.raises(ValueError, match="external post id"):
            job.transition_to("PUBLISHED")

    def test_published_record_is_frozen(self):
        job = _job(status="PUBLISHED", external_post_id="ext-9")
        with pytest.raises(ValueError, match="Illegal publishing transition"):
            job.transition_to("FAILED")  # §40: history is never rewritten

    def test_failed_can_retry_via_ready(self):
        job = _job()
        job.transition_to("READY")
        job.transition_to("FAILED", error="timeout")
        job.transition_to("READY")
        assert job.status == "READY" and job.error == "timeout"

    def test_illegal_skip_rejected(self):
        job = _job()
        assert can_transition("DRAFT", "PUBLISHED") is False
        with pytest.raises(ValueError):
            job.transition_to("PUBLISHED", external_post_id="x")

    def test_schedule_must_be_timezone_aware(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            _job(scheduled_at="2027-01-01T09:00:00")  # naive → rejected, never assumed
        job = _job(scheduled_at=FUTURE)
        assert parse_scheduled_at(job.scheduled_at).tzinfo is not None

    def test_schedule_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_scheduled_at("next tuesday")

    def test_ensure_future_rejects_past(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with pytest.raises(ValueError, match="future"):
            ensure_future(past)

    def test_account_model(self):
        account = PublishingAccount(platform="YouTube", display_name="Chan")
        assert account.state == "disconnected" and account.connected is False
        account.mark("connected")
        assert account.connected is True
        account.mark("expired")
        assert account.state == "expired" and account.connected is False
        assert set(ACCOUNT_STATES) == {"connected", "disconnected", "expired", "needs_reauthorization"}
        with pytest.raises(ValueError):
            account.mark("vibing")


class TestCapabilityMatrix:
    def test_all_documented_platforms_present(self):
        assert set(PLATFORM_CAPABILITIES) == {"YouTube", "YouTube Shorts", "Instagram Reels",
                                              "Square Feed", "TikTok", "LinkedIn", "Webhook"}

    def test_instagram_honestly_lacks_scheduling(self):
        caps = capabilities_for("Instagram Reels")
        assert caps.scheduling is False and caps.thumbnail is False and caps.captions is False
        assert supports("Instagram Reels", "scheduling") is False

    def test_youtube_full_capabilities(self):
        assert supports("YouTube", "scheduling") and supports("YouTube", "captions")
        assert supports("YouTube", "thumbnail") and supports("YouTube", "processing_status")

    def test_tiktok_scheduling_but_no_thumbnail(self):
        assert supports("TikTok", "scheduling") and not supports("TikTok", "thumbnail")

    def test_unknown_platform_or_capability_rejected(self):
        with pytest.raises(ValueError):
            capabilities_for("MySpace")
        with pytest.raises(ValueError):
            supports("TikTok", "teleport")

    def test_as_dict_exposes_ui_flags(self):
        payload = capabilities_for("LinkedIn").as_dict()
        assert payload["scheduling"] is True and "notes" not in payload


class TestProviderContract:
    def test_provider_response_guards(self):
        with pytest.raises(ValueError, match="Unknown provider status"):
            ProviderResponse(provider_status="DONE")
        with pytest.raises(ValueError, match="external id"):
            ProviderResponse(provider_status="PUBLISHED")
        assert set(PROVIDER_STATES) == {"UPLOADING", "PROCESSING", "READY", "FAILED",
                                        "PUBLISHED", "SCHEDULED"}

    def test_error_classification(self):
        assert ProviderError("timeout", "slow").retryable is True
        assert ProviderError("invalid_credentials", "bad").retryable is False
        assert RETRYABLE_ERRORS & NON_RETRYABLE_ERRORS == set()
        with pytest.raises(ValueError):
            ProviderError("mystery", "?")


class TestMockProvider:
    def test_unknown_scenario_rejected(self):
        with pytest.raises(ValueError):
            MockPlatformProvider(scenario="explode")

    def test_upload_processing_publish_flow(self):
        provider = MockPlatformProvider(platform="TikTok", processing_steps=2)
        job = _job()
        upload = provider.upload(job)
        assert upload.provider_status == "UPLOADING"
        assert provider.check_processing(job).provider_status == "PROCESSING"
        assert provider.check_processing(job).provider_status == "PROCESSING"
        assert provider.check_processing(job).provider_status == "READY"
        published = provider.publish(job)
        assert published.provider_status == "PUBLISHED" and published.external_id
        assert published.external_url.startswith("https://")

    def test_idempotent_replay_prevents_duplicates(self):
        provider = MockPlatformProvider()
        job = _job()
        first = provider.publish(job)
        second = provider.publish(job)
        assert first.external_id == second.external_id
        assert second.metadata.get("idempotent_replay") is True
        assert len(provider._posts) == 1  # never POST 1 + DUPLICATE

    def test_scenario_failures_are_classified(self):
        cases = {
            "rate_limited": "rate_limited", "timeout": "timeout",
            "expired_token": "expired_token", "permission_denied": "permission_denied",
            "invalid_media": "invalid_media", "server_error": "server_error",
        }
        for scenario, kind in cases.items():
            provider = MockPlatformProvider(scenario=scenario)
            response = provider.upload(_job())
            assert response.provider_status == "FAILED", scenario
            assert response.error_kind == kind, scenario
            assert response.retryable == (kind in RETRYABLE_ERRORS), scenario

    def test_schedule_flow_and_cancel(self):
        provider = MockPlatformProvider(platform="YouTube")
        job = _job(platform="YouTube", scheduled_at=FUTURE)
        scheduled = provider.schedule(job)
        assert scheduled.provider_status == "SCHEDULED" and scheduled.external_id
        assert provider.cancel(job).provider_status == "READY"
        assert provider.get_status(scheduled.external_id).provider_status == "FAILED"

    def test_schedule_unsupported_platform_honest(self):
        provider = MockPlatformProvider(platform="Instagram Reels")
        job = _job(platform="Instagram Reels", scheduled_at=FUTURE)
        response = provider.schedule(job)
        assert response.error_kind == "unsupported"
        assert "scheduling unsupported" in response.message

    def test_unauthenticated_never_succeeds(self):
        provider = MockPlatformProvider(authenticated=False)
        job = _job()
        assert provider.upload(job).provider_status == "FAILED"
        assert provider.publish(job).error_kind == "invalid_credentials"

    def test_processing_failure_scenario(self):
        provider = MockPlatformProvider(scenario="processing_failure", processing_steps=2)
        job = _job()
        provider.upload(job)
        provider.check_processing(job)
        failed = provider.check_processing(job)
        assert failed.provider_status == "FAILED" and failed.error_kind == "server_error"

    def test_metrics_never_invented(self):
        provider = MockPlatformProvider()
        job = _job()
        published = provider.publish(job)
        metrics = provider.get_metrics(published.external_id)
        assert metrics.metadata == {"views": None, "likes": None}


@pytest.fixture()
def token_store(tmp_path):
    return TokenStore(secrets_path=str(tmp_path / "secrets.json"))


@pytest.fixture()
def account_store(tmp_path, token_store):
    return AccountStore(accounts_path=str(tmp_path / "accounts.json"), token_store=token_store)


class TestMaskToken:
    def test_empty_and_short_are_never_revealed(self):
        assert mask_token("") == ""
        assert mask_token("abc123") == "***"
        assert mask_token("12345678") == "***"  # boundary: 8 chars still hidden

    def test_long_token_shows_only_edges(self):
        masked = mask_token("ya29.SECRET-TOKEN-VALUE-1234")
        assert masked.startswith("ya29") and masked.endswith("(28 chars)")
        assert "SECRET-TOKEN-VALUE" not in masked  # never display a complete token (§6)


class TestTokenStore:
    def test_env_reference_resolution(self, token_store, monkeypatch):
        monkeypatch.setenv("FAKE_PLATFORM_TOKEN", "env-secret-1")
        assert token_store.resolve("env:FAKE_PLATFORM_TOKEN") == "env-secret-1"
        assert token_store.resolve("FAKE_PLATFORM_TOKEN") == "env-secret-1"  # bare fallback
        assert token_store.resolve("env:NOPE_MISSING") == ""
        assert token_store.resolve("") == ""

    def test_store_roundtrip_and_delete(self, token_store, tmp_path):
        reference = token_store.store("tiktok:main", "tok-abc", refresh_token="ref-1",
                                      expires_at=FUTURE)
        assert reference == "store:tiktok:main"
        assert token_store.resolve(reference) == "tok-abc"
        assert token_store.delete("tiktok:main") is True
        assert token_store.resolve(reference) == ""
        assert token_store.delete("tiktok:main") is False

    def test_store_rejects_bad_keys(self, token_store):
        with pytest.raises(ValueError):
            token_store.store("", "tok")
        with pytest.raises(ValueError):
            token_store.store("key\nline", "tok")
        # colons ARE allowed: keys are hierarchical like "youtube:main"
        token_store.store("ok:key", "tok")
        assert token_store.resolve("store:ok:key") == "tok"

    def test_expiry_parsing(self, token_store):
        assert token_store.expiry("env:WHATEVER") is None  # env tokens carry no stored expiry
        token_store.store("ig:main", "tok", expires_at=FUTURE)
        assert token_store.expiry("store:ig:main") == datetime.fromisoformat(FUTURE)
        token_store.store("ig:garbage", "tok", expires_at="not-a-date")
        assert token_store.expiry("store:ig:garbage") is None

    def test_missing_or_corrupt_file_is_empty(self, token_store):
        assert token_store.resolve("store:nothing") == ""
        with open(token_store.secrets_path, "w") as handle:
            handle.write("{corrupt")
        assert token_store.resolve("store:nothing") == ""  # never crash on a bad file


class TestAccountStore:
    def test_connect_requires_resolvable_reference(self, account_store):
        with pytest.raises(ValueError, match="does not resolve"):
            account_store.connect("YouTube", "Main", token_reference="env:DEFINITELY_MISSING")
        with pytest.raises(ValueError):
            account_store.connect("", "Main")

    def test_connected_via_env_token(self, account_store, monkeypatch):
        monkeypatch.setenv("YT_TOKEN", "yt-secret")
        account = account_store.connect("YouTube", "Main Channel",
                                        token_reference="env:YT_TOKEN")
        assert account.state == "connected" and account.connected is True
        # §24: the secret itself must never be serialized onto the account
        dump = json.dumps(account.model_dump())
        assert "yt-secret" not in dump
        assert account.token_reference == "env:YT_TOKEN"

    def test_expired_token_marks_expired(self, account_store, token_store):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        token_store.store("ig:expired", "tok", expires_at=past)
        account = account_store.connect("Instagram Reels", "IG", token_reference="store:ig:expired")
        assert account.state == "expired" and account.connected is False

    def test_vanished_secret_marks_needs_reauthorization(self, account_store, token_store):
        token_store.store("tk:gone", "tok")
        account = account_store.connect("TikTok", "TK", token_reference="store:tk:gone")
        assert account.state == "connected"
        token_store.delete("tk:gone")
        refreshed = account_store.get(account.account_id)
        assert refreshed.state == "needs_reauthorization"

    def test_disconnect_clears_token_reference(self, account_store, token_store):
        token_store.store("li:main", "tok")
        account = account_store.connect("LinkedIn", "LI", token_reference="store:li:main")
        assert account_store.disconnect(account.account_id) is True
        refreshed = account_store.get(account.account_id)
        assert refreshed.state == "disconnected" and refreshed.token_reference == ""
        assert account_store.disconnect("missing-id") is False

    def test_list_filters_by_platform_and_rereads_state(self, account_store, monkeypatch):
        monkeypatch.setenv("A_TOKEN", "a")
        account_store.connect("YouTube", "YT", token_reference="env:A_TOKEN")
        account_store.connect("TikTok", "TK", token_reference="")
        assert len(account_store.list()) == 2
        tiktoks = account_store.list(platform="TikTok")
        assert len(tiktoks) == 1 and tiktoks[0].state == "disconnected"
        assert account_store.get("missing") is None

    def test_secrets_never_written_to_accounts_file(self, account_store, token_store, tmp_path):
        token_store.store("yt:main", "SUPER-SECRET-VALUE")
        account_store.connect("YouTube", "Main", token_reference="store:yt:main")
        raw = (tmp_path / "accounts.json").read_text(encoding="utf-8")
        assert "SUPER-SECRET-VALUE" not in raw  # accounts.json holds references only


class TestAssetValidation:
    def test_landscape_fits_youtube(self):
        report = validate_asset(MEDIA["landscape"], "YouTube")
        assert report.ok and not report.problems and not report.requires_adaptation

    def test_portrait_fits_vertical_platforms(self):
        for platform in ("TikTok", "Instagram Reels", "YouTube Shorts"):
            assert validate_asset(MEDIA["portrait"], platform).ok, platform

    def test_aspect_mismatch_requires_adaptation(self):
        report = validate_asset(MEDIA["landscape"], "TikTok")  # 16:9 vs 9:16 profile
        assert not report.ok and report.requires_adaptation
        assert any("re-export" in problem for problem in report.problems)

    def test_missing_asset_is_hard_failure(self):
        report = validate_asset("nowhere/ghost.mp4", "YouTube")
        assert not report.ok and report.problems == [report.problems[0]]
        assert not report.requires_adaptation  # nothing to adapt
        assert not validate_asset("", "YouTube").ok

    def test_bad_container_requires_adaptation(self, tmp_path):
        fake = tmp_path / "clip.avi"
        fake.write_bytes(b"x" * 16)
        report = validate_asset(str(fake), "YouTube")
        assert not report.ok and report.requires_adaptation

    def test_low_resolution_is_warning_not_failure(self):
        report = validate_asset(MEDIA["lowres"], "YouTube")  # 640x360 h264 16:9
        assert report.ok and report.warnings  # advisory only (§10: honest, not blocking)

    def test_unprofiled_platform_gets_basic_checks(self):
        report = validate_asset(MEDIA["landscape"], "LinkedIn")
        assert report.ok and any("basic checks" in w for w in report.warnings)


class TestMetadataValidation:
    def test_overlong_title_rejected(self):
        payload = {"title": "x" * 101}
        report = validate_metadata(payload, "YouTube")
        assert not report.ok and any("Title" in p for p in report.problems)

    def test_caption_limits_for_instagram(self):
        assert validate_metadata({"caption": "c" * 2200}, "Instagram Reels").ok
        assert not validate_metadata({"caption": "c" * 2201}, "Instagram Reels").ok

    def test_hashtag_counting_includes_inline_tags(self):
        payload = {"description": "great #video #clip", "hashtags": ["a", "b"]}
        report = validate_metadata(payload, "YouTube")  # guidance cap 15
        assert report.ok  # 4 total → fine
        many = {"hashtags": [f"tag{i}" for i in range(20)]}
        report = validate_metadata(many, "YouTube")
        assert report.ok and report.warnings  # advisory, not blocking

    def test_empty_text_is_honest_warning(self):
        report = validate_metadata({}, "TikTok")
        assert report.ok and report.warnings

    def test_unknown_platform_rejected(self):
        assert not validate_metadata({}, "MySpace").ok

    def test_webhook_has_no_text_limits(self):
        assert validate_metadata({"description": "x" * 99999}, "Webhook").ok


class TestScheduleValidation:
    def test_valid_future_timezone_aware(self):
        assert validate_schedule(FUTURE, "YouTube").ok

    def test_naive_rejected(self):
        report = validate_schedule("2027-01-01T09:00:00", "YouTube")
        assert not report.ok and any("timezone-aware" in p for p in report.problems)

    def test_past_rejected(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert not validate_schedule(past, "YouTube").ok

    def test_unsupported_platform_honest(self):
        report = validate_schedule(FUTURE, "Instagram Reels")
        assert not report.ok and any("scheduling unsupported" in p for p in report.problems)

    def test_empty_schedule_is_immediate_publish(self):
        assert validate_schedule("", "Instagram Reels").ok


class TestPrePublishChecklist:
    def test_valid_job_passes_all_items(self):
        job = _job(platform="YouTube", asset_path=MEDIA["landscape"], title="Launch")
        items = pre_publish_checklist(job)
        assert len(items) == 3 and all(item["passed"] for item in items)

    def test_bad_asset_flags_adaptation_in_checklist(self):
        job = _job(platform="TikTok", asset_path=MEDIA["landscape"], title="Launch")
        items = pre_publish_checklist(job)
        asset_item = items[0]
        assert not asset_item["passed"] and asset_item["requires_adaptation"] is True

    def test_metadata_limits_in_metadata_limits_table(self):
        assert METADATA_LIMITS["YouTube"]["title"] == 100
        assert METADATA_LIMITS["Instagram Reels"]["description"] == 2200


def _manager(provider, sleeps=None, **kwargs):
    recorded = sleeps if sleeps is not None else []
    return PublishingManager(provider, sleep_fn=recorded.append, **kwargs)


def _youtube_job(**kwargs):
    base = {"platform": "YouTube", "asset_path": MEDIA["landscape"], "title": "Launch"}
    base.update(kwargs)
    return _job(**base)


class TestPipelineManager:
    def test_happy_path_publishes_with_external_id(self):
        provider = MockPlatformProvider(platform="YouTube", processing_steps=2)
        job = _youtube_job()
        result = _manager(provider).run_job(job)
        assert result.status == "PUBLISHED" and result.external_post_id
        assert result.external_url.startswith("https://")
        assert result.retry_count == 0
        assert "upload" in provider.call_log and "publish" in provider.call_log

    def test_invalid_job_fails_before_any_provider_call(self):
        provider = MockPlatformProvider(platform="YouTube")
        job = _youtube_job(asset_path="nowhere/ghost.mp4")
        result = _manager(provider).run_job(job)
        assert result.status == "FAILED" and "validation" in result.error.lower()
        assert provider.call_log == []  # §29: validate BEFORE touching the platform

    def test_never_retries_permanent_errors(self):
        provider = MockPlatformProvider(platform="YouTube", scenario="invalid_media")
        job = _youtube_job()
        result = _manager(provider, max_retries=3).run_job(job)
        assert result.status == "FAILED" and result.retry_count == 0
        assert provider.call_log.count("upload") == 1  # §16: no retry on invalid media

    def test_retries_transient_errors_with_exponential_backoff(self):
        provider = MockPlatformProvider(platform="YouTube", scenario="upload_failure_retryable")
        sleeps: list[float] = []
        job = _youtube_job()
        result = _manager(provider, sleeps=sleeps, max_retries=2, backoff_base=1.0).run_job(job)
        assert result.status == "FAILED" and "Retry limit reached" in result.error
        assert result.retry_count == 2 and provider.call_log.count("upload") == 3
        assert sleeps == [2.0, 4.0]  # exponential: base * 2^attempt

    def test_auth_failure_is_terminal_without_upload(self):
        provider = MockPlatformProvider(platform="YouTube", scenario="expired_token")
        job = _youtube_job()
        result = _manager(provider, max_retries=5).run_job(job)
        assert result.status == "FAILED" and "Authentication" in result.error
        assert "upload" not in provider.call_log

    def test_bounded_polling_gives_up(self):
        provider = MockPlatformProvider(platform="YouTube", processing_steps=100)
        job = _youtube_job()
        result = _manager(provider, max_polls=3, max_retries=1).run_job(job)
        assert result.status == "FAILED" and "poll limit" in result.error
        assert provider.call_log.count("check_processing") == 6  # 3 polls x 2 attempts

    def test_scheduled_job_lands_in_scheduled(self):
        provider = MockPlatformProvider(platform="YouTube")
        job = _youtube_job(scheduled_at=FUTURE)
        result = _manager(provider).run_job(job)
        assert result.status == "SCHEDULED" and result.external_post_id

    def test_schedule_on_unsupported_platform_rejected(self):
        provider = MockPlatformProvider(platform="Instagram Reels")
        job = _job(platform="Instagram Reels", asset_path=MEDIA["portrait"], scheduled_at=FUTURE)
        result = _manager(provider).run_job(job)
        assert result.status == "FAILED" and "scheduling unsupported" in result.error

    def test_idempotency_across_jobs_no_duplicate_posts(self):
        provider = MockPlatformProvider(platform="YouTube")
        first = _manager(provider).run_job(_youtube_job())
        twin = _youtube_job()  # fresh job id, same intent
        twin.idempotency_key = first.idempotency_key
        second = _manager(provider).run_job(twin)
        assert second.status == "PUBLISHED"
        assert second.external_post_id == first.external_post_id  # §17: adopted, not duplicated
        assert len(provider._posts) == 1

    def test_existing_external_post_adopted_without_reupload(self):
        provider = MockPlatformProvider(platform="YouTube")
        first = _manager(provider).run_job(_youtube_job())
        uploads_before = provider.call_log.count("upload")
        rerun = _youtube_job(external_post_id=first.external_post_id, status="READY")
        result = _manager(provider).run_job(rerun)
        assert result.status == "PUBLISHED"
        assert provider.call_log.count("upload") == uploads_before  # no second upload

    def test_ready_job_skips_draft_validation(self):
        provider = MockPlatformProvider(platform="YouTube")
        job = _youtube_job(status="READY")
        result = _manager(provider).run_job(job)
        assert result.status == "PUBLISHED"


class TestPublishQueue:
    def test_queue_states_vocabulary(self):
        assert set(QUEUE_STATES) == {"queued", "waiting", "running", "completed", "failed", "cancelled"}

    def test_invalid_job_rejected_before_queueing(self):
        provider = MockPlatformProvider(platform="TikTok")
        manager = _manager(provider)
        entry = manager.queue_job(_job(platform="TikTok", asset_path=MEDIA["landscape"]))  # wrong aspect
        assert entry["state"] == "failed" and entry["reason"]
        assert manager.run_queue() and provider.call_log == []  # never uploaded (§10)

    def test_queue_runs_to_completion_in_order(self):
        provider = MockPlatformProvider(platform="YouTube")
        manager = _manager(provider)
        e1 = manager.queue_job(_youtube_job())
        e2 = manager.queue_job(_youtube_job())
        manager.run_queue()
        assert e1["state"] == "completed" and e2["state"] == "completed"
        assert e1["job"].status == "PUBLISHED" and e2["job"].status == "PUBLISHED"

    def test_duplicate_queue_entry_is_reused(self):
        provider = MockPlatformProvider(platform="YouTube")
        manager = _manager(provider)
        job = _youtube_job()
        first = manager.queue_job(job)
        second = manager.queue_job(job)
        assert first is second and len(manager.queue) == 1

    def test_cancelled_job_is_skipped(self):
        provider = MockPlatformProvider(platform="YouTube")
        manager = _manager(provider)
        entry = manager.queue_job(_youtube_job())
        assert manager.cancel_queued(entry["job_id"]) is True
        assert entry["state"] == "cancelled" and entry["job"].status == "CANCELLED"
        manager.run_queue()
        assert entry["state"] == "cancelled" and provider.call_log == []
        assert manager.cancel_queued("nope") is False


class TestBatchPublishing:
    def test_preview_verdicts_are_honest(self):
        ready = build_batch_item("YouTube", MEDIA["landscape"], title="Launch")
        warning = build_batch_item("YouTube", MEDIA["lowres"], title="Launch")  # low res → advisory
        adapt = build_batch_item("TikTok", MEDIA["landscape"], title="Launch")                # wrong aspect
        missing = build_batch_item("YouTube", "nowhere/ghost.mp4", title="Launch")
        assert ready.verdict == "READY" and not ready.reasons
        assert warning.verdict == "WARNING" and warning.reasons
        assert adapt.verdict == "ERROR" and any("adaptation" in r for r in adapt.reasons)
        assert missing.verdict == "ERROR"

    def test_campaign_pairs_use_real_assets_only(self):
        campaign = {"assets": {"hero_image": MEDIA["portrait"], "promo_video": None}}
        assert pairs_for_campaign(campaign, ["Instagram Reels"]) == [("Instagram Reels", MEDIA["portrait"])]
        campaign = {"assets": {"hero_image": MEDIA["portrait"], "promo_video": MEDIA["landscape"]}}
        pairs = pairs_for_campaign(campaign, ["YouTube", "TikTok"])
        assert pairs == [("YouTube", MEDIA["landscape"]), ("TikTok", MEDIA["landscape"])]
        assert pairs_for_campaign({}, ["YouTube"]) == []  # no assets → no pairs

    def test_project_pairs_pin_latest_rendered_version(self):
        from services.project_model import ProjectState
        project = ProjectState()
        project.add_version(MEDIA["landscape"])
        pairs = pairs_for_project(project, ["YouTube", "LinkedIn"])
        assert len(pairs) == 2 and all(asset.endswith("landscape.mp4") for _, asset in pairs)
        assert pairs_for_project(ProjectState(), ["YouTube"]) == []

    def test_batch_items_carry_version_pinning(self):
        from services.project_model import ProjectState
        project = ProjectState()
        version = project.add_version(MEDIA["landscape"])
        item = build_batch_item("YouTube", MEDIA["landscape"], project=project)
        assert item.project_id == project.project_id and item.version_id == version.version_id

    def test_queue_batch_requires_explicit_confirmation(self):
        provider = MockPlatformProvider(platform="YouTube")
        manager = _manager(provider)
        items = build_batch([("YouTube", MEDIA["landscape"])])
        with pytest.raises(ValueError, match="confirmation"):
            queue_batch(manager, items)  # §30: no silent batch publishing

    def test_queue_batch_skips_errors_and_publishes_ready(self):
        provider = MockPlatformProvider(platform="YouTube")
        manager = _manager(provider)
        items = build_batch([("YouTube", MEDIA["landscape"]), ("TikTok", MEDIA["landscape"])], title="Launch")
        summary = queue_batch(manager, items, confirmed=True, title="Launch")
        assert summary["queued"] == 1 and summary["rejected"] == 1 and summary["ERROR"] == 1
        manager.run_queue()
        ready_item = next(i for i in items if i.verdict == "READY")
        assert ready_item.job.status == "PUBLISHED" and len(provider._posts) == 1
        error_item = next(i for i in items if i.verdict == "ERROR")
        assert error_item.job is None  # never queued, never uploaded (§21)


class TestN8nIntegration:
    def test_webhook_url_validation(self):
        assert validate_webhook_url("https://n8n.example/webhook/abc") == []
        assert validate_webhook_url("") 
        assert validate_webhook_url("ftp://n8n.example/hook")
        assert validate_webhook_url("https://user:pass@n8n.example/hook")  # embedded creds
        assert validate_webhook_url("https://")  # no host

    def test_scrub_secrets_recursive(self):
        payload = {"job_id": "j1", "access_token": "LEAK", "Authorization": "Bearer x",
                   "nested": {"refresh_token": "LEAK2", "status": "ok"},
                   "items": [{"password": "p", "name": "n"}]}
        clean = scrub_secrets(payload)
        serialized = json.dumps(clean)
        assert "LEAK" not in serialized and "Bearer" not in serialized
        assert clean["nested"]["status"] == "ok" and clean["items"][0]["name"] == "n"

    def test_payload_carries_publication_facts_only(self):
        job = _job(platform="YouTube", status="PUBLISHED", external_post_id="ext-7",
                   external_url="https://mock.example/ext-7")
        payload = build_n8n_payload(job, extra={"api_key": "SECRETKEY"})
        assert payload["external_post_id"] == "ext-7" and payload["platform"] == "YouTube"
        assert payload["api_key"] == "[redacted]"
        assert "NOT publication confirmation" in payload["note"]

    def test_notify_success_reports_delivery_not_publication(self):
        captured = {}

        def transport(url, data):
            captured["url"] = url
            captured["body"] = json.loads(data.decode("utf-8"))
            return 200

        result = notify_n8n("https://n8n.example/hook", {"status": "PUBLISHED", "token": "X"},
                            transport=transport)
        assert result["delivered"] is True and result["http_status"] == 200
        assert "NOT publication confirmation" in result["note"]
        assert captured["body"]["token"] == "[redacted]"  # §23: secrets never sent

    def test_notify_failure_is_honest(self):
        def transport(url, data):
            raise OSError("connection reset")

        result = notify_n8n("https://n8n.example/hook", {"a": 1}, transport=transport)
        assert result["delivered"] is False and "connection reset" in result["error"]

    def test_invalid_url_never_hit(self):
        called = []
        result = notify_n8n("not a url", {"a": 1}, transport=lambda u, d: called.append(u) or 200)
        assert result["delivered"] is False and called == []  # transport never invoked


class TestHistoryPersistence:
    def test_publishing_dir_is_project_scoped_and_safe(self, tmp_path):
        assert publishing_dir("abc") == os.path.join("projects", "abc", "publishing")
        with pytest.raises(ValueError):
            publishing_dir("../escape")
        with pytest.raises(ValueError):
            publishing_dir("")

    def test_save_load_roundtrip(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        job = _job(platform="YouTube")
        store.save_job(job)
        loaded = store.get_job(job.job_id)
        assert loaded is not None and loaded.platform == "YouTube"
        assert store.load_jobs()[0].job_id == job.job_id
        assert store.get_job("missing") is None

    def test_terminal_records_never_rewritten(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        published = _job(platform="YouTube", status="PUBLISHED", external_post_id="ext-1")
        store.save_job(published)
        regression = published.model_copy(update={"status": "UPLOADING"})
        store.save_job(regression)  # §40: must be ignored
        assert store.get_job(published.job_id).status == "PUBLISHED"

    def test_history_is_append_only(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        job = _job(platform="YouTube", status="PUBLISHED", external_post_id="ext-1")
        store.record_result(job)
        store.record_result(job)  # second event appends, never rewrites
        history = store.load_history()
        assert len(history) == 2 and history[0]["external_post_id"] == "ext-1"
        assert all(entry["recorded_at"] for entry in history)

    def test_non_terminal_jobs_make_no_history_entry(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        store.record_result(_job(platform="YouTube", status="READY"))
        assert store.load_history() == []

    def test_refresh_promotes_scheduled_to_published(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        provider = MockPlatformProvider(platform="YouTube")
        published = provider.publish(_job(platform="YouTube"))  # creates a real mock post
        job = _job(platform="YouTube", status="SCHEDULED",
                   external_post_id=published.external_id)
        refreshed = store.refresh_status(job, provider)
        assert refreshed.status == "PUBLISHED"  # platform confirmed, record updated
        assert any("status_refresh" in entry["event"] for entry in store.load_history())

    def test_refresh_keeps_record_on_platform_failure(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        provider = MockPlatformProvider(platform="YouTube")
        job = _job(platform="YouTube", status="PUBLISHED", external_post_id="ghost")
        refreshed = store.refresh_status(job, provider)
        assert refreshed.status == "PUBLISHED"  # unknown post → keep honest record
        assert store.load_history() == []

    def test_metrics_candidates_expose_external_ids(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        store.save_job(_job(platform="YouTube", status="PUBLISHED", external_post_id="ext-9"))
        store.save_job(_job(platform="TikTok", status="FAILED"))
        candidates = store.metrics_candidates()
        assert len(candidates) == 1 and candidates[0]["external_post_id"] == "ext-9"

    def test_no_tokens_in_published_storage(self, tmp_path):
        store = PublishingStore("p1", base_dir=str(tmp_path / "pub"))
        job = _job(platform="YouTube", status="PUBLISHED", external_post_id="ext-1")
        job.account_id = "acc-1"
        store.record_result(job)
        raw_jobs = (tmp_path / "pub" / "jobs.json").read_text(encoding="utf-8")
        raw_history = (tmp_path / "pub" / "history.json").read_text(encoding="utf-8")
        assert "token" not in raw_jobs.lower()  # §41: job storage carries no credentials
        assert "secret" not in raw_jobs.lower() and "secret" not in raw_history.lower()
