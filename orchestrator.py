import json

import math

import os
import re
import subprocess
import uuid
from typing import List, Optional, Tuple

from advanced_editing import auto_caption_video, check_audio_stream, extract_highlights, remove_silence, resize_video_aspect
from schema import VideoEditPlan
from services.ai_service import DEFAULT_GEMINI_MODEL, get_gemini_client
from services.media_probe import probe_media


def get_video_metadata(video_path: str) -> Tuple[float, int, int]:
    """Fetch exact duration and dimensions; probing failures are actionable errors."""
    metadata = probe_media(video_path)
    if metadata.width is None or metadata.height is None:
        raise RuntimeError(f"Video stream dimensions are unavailable: {video_path}")
    return metadata.duration, metadata.width, metadata.height


def get_system_font_path() -> str:
    """Locates a valid system font path and escapes Windows colons for FFmpeg."""
    # Use %WINDIR% / $WINDIR env var so the path works regardless of install drive.
    windir = os.environ.get("WINDIR", "C:/Windows")
    possible_fonts = [
        os.path.join(windir, "Fonts", "arial.ttf"),
        os.path.join(windir, "Fonts", "calibri.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for font in possible_fonts:
        if os.path.exists(font):
            return font.replace("\\", "/").replace(":", "\\:")
    return ""


def generate_tts_voiceover(text: str, output_path: str) -> bool:
    """Generates an AI voiceover MP3 using gTTS if available."""
    try:
        from gtts import gTTS  # type: ignore

        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(output_path)
        return True
    except Exception as e:
        print(f"[Warning] TTS generation skipped ({e}). Ensure gTTS is installed.")
        return False


def build_atempo_filter(speed: float) -> str:
    """Chains multiple atempo filters to support speed ratios outside [0.5, 2.0]."""
    if speed <= 0:
        return "atempo=1.0"

    filters = []
    curr = speed
    while curr > 2.0:
        filters.append("atempo=2.0")
        curr /= 2.0
    while curr < 0.5:
        filters.append("atempo=0.5")
        curr /= 0.5
    filters.append(f"atempo={curr:.4f}")
    return ",".join(filters)


def extract_filter_time_window(user_prompt: str) -> Tuple[Optional[float], Optional[float]]:
    """Parse time range strictly for filters/effects, supporting units (s, sec, second) and ordinals (5th, 8th)."""
    prompt_lower = user_prompt.lower()

    # Robust matching for: "5", "5.5", "5th", "5 sec", "5 second", "5 seconds"
    num_pattern = r"(\d+(?:\.\d+)?)(?:\s*(?:st|nd|rd|th))?(?:\s*(?:s|sec|secs|second|seconds))?"
    
    range_pattern = re.compile(
        rf"\b(?:from|between|at)?\s*{num_pattern}\s*(?:to|-|and|until)\s*{num_pattern}\b",
        re.IGNORECASE,
    )
    
    effect_pattern = re.compile(
        r"\b(teal|orange|cinematic|monochrome|bw|color|filter|effect|text|overlay|hue|gamma)\b",
        re.IGNORECASE,
    )
    trim_pattern = re.compile(r"\b(trim|cut|crop)\b", re.IGNORECASE)

    for time_match in range_pattern.finditer(prompt_lower):
        window_start = max(0, time_match.start() - 80)
        window_end = min(len(prompt_lower), time_match.end() + 80)
        
        nearby_effects = list(effect_pattern.finditer(prompt_lower, window_start, window_end))
        if not nearby_effects:
            continue

        nearby_trims = list(trim_pattern.finditer(prompt_lower, window_start, time_match.start()))
        effects_before_range = [e for e in nearby_effects if e.end() <= time_match.start()]

        # Prevent a trimming range from being absorbed by a downstream filter keyword
        if nearby_trims and not effects_before_range:
            continue

        try:
            start_t = float(time_match.group(1))
            end_t = float(time_match.group(2))
            if math.isfinite(start_t) and math.isfinite(end_t) and start_t >= 0 and end_t > start_t:
                return start_t, end_t
        except (TypeError, ValueError):
            continue

    return None, None


def apply_rule_based_fallbacks(
    user_prompt: str, plan: VideoEditPlan
) -> VideoEditPlan:
    """Guarantees prompt intent parsing accuracy via regex heuristics."""
    prompt_lower = user_prompt.lower()

    if any(k in prompt_lower for k in ["mute", "no audio", "remove audio", "silent", "remove sound"]):
        plan.mute_original_audio = True

    if any(k in prompt_lower for k in ["remove silence", "cut pauses", "remove silent", "trim dead space"]):
        plan.remove_silence = True

    if any(k in prompt_lower for k in ["caption", "subtitles", "add captions", "auto caption"]):
        plan.auto_caption = True

    if any(k in prompt_lower for k in ["highlight", "best moments", "extract key moment", "auto highlight"]):
        plan.extract_highlights = True

    # Trimming detection - isolated from filter keywords
    trim_match_full = re.search(r"\btrim\b\s+(?:from\s+)?(\d+\.?\d*)\s*(?:to|-|until)\s*(\d+\.?\d*)", prompt_lower)
    trim_match_end = re.search(
        r"\btrim\b(?:(?!\b(?:teal|orange|cinematic|monochrome|bw|color|filter|effect)\b).)*?"
        r"(?:to|first|for)\s+(\d+\.?\d*)",
        prompt_lower,
    )

    if trim_match_full:
        plan.trim_start = float(trim_match_full.group(1))
        plan.trim_end = float(trim_match_full.group(2))
    elif trim_match_end:
        plan.trim_start = 0.0
        plan.trim_end = float(trim_match_end.group(1))

    speed_match = re.search(r"(\d+(\.\d+)?)x", prompt_lower)
    if speed_match:
        plan.speed = float(speed_match.group(1))
    elif "speed up" in prompt_lower or "faster" in prompt_lower:
        if plan.speed == 1.0:
            plan.speed = 1.2
    elif "slow down" in prompt_lower or "slower" in prompt_lower:
        if plan.speed == 1.0:
            plan.speed = 0.5

    if "1:1" in prompt_lower or "square" in prompt_lower:
        plan.aspect_ratio = "1:1"
    elif any(k in prompt_lower for k in ["9:16", "vertical", "shorts", "reel", "tiktok"]):
        plan.aspect_ratio = "9:16"
    elif any(k in prompt_lower for k in ["16:9", "landscape", "widescreen", "youtube"]):
        plan.aspect_ratio = "16:9"

    if "zoom in" in prompt_lower or "zooming in" in prompt_lower:
        plan.camera_animation = "zoom_in"
    elif "zoom out" in prompt_lower or "zooming out" in prompt_lower:
        plan.camera_animation = "zoom_out"

    if "teal" in prompt_lower or "orange" in prompt_lower:
        plan.color_preset = "teal_orange"
    elif "cinematic" in prompt_lower:
        plan.color_preset = "cinematic"
    elif any(k in prompt_lower for k in ["black and white", "monochrome", "bw"]):
        plan.color_preset = "monochrome"

    if "fade" in prompt_lower:
        plan.fade_transition = True

    # Extract filter window
    filter_start, filter_end = extract_filter_time_window(user_prompt)
    if filter_start is not None and filter_end is not None:
        plan.filter_start = filter_start
        plan.filter_end = filter_end

    if "top left" in prompt_lower:
        plan.logo_position = "top_left"
    elif "bottom right" in prompt_lower:
        plan.logo_position = "bottom_right"
    elif "bottom left" in prompt_lower:
        plan.logo_position = "bottom_left"
    elif "top right" in prompt_lower or "logo" in prompt_lower:
        plan.logo_position = "top_right"

    overlay_match = re.search(
        r"(?:overlay\s+text|text|title)\s+['\"]([^'\"]+)['\"]",
        user_prompt,
        re.IGNORECASE,
    )
    if overlay_match:
        plan.overlay_text = overlay_match.group(1).strip()

    tts_match = re.search(
        r"(?:say|narrate|voiceover)\s+['\"]([^'\"]+)['\"]",
        user_prompt,
        re.IGNORECASE,
    )
    if tts_match:
        plan.ai_voiceover_text = tts_match.group(1).strip()

    return plan


def run_editing_agent(
    user_prompt: str,
    media_paths: List[str],
    ui_options: Optional[dict] = None,
    output_dir: Optional[str] = None,
) -> str:
    """Core Autonomous Orchestrator function."""

    client = None
    try:
        from google.genai import types

        client = get_gemini_client()
    except Exception as e:
        print(f"[Info] Google GenAI SDK initialized in fallback mode: {e}")

    video_path = next(
        (p for p in media_paths if os.path.splitext(p)[1].lower() in [".mp4", ".mov", ".avi", ".mkv"]),
        None,
    )
    audio_path = next(
        (p for p in media_paths if os.path.splitext(p)[1].lower() in [".mp3", ".wav", ".m4a"]),
        None,
    )
    logo_path = next(
        (p for p in media_paths if os.path.splitext(p)[1].lower() in [".png", ".jpg", ".jpeg", ".webp"]),
        None,
    )

    if not video_path:
        raise ValueError("No valid video file provided in media_paths.")

    job_id = uuid.uuid4().hex
    artifact_dir = os.path.abspath(output_dir or "outputs")
    os.makedirs(artifact_dir, exist_ok=True)
    plan = VideoEditPlan()

    if client:
        try:
            response = client.models.generate_content(
                model=DEFAULT_GEMINI_MODEL,
                contents=f"User Prompt: '{user_prompt}'",
                config=types.GenerateContentConfig(
                    system_instruction="Generate strict JSON parameter edit plans matching VideoEditPlan schema.",
                    response_mime_type="application/json",
                    response_schema=VideoEditPlan,
                    temperature=0.1,
                ),
            )
            plan = VideoEditPlan.model_validate(json.loads(response.text))
        except Exception as e:
            print(f"[Warning] Gemini API call skipped ({e}). Fallback to rule parser.")

    plan = apply_rule_based_fallbacks(user_prompt, plan)

    if ui_options:
        if ui_options.get("auto_silence"):
            plan.remove_silence = True
        if ui_options.get("auto_caps"):
            plan.auto_caption = True
        if ui_options.get("auto_highlight"):
            plan.extract_highlights = True
        if ui_options.get("auto_resize") and ui_options["auto_resize"] != "Original":
            if "9:16" in ui_options["auto_resize"]:
                plan.aspect_ratio = "9:16"
            elif "1:1" in ui_options["auto_resize"]:
                plan.aspect_ratio = "1:1"
            elif "16:9" in ui_options["auto_resize"]:
                plan.aspect_ratio = "16:9"

    current_video = video_path
    applied_trim_start = 0.0

    orig_dur, _, _ = get_video_metadata(current_video)

    trim_s = plan.trim_start or 0.0
    trim_e = plan.trim_end or 0.0

    if trim_e > trim_s and trim_e > 0:
        actual_trim_end = min(trim_e, orig_dur)
        if actual_trim_end > trim_s:
            trim_duration = actual_trim_end - trim_s
            trimmed_out = os.path.join(artifact_dir, f"trimmed_{job_id}.mp4")
            trim_audio = check_audio_stream(current_video)
            trim_cmd = [
                "ffmpeg", "-y", "-ss", f"{trim_s}",
                "-i", current_video, "-t", f"{trim_duration}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
            ]
            if trim_audio:
                trim_cmd.extend(["-c:a", "aac"])
            else:
                trim_cmd.append("-an")
            trim_cmd.append(trimmed_out)
            try:
                subprocess.run(trim_cmd, capture_output=True, text=True, check=True, timeout=300)
                if os.path.exists(trimmed_out) and os.path.getsize(trimmed_out) > 0:
                    current_video = trimmed_out
                    applied_trim_start = trim_s
            except subprocess.TimeoutExpired as err:
                print(f"❌ Trimming timed out after 300 s; using untrimmed source.")
            except subprocess.CalledProcessError as err:
                print(f"❌ Trimming failed: {err.stderr}")

    if plan.remove_silence:
        silence_out = os.path.join(artifact_dir, f"nosilence_{job_id}.mp4")
        try:
            res = remove_silence(current_video, silence_out)
            if os.path.exists(res) and os.path.getsize(res) > 0:
                current_video = res
            else:
                print(f"[Warning] Silence removal produced empty output; skipping.")
        except RuntimeError as exc:
            print(f"[Warning] Silence removal failed: {exc}")

    if plan.extract_highlights:
        highlight_out = os.path.join(artifact_dir, f"highlight_{job_id}.mp4")
        try:
            res = extract_highlights(current_video, highlight_out)
            if os.path.exists(res) and os.path.getsize(res) > 0:
                current_video = res
            else:
                print(f"[Warning] Highlight extraction produced empty output; skipping.")
        except RuntimeError as exc:
            print(f"[Warning] Highlight extraction failed: {exc}")

    if plan.auto_caption:
        captioned_out = os.path.join(artifact_dir, f"captioned_{job_id}.mp4")
        try:
            res = auto_caption_video(current_video, captioned_out)
            if os.path.exists(res) and os.path.getsize(res) > 0:
                current_video = res
            else:
                print(f"[Warning] Auto-captioning produced empty output; skipping.")
        except RuntimeError as exc:
            print(f"[Warning] Auto-captioning failed: {exc}")

    duration, in_w, in_h = get_video_metadata(current_video)
    has_video_audio = check_audio_stream(current_video)
    output_path = os.path.join(artifact_dir, f"core_render_{job_id}.mp4")

    voiceover_path = os.path.join(artifact_dir, f"tts_{job_id}.mp3")
    has_generated_tts = False
    voiceover_text = (plan.ai_voiceover_text or "").strip()
    if voiceover_text:
        has_generated_tts = generate_tts_voiceover(voiceover_text, voiceover_path)

    ffmpeg_cmd = ["ffmpeg", "-y", "-i", current_video]
    input_count = 1

    logo_input_idx = -1
    if logo_path and os.path.exists(logo_path):
        ffmpeg_cmd.extend(["-i", logo_path])
        logo_input_idx = input_count
        input_count += 1

    audio_input_idx = -1
    if has_generated_tts:
        ffmpeg_cmd.extend(["-i", voiceover_path])
        audio_input_idx = input_count
        input_count += 1
    elif audio_path and os.path.exists(audio_path):
        ffmpeg_cmd.extend(["-i", audio_path])
        audio_input_idx = input_count
        input_count += 1

    effective_duration = duration
    vf_pipeline = []
    af_pipeline = []

    speed_factor = plan.speed or 1.0
    if speed_factor != 1.0 and speed_factor > 0:
        pts = 1.0 / speed_factor
        vf_pipeline.append(f"setpts={pts:.4f}*PTS")
        effective_duration = max(0.5, effective_duration / speed_factor)
        if has_video_audio:
            af_pipeline.append(build_atempo_filter(speed_factor))

    cam_anim = (plan.camera_animation or "none").lower()
    if cam_anim in ["zoom_in", "zoom_out"]:
        frames = int(max(0.5, effective_duration) * 30)
        safe_w = (in_w // 2) * 2
        safe_h = (in_h // 2) * 2

        if cam_anim == "zoom_in":
            z_expr = f"1+(0.35*(on/{frames}))"
        else:
            z_expr = f"1.35-(0.35*(on/{frames}))"

        vf_pipeline.append(
            f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={safe_w}x{safe_h}:fps=30"
        )

    # Calculate precise frame alignment factoring in pre-trimming and speed adjustments
    enable_expr = ""
    filter_start = plan.filter_start
    filter_end = plan.filter_end

    if applied_trim_start > 0 and filter_start is not None:
        filter_start = max(0.0, filter_start - applied_trim_start)
        if filter_end is not None:
            filter_end = max(0.0, filter_end - applied_trim_start)
            
    if speed_factor != 1.0 and speed_factor > 0 and filter_start is not None:
        filter_start = filter_start / speed_factor
        if filter_end is not None:
            filter_end = filter_end / speed_factor

    if (
        filter_start is not None
        and filter_end is not None
        and math.isfinite(filter_start)
        and math.isfinite(filter_end)
        and filter_start >= 0
        and filter_end > filter_start
    ):
        # Bulletproof FFmpeg syntax. We omit single quotes and use raw backslash-escaped commas 
        # to ensure it securely passes through Python's list2cmdline directly into the avfilter graph parser.
        enable_expr = f":enable=between(t\\,{filter_start:g}\\,{filter_end:g})"

    color = (plan.color_preset or "none").lower()
    if color == "teal_orange":
        vf_pipeline.append(f"eq=gamma_r=1.3:gamma_g=1.0:gamma_b=0.7:contrast=1.2:saturation=1.4{enable_expr}")
    elif color == "cinematic":
        vf_pipeline.append(f"eq=contrast=1.12:saturation=1.2{enable_expr}")
    elif color == "monochrome":
        vf_pipeline.append(f"hue=s=0{enable_expr}")

    overlay_text = (plan.overlay_text or "").strip()
    if overlay_text:
        clean_text = re.sub(r"[^a-zA-Z0-9 ]", "", overlay_text)
        if clean_text:
            pos = plan.text_position
            y_val = (
                "h-250" if pos == "bottom_third" else ("(h-text_h)/2" if pos == "center" else "120")
            )
            font_path = get_system_font_path()
            font_opt = f"fontfile='{font_path}':" if font_path else ""
            vf_pipeline.append(
                f"drawtext={font_opt}text='{clean_text}':fontsize=48:fontcolor=white:"
                f"box=1:boxcolor=black@0.6:boxborderw=12:x=(w-text_w)/2:y={y_val}{enable_expr}"
            )

    if plan.fade_transition:
        fade_out_start = max(0.0, effective_duration - 1.0)
        vf_pipeline.append(f"fade=t=in:st=0:d=1,fade=t=out:st={fade_out_start:.2f}:d=1")
        if has_video_audio and not plan.mute_original_audio:
            af_pipeline.append(f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start:.2f}:d=1")

    vf_pipeline.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    vf_chain_str = ",".join(vf_pipeline) if vf_pipeline else "null"

    if logo_input_idx > 0:
        pos_map = {
            "top_right": "main_w-overlay_w-30:30",
            "top_left": "30:30",
            "bottom_right": "main_w-overlay_w-30:main_h-overlay_h-30",
            "bottom_left": "30:main_h-overlay_h-30",
        }
        logo_pos = pos_map.get(plan.logo_position, pos_map["top_right"])
        filter_complex = f"[0:v]{vf_chain_str}[v_main]; [{logo_input_idx}:v]scale=iw*0.18:-1[logo]; [v_main][logo]overlay={logo_pos}[v_out]"
        ffmpeg_cmd.extend(["-filter_complex", filter_complex, "-map", "[v_out]"])
    else:
        ffmpeg_cmd.extend(["-vf", vf_chain_str, "-map", "0:v:0"])

    if audio_input_idx > 0:
        ffmpeg_cmd.extend(["-map", f"{audio_input_idx}:a:0"])
    elif has_video_audio and not plan.mute_original_audio:
        ffmpeg_cmd.extend(["-map", "0:a:0"])
        if af_pipeline:
            ffmpeg_cmd.extend(["-af", ",".join(af_pipeline)])
    else:
        ffmpeg_cmd.append("-an")

    ffmpeg_cmd.extend(["-t", f"{effective_duration:.2f}"])
    ffmpeg_cmd.extend([
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ])

    try:
        subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True, timeout=300)
    except subprocess.TimeoutExpired as err:
        raise RuntimeError("FFmpeg execution exceeded the 300 second timeout") from err
    except subprocess.CalledProcessError as err:
        print("❌ FFmpeg execution failed!")
        print("Command:", " ".join(ffmpeg_cmd))
        print("FFmpeg Error Log:\n", err.stderr)
        raise err

    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"FFmpeg produced no usable output: {output_path}")

    rendered_video = output_path

    if plan.aspect_ratio in ["9:16", "1:1", "16:9"]:
        resized_out = os.path.join(artifact_dir, f"resized_{job_id}.mp4")
        res = resize_video_aspect(rendered_video, resized_out, target_ratio=plan.aspect_ratio)
        if os.path.exists(res) and os.path.getsize(res) > 0:
            rendered_video = res

    return rendered_video