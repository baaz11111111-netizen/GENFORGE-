from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VideoEditPlan(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    # Timing & Trimming
    trim_start: Optional[float] = Field(default=0.0, description="Start time for trimming in seconds")
    trim_end: Optional[float] = Field(default=0.0, description="End time for trimming in seconds")
    filter_start: Optional[float] = Field(default=None, description="Start time for filter application in seconds")
    filter_end: Optional[float] = Field(default=None, description="End time for filter application in seconds")

    # Effects & Motion
    speed: Optional[float] = Field(default=1.0, alias="speed_factor", description="Playback speed multiplier")
    color_preset: Optional[str] = Field(default="none", description="Color preset (teal_orange, monochrome, cinematic)")
    camera_animation: Optional[str] = Field(default="none", description="Camera effect (zoom_in, zoom_out, none)")
    fade_transition: bool = Field(default=False, description="Apply fade in/out transitions")

    # Overlays & Framing
    overlay_text: Optional[str] = Field(default="", alias="text_overlay", description="Text string to overlay")
    text_position: Optional[str] = Field(default="bottom_third", description="Text position (top, center, bottom_third)")
    aspect_ratio: Optional[str] = Field(default="original", description="Target aspect ratio (16:9, 9:16, 1:1)")
    logo_position: Optional[str] = Field(default="top_right", description="Watermark position")

    # Audio & Voiceover
    ai_voiceover_text: Optional[str] = Field(default="", description="Text to render via TTS voiceover")
    mute_original_audio: bool = Field(default=False, alias="audio_mute", description="Mute input video audio")

    # Pipeline Flags
    remove_silence: bool = Field(default=False, description="Auto-remove quiet pauses")
    auto_caption: bool = Field(default=False, description="Generate subtitles")
    extract_highlights: bool = Field(default=False, description="Auto-extract key moments")