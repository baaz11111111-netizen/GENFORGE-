"""Thumbnail Studio: frame selection, text overlays, variants, project assets.

Frame scoring is deterministic (Laplacian sharpness via OpenCV) and honestly
labelled — it is never presented as Gemini output. Variants are stored as
project assets so users can compare and select a preferred thumbnail.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

PLACEMENTS = ("bottom_bar", "top_left", "top_right", "auto")


def _require_cv2() -> None:
    if not HAS_CV2:
        raise RuntimeError(
            "FEATURE UNAVAILABLE: Thumbnail frame extraction requires OpenCV. "
            "Install with: pip install opencv-python"
        )


def extract_candidate_frames(video_path: str, count: int = 8) -> list[dict[str, Any]]:
    """Sample evenly spaced frames with deterministic sharpness scores."""
    _require_cv2()
    if count <= 0 or count > 30:
        raise ValueError("count must be between 1 and 30.")
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        if frame_count <= 0:
            raise ValueError(f"Video file has no frames: {video_path}")
        indices = [int(i * (frame_count - 1) / max(1, count - 1)) for i in range(count)] if count > 1 else [frame_count // 2]
        wanted = sorted(set(indices))
        wanted_set = set(wanted)
        candidates = []
        # Sequential grab/read: one decode pass instead of one seek per candidate.
        index = 0
        while True:
            if index in wanted_set:
                ok, frame = capture.read()
            else:
                ok = capture.grab()   # skip this frame; don't decode it
                frame = None
            if not ok:
                break
            if frame is not None:
                score = float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
                candidates.append({
                    "candidate_id": uuid4().hex,
                    "frame_index": index,
                    "time": round(index / fps, 3),
                    "sharpness": round(score, 3),
                    "image": cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                })
            index += 1
    finally:
        capture.release()
    if not candidates:
        raise ValueError(f"Could not extract any frames: {video_path}")
    return candidates


def select_best_frame(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic auto-selection: sharpest sampled frame."""
    if not candidates:
        raise ValueError("No candidate frames supplied.")
    return max(candidates, key=lambda candidate: candidate["sharpness"])


def select_frame_at(video_path: str, seconds: float) -> dict[str, Any]:
    """Manual frame selection at an explicit timestamp."""
    _require_cv2()
    if seconds < 0:
        raise ValueError("Frame timestamp cannot be negative.")
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    capture = cv2.VideoCapture(video_path)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        ok, frame = capture.read()
        if not ok:
            raise ValueError(f"Could not read frame at {seconds:.2f}s: {video_path}")
    finally:
        capture.release()
    return {"candidate_id": uuid4().hex, "time": round(seconds, 3), "image": cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)}


def _load_font(size: int):
    for candidate in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _quiet_half(image: Image.Image) -> str:
    """Subject-aware placement: choose the side with less edge activity."""
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    width, height = edges.size
    left = edges.crop((0, 0, width // 2, height)).getbbox()
    right = edges.crop((width // 2, 0, width, height)).getbbox()
    left_energy = (left[2] - left[0]) * (left[3] - left[1]) if left else 0
    right_energy = (right[2] - right[0]) * (right[3] - right[1]) if right else 0
    return "top_right" if left_energy > right_energy else "top_left"


def render_thumbnail(
    frame_image: Image.Image,
    output_path: str,
    title: str = "",
    placement: str = "auto",
) -> str:
    """Enhance a frame and overlay a title with the requested placement."""
    if placement not in PLACEMENTS:
        raise ValueError(f"Unknown placement '{placement}'. Available: {', '.join(PLACEMENTS)}")
    image = frame_image.convert("RGB")
    image = ImageEnhance.Contrast(image).enhance(1.15)
    image = ImageEnhance.Sharpness(image).enhance(1.3)
    width, height = image.size
    draw = ImageDraw.Draw(image)

    if title and title.strip():
        resolved = _quiet_half(image) if placement == "auto" else placement
        font = _load_font(max(16, height // 10))
        clean = title.strip().upper()
        if resolved == "bottom_bar":
            draw.rectangle([0, int(height * 0.72), width, height], fill=(0, 0, 0))
            position = (int(width * 0.04), int(height * 0.78))
        elif resolved == "top_left":
            position = (int(width * 0.04), int(height * 0.05))
        else:
            bbox = draw.textbbox((0, 0), clean, font=font)
            position = (int(width * 0.96) - (bbox[2] - bbox[0]), int(height * 0.05))
        draw.text((position[0] + 3, position[1] + 3), clean, font=font, fill="black")
        draw.text(position, clean, font=font, fill="#FFD60A")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    image.save(output_path, format="PNG", quality=95)
    return output_path


def generate_thumbnail_variants(
    video_path: str,
    output_dir: str,
    titles: list[str],
    frame_count: int = 6,
) -> list[dict[str, Any]]:
    """Build comparable variants: best auto frame + manual first-frame, per title."""
    candidates = extract_candidate_frames(video_path, count=frame_count)
    best = select_best_frame(candidates)
    manual = candidates[0]
    os.makedirs(output_dir, exist_ok=True)
    variants = []
    for index, title in enumerate(titles):
        for source, label in ((best, "auto"), (manual, "first")):
            destination = os.path.join(output_dir, f"thumb_{label}_{index}.png")
            render_thumbnail(Image.fromarray(source["image"]), destination, title=title, placement="auto")
            variants.append({
                "thumbnail_id": uuid4().hex,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "title": title,
                "frame_source": label,
                "frame_time": source.get("time", 0.0),
                "path": destination,
                "selected": False,
            })
    return variants


def add_thumbnails_to_project(project, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Store thumbnail variants as project assets (additive; never overwrites)."""
    if not variants:
        raise ValueError("No thumbnail variants supplied.")
    stored = list(getattr(project, "thumbnails", []) or [])
    stored.extend(dict(variant) for variant in variants)
    project.thumbnails = stored
    return stored


def select_preferred_thumbnail(project, thumbnail_id: str) -> dict[str, Any]:
    """Mark one stored variant as preferred (selection is stored, not destructive)."""
    stored = getattr(project, "thumbnails", []) or []
    target = next((entry for entry in stored if entry.get("thumbnail_id") == thumbnail_id), None)
    if target is None:
        raise KeyError(f"Thumbnail not found: {thumbnail_id}")
    for entry in stored:
        entry["selected"] = entry.get("thumbnail_id") == thumbnail_id
    project.thumbnails = stored
    return target


__all__ = [
    "PLACEMENTS",
    "extract_candidate_frames",
    "select_best_frame",
    "select_frame_at",
    "render_thumbnail",
    "generate_thumbnail_variants",
    "add_thumbnails_to_project",
    "select_preferred_thumbnail",
]
