import os
import cv2
import subprocess
import tempfile
from typing import Dict, List, Tuple
from services.platform_profiles import PLATFORM_PROFILES, export_for_platform
from services.ai_service import generate_json
# ---------------------------------------------------------
# FEATURE B: GEMINI MULTIMODAL VIDEO KEYFRAME ANALYSIS
# ---------------------------------------------------------
def extract_sample_keyframes(video_path: str, num_frames: int = 5) -> List[str]:
    """Extracts N keyframes evenly across the video duration for AI visual scoring.

    Frames are written into a per-call temporary directory to prevent
    concurrent-user races on predictable ``uploads/frame_N.jpg`` filenames.
    The caller is responsible for deleting the returned directory after use;
    the tmpdir path is the first element of the tuple returned.
    Returns absolute paths inside the tmpdir.
    """
    import shutil as _shutil

    tmpdir = tempfile.mkdtemp(prefix="genforge_keyframes_")
    cap = cv2.VideoCapture(video_path)
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            _shutil.rmtree(tmpdir, ignore_errors=True)
            return []

        frame_paths = []
        step = max(1, total_frames // num_frames)

        for i in range(num_frames):
            frame_idx = i * step
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret:
                out_path = os.path.join(tmpdir, f"frame_{i}.jpg")
                cv2.imwrite(out_path, frame)
                frame_paths.append(out_path)

        return frame_paths
    except Exception:
        # If extraction fails before returning any paths, clean up now.
        _shutil.rmtree(tmpdir, ignore_errors=True)
        return []
    finally:
        cap.release()


def analyze_video_emotions_and_hooks(video_path: str) -> Dict[str, str]:
    """Uses Gemini Vision API to score visual hook quality and recommend best cut points."""
    from PIL import Image
    import shutil

    frame_paths = extract_sample_keyframes(video_path, num_frames=4)
    if not frame_paths:
        return {"status": "unavailable", "reason": "No video frames could be extracted"}

    # All frame files share the same tmpdir — clean it up when done.
    tmpdir = os.path.dirname(frame_paths[0]) if frame_paths else None
    try:
        pil_images = []
        for path in frame_paths:
            img = Image.open(path)
            img.load()   # force read while file is still open-able
            pil_images.append(img.copy())
            img.close()

        prompt = (
            "Analyze these sequential keyframes from a video reel. "
            "1. Give a Hook Quality Score out of 10. "
            "2. Identify the most engaging visual moment timestamp. "
            "3. Give 1 sentence of creator advice for maximum retention. "
            "Format response strictly as JSON with keys: 'hook_score', 'best_moment', 'summary'."
        )

        return generate_json(prompt, contents=[prompt, *pil_images])
    except (RuntimeError, ValueError, OSError) as exc:
        return {"status": "unavailable", "reason": f"Gemini analysis failed: {exc}"}
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------
# FEATURE D: ONE-CLICK OMNI-PLATFORM ADAPTATION ENGINE
# ---------------------------------------------------------
def export_omni_platform_suite(input_video: str, output_dir: str = "outputs") -> Dict[str, str]:
    """Renders a single video asset into 3 platform formats: 9:16 (TikTok), 1:1 (Insta), 16:9 (YouTube)."""
    outputs = {}
    base_name = os.path.splitext(os.path.basename(input_video))[0]

    formats = {"tiktok_9_16": "TikTok", "square_1_1": "Square Feed", "youtube_16_9": "YouTube"}
    for fmt_key, platform in formats.items():
        fmt_info = PLATFORM_PROFILES[platform]
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{base_name}_{fmt_info.ratio.replace(':', 'x')}.mp4")
        try:
            outputs[fmt_key] = export_for_platform(input_video, output_path, platform)
        except (OSError, RuntimeError, ValueError) as e:
            print(f"[Warning] Omni-platform export failed for {fmt_key}: {e}")
            outputs[fmt_key] = None

    return outputs