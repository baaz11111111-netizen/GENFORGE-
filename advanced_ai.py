"""AI voice and thumbnail helpers used by the Streamlit demo."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Thumbnail sampling budget: how many evenly spaced candidate frames to score,
# and the width used for cheap sharpness scoring (final frame stays full-res).
_THUMB_SAMPLE_TARGET = 15
_THUMB_SCORE_WIDTH = 640

VOICE_PRESETS = {
    "narrator_male": "en-US-ChristopherNeural",
    "narrator_female": "en-US-AriaNeural",
    "energetic_male": "en-US-GuyNeural",
    "news_anchor": "en-GB-RyanNeural",
    "casual_female": "en-US-JennyNeural",
}


async def _edge_tts(text: str, voice_key: str, output_path: str) -> None:
    import edge_tts

    voice = VOICE_PRESETS.get(voice_key, VOICE_PRESETS["narrator_male"])
    await edge_tts.Communicate(text=text, voice=voice).save(output_path)


def _run_coroutine(coroutine: Any) -> None:
    """Run a coroutine from sync Streamlit code, including an active-loop context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coroutine)
        return

    import threading
    import queue

    errors: queue.Queue[BaseException] = queue.Queue()

    def worker() -> None:
        try:
            asyncio.run(coroutine)
        except BaseException as exc:  # propagate provider failure to the caller
            errors.put(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=90)
    if thread.is_alive():
        raise TimeoutError("Voiceover generation exceeded 90 seconds")
    if not errors.empty():
        raise errors.get()


def _verify_audio(path: str) -> str:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise RuntimeError(f"Voice provider produced no audio file: {path}")
    return path


def generate_expressive_tts_async(text: str, voice_key: str, output_path: str):
    """Compatibility coroutine for callers that already use async execution."""
    return _edge_tts(text, voice_key, output_path)


def generate_expressive_tts(text: str, voice_key: str, output_path: str) -> str:
    """Generate narration using Edge-TTS, falling back to gTTS when needed."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Voiceover script cannot be empty")
    destination = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(destination) or os.curdir, exist_ok=True)
    if os.path.exists(destination):
        os.remove(destination)

    edge_error: Exception | None = None
    try:
        _run_coroutine(_edge_tts(text.strip(), voice_key, destination))
        return _verify_audio(destination)
    except Exception as exc:
        edge_error = exc
        logger.warning("Edge-TTS failed; trying gTTS fallback: %s", exc)
        try:
            from gtts import gTTS

            gTTS(text=text.strip(), lang="en", slow=False).save(destination)
            return _verify_audio(destination)
        except Exception as fallback_error:
            raise RuntimeError(
                "Voiceover generation failed with both Edge-TTS and gTTS. "
                f"Edge-TTS: {edge_error}; gTTS: {fallback_error}"
            ) from fallback_error


def _thumb_sample_indices(frame_count: int) -> list[int]:
    step = max(1, frame_count // _THUMB_SAMPLE_TARGET)
    return list(range(0, frame_count, step))


def _sharpness(frame) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def _split_jpeg_stream(data: bytes) -> list[bytes]:
    """Split an image2pipe mjpeg stream into individual JPEG payloads."""
    frames: list[bytes] = []
    start = data.find(b"\xff\xd8")
    while start != -1:
        end = data.find(b"\xff\xd9", start + 2)
        if end == -1:
            break
        frames.append(data[start:end + 2])
        start = data.find(b"\xff\xd8", end + 2)
    return frames


def _score_candidates_ffmpeg(video_path: str, indices: list[int]) -> int | None:
    """Single FFmpeg pass: decode once, keep only candidate frames downscaled for scoring.

    Returns the winning source-frame index, or None when FFmpeg is unavailable.
    """
    select = "+".join(f"eq(n\\,{index})" for index in indices)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", video_path,
        "-vf", f"select='{select}',scale={_THUMB_SCORE_WIDTH}:-2",
        "-vsync", "vfr", "-c:v", "mjpeg", "-q:v", "3",
        "-f", "image2pipe", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("FFmpeg thumbnail sampling unavailable: %s", exc)
        return None
    if result.returncode != 0:
        return None
    best_rank, best_score = -1, -1.0
    for rank, payload in enumerate(_split_jpeg_stream(result.stdout)):
        decoded = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            continue
        score = _sharpness(decoded)
        if score > best_score:
            best_rank, best_score = rank, score
    if best_rank < 0 or best_rank >= len(indices):
        return None
    return indices[best_rank]


def _extract_full_frame_ffmpeg(video_path: str, index: int, fps: float):
    """Extract a single full-resolution frame at the winning timestamp."""
    timestamp = index / fps if fps > 0 else 0.0
    with tempfile.TemporaryDirectory(prefix="thumb_frame_") as tmpdir:
        frame_path = os.path.join(tmpdir, "frame.jpg")
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, timestamp):.6f}", "-i", video_path,
            "-frames:v", "1", "-q:v", "2", frame_path,
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0 or not os.path.isfile(frame_path):
            return None
        return cv2.imread(frame_path, cv2.IMREAD_COLOR)


def _pick_sharpest_frame_sequential(video_path: str, indices: list[int]):
    """OpenCV fallback: sequential grab/decode — never random-seeks."""
    wanted = set(indices)
    best_frame, best_score = None, -1.0
    cap = cv2.VideoCapture(video_path)
    try:
        index = 0
        while True:
            if index in wanted:
                ok, frame = cap.read()
            else:
                ok, frame = cap.grab(), None
            if not ok:
                break
            if frame is not None:
                score = _sharpness(frame)
                if score > best_score:
                    best_score, best_frame = score, frame
            index += 1
    finally:
        cap.release()
    return best_frame


def generate_auto_thumbnail(video_path: str, output_path: str, title_text: str = "MUST WATCH!") -> str:
    """Extract the sharpest sampled frame and add a high-visibility title.

    Frame selection samples evenly spaced candidates once (FFmpeg select
    pipeline at reduced scoring resolution, sequential OpenCV reads as
    fallback) instead of random-seeking per candidate, then extracts only the
    winning frame at full resolution.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    destination = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(destination) or os.curdir, exist_ok=True)

    # Deterministic asset cache: identical source + identical request reuses
    # the previously generated thumbnail instead of re-rendering.
    from services.asset_cache import asset_cache_key, fetch_asset, store_asset
    ext = os.path.splitext(destination)[1] or ".png"
    cache_key = asset_cache_key(video_path, "auto_thumbnail",
                                title_text=str(title_text), ext=ext)
    if fetch_asset(cache_key, ext, destination):
        return destination

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    finally:
        cap.release()
    if frame_count <= 0:
        raise ValueError(f"Video file has no frames: {video_path}")
    # Guard against broken metadata reporting fps=0.
    if fps <= 0:
        fps = 30.0  # safe fallback; timestamp precision is not critical here

    indices = _thumb_sample_indices(frame_count)
    best_frame = None
    winning_index = _score_candidates_ffmpeg(video_path, indices)
    if winning_index is not None:
        best_frame = _extract_full_frame_ffmpeg(video_path, winning_index, fps)
    if best_frame is None:
        best_frame = _pick_sharpest_frame_sequential(video_path, indices)
    if best_frame is None:
        raise ValueError(f"Could not extract a frame: {video_path}")

    image = Image.fromarray(cv2.cvtColor(best_frame, cv2.COLOR_BGR2RGB)).convert("RGB")
    image = ImageEnhance.Contrast(image).enhance(1.25)
    image = ImageEnhance.Color(image).enhance(1.35)
    image = ImageEnhance.Sharpness(image).enhance(1.4)
    draw = ImageDraw.Draw(image)
    width, height = image.size
    draw.rectangle([0, int(height * 0.7), width, height], fill=(0, 0, 0, 160))
    position = (int(width * 0.05), int(height * 0.78))
    clean_title = str(title_text).upper()
    # Load a system font; fall back to PIL's built-in bitmap font if none found.
    font_size = max(18, width // 20)
    font = None
    for candidate in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(candidate, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    draw.text((position[0] + 3, position[1] + 3), clean_title, fill="black", font=font)
    draw.text(position, clean_title, fill="#FFFF00", font=font)
    image.save(destination, quality=95)
    store_asset(cache_key, ext, destination)
    return destination
