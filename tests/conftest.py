"""Shared pytest fixtures: self-contained synthetic media (§test reproducibility).

Publishing tests need real video files (ffprobe measures dimensions, codecs,
aspect ratios). Instead of depending on manually prepared files under temp/
(which breaks clean checkouts), the suite generates deterministic synthetic
media with FFmpeg into a temporary directory ONCE per session and removes it
at session teardown. No developer-specific paths, no order dependence.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

import pytest


def _encode(root: str, name: str, size: str, with_audio: bool) -> str:
    """Deterministic h264/yuv420p test video (testsrc2 + optional sine tone)."""
    path = os.path.join(root, name)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration=2",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    cmd += ["-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if with_audio else ["-an"]
    cmd.append(path)
    try:
        subprocess.run(cmd, check=True, timeout=180)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.fail(f"Cannot generate synthetic test media ({name}): {exc}")
    return path


@pytest.fixture(scope="session")
def media() -> SimpleNamespace:
    """Synthetic media generated in a temp dir; cleaned up after the session.

    Attributes:
        landscape  1920x1080 16:9 h264, with audio
        portrait   1080x1920 9:16 h264, with audio
        audio      640x360 h264, with audio track
        silent     640x360 h264, NO audio stream
        lowres     640x360 h264 (low-resolution advisory case)
        e2e_input  640x360 h264, with audio (pipeline e2e input)
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to generate synthetic test media.")
    root = tempfile.mkdtemp(prefix="genforge_synthetic_media_")
    try:
        yield SimpleNamespace(
            landscape=_encode(root, "landscape.mp4", "1920x1080", with_audio=True),
            portrait=_encode(root, "portrait.mp4", "1080x1920", with_audio=True),
            audio=_encode(root, "audio.mp4", "640x360", with_audio=True),
            silent=_encode(root, "silent.mp4", "640x360", with_audio=False),
            lowres=_encode(root, "lowres.mp4", "640x360", with_audio=False),
            e2e_input=_encode(root, "e2e_input.mp4", "640x360", with_audio=True),
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
