"""List available Gemini models. Requires GEMINI_API_KEY to be configured."""

import os
import sys


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "ERROR: GEMINI_API_KEY is not set in the environment.\n"
            "Export it before running this script:\n"
            "  set GEMINI_API_KEY=your-key-here   (Windows)\n"
            "  export GEMINI_API_KEY=your-key-here (bash/zsh)",
            file=sys.stderr,
        )
        return 1
    try:
        from google import genai
    except ImportError:
        print("ERROR: google-genai package is not installed. Run: pip install google-genai", file=sys.stderr)
        return 1
    try:
        client = genai.Client(api_key=api_key)
        print("Available models:")
        for model in client.models.list():
            print(f"  {model.name}")
    except Exception as exc:
        print(f"ERROR: Could not list models — {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
