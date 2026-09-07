"""Phase 12 — Performance feedback regression tests (no fabricated metrics)."""
import subprocess
from pathlib import Path

import pytest

from services.performance import (
    METRIC_KEYS,
    fetch_platform_metrics,
    interpret_metrics,
    measure_local_metrics,
    recommend_next_campaign,
    record_performance,
    validate_metrics,
)
from services.project_model import ProjectState


def _make_video(path: Path, duration=2.0):
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path),
    ], check=True, capture_output=True)
    return path


class TestValidation:
    def test_known_metrics_accepted(self):
        cleaned = validate_metrics({"views": 1000, "shares": 12})
        assert cleaned == {"views": 1000.0, "shares": 12.0}

    def test_unknown_metric_rejected(self):
        with pytest.raises(ValueError, match="Unknown metric"):
            validate_metrics({"likes": 5})

    def test_negative_and_non_numeric_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            validate_metrics({"views": -3})
        with pytest.raises(ValueError, match="numeric"):
            validate_metrics({"views": "many"})

    def test_empty_metrics_rejected(self):
        with pytest.raises(ValueError):
            validate_metrics({})

    def test_metric_key_surface_matches_mandate(self):
        assert set(METRIC_KEYS) == {"views", "watch_time", "retention", "engagement", "shares", "clicks"}


class TestPlatformFetch:
    def test_no_credentials_means_unavailable(self):
        report = fetch_platform_metrics("TikTok", "ext-1")
        assert report["status"] == "unavailable"
        assert report["metrics"] == {}
        assert "not be fabricated" in report["message"]

    def test_missing_arguments_rejected(self):
        with pytest.raises(ValueError):
            fetch_platform_metrics("", "ext-1")
        with pytest.raises(ValueError):
            fetch_platform_metrics("TikTok", "  ")

    def test_transport_metrics_fetched(self):
        report = fetch_platform_metrics("YouTube", "v123",
                                        transport=lambda p, e: {"views": 5000, "retention": 62.5})
        assert report["status"] == "fetched" and report["source"] == "platform_api"
        assert report["metrics"]["views"] == 5000.0

    def test_transport_failure_is_honest(self):
        def broken(platform, external_id):
            raise ConnectionError("analytics down")
        report = fetch_platform_metrics("YouTube", "v1", transport=broken)
        assert report["status"] == "unavailable" and "analytics down" in report["message"]

    def test_transport_garbage_is_invalid(self):
        report = fetch_platform_metrics("YouTube", "v1", transport=lambda p, e: {"sentiment": 0.9})
        assert report["status"] == "invalid"


class TestLocalMeasurement:
    def test_real_local_measurement(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        report = measure_local_metrics(str(video))
        assert report["status"] == "measured" and report["source"] == "local"
        assert 1.5 <= report["metrics"]["duration"] <= 2.6
        assert report["metrics"]["file_size_bytes"] > 0
        assert report["metrics"]["has_audio"] is False
        # Impossible local metrics must not exist at all.
        assert not set(report["metrics"]) & set(METRIC_KEYS)

    def test_missing_asset_rejected(self):
        with pytest.raises(FileNotFoundError):
            measure_local_metrics("missing.mp4")


class TestInterpretation:
    def test_derived_rates_only_from_real_numbers(self):
        result = interpret_metrics({"views": 1000, "engagement": 50, "clicks": 25})
        assert result["derived"]["engagement_rate"] == 0.05
        assert result["derived"]["click_through_rate"] == 0.025
        assert "shares" not in result["derived"]
        assert "retention" in result["gaps"] and "watch_time" in result["gaps"]
        assert result["method"].startswith("deterministic")

    def test_zero_views_never_divides(self):
        result = interpret_metrics({"views": 0, "engagement": 4})
        assert "engagement_rate" not in result["derived"]

    def test_low_retention_triggers_recommendation(self):
        result = interpret_metrics({"views": 9000, "retention": 31.0})
        assert any("Retention" in item for item in result["recommendations"])

    def test_healthy_metrics_report_no_issues(self):
        result = interpret_metrics({"views": 9000, "retention": 72.0, "engagement": 400})
        assert result["recommendations"] == ["No deterministic issues detected with the available metrics."]

    def test_empty_metrics_rejected(self):
        with pytest.raises(ValueError):
            interpret_metrics({})


class TestProjectFeedbackLoop:
    def test_record_and_recommend_flow_into_telemetry(self):
        project = ProjectState()
        report = fetch_platform_metrics("YouTube", "v1",
                                        transport=lambda p, e: {"views": 80, "retention": 40.0})
        entry = {"platform": "YouTube", "external_id": "v1"}
        recorded = record_performance(project, entry, report)
        assert recorded["status"] == "fetched"

        interpretation = interpret_metrics(report["metrics"])
        guidance = recommend_next_campaign(project, interpretation)
        assert guidance["based_on_metrics"]["views"] == 80.0
        assert len(project.telemetry) == 2
        assert {item["type"] for item in project.telemetry} == {"performance_report", "performance_feedback"}

    def test_unavailable_report_cannot_be_recorded(self):
        project = ProjectState()
        report = fetch_platform_metrics("TikTok", "ext-1")  # unavailable
        with pytest.raises(ValueError, match="fetched or measured"):
            record_performance(project, {"platform": "TikTok"}, report)
        assert project.telemetry == []

    def test_recommendation_requires_interpretation(self):
        with pytest.raises(ValueError):
            recommend_next_campaign(ProjectState(), {"metrics": {}})

    def test_feedback_survives_project_roundtrip(self):
        project = ProjectState()
        interpretation = interpret_metrics({"views": 4000, "retention": 55.0})
        recommend_next_campaign(project, interpretation)
        restored = ProjectState.model_validate_json(project.model_dump_json())
        assert restored.telemetry[0]["type"] == "performance_feedback"
