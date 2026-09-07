"""Print non-secret capability diagnostics for local GENFORGE startup."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys


def main() -> int:
    # Import the single source of truth for the Gemini model name.
    # This ensures startup_check always reports whatever ai_service will use,
    # eliminating the risk of the two getting out of sync.
    try:
        from services.ai_service import DEFAULT_GEMINI_MODEL
    except Exception:
        DEFAULT_GEMINI_MODEL = os.getenv("GENFORGE_GEMINI_MODEL", "gemini-2.5-flash")

    checks = {
        "python": sys.version.split()[0],
        "ffmpeg": shutil.which("ffmpeg") or "unavailable",
        "ffprobe": shutil.which("ffprobe") or "unavailable",
        "google-genai": "installed" if importlib.util.find_spec("google.genai") else "unavailable",
        "Gemini API key": "configured" if os.getenv("GEMINI_API_KEY") else "missing",
        "Whisper": "installed" if importlib.util.find_spec("whisper") else "unavailable",
        "rembg": "installed" if importlib.util.find_spec("rembg") else "unavailable",
        "Edge-TTS": "installed" if importlib.util.find_spec("edge_tts") else "unavailable",
        "Gemini model": DEFAULT_GEMINI_MODEL,
    }
    for name, value in checks.items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
