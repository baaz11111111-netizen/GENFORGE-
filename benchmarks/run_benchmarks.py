"""GENFORGE performance benchmark harness (deterministic, offline).

Generates synthetic media once (cached under benchmarks/media) and times the
major pipelines. Output is a JSON table: operation, elapsed seconds, notes.
Run: python benchmarks/run_benchmarks.py [--json path]
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MEDIA_DIR = Path(__file__).resolve().parent / "media"


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
                   check=True, capture_output=True)


def _make_video(name: str, size: str, fps: int, duration: float, audio: bool) -> str:
    path = MEDIA_DIR / name
    if path.is_file():
        return str(path)
    inputs = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}"]
    maps = ["-map", "0:v"]
    audio_args: list[str] = []
    if audio:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100"]
        maps += ["-map", "1:a"]
        audio_args = ["-c:a", "aac", "-b:a", "128k"]
    _run_ffmpeg(inputs + maps + ["-t", str(duration), "-c:v", "libx264",
                                 "-preset", "veryfast", "-pix_fmt", "yuv420p"]
                + audio_args + [str(path)])
    return str(path)


def _make_image(name: str, size: str) -> str:
    path = MEDIA_DIR / name
    if path.is_file():
        return str(path)
    _run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=1",
                 "-frames:v", "1", str(path)])
    return str(path)


def make_fixture_set() -> dict[str, str]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "clip_720p_24": _make_video("clip_720p_24.mp4", "1280x720", 24, 3.0, audio=True),
        "clip_1080p_30": _make_video("clip_1080p_30.mp4", "1920x1080", 30, 3.0, audio=True),
        "clip_portrait_30": _make_video("clip_portrait_30.mp4", "720x1280", 30, 3.0, audio=False),
        "clip_60fps": _make_video("clip_60fps.mp4", "1280x720", 60, 2.0, audio=True),
        "clip_silent": _make_video("clip_silent.mp4", "1280x720", 24, 3.0, audio=False),
        "image_large": _make_image("image_large.png", "2560x1440"),
        "image_small": _make_image("image_small.png", "640x360"),
    }


class Timer:
    """Collect named timings; usable as a context manager."""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def measure(self, operation: str, fn, notes: str = "") -> float:
        start = time.perf_counter()
        fn()
        elapsed = round(time.perf_counter() - start, 4)
        self.results.append({"operation": operation, "seconds": elapsed, "notes": notes})
        return elapsed


def run_all() -> list[dict]:
    fixtures = make_fixture_set()
    timer = Timer()
    work = MEDIA_DIR / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # --- A. Startup: import of heavy app modules (fresh interpreter cost) ---
    def startup():
        for module in ("advanced_editing", "production_features", "orchestrator",
                       "services.media_probe", "services.platform_profiles"):
            if module in sys.modules:
                del sys.modules[module]
        for module in ("advanced_editing", "production_features", "orchestrator",
                       "services.media_probe", "services.platform_profiles"):
            importlib.import_module(module)
    timer.measure("startup_core_imports", startup, "cold import of core modules")

    # --- C. Media probing (10 probes of the same file) ---
    from services.media_probe import clear_probe_cache, probe_media
    clear_probe_cache()  # deterministic: single = cold miss, x10 = 1 miss + 9 hits
    timer.measure("media_probe_single", lambda: probe_media(fixtures["clip_1080p_30"]))
    timer.measure("media_probe_x10_same_file",
                  lambda: [probe_media(fixtures["clip_1080p_30"]) for _ in range(10)],
                  "repeated probe of identical file")

    # --- FFmpeg capability check x10 ---
    from advanced_editing import check_ffmpeg
    timer.measure("capability_check_x10", lambda: [check_ffmpeg() for _ in range(10)])

    # --- D. Thumbnail generation (cold path, then deterministic asset-cache hit) ---
    from advanced_ai import generate_auto_thumbnail
    from services.asset_cache import clear_asset_cache
    clear_asset_cache()  # measure the real generation path, not a stale hit
    def thumbnails():
        try:
            generate_auto_thumbnail(fixtures["clip_720p_24"], str(work / "thumb.png"))
        except Exception as exc:
            timer.results.append({"operation": "thumbnail_generation", "seconds": -1,
                                  "notes": f"unavailable: {exc}"})
    timer.measure("thumbnail_generation", thumbnails, "cold generation path")
    timer.measure("thumbnail_generation_cached",
                  lambda: generate_auto_thumbnail(fixtures["clip_720p_24"], str(work / "thumb2.png")),
                  "identical request served from asset cache")

    # --- E. Highlight detection ---
    from services.highlights import detect_highlights
    timer.measure("highlight_detection", lambda: detect_highlights(fixtures["clip_1080p_30"], count=3))

    # --- G/H/I. Trim + transition + final render ---
    from production_features import trim_clip_for_timeline, assemble_timeline
    def trim():
        trim_clip_for_timeline(fixtures["clip_720p_24"], str(work / "trim.mp4"), 0.5, 2.0)
    timer.measure("single_clip_trim_render", trim)

    def transition():
        from advanced_video import apply_clip_transition
        clip_a = str(work / "trim.mp4")
        clip_b = trim_clip_for_timeline(fixtures["clip_portrait_30"], str(work / "trim_b.mp4"), 0.0, 1.5)
        apply_clip_transition(clip_a, clip_b, str(work / "transition.mp4"), "fade", 0.4)
    timer.measure("transition_render_mixed", transition, "720p24 -> portrait30 fade")

    def transition_cached():
        from advanced_video import apply_clip_transition
        apply_clip_transition(str(work / "trim.mp4"), str(work / "trim_b.mp4"),
                              str(work / "transition_cached.mp4"), "fade", 0.4)
    timer.measure("transition_render_cached", transition_cached,
                  "identical clips re-rendered via normalization cache")

    def final_render():
        assemble_timeline([str(work / "trim.mp4"), str(work / "trim_b.mp4")],
                          str(work / "assembled.mp4"))
    timer.measure("multi_clip_render", final_render)

    # --- J. Audio mastering ---
    def audio_master():
        try:
            from production_features import normalize_audio_lufs
            normalize_audio_lufs(fixtures["clip_720p_24"], str(work / "lufs.mp4"))
        except Exception as exc:
            timer.results.append({"operation": "audio_mastering", "seconds": -1,
                                  "notes": f"unavailable: {exc}"})
    timer.measure("audio_mastering_lufs", audio_master)

    # --- L. Caption generation ---
    def captions():
        from caption_presets import write_styled_ass
        segments = [{"start": 0.0, "end": 1.0, "text": "Benchmark line one"},
                    {"start": 1.0, "end": 2.0, "text": "Benchmark line two"}]
        write_styled_ass(segments, str(work / "caps.ass"), preset="Bold")
    timer.measure("caption_generation", captions)

    # --- M. Image processing ---
    def image_ops():
        from advanced_image import apply_cinematic_color_grading
        apply_cinematic_color_grading(fixtures["image_large"], str(work / "graded.png"))
    timer.measure("image_color_grading_1440p", image_ops)

    # --- O. Platform export ---
    def platform_export():
        from services.platform_profiles import export_for_platform
        export_for_platform(str(work / "trim.mp4"), str(work / "tiktok.mp4"), "TikTok")
    timer.measure("platform_export_tiktok", platform_export)

    # --- Q. Project save/load ---
    def project_io():
        from services.project_model import ProjectState
        from services.project_store import ProjectStore
        project = ProjectState()
        project.add_source(fixtures["clip_720p_24"])
        store = ProjectStore()
        store.save(project)
        store.load(project.project_id)
    timer.measure("project_save_load", project_io)

    # --- Preview vs final encode profile comparison (same source) ---
    sizes: dict[str, int] = {}

    def encode_profile(preset: str, name: str):
        dest = work / f"enc_{name}.mp4"
        _run_ffmpeg(["-i", fixtures["clip_1080p_30"], "-c:v", "libx264", "-preset", preset,
                     "-pix_fmt", "yuv420p", "-an", str(dest)])
        sizes[name] = dest.stat().st_size
    timer.measure("encode_1080p_ultrafast", lambda: encode_profile("ultrafast", "preview"), "preview profile")
    timer.measure("encode_1080p_medium", lambda: encode_profile("medium", "final"), "final profile")
    timer.results.append({"operation": "encode_size_delta", "seconds": 0,
                          "notes": f"preview_bytes={sizes.get('preview')} final_bytes={sizes.get('final')}"})

    return timer.results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="benchmarks/results.json")
    args = parser.parse_args()
    results = run_all()
    out_path = ROOT / args.json if not os.path.isabs(args.json) else Path(args.json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    print(f"{'operation':<34} {'seconds':>9}  notes")
    for item in results:
        print(f"{item['operation']:<34} {item['seconds']:>9}  {item.get('notes', '')}")
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
