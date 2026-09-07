"""Phase 10 — Campaign builder regression tests."""
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.campaign_builder import (
    CampaignBrief,
    build_calendar,
    build_campaign,
    build_cta,
    build_hashtags,
    build_pillars,
    classify_goal,
)
from services.project_model import ProjectState


def _brief(**overrides):
    base = dict(
        brand="GenForge Labs",
        goal="Grow brand awareness",
        audience="indie creators",
        platforms=["TikTok", "YouTube"],
        posts_per_week=2,
        topic="AI video editing",
        horizon_weeks=2,
    )
    base.update(overrides)
    return CampaignBrief(**base)


def _stub_script_generator(prompt: str) -> dict:
    return {
        "hook": "Stop scrolling.",
        "introduction": "Here is the idea.",
        "body": "Here is the proof and the how-to.",
        "cta": "Follow for more.",
        "alternate_hooks": ["Wait for it.", "You missed this."],
        "short_version": "Short cut of the script.",
        "long_version": "Longer cut of the script with extra detail.",
    }


class TestBriefValidation:
    def test_required_fields_enforced(self):
        with pytest.raises(ValidationError):
            _brief(brand="   ")

    def test_unknown_platform_rejected(self):
        with pytest.raises(ValidationError, match="Unknown platform"):
            _brief(platforms=["MySpace"])

    def test_duplicate_platforms_deduplicated(self):
        brief = _brief(platforms=["TikTok", "TikTok", "YouTube"])
        assert brief.platforms == ["TikTok", "YouTube"]

    def test_frequency_bounds(self):
        with pytest.raises(ValidationError):
            _brief(posts_per_week=0)
        with pytest.raises(ValidationError):
            _brief(posts_per_week=99)


class TestStrategy:
    def test_goal_classification(self):
        assert classify_goal("Drive SALES and leads") == "conversion"
        assert classify_goal("teach people how to edit") == "education"
        assert classify_goal("something vague") == "awareness"

    def test_pillars_are_deterministic_and_on_brief(self):
        brief = _brief(goal="education and tutorials")
        first = build_pillars(brief)
        assert first == build_pillars(brief)
        assert len(first) == 3
        assert all("AI video editing" in pillar["angle"] for pillar in first)
        assert all(pillar["goal"] == "education" for pillar in first)

    def test_calendar_size_and_rotation(self):
        brief = _brief(posts_per_week=2, horizon_weeks=3)
        pillars = build_pillars(brief)
        calendar = build_calendar(brief, pillars, start_date=date(2026, 1, 5))
        assert len(calendar) == 6
        assert [entry["platform"] for entry in calendar] == ["TikTok", "YouTube"] * 3
        assert calendar[0]["pillar"] == pillars[0]["name"]
        assert calendar[1]["pillar"] == pillars[1]["name"]
        assert calendar[0]["date"] == "2026-01-05"
        assert all(entry["status"] == "planned" for entry in calendar)

    def test_hashtags_clean_and_deterministic(self):
        brief = _brief()
        tags = build_hashtags(brief)
        assert tags == build_hashtags(brief)
        assert all(tag.startswith("#") and " " not in tag for tag in tags)
        assert "#GenForgeLabs" in tags and "#AIVideoEditing" in tags

    def test_cta_follows_goal(self):
        assert "link in bio" in build_cta(_brief(goal="increase sales"))
        assert "Comment" in build_cta(_brief(goal="boost engagement"))


class TestBuildCampaign:
    def test_no_video_no_fakes(self, tmp_path):
        project = ProjectState()
        campaign = build_campaign(
            project, _brief(), output_dir=str(tmp_path),
            script_generator=_stub_script_generator,
        )
        assert campaign["status"] == "partial"
        assert project.campaign is campaign
        clips = campaign["assets"]["clips"]
        assert clips[0]["status"] == "unavailable" and clips[0]["path"] is None
        thumbs = campaign["assets"]["thumbnails"]
        assert thumbs[0]["status"] == "unavailable"
        # Every referenced script id really exists in the project.
        for item in campaign["assets"]["scripts"]:
            assert item["status"] == "generated"
            assert any(entry["script_id"] == item["script_id"] for entry in project.scripts)

    def test_failed_generator_is_honest(self, tmp_path):
        def broken(prompt):
            raise RuntimeError("Gemini quota exhausted")

        project = ProjectState()
        campaign = build_campaign(project, _brief(), output_dir=str(tmp_path), script_generator=broken)
        assert all(item["status"] == "unavailable" for item in campaign["assets"]["scripts"])
        assert campaign["status"] == "unavailable"
        assert project.scripts == []
        assert all(entry["script_ref"] is None for entry in campaign["calendar"])

    def test_full_pipeline_with_injected_builders(self, tmp_path):
        clip_path = tmp_path / "clip.mp4"
        clip_path.write_bytes(b"\x00\x00\x00\x18ftypisom")  # only paths matter; builders are stubbed

        def clip_builder(video, out_dir, platforms):
            rendered = Path(out_dir) / "campaign_clip.mp4"
            rendered.write_bytes(b"rendered")
            return {"status": "rendered", "path": str(rendered),
                    "platform_versions": {"master": str(rendered), **{p: str(rendered) for p in platforms}},
                    "version_errors": {}, "highlight": {"start": 0.0, "end": 4.0, "score": 71.0, "reason": "stub"}}

        def thumb_builder(video, out_dir, titles):
            return {"status": "rendered", "variants": [
                {"thumbnail_id": "t1", "title": titles[0], "path": str(Path(out_dir) / "thumb.png"),
                 "created_at": "2026-01-01T00:00:00+00:00", "frame_source": "auto",
                 "frame_time": 0.0, "selected": False},
            ]}

        project = ProjectState()
        campaign = build_campaign(
            project, _brief(), video_source=str(clip_path), output_dir=str(tmp_path),
            script_generator=_stub_script_generator,
            clip_builder=clip_builder, thumbnail_builder=thumb_builder,
        )
        assert campaign["status"] == "ready"
        assert campaign["assets"]["clips"][0]["status"] == "rendered"
        assert campaign["assets"]["thumbnails"][0]["status"] == "rendered"
        # Real project state was updated: source, version, thumbnails.
        assert any(Path(source).name == "clip.mp4" for source in project.source_assets)
        assert len(project.outputs) == 1 and project.outputs[0].analytics["campaign"] is True
        assert len(project.thumbnails) == 1
        # Captions reference the stored scripts.
        caption = campaign["assets"]["captions"][0]
        assert caption["script_ref"] is not None
        assert caption["cta"] == campaign["cta"]
        assert caption["text"].endswith(campaign["hashtags"][4] if len(campaign["hashtags"]) > 4 else campaign["hashtags"][-1])

    def test_campaign_survives_project_roundtrip(self, tmp_path):
        project = ProjectState()
        build_campaign(project, _brief(), output_dir=str(tmp_path), script_generator=_stub_script_generator)
        restored = ProjectState.model_validate_json(project.model_dump_json())
        assert restored.campaign is not None
        assert restored.campaign["brief"]["brand"] == "GenForge Labs"
        assert "campaign" in restored.ai_context()

    def test_invalid_webhook_reported_honestly(self, tmp_path):
        project = ProjectState()
        campaign = build_campaign(
            project, _brief(), output_dir=str(tmp_path),
            script_generator=_stub_script_generator, webhook_url="not-a-url",
        )
        assert campaign["webhook_dispatched"] is False
        assert "webhook_error" in campaign
