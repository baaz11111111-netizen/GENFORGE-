"""Canonical project state shared by UI, orchestration, and exports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from pydantic import field_validator


class TimelineClip(BaseModel):
    clip_id: str = Field(default_factory=lambda: uuid4().hex)
    source_path: str
    order: int
    trim_start: float = 0.0
    trim_end: float | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)
    speed: float = 1.0
    transition: dict[str, Any] | None = None
    audio_operations: list[dict[str, Any]] = Field(default_factory=list)
    captions: list[dict[str, Any]] = Field(default_factory=list)
    transform: dict[str, Any] = Field(default_factory=dict)


class ProjectVersion(BaseModel):
    version_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    output_path: str
    status: Literal["rendered", "failed"] = "rendered"
    analytics: dict[str, Any] | None = None


class ProjectState(BaseModel):
    project_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = "Untitled Project"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: Literal["draft", "processing", "ready", "failed"] = "draft"
    source_assets: list[str] = Field(default_factory=list)
    timeline: list[TimelineClip] = Field(default_factory=list)
    ai_plan: dict[str, Any] | None = None
    analytics: dict[str, Any] | None = None
    captions: list[dict[str, Any]] = Field(default_factory=list)
    scripts: list[dict[str, Any]] = Field(default_factory=list)
    thumbnails: list[dict[str, Any]] = Field(default_factory=list)
    campaign: dict[str, Any] | None = None
    outputs: list[ProjectVersion] = Field(default_factory=list)
    telemetry: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Project name must be text.")
        name = value.strip()
        if not name:
            raise ValueError("Project name cannot be empty.")
        if len(name) > 120:
            raise ValueError("Project name must be 120 characters or fewer.")
        if name in {".", ".."} or any(char in name for char in '<>:"/\\|?*'):
            raise ValueError("Project name contains invalid filesystem characters.")
        if any(ord(char) < 32 for char in name):
            raise ValueError("Project name contains invalid control characters.")
        return name

    def set_timeline(self, clips: list[TimelineClip]) -> None:
        """Replace the canonical timeline after validating clip ordering."""
        orders = [clip.order for clip in clips]
        if len(set(orders)) != len(orders) or sorted(orders) != list(range(len(orders))):
            raise ValueError("Timeline clip orders must be unique and contiguous from zero.")
        self.timeline = sorted(clips, key=lambda clip: clip.order)

    def update_clip(self, clip_id: str, **changes: Any) -> TimelineClip:
        for clip in self.timeline:
            if clip.clip_id == clip_id:
                updated = clip.model_copy(update=changes)
                self.timeline[self.timeline.index(clip)] = updated
                return updated
        raise KeyError(f"Timeline clip not found: {clip_id}")

    def add_source(self, path: str) -> None:
        resolved = str(Path(path).resolve())
        if resolved not in self.source_assets:
            self.source_assets.append(resolved)

    def add_version(self, output_path: str, analytics: dict[str, Any] | None = None) -> ProjectVersion:
        version = ProjectVersion(output_path=str(Path(output_path).resolve()), analytics=analytics)
        self.outputs.append(version)
        self.analytics = analytics
        self.status = "ready"
        return version

    def record_error(self, message: str) -> None:
        self.errors.append(message)
        self.status = "failed"

    def touch(self) -> None:
        """Stamp updated_at with the current UTC time."""
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def update_settings(self, **kwargs: Any) -> None:
        """Merge keyword arguments into project settings and stamp updated_at."""
        self.settings.update(kwargs)
        self.touch()

    def ai_context(self) -> dict[str, Any]:
        """Return the current canonical state for a planning or re-edit request."""
        return {
            "project_id": self.project_id,
            "timeline": [clip.model_dump() for clip in self.timeline],
            "ai_plan": self.ai_plan,
            "captions": self.captions,
            "scripts": self.scripts,
            "thumbnails": self.thumbnails,
            "campaign": self.campaign,
            "analytics": self.analytics,
            "outputs": [version.model_dump() for version in self.outputs],
            "status": self.status,
        }
