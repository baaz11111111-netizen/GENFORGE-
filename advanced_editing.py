import os
import re
import shutil
import subprocess
import uuid
from functools import lru_cache
from typing import Optional


def check_ffmpeg() -> bool:
    """Checks if FFmpeg binary is accessible in system PATH."""
    return shutil.which("ffmpeg") is not None


def _require_input(path: str) -> str:
    if not isinstance(path, str) or not path.strip() or not os.path.isfile(path):
        raise FileNotFoundError(f"Media input not found: {path}")
    return os.path.abspath(path)


def _prepare_output(input_path: str, output_path: str) -> str:
    destination = os.path.abspath(output_path)
    if os.path.normcase(os.path.abspath(input_path)) == os.path.normcase(destination):
        raise ValueError("output_path must differ from input_path")
    os.makedirs(os.path.dirname(destination) or os.curdir, exist_ok=True)
    return destination


def _verify_output(path: str) -> str:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise RuntimeError(f"FFmpeg produced no usable output: {path}")
    return path


def check_audio_stream(video_path: str) -> bool:
    """Safely checks whether a video file contains an audio stream."""
    if not check_ffmpeg() or not os.path.exists(video_path):
        return False
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        return "audio" in res.stdout.strip().lower()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=2)
def _load_whisper_model(model_name: str):
    """Load an optional Whisper model once per process."""
    import whisper  # type: ignore

    return whisper.load_model(model_name)


def trim_clip(input_path: str, output_path: str, start_time: float, end_time: float) -> str:
    """Trims clip accurately between start_time and end_time (in seconds)."""
    input_path = _require_input(input_path)
    output_path = _prepare_output(input_path, output_path)
    if start_time < 0 or end_time <= start_time:
        raise ValueError("end_time must be greater than start_time")
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg binary not found.")

    has_audio = check_audio_stream(input_path)
    cmd = ["ffmpeg", "-y", "-ss", str(start_time), "-to", str(end_time), "-i", input_path, "-c:v", "libx264"]
    
    if has_audio:
        cmd.extend(["-c:a", "aac"])
    else:
        cmd.append("-an")

    cmd.append(output_path)
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg trim exceeded 300 second timeout") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"FFmpeg trim failed: {exc.stderr[-3000:]}") from exc
    return _verify_output(output_path)


def remove_silence(input_path: str, output_path: str, noise_threshold_db: int = -30, min_silence_duration: float = 0.5) -> str:
    """Detects and cuts out quiet pauses from media files."""
    input_path = _require_input(input_path)
    output_path = _prepare_output(input_path, output_path)
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg binary not found.")
    
    has_audio = check_audio_stream(input_path)
    if not has_audio:
        shutil.copy(input_path, output_path)
        return output_path

    try:
        detect_cmd = [
            "ffmpeg", "-i", input_path,
            "-af", f"silencedetect=noise={noise_threshold_db}dB:d={min_silence_duration}",
            "-f", "null", "-"
        ]
        res = subprocess.run(detect_cmd, capture_output=True, text=True, check=False, timeout=300)
        
        starts = [float(x) for x in re.findall(r"silence_start: (\d+\.?\d*)", res.stderr)]
        ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", res.stderr)]
        
        if not starts or not ends:
            shutil.copy(input_path, output_path)
            return output_path

        filter_parts = []
        last_end = 0.0
        
        for s, e in zip(starts, ends):
            if s > last_end:
                filter_parts.append(f"between(t,{last_end},{s})")
            last_end = e
            
        filter_parts.append(f"gte(t,{last_end})")
        select_expr = "+".join(filter_parts)

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"select='{select_expr}',setpts=N/FRAME_RATE/TB",
            "-af", f"aselect='{select_expr}',asetpts=N/SR/TB",
            "-c:v", "libx264", "-c:a", "aac", output_path
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        return output_path
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Silence removal exceeded 300 second timeout") from exc
    except Exception as e:
        raise RuntimeError(f"Silence removal failed: {e}") from e


def extract_highlights(input_path: str, output_path: str, max_duration: float = 15.0) -> str:
    """Extracts a highlights clip by finding the loudest audio segment or falling back to the opening."""
    input_path = _require_input(input_path)
    output_path = _prepare_output(input_path, output_path)
    if max_duration <= 0:
        raise ValueError("max_duration must be positive")
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg binary not found.")

    has_audio = check_audio_stream(input_path)
    seek_offset = 0.0

    if has_audio:
        # Analyze audio loudness in overlapping windows to find the peak segment
        try:
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", input_path,
            ]
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            total_dur = float(probe_res.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
            total_dur = 0.0

        if total_dur > max_duration:
            window_size = max_duration
            step = max(1.0, window_size / 2)
            best_loudness = -999.0
            best_start = 0.0
            t = 0.0
            while t + window_size <= total_dur + 0.5:
                try:
                    vol_cmd = [
                        "ffmpeg", "-ss", f"{t:.3f}", "-t", f"{window_size:.3f}",
                        "-i", input_path, "-af", "volumedetect", "-f", "null", "-",
                    ]
                    vol_res = subprocess.run(vol_cmd, capture_output=True, text=True, timeout=60)
                    import re
                    mean_matches = re.findall(r"mean_volume:\s*([-\d.]+)\s*dB", vol_res.stderr)
                    if mean_matches:
                        loudness = float(mean_matches[-1])
                        if loudness > best_loudness:
                            best_loudness = loudness
                            best_start = t
                except (subprocess.TimeoutExpired, ValueError):
                    pass
                t += step
            seek_offset = best_start

    cmd = ["ffmpeg", "-y"]
    if seek_offset > 0:
        cmd.extend(["-ss", f"{seek_offset:.3f}"])
    cmd.extend(["-i", input_path, "-t", str(max_duration), "-c:v", "libx264"])

    if has_audio:
        cmd.extend(["-c:a", "aac"])
    else:
        cmd.append("-an")

    cmd.append(output_path)
    subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
    return _verify_output(output_path)


def auto_caption_video(input_path: str, output_path: str) -> str:
    """Generates burned-in subtitles using OpenAI Whisper."""
    input_path = _require_input(input_path)
    output_path = _prepare_output(input_path, output_path)
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg binary not found.")
        
    srt_path = None
    try:
        model = _load_whisper_model("base")
        result = model.transcribe(input_path)
        
        srt_path = os.path.join(os.path.dirname(output_path), f"{os.path.basename(input_path)}_{uuid.uuid4().hex}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(result.get("segments", []), start=1):
                s_h, s_m, s_s = int(segment["start"] // 3600), int((segment["start"] % 3600) // 60), segment["start"] % 60
                e_h, e_m, e_s = int(segment["end"] // 3600), int((segment["end"] % 3600) // 60), segment["end"] % 60
                f.write(f"{i}\n")
                f.write(f"{s_h:02d}:{s_m:02d}:{s_s:06.3f}".replace(".", ",") + " --> " + f"{e_h:02d}:{e_m:02d}:{e_s:06.3f}".replace(".", ",") + "\n")
                f.write(f"{segment['text'].strip()}\n\n")

        escaped_srt = srt_path.replace("\\", "/").replace(":", "\\:")
        sub_filter = f"subtitles='{escaped_srt}':force_style='FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3'"
        
        has_audio = check_audio_stream(input_path)
        cmd = ["ffmpeg", "-y", "-i", input_path, "-vf", sub_filter]
        if has_audio:
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.append("-an")
        cmd.append(output_path)

        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        return output_path
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Captioning exceeded 300 second timeout") from exc
    except Exception as e:
        raise RuntimeError(f"Captioning failed: {e}") from e
    finally:
        try:
            if srt_path and os.path.exists(srt_path):
                os.remove(srt_path)
        except OSError:
            pass


def resize_video_aspect(input_path: str, output_path: str, target_ratio: str = "9:16",
                        profile: str | None = None) -> str:
    """Resizes video with padded blurred background or aspect ratio fitting.

    ``profile`` optionally selects an encode preset (services.encode_profiles);
    when omitted, FFmpeg's default x264 settings are used exactly as before.
    """
    input_path = _require_input(input_path)
    output_path = _prepare_output(input_path, output_path)
    if target_ratio not in {"9:16", "1:1", "16:9"}:
        raise ValueError(f"Unsupported target_ratio: {target_ratio}")
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg binary not found.")
        
    aspect_filters = {
        "9:16": "split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20[bg];[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2",
        "1:1": "split[a][b];[a]scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,boxblur=20[bg];[b]scale=1080:1080:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2",
        "16:9": "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    }
    
    vf = aspect_filters.get(target_ratio, aspect_filters["9:16"])
    has_audio = check_audio_stream(input_path)
    
    if profile is None:
        video_flags = ["-c:v", "libx264"]
    else:
        from services.encode_profiles import encode_flags
        video_flags = encode_flags(profile)
    cmd = ["ffmpeg", "-y", "-i", input_path, "-vf", vf, *video_flags]
    if has_audio:
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.append("-an")
    cmd.append(output_path)

    subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
    return _verify_output(output_path)