"""AI Script Studio: structured script generation, versioning, and TTS handoff.

Built on the shared Gemini client (services.ai_service) and the existing
voiceover pipeline (advanced_ai.generate_expressive_tts). AI output is always
validated against the GeneratedScript schema; when the AI is unavailable the
feature reports "unavailable" instead of fabricating text.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from services.ai_service import generate_json

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ("TikTok", "Instagram Reels", "YouTube Shorts", "YouTube", "Square/Social", "Podcast", "Blog")
SUPPORTED_TONES = ("Energetic", "Friendly", "Professional", "Dramatic", "Educational", "Humorous")


class ScriptRequest(BaseModel):
    """User brief for one script generation."""

    topic: str
    audience: str
    platform: str = "YouTube"
    duration_seconds: float = Field(default=60.0, gt=0, le=3600)
    tone: str = "Friendly"
    goal: str = ""

    @field_validator("topic", "audience")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Topic and audience are required.")
        return value.strip()

    @field_validator("platform")
    @classmethod
    def _known_platform(cls, value: str) -> str:
        if value not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unknown platform '{value}'. Available: {', '.join(SUPPORTED_PLATFORMS)}")
        return value

    @field_validator("tone")
    @classmethod
    def _known_tone(cls, value: str) -> str:
        if value not in SUPPORTED_TONES:
            raise ValueError(f"Unknown tone '{value}'. Available: {', '.join(SUPPORTED_TONES)}")
        return value


class GeneratedScript(BaseModel):
    """Validated AI script structure."""

    hook: str
    introduction: str
    body: str
    cta: str
    alternate_hooks: list[str] = Field(default_factory=list)
    short_version: str
    long_version: str

    @field_validator("hook", "introduction", "body", "cta", "short_version", "long_version")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Script sections must be non-empty text.")
        return value.strip()

    def full_text(self) -> str:
        return "\n\n".join([self.hook, self.introduction, self.body, self.cta])


_SCRIPT_PROMPT = """You are a professional short-form video scriptwriter.
Write a script for this brief and return ONLY a JSON object with keys:
hook, introduction, body, cta, alternate_hooks (list of 2 strings),
short_version, long_version.

Brief:
- Topic: {topic}
- Audience: {audience}
- Platform: {platform}
- Target duration: {duration}s
- Tone: {tone}
- Goal: {goal}
"""


def generate_script(request: ScriptRequest, generator: Callable[[str], dict] | None = None) -> dict:
    """Generate a validated script. Never fabricates output.

    Returns {"status": "generated"|"unavailable"|"invalid", "script": ..., "message": ...}.
    ``generator`` is injectable for tests; production uses the shared Gemini client.
    """
    prompt = _SCRIPT_PROMPT.format(
        topic=request.topic, audience=request.audience, platform=request.platform,
        duration=int(request.duration_seconds), tone=request.tone, goal=request.goal or "engagement",
    )
    produce = generator or (lambda p: generate_json(p))
    try:
        raw = produce(prompt)
    except RuntimeError as exc:
        return {"status": "unavailable", "script": None, "message": f"FEATURE UNAVAILABLE: {exc}"}
    except Exception as exc:
        return {"status": "unavailable", "script": None, "message": f"AI generation could not run: {exc}"}
    try:
        script = GeneratedScript.model_validate(raw)
    except Exception as exc:
        logger.warning("AI script response failed validation: %s", exc)
        return {"status": "invalid", "script": None, "message": f"AI returned an invalid script: {exc}"}
    return {"status": "generated", "script": script.model_dump(), "message": "Script generated."}


def save_script_version(project, script: dict, label: str = "AI draft", parent_id: str | None = None) -> dict:
    """Store a script version in the project (additive; older versions survive)."""
    GeneratedScript.model_validate(script)
    if not label or not label.strip():
        raise ValueError("Script version label is required.")
    version = {
        "script_id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": label.strip(),
        "parent_id": parent_id,
        "script": dict(script),
    }
    scripts = list(getattr(project, "scripts", []) or [])
    scripts.append(version)
    project.scripts = scripts
    return version


def edit_script_version(project, script_id: str, updates: dict[str, str], label: str = "Manual edit") -> dict:
    """Edit a stored script by creating a validated child version."""
    current = next((entry for entry in getattr(project, "scripts", []) if entry.get("script_id") == script_id), None)
    if current is None:
        raise KeyError(f"Script version not found: {script_id}")
    merged = dict(current["script"])
    allowed = set(GeneratedScript.model_fields)
    for key, value in updates.items():
        if key not in allowed:
            raise ValueError(f"Unknown script field: {key}")
        merged[key] = value
    GeneratedScript.model_validate(merged)  # rejects edits that empty sections
    return save_script_version(project, merged, label=label, parent_id=script_id)


def estimate_duration_seconds(text: str, words_per_second: float = 2.5) -> float:
    """Deterministic speech-duration estimate used when TTS is unavailable."""
    words = [word for word in text.split() if word.strip()]
    if not words:
        raise ValueError("Cannot estimate duration of empty text.")
    if words_per_second <= 0:
        raise ValueError("words_per_second must be positive.")
    return max(1.0, round(len(words) / words_per_second, 2))


def script_caption_segments(text: str, total_seconds: float, max_words_per_caption: int = 8) -> list[dict]:
    """Split script text into timed caption segments (compatible with caption_presets)."""
    if total_seconds <= 0:
        raise ValueError("total_seconds must be positive.")
    if max_words_per_caption <= 0:
        raise ValueError("max_words_per_caption must be positive.")
    words = text.split()
    if not words:
        raise ValueError("Caption text is required.")
    chunks = [words[i:i + max_words_per_caption] for i in range(0, len(words), max_words_per_caption)]
    weight_total = sum(len(chunk) for chunk in chunks)
    segments = []
    cursor = 0.0
    for chunk in chunks:
        span = total_seconds * len(chunk) / weight_total
        segments.append({
            "start": round(cursor, 3),
            "end": round(min(cursor + span, total_seconds), 3),
            "text": " ".join(chunk),
        })
        cursor += span
    return segments


def script_to_voiceover(script_text: str, output_path: str, voice_key: str = "en-US-AriaNeural") -> dict:
    """SCRIPT → TTS handoff using the existing expressive TTS pipeline.

    Honest status reporting: unavailable TTS dependencies never fake success.
    """
    if not script_text or not script_text.strip():
        raise ValueError("Script text is required for voiceover.")
    from advanced_ai import generate_expressive_tts
    try:
        path = generate_expressive_tts(script_text, voice_key, output_path)
        return {"status": "rendered", "path": path, "message": "Voiceover rendered."}
    except Exception as exc:
        return {"status": "unavailable", "path": None,
                "message": f"TTS FEATURE UNAVAILABLE: {exc}. Install edge-tts or gTTS."}


__all__ = [
    "SUPPORTED_PLATFORMS",
    "SUPPORTED_TONES",
    "ScriptRequest",
    "GeneratedScript",
    "generate_script",
    "save_script_version",
    "edit_script_version",
    "estimate_duration_seconds",
    "script_caption_segments",
    "script_to_voiceover",
]
