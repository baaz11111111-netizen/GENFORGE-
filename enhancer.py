import json
import os
import subprocess
import tempfile
import uuid as _uuid
from PIL import Image, ImageEnhance
from advanced_editing import check_audio_stream
from services.ai_service import generate_json


def auto_enhance_image(image_path: str, output_dir: str = "outputs") -> str:
    """Zero-prompt One-Click Image Enhancer.

    Output filename is unique per call so concurrent renders across different
    projects cannot overwrite one another's results.
    """
    img = Image.open(image_path).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.18)
    img = ImageEnhance.Sharpness(img).enhance(1.25)
    img = ImageEnhance.Brightness(img).enhance(1.03)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"enhanced_{_uuid.uuid4().hex}_image.png")
    img.save(out_path)
    return out_path


def auto_enhance_video(video_path: str, output_dir: str = "outputs") -> str:
    """Zero-prompt Video Enhancer with broadcast audio normalization.

    Output filename is unique per call so concurrent renders across different
    projects cannot overwrite one another's results.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"enhanced_{_uuid.uuid4().hex}_video.mp4")
    
    vf_filter = "eq=contrast=1.15:brightness=0.02:saturation=1.20:gamma=1.05,unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=0.8"
    has_audio = check_audio_stream(video_path)
    
    if has_audio:
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", vf_filter,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            out_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", vf_filter,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast",
            "-an",
            out_path
        ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Video enhancement exceeded 300 second timeout: {video_path}") from exc
    except subprocess.CalledProcessError as exc:
        diagnostics = (exc.stderr or exc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Video enhancement failed: {diagnostics[-3000:]}") from exc
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"Video enhancement produced no usable output: {out_path}")
    return out_path


def analyze_viral_score(media_path: str, media_type: str = "Video") -> dict:
    """Dynamic AI Viral Hook & Quality Analytics using Gemini Vision."""
    if not os.path.exists(media_path):
        return {"status": "unavailable", "reason": "Gemini API unavailable or media missing"}

    try:
        if media_type == "Image":
            img_asset = Image.open(media_path)
            prompt = (
                "Analyze this enhanced media asset for short-form video/social media performance. "
                "Return a strictly valid JSON object with keys: "
                "'viral_score' (string e.g. '91 / 100'), "
                "'hook_rating' (string e.g. 'A+ (High Retention)'), "
                "'audio_level' (string e.g. 'Optimized'), "
                "and 'recommendations' (array of 3 short string items)."
            )
            return generate_json(prompt, contents=[img_asset, prompt])
        if media_type == "Video":
            import cv2

            capture = cv2.VideoCapture(media_path)
            try:
                total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
                if total_frames <= 0 or fps <= 0:
                    return {"status": "unavailable", "reason": "Video has no readable frames"}

                with tempfile.TemporaryDirectory(prefix="genforge_analytics_") as frame_dir:
                    frame_paths = []
                    sample_count = min(4, total_frames)
                    for index in range(sample_count):
                        frame_number = min(total_frames - 1, round(index * (total_frames - 1) / max(1, sample_count - 1)))
                        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                        success, frame = capture.read()
                        if success:
                            frame_path = os.path.join(frame_dir, f"frame_{index}.jpg")
                            if cv2.imwrite(frame_path, frame):
                                frame_paths.append((frame_path, frame_number / fps))
                    if not frame_paths:
                        return {"status": "unavailable", "reason": "Video frames could not be extracted"}

                    images = []
                    for path, _ in frame_paths:
                        img = Image.open(path)
                        img.load()   # read fully before the tmpdir closes
                        images.append(img.copy())
                        img.close()
                    timestamps = ", ".join(f"{timestamp:.2f}s" for _, timestamp in frame_paths)
                    prompt = (
                        "Analyze these sequential keyframes from a video for short-form social performance. "
                        f"The keyframes occur at {timestamps}. Return strict JSON with keys: "
                        "'viral_score' (string like '91 / 100'), "
                        "'hook_rating' (string), 'audio_level' (string), "
                        "and 'recommendations' (array of 3 concise strings). "
                        "Assess only what is visible and do not invent audio facts."
                    )
                    result = generate_json(prompt, contents=[prompt, *images])
                    result.setdefault("audio_level", "Audio present" if check_audio_stream(media_path) else "No audio track")
                    return result
            finally:
                capture.release()
        return {"status": "unavailable", "reason": f"Unsupported media type: {media_type}"}
    except Exception as e:
        return {"status": "unavailable", "reason": f"Gemini Vision analysis failed: {e}"}