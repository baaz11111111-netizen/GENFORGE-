"""Phase 5 — AI Script Studio regression tests."""
import pytest

from services.project_model import ProjectState
from services.script_studio import (
    GeneratedScript,
    ScriptRequest,
    edit_script_version,
    estimate_duration_seconds,
    generate_script,
    save_script_version,
    script_caption_segments,
    script_to_voiceover,
)

VALID_SCRIPT = {
    "hook": "Stop scrolling — this changes everything.",
    "introduction": "Today we cover the one technique most creators miss.",
    "body": "Step one: plan. Step two: record. Step three: publish consistently.",
    "cta": "Follow for part two tomorrow.",
    "alternate_hooks": ["You are editing this wrong.", "Nobody tells you this."],
    "short_version": "Plan, record, publish. Follow for more.",
    "long_version": "A longer detailed walkthrough of planning, recording, and publishing.",
}


def _request(**overrides):
    base = dict(topic="Video editing workflow", audience="new creators",
                platform="TikTok", duration_seconds=45.0, tone="Energetic", goal="growth")
    base.update(overrides)
    return ScriptRequest(**base)


class TestRequestValidation:
    def test_valid_request(self):
        assert _request().platform == "TikTok"

    def test_empty_topic_rejected(self):
        with pytest.raises(ValueError):
            _request(topic="   ")

    def test_unknown_platform_rejected(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            _request(platform="MySpace")

    def test_unknown_tone_rejected(self):
        with pytest.raises(ValueError, match="Unknown tone"):
            _request(tone="Angry")

    def test_absurd_duration_rejected(self):
        with pytest.raises(ValueError):
            _request(duration_seconds=99999.0)


class TestGeneration:
    def test_generated_script_validated(self):
        result = generate_script(_request(), generator=lambda prompt: dict(VALID_SCRIPT))
        assert result["status"] == "generated"
        assert result["script"]["hook"] == VALID_SCRIPT["hook"]

    def test_unavailable_ai_reports_honestly(self):
        def broken(prompt):
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        result = generate_script(_request(), generator=broken)
        assert result["status"] == "unavailable" and result["script"] is None
        assert "FEATURE UNAVAILABLE" in result["message"]

    def test_invalid_ai_response_never_fabricated(self):
        result = generate_script(_request(), generator=lambda prompt: {"hook": ""})
        assert result["status"] == "invalid" and result["script"] is None

    def test_empty_section_rejected(self):
        with pytest.raises(ValueError):
            GeneratedScript.model_validate({**VALID_SCRIPT, "body": "  "})


class TestVersioning:
    def test_save_and_edit_versions(self):
        project = ProjectState()
        v1 = save_script_version(project, VALID_SCRIPT, label="AI draft")
        v2 = edit_script_version(project, v1["script_id"], {"cta": "Comment YES below."})
        assert len(project.scripts) == 2
        assert v2["parent_id"] == v1["script_id"]
        assert project.scripts[0]["script"]["cta"] == VALID_SCRIPT["cta"]  # v1 intact

    def test_edit_unknown_script_raises(self):
        project = ProjectState()
        with pytest.raises(KeyError):
            edit_script_version(project, "missing", {"hook": "x"})

    def test_edit_rejects_emptying_section(self):
        project = ProjectState()
        v1 = save_script_version(project, VALID_SCRIPT)
        with pytest.raises(ValueError):
            edit_script_version(project, v1["script_id"], {"hook": ""})

    def test_scripts_survive_project_roundtrip(self):
        project = ProjectState()
        save_script_version(project, VALID_SCRIPT)
        restored = ProjectState.model_validate_json(project.model_dump_json())
        assert restored.scripts[0]["script"]["hook"] == VALID_SCRIPT["hook"]
        assert "scripts" in restored.ai_context()


class TestTimingHelpers:
    def test_duration_estimate(self):
        assert estimate_duration_seconds("one two three four five") == 2.0

    def test_empty_text_rejected(self):
        with pytest.raises(ValueError):
            estimate_duration_seconds("")

    def test_caption_segments_cover_timeline(self):
        segments = script_caption_segments("a b c d e f g h i j", total_seconds=10.0, max_words_per_caption=4)
        assert len(segments) == 3
        assert segments[0]["start"] == 0.0
        assert segments[-1]["end"] == pytest.approx(10.0)
        assert all(seg["end"] > seg["start"] for seg in segments)

    def test_caption_segments_reject_bad_input(self):
        with pytest.raises(ValueError):
            script_caption_segments("words", total_seconds=0)
        with pytest.raises(ValueError):
            script_caption_segments("", total_seconds=5)


class TestVoiceoverHandoff:
    def test_empty_script_rejected(self):
        with pytest.raises(ValueError):
            script_to_voiceover("   ", "out.mp3")

    def test_unavailable_tts_reported_honestly(self, monkeypatch, tmp_path):
        import advanced_ai
        def boom(text, voice, path):
            raise RuntimeError("Voiceover generation failed with both Edge-TTS and gTTS.")
        monkeypatch.setattr(advanced_ai, "generate_expressive_tts", boom)
        result = script_to_voiceover("Hello world", str(tmp_path / "vo.mp3"))
        assert result["status"] == "unavailable" and result["path"] is None
        assert "TTS FEATURE UNAVAILABLE" in result["message"]
