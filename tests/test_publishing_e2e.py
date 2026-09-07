"""Phase 12 — end-to-end publishing against the mock platform (§36).

Full pipeline: project → rendered version → platform version → metadata →
validate → job → upload → processing → published → external id/url →
history record. Everything runs against MockPlatformProvider; no real
platform is ever touched, and no statistic is ever invented (§32).
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.slow

from services.project_model import ProjectState, ProjectVersion
from services.publishing.batch import build_batch, pairs_for_project, queue_batch
from services.publishing.history import PublishingStore
from services.publishing.manager import PublishingManager
from services.publishing.metrics import collect_metrics, metrics_without_numbers
from services.publishing.mock import MockPlatformProvider
from services.publishing.models import PublishingJob
from services.publishing.n8n import build_n8n_payload, notify_n8n

FUTURE = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

# Deterministic synthetic media from the conftest `media` fixture: the suite
# is self-contained on a clean checkout (no pre-existing temp/ files needed).
MEDIA: dict[str, str] = {}


@pytest.fixture(scope="session", autouse=True)
def _bind_synthetic_media(media):
    MEDIA.update(vars(media))


@pytest.fixture()
def project():
    state = ProjectState(source_assets=[MEDIA["landscape"]])
    state.outputs.append(ProjectVersion(output_path=MEDIA["landscape"]))
    return state


@pytest.fixture()
def store(project, tmp_path):
    return PublishingStore(project.project_id, base_dir=str(tmp_path / "publishing"))


def _manager(provider, **kwargs):
    return PublishingManager(provider, sleep_fn=lambda _s: None, **kwargs)


class TestEndToEndMockPipeline:
    def test_full_pipeline_project_to_published_record(self, project, store):
        provider = MockPlatformProvider(platform="YouTube", scenario="normal",
                                        processing_steps=2)
        manager = _manager(provider)
        pairs = pairs_for_project(project, ["YouTube"])
        items = build_batch(pairs, project=project, title="Launch video")
        assert [item.verdict for item in items] == ["READY"]

        summary = queue_batch(manager, items, confirmed=True, title="Launch video")
        assert summary["queued"] == 1 and summary["rejected"] == 0

        manager.run_queue()
        job = items[0].job
        assert job.status == "PUBLISHED"
        assert job.external_post_id.startswith("mock-")          # platform's own id
        assert job.external_url.startswith("https://mock.example/")
        assert job.version_id == project.outputs[0].version_id    # §40 version pin

        store.record_result(job)
        reloaded = store.get_job(job.job_id)
        assert reloaded is not None and reloaded.status == "PUBLISHED"
        history = store.load_history()
        assert len(history) == 1 and history[0]["event"] == "terminal"
        assert history[0]["external_post_id"] == job.external_post_id

        raw = json.dumps(store.load_jobs()[0].model_dump())
        assert "token" not in raw.lower()                         # §24: never persisted

    def test_metrics_interface_never_invents_statistics(self, project, store):
        provider = MockPlatformProvider(platform="YouTube")
        job = _manager(provider).run_job(
            PublishingJob(platform="YouTube", asset_path=MEDIA["landscape"], title="Launch",
                          project_id=project.project_id))
        assert job.status == "PUBLISHED"
        store.record_result(job)

        entries = collect_metrics(store, lambda platform: provider)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["available"] is True
        assert entry["metrics"] == {"views": None, "likes": None}   # None ≠ 0 (§32)
        assert metrics_without_numbers(entries) == entries          # honest: no numbers yet

    def test_metrics_without_provider_stays_unavailable(self, project, store):
        provider = MockPlatformProvider(platform="YouTube")
        job = _manager(provider).run_job(
            PublishingJob(platform="YouTube", asset_path=MEDIA["landscape"], title="Launch",
                          project_id=project.project_id))
        store.record_result(job)

        def no_provider(platform):
            raise ValueError(f"No credentials configured for {platform}")

        entries = collect_metrics(store, no_provider)
        assert entries[0]["available"] is False
        assert "No metrics provider configured" in entries[0]["reason"]
        assert entries[0]["metrics"] == {}                          # nothing invented

    def test_unfit_asset_never_reaches_the_platform(self, project):
        provider = MockPlatformProvider(platform="TikTok")
        manager = _manager(provider)
        items = build_batch(pairs_for_project(project, ["TikTok"]),
                            project=project, title="Launch video")
        assert items[0].verdict == "ERROR"                          # 16:9 ≠ 9:16
        summary = queue_batch(manager, items, confirmed=True, title="Launch video")
        assert summary["queued"] == 0 and summary["rejected"] == 1
        assert provider.call_log == []                              # zero provider calls

    def test_scheduled_flow_and_refresh_only_promotes_on_confirmation(self, project, store):
        provider = MockPlatformProvider(platform="YouTube")
        job = _manager(provider).run_job(
            PublishingJob(platform="YouTube", asset_path=MEDIA["landscape"], title="Launch",
                          scheduled_at=FUTURE, project_id=project.project_id))
        assert job.status == "SCHEDULED" and job.external_post_id
        store.record_result(job)

        job = store.refresh_status(job, provider)
        assert job.status == "SCHEDULED"                            # platform says scheduled
        assert any("status_refresh" in e["event"] for e in store.load_history())

        provider._posts[job.external_post_id]["status"] = "PUBLISHED"  # platform goes live
        job = store.refresh_status(job, provider)
        assert job.status == "PUBLISHED"                            # confirmed promotion only
        assert store.get_job(job.job_id).status == "PUBLISHED"

    def test_failure_path_is_recorded_and_persisted(self, project, store):
        provider = MockPlatformProvider(platform="YouTube", scenario="server_error")
        job = _manager(provider, max_retries=2).run_job(
            PublishingJob(platform="YouTube", asset_path=MEDIA["landscape"], title="Launch",
                          project_id=project.project_id))
        assert job.status == "FAILED"
        assert "Retry limit reached (2)" in (job.error or "")
        store.record_result(job)
        assert store.get_job(job.job_id).status == "FAILED"
        assert store.load_history()[0]["status"] == "FAILED"

    def test_n8n_dispatch_is_delivery_not_publication(self, project):
        provider = MockPlatformProvider(platform="YouTube")
        job = _manager(provider).run_job(
            PublishingJob(platform="YouTube", asset_path=MEDIA["landscape"], title="Launch",
                          project_id=project.project_id))
        sent = []
        payload = build_n8n_payload(job, extra={"access_token": "SECRET-VALUE"})
        report = notify_n8n("https://hooks.example/n8n/publication", payload,
                            transport=lambda url, data: sent.append((url, data)) or 200)
        assert report["delivered"] is True
        assert "NOT publication confirmation" in report["note"]
        assert job.status == "PUBLISHED"                            # webhook changes nothing
        body = json.loads(sent[0][1].decode("utf-8"))
        assert body["access_token"] == "[redacted]"                 # §23 secret-free
        assert "SECRET-VALUE" not in json.dumps(body)
