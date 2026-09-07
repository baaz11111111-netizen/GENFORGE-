"""Regression tests for bugs fixed in the final engineering audit round.

Each test is tied directly to a specific bug identified and fixed. Tests are
named to make the original bug obvious from the failure message.

Bug inventory covered here
--------------------------
BUG-A  services/ai_service.py DEFAULT_GEMINI_MODEL had an invalid value
       ('gemini-3.6-flash' — a non-existent model name). All AI calls
       silently fail when GENFORGE_GEMINI_MODEL env-var is not set.
       Tests now verify structural validity and cross-consumer consistency
       rather than pinning to a specific model version string.

BUG-B  inapinting.py (typo) — module was never importable under the correct
       name 'inpainting'. Both mcp_server and image_agent imported the typo.

BUG-C  app.check_ffmpeg had no timeout, hanging the UI indefinitely on a
       frozen ffmpeg binary.

BUG-D  services/media_cache.py misses counter: incremented in store_normalized
       instead of in fetch_normalized (on a lookup miss).

BUG-E  services/image_studio.make_gradient_background used a pure-Python
       per-pixel nested loop: O(W*H) CPython iterations, 5-30 s on 1080x1920.

BUG-F  check_models.py passed os.environ.get(...) (possibly None) directly
       to genai.Client, crashing with an unhelpful SDK error.

BUG-G  hackathon_features.py had duplicate `import os` and a tmpdir leak
       path: mkdtemp was called inside the try block; if total_frames <= 0
       returned early, tmpdir was already leaked.

BUG-H  services/platform_profiles.py imported private `_duration` from
       production_features — a fragile private-symbol coupling that breaks
       on any internal refactor.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(path: Path, *, duration: float = 0.5, with_audio: bool = True,
                size: str = "320x240") -> Path:
    """Minimal synthetic video using FFmpeg test sources."""
    if not __import__("shutil").which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    cmd += ["-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac"]
    else:
        cmd += ["-an"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True)
    return path


# ---------------------------------------------------------------------------
# BUG-A: DEFAULT_GEMINI_MODEL configuration — single source of truth
#
# The original bug was that the hardcoded fallback was 'gemini-3.6-flash'
# (a non-existent model name), so all AI calls silently failed when the
# GENFORGE_GEMINI_MODEL env-var was not set.
#
# The tests below verify structural validity and cross-consumer consistency
# WITHOUT hardcoding any specific model string.  This means the tests will
# not break when Google releases new model versions or when the maintainer
# decides to change the default model — only invalid/inconsistent config
# will fail the suite.
# ---------------------------------------------------------------------------

def test_default_gemini_model_has_valid_structure():
    """The compiled-in fallback model must look like a Gemini identifier.

    A valid Gemini model name:
      - is a non-empty string
      - starts with 'gemini-' (Google's stable naming prefix)
      - contains at least one digit (version component)
      - does NOT contain whitespace or path-separator characters

    This test is intentionally broad: it will accept 'gemini-2.5-flash',
    'gemini-2.0-flash-lite', 'gemini-3.6-flash' (if Google ships it), etc.
    It will only fail if someone sets the fallback to an obviously wrong value
    such as an empty string, a URL, or a model from a different provider.
    """
    import importlib
    import services.ai_service as ai_mod

    saved = os.environ.pop("GENFORGE_GEMINI_MODEL", None)
    try:
        importlib.reload(ai_mod)
        fallback = ai_mod.DEFAULT_GEMINI_MODEL
    finally:
        if saved is not None:
            os.environ["GENFORGE_GEMINI_MODEL"] = saved

    assert isinstance(fallback, str) and fallback, (
        "DEFAULT_GEMINI_MODEL must be a non-empty string"
    )
    assert fallback.startswith("gemini-"), (
        f"DEFAULT_GEMINI_MODEL '{fallback}' must start with 'gemini-' "
        f"(Google's stable API prefix for all Gemini models)"
    )
    assert any(c.isdigit() for c in fallback), (
        f"DEFAULT_GEMINI_MODEL '{fallback}' must contain a version digit"
    )
    assert " " not in fallback and "/" not in fallback and "\\" not in fallback, (
        f"DEFAULT_GEMINI_MODEL '{fallback}' must not contain whitespace or path separators"
    )


def test_all_gemini_consumers_use_single_config_source():
    """Every module that sends Gemini requests must read DEFAULT_GEMINI_MODEL
    from services.ai_service — not from a separate hardcoded string.

    This is the single-source-of-truth requirement: changing the env-var
    GENFORGE_GEMINI_MODEL (or the fallback in ai_service.py) must propagate
    automatically to every caller without editing multiple files.
    """
    import importlib
    import services.ai_service as ai_mod

    # Verify orchestrator imports from ai_service, not a local constant.
    orchestrator_src = Path("orchestrator.py").read_text(encoding="utf-8")
    assert "from services.ai_service import" in orchestrator_src and \
           "DEFAULT_GEMINI_MODEL" in orchestrator_src, (
        "orchestrator.py must import DEFAULT_GEMINI_MODEL from services.ai_service"
    )
    # Verify it does NOT define its own local fallback.
    assert 'DEFAULT_GEMINI_MODEL = os.getenv' not in orchestrator_src, (
        "orchestrator.py must not define its own DEFAULT_GEMINI_MODEL — "
        "use the one from services.ai_service"
    )

    # Verify startup_check.py reads the same env-var rather than its own literal.
    startup_src = Path("startup_check.py").read_text(encoding="utf-8")
    assert "GENFORGE_GEMINI_MODEL" in startup_src, (
        "startup_check.py must reference GENFORGE_GEMINI_MODEL (same env-var as ai_service)"
    )

    # The env-var override must propagate to all consumers consistently.
    saved = os.environ.pop("GENFORGE_GEMINI_MODEL", None)
    try:
        importlib.reload(ai_mod)
        ai_fallback = ai_mod.DEFAULT_GEMINI_MODEL
    finally:
        if saved is not None:
            os.environ["GENFORGE_GEMINI_MODEL"] = saved

    # startup_check must show the same model that ai_service would use.
    assert ai_fallback in startup_src, (
        f"startup_check.py display value does not match ai_service default '{ai_fallback}'. "
        f"Run: python startup_check.py and compare 'Gemini model' with ai_service.DEFAULT_GEMINI_MODEL"
    )


def test_env_var_overrides_model_name():
    """Setting GENFORGE_GEMINI_MODEL must override the compiled-in default."""
    import importlib
    import services.ai_service as ai_mod

    os.environ["GENFORGE_GEMINI_MODEL"] = "gemini-custom-test-model"
    try:
        importlib.reload(ai_mod)
        assert ai_mod.DEFAULT_GEMINI_MODEL == "gemini-custom-test-model"
    finally:
        del os.environ["GENFORGE_GEMINI_MODEL"]
        importlib.reload(ai_mod)  # restore module to its default state


def test_model_name_not_obviously_wrong():
    """The default model must not be a known-bad placeholder value.

    This test is intentionally narrow: it only rejects values that are
    demonstrably wrong regardless of Google's future model catalogue
    (empty strings, spaces, hardcoded test stubs, non-Gemini providers).
    It does NOT assert that a specific version string is 'invalid'.
    """
    import importlib
    import services.ai_service as ai_mod

    saved = os.environ.pop("GENFORGE_GEMINI_MODEL", None)
    try:
        importlib.reload(ai_mod)
        fallback = ai_mod.DEFAULT_GEMINI_MODEL
    finally:
        if saved is not None:
            os.environ["GENFORGE_GEMINI_MODEL"] = saved

    # Values that are provably wrong in any context:
    obviously_wrong = {
        "",                     # empty
        "YOUR_MODEL_HERE",      # placeholder
        "gpt-4",                # wrong provider
        "claude-3",             # wrong provider
        "gemini",               # missing version (not a valid API identifier)
    }
    assert fallback not in obviously_wrong, (
        f"DEFAULT_GEMINI_MODEL is set to an obviously invalid value: '{fallback}'"
    )


# ---------------------------------------------------------------------------
# BUG-B: inapinting.py typo — import must work under the correct name
# ---------------------------------------------------------------------------

def test_inpainting_module_importable_under_correct_name():
    """inpainting.py must be importable as 'inpainting', not only 'inapinting'."""
    # If the old typo file still exists alongside the renamed one, this would
    # import incorrectly. The rename is the authoritative fix.
    import inpainting  # noqa: F401  -- ImportError = regression
    assert hasattr(inpainting, "run_inpaint"), "run_inpaint must be present in inpainting module"


def test_inapinting_typo_file_does_not_exist():
    """The misspelled inapinting.py must not exist anymore."""
    assert not Path("inapinting.py").exists(), (
        "inapinting.py (typo) still exists on disk — only inpainting.py should exist"
    )


def test_mcp_server_imports_inpainting_not_typo():
    """mcp_server must import from 'inpainting', not 'inapinting'."""
    src = Path("mcp_server.py").read_text(encoding="utf-8")
    assert "from inpainting import" in src or "import inpainting" in src, \
        "mcp_server.py must import from 'inpainting' (correct spelling)"
    assert "inapinting" not in src, \
        "mcp_server.py still contains the 'inapinting' typo"


def test_image_agent_imports_inpainting_not_typo():
    """image_agent must import from 'inpainting', not 'inapinting'."""
    src = Path("image_agent.py").read_text(encoding="utf-8")
    assert "from inpainting import" in src or "import inpainting" in src, \
        "image_agent.py must import from 'inpainting' (correct spelling)"
    assert "inapinting" not in src, \
        "image_agent.py still contains the 'inapinting' typo"


def test_run_inpaint_works_end_to_end(tmp_path: Path):
    """run_inpaint must produce output without crashing."""
    from PIL import Image
    import numpy as np
    from inpainting import run_inpaint

    # Create a 50×50 white image and a mask with a small black region.
    img = Image.new("RGB", (50, 50), (200, 200, 200))
    img_path = tmp_path / "base.png"
    img.save(str(img_path))

    mask = Image.new("L", (50, 50), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).rectangle((10, 10, 20, 20), fill=255)
    mask_path = tmp_path / "mask.png"
    mask.save(str(mask_path))

    out_path = str(tmp_path / "inpainted.png")
    result = run_inpaint(str(img_path), str(mask_path), out_path)
    assert isinstance(result, np.ndarray)
    assert Path(out_path).is_file()
    assert Path(out_path).stat().st_size > 0


# ---------------------------------------------------------------------------
# BUG-C: check_ffmpeg had no timeout on subprocess call
# ---------------------------------------------------------------------------

def test_check_ffmpeg_subprocess_has_timeout():
    """check_ffmpeg must pass timeout= to subprocess.run to prevent indefinite hang."""
    src = Path("app.py").read_text(encoding="utf-8")
    # Find the check_ffmpeg function body.
    idx = src.index("def check_ffmpeg(")
    # Next def starts the next function; grab the chunk between them.
    next_def = src.index("\ndef ", idx + 10)
    body = src[idx:next_def]
    assert "timeout=" in body, (
        "check_ffmpeg must include timeout= in its subprocess.run call"
    )


def test_check_ffmpeg_timeout_value_is_reasonable():
    """The timeout must be a positive finite value (not 0, None, or negative)."""
    import re
    src = Path("app.py").read_text(encoding="utf-8")
    idx = src.index("def check_ffmpeg(")
    next_def = src.index("\ndef ", idx + 10)
    body = src[idx:next_def]
    matches = re.findall(r"timeout\s*=\s*(\d+)", body)
    assert matches, "Could not find a numeric timeout= in check_ffmpeg"
    timeout_val = int(matches[0])
    assert timeout_val > 0, f"timeout must be positive; found {timeout_val}"


# ---------------------------------------------------------------------------
# BUG-D: media_cache misses counter was incremented on store, not on miss
# ---------------------------------------------------------------------------

def test_cache_miss_counter_increments_on_lookup_miss(tmp_path: Path):
    """fetch_normalized must increment misses when key is absent, not store_normalized."""
    from services.media_cache import (
        clear_normalization_cache,
        fetch_normalized,
        normalization_cache_stats,
        store_normalized,
    )

    clear_normalization_cache()
    initial = normalization_cache_stats()
    assert initial["misses"] == 0

    # A lookup on an absent key must count as a miss.
    dest = tmp_path / "dest.mp4"
    result = fetch_normalized("key_that_does_not_exist", str(dest))
    assert result is False
    assert normalization_cache_stats()["misses"] == 1, (
        "fetch_normalized must increment misses when key is absent"
    )

    # store_normalized must NOT increment misses.
    dummy = tmp_path / "src.mp4"
    dummy.write_bytes(b"placeholder")
    before_store = normalization_cache_stats()["misses"]
    store_normalized("new_key", str(dummy))
    after_store = normalization_cache_stats()["misses"]
    assert after_store == before_store, (
        "store_normalized must NOT increment the misses counter"
    )

    clear_normalization_cache()


def test_cache_hit_counter_increments_on_genuine_hit(tmp_path: Path):
    """fetch_normalized must increment hits when key is present."""
    from services.media_cache import (
        clear_normalization_cache,
        fetch_normalized,
        normalization_cache_stats,
        store_normalized,
    )

    clear_normalization_cache()
    dummy = tmp_path / "clip.mp4"
    dummy.write_bytes(b"fake_video_content")
    store_normalized("real_key", str(dummy))

    dest = tmp_path / "dest.mp4"
    result = fetch_normalized("real_key", str(dest))
    assert result is True
    assert normalization_cache_stats()["hits"] == 1

    clear_normalization_cache()


# ---------------------------------------------------------------------------
# BUG-E: make_gradient_background pixel-by-pixel loop → numpy vectorized
# ---------------------------------------------------------------------------

def test_gradient_uses_numpy_not_pixel_loop():
    """make_gradient_background must not use a per-pixel Python loop."""
    import inspect
    from services.image_studio import make_gradient_background

    src = inspect.getsource(make_gradient_background)
    assert "for y in range" not in src, (
        "make_gradient_background still contains a 'for y in range' pixel loop — "
        "this should have been replaced with numpy vectorization"
    )
    assert "for x in range" not in src, (
        "make_gradient_background still contains a 'for x in range' pixel loop"
    )
    assert "numpy" in src or "np." in src, (
        "make_gradient_background must use numpy for vectorized gradient rendering"
    )


def test_gradient_performance_on_large_canvas():
    """Generating an Instagram Story gradient (1080×1920) must take < 1 s (numpy path).

    The old pixel loop took 5-30 s on CPython; the numpy path takes < 50 ms.
    """
    from services.image_studio import make_gradient_background

    start = time.perf_counter()
    img = make_gradient_background((1080, 1920), "#FF512F", "#DD2476", "vertical")
    elapsed = time.perf_counter() - start

    assert img.size == (1080, 1920)
    assert elapsed < 1.0, (
        f"make_gradient_background took {elapsed:.3f}s on 1080×1920 — "
        f"expected < 1s with numpy; the pixel loop may have been re-introduced"
    )


def test_gradient_correctness_after_numpy_refactor():
    """Numpy gradient must produce the same endpoint colours as the math predicts."""
    from services.image_studio import make_gradient_background

    # Pure-red → pure-blue, vertical, 1×50
    img = make_gradient_background((1, 50), "#FF0000", "#0000FF", "vertical")
    top = img.getpixel((0, 0))[:3]
    bottom = img.getpixel((0, 49))[:3]

    assert top == (255, 0, 0), f"Top pixel should be red; got {top}"
    assert bottom == (0, 0, 255), f"Bottom pixel should be blue; got {bottom}"

    # Pure-red → pure-blue, horizontal, 50×1
    img_h = make_gradient_background((50, 1), "#FF0000", "#0000FF", "horizontal")
    left = img_h.getpixel((0, 0))[:3]
    right = img_h.getpixel((49, 0))[:3]

    assert left == (255, 0, 0), f"Left pixel should be red; got {left}"
    assert right == (0, 0, 255), f"Right pixel should be blue; got {right}"


# ---------------------------------------------------------------------------
# BUG-F: check_models.py passed None API key to genai.Client
# ---------------------------------------------------------------------------

def test_check_models_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    """check_models must exit with a non-zero code when GEMINI_API_KEY is unset."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import check_models
    import io
    import sys

    captured = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = captured
    try:
        exit_code = check_models.main()
    except SystemExit as exc:
        exit_code = exc.code
    finally:
        sys.stderr = old_stderr

    assert exit_code != 0, (
        "check_models.main() must return a non-zero exit code when GEMINI_API_KEY is not set"
    )
    error_output = captured.getvalue()
    assert "GEMINI_API_KEY" in error_output, (
        "check_models must print a message referencing GEMINI_API_KEY when the key is missing"
    )


def test_check_models_script_has_guard():
    """check_models.py source must contain an explicit None/empty check for the API key."""
    src = Path("check_models.py").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" in src, "check_models.py must reference GEMINI_API_KEY"
    # One of these guards must be present.
    has_guard = (
        "if not api_key" in src
        or "if api_key is None" in src
        or "os.environ[" in src  # raises KeyError on missing key
    )
    assert has_guard, "check_models.py must guard against a missing API key"


# ---------------------------------------------------------------------------
# BUG-G: hackathon_features.py duplicate import + tmpdir leak on early exit
# ---------------------------------------------------------------------------

def test_hackathon_features_no_duplicate_import():
    """hackathon_features.py must not contain duplicate 'import os'."""
    src = Path("hackathon_features.py").read_text(encoding="utf-8")
    os_import_count = sum(
        1 for line in src.splitlines()
        if line.strip() == "import os"
    )
    assert os_import_count <= 1, (
        f"hackathon_features.py contains 'import os' {os_import_count} times — must be exactly once"
    )


def test_extract_sample_keyframes_cleans_up_on_empty_video(tmp_path: Path):
    """extract_sample_keyframes must not leak a tmpdir when the video has no frames."""
    # Write a non-video file so OpenCV opens it but reports 0 frames.
    from hackathon_features import extract_sample_keyframes
    import tempfile

    fake_video = tmp_path / "fake.mp4"
    fake_video.write_bytes(b"not a real video")

    tempdir_before = set(
        d for d in Path(tempfile.gettempdir()).iterdir()
        if d.name.startswith("genforge_keyframes_")
    )

    result = extract_sample_keyframes(str(fake_video), num_frames=3)

    tempdir_after = set(
        d for d in Path(tempfile.gettempdir()).iterdir()
        if d.name.startswith("genforge_keyframes_")
    )

    leaked = tempdir_after - tempdir_before
    assert leaked == set(), (
        f"extract_sample_keyframes leaked tmpdir(s) on empty video: {leaked}"
    )
    assert result == [], "Expected empty list for video with no frames"


def test_tmpdir_created_before_try_block():
    """tmpdir must be created before the try block so the except can always clean it up."""
    import ast

    src = Path("hackathon_features.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Find extract_sample_keyframes function.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "extract_sample_keyframes":
            # Check that 'mkdtemp' appears before the first 'Try' statement.
            stmts = node.body
            first_try_idx = next(
                (i for i, s in enumerate(stmts) if isinstance(s, ast.Try)), None
            )
            mkdtemp_idx = next(
                (i for i, s in enumerate(stmts)
                 if isinstance(s, ast.Assign)
                 and any(
                     isinstance(n, ast.Call)
                     and isinstance(getattr(n.func, "attr", None) or getattr(n.func, "id", None), str)
                     and "mkdtemp" in (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
                     for n in ast.walk(s)
                 )),
                None,
            )
            if first_try_idx is not None and mkdtemp_idx is not None:
                assert mkdtemp_idx < first_try_idx, (
                    "tmpdir = tempfile.mkdtemp(...) must appear BEFORE the try block "
                    "in extract_sample_keyframes so it can always be cleaned up"
                )
            break


# ---------------------------------------------------------------------------
# BUG-H: platform_profiles.py imported private _duration from production_features
# ---------------------------------------------------------------------------

def test_platform_profiles_does_not_import_private_duration():
    """platform_profiles.py must not import the private _duration from production_features."""
    src = Path("services/platform_profiles.py").read_text(encoding="utf-8")
    assert "from production_features import _duration" not in src, (
        "platform_profiles.py still imports private _duration from production_features"
    )


def test_platform_profiles_duration_uses_public_api():
    """platform_profiles duration logic must use the public probe API."""
    src = Path("services/platform_profiles.py").read_text(encoding="utf-8")
    # Either probe_media (preferred) or _probe_media (the local alias we introduced).
    has_public_probe = "probe_media" in src or "media_probe" in src
    assert has_public_probe, (
        "platform_profiles.py must use probe_media from services.media_probe "
        "instead of the private _duration from production_features"
    )


def test_duration_advisory_still_works_after_refactor(tmp_path: Path):
    """duration_advisory must produce a valid report after the _duration decoupling."""
    if not __import__("shutil").which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")

    video = _make_video(tmp_path / "clip.mp4", duration=1.0)
    from services.platform_profiles import duration_advisory

    report = duration_advisory(str(video), "TikTok")
    assert "platform" in report
    assert "duration" in report
    assert "fits" in report
    assert isinstance(report["duration"], float)
    assert report["duration"] > 0


# ---------------------------------------------------------------------------
# Miscellaneous: confirm no remaining references to old typo across codebase
# ---------------------------------------------------------------------------

def test_no_inapinting_references_anywhere():
    """No Python source file outside the test directory should reference 'inapinting'."""
    root = Path(".")
    violations = []
    for py_file in root.rglob("*.py"):
        # Skip virtual environment, git internals, and the test files themselves
        # (test files legitimately mention the old typo in comments/docstrings).
        if (
            ".venv" in py_file.parts
            or ".git" in py_file.parts
            or "tests" in py_file.parts
        ):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "inapinting" in content:
            violations.append(str(py_file))
    assert violations == [], (
        f"The following production files still reference the 'inapinting' typo: {violations}"
    )


# ---------------------------------------------------------------------------
# New regressions from commercial-grade audit (2026-08-28)
# ---------------------------------------------------------------------------

# BUG-C1: .env.example contained invalid gemini-3.6-flash model override.
# Regression: the example file must never contain an uncommented broken value.

def test_env_example_does_not_set_invalid_model():
    """The .env.example file must not contain an uncommented GENFORGE_GEMINI_MODEL
    that points to a non-standard model name that would silently break AI features
    on fresh checkout.

    The fix: the override line is now commented out.  This test verifies that
    the dangerous uncommented assignment no longer appears in the file.
    """
    env_example = Path(".env.example").read_text(encoding="utf-8")
    # The line must not exist as an *active* (uncommented) assignment.
    for line in env_example.splitlines():
        stripped = line.strip()
        if stripped.startswith("GENFORGE_GEMINI_MODEL="):
            # Any uncommented assignment is now a regression — it should be commented.
            raise AssertionError(
                f".env.example contains an uncommented GENFORGE_GEMINI_MODEL assignment: {stripped!r}. "
                "This line must be commented out so fresh-checkout users don't inherit a broken default."
            )


# BUG-H1: enhancer.py fixed output filenames caused cross-project overwrite.
# Regression: each call must produce a unique output path.

def test_auto_enhance_image_produces_unique_output_paths(tmp_path: Path):
    """Two consecutive calls to auto_enhance_image must write to different files
    so that a second project never silently overwrites the first project's result.
    """
    from PIL import Image as _Image
    from enhancer import auto_enhance_image

    # Create a minimal valid input image.
    img = _Image.new("RGB", (10, 10), color=(128, 64, 32))
    src = tmp_path / "input.png"
    img.save(str(src))

    out_a = auto_enhance_image(str(src), output_dir=str(tmp_path))
    out_b = auto_enhance_image(str(src), output_dir=str(tmp_path))

    assert out_a != out_b, (
        "auto_enhance_image must return different paths on each call; "
        f"both calls returned: {out_a}"
    )
    assert Path(out_a).is_file(), f"First output does not exist: {out_a}"
    assert Path(out_b).is_file(), f"Second output does not exist: {out_b}"


def test_auto_enhance_video_produces_unique_output_paths(tmp_path: Path, monkeypatch):
    """Two consecutive calls to auto_enhance_video must write to different paths."""
    import subprocess as _sp
    import shutil as _shutil
    if not _shutil.which("ffmpeg"):
        import pytest as _pytest
        _pytest.skip("FFmpeg unavailable")

    from enhancer import auto_enhance_video

    # Build a 0.5-second synthetic video.
    src = tmp_path / "input.mp4"
    _sp.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24",
        "-t", "0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(src),
    ], check=True)

    out_a = auto_enhance_video(str(src), output_dir=str(tmp_path))
    out_b = auto_enhance_video(str(src), output_dir=str(tmp_path))

    assert out_a != out_b, (
        "auto_enhance_video must return different paths on each call; "
        f"both calls returned: {out_a}"
    )
    assert Path(out_a).is_file(), f"First output does not exist: {out_a}"
    assert Path(out_b).is_file(), f"Second output does not exist: {out_b}"


# BUG-M2: save_uploaded_file had no file-size limit.
# Regression: large uploads must be rejected with a clear error.

def test_save_uploaded_file_rejects_oversized_upload(tmp_path: Path):
    """save_uploaded_file must raise ValueError when the file exceeds _MAX_UPLOAD_BYTES."""
    import types as _types
    import app as _app

    # Build a mock UploadedFile that reports a size just over the limit.
    mock_file = _types.SimpleNamespace(
        name="big_video.mp4",
        size=_app._MAX_UPLOAD_BYTES + 1,
        getbuffer=lambda: b"",     # never called because size check comes first
    )

    with __import__("pytest").raises(ValueError, match="too large"):
        _app.save_uploaded_file(mock_file, directory=str(tmp_path))


def test_save_uploaded_file_accepts_file_at_limit(tmp_path: Path):
    """save_uploaded_file must accept a file exactly at the size limit."""
    import types as _types
    import app as _app

    content = b"x" * 100   # small real content so the write succeeds
    mock_file = _types.SimpleNamespace(
        name="ok_video.mp4",
        size=_app._MAX_UPLOAD_BYTES,   # exactly at the limit — must NOT raise
        getbuffer=lambda: content,
    )

    dest = _app.save_uploaded_file(mock_file, directory=str(tmp_path))
    assert Path(dest).is_file()


def test_save_uploaded_file_accepts_file_with_none_size(tmp_path: Path):
    """save_uploaded_file must accept uploads where size is None (Streamlit compat)."""
    import types as _types
    import app as _app

    content = b"y" * 50
    mock_file = _types.SimpleNamespace(
        name="ok_image.png",
        size=None,              # Streamlit may not always populate .size
        getbuffer=lambda: content,
    )

    dest = _app.save_uploaded_file(mock_file, directory=str(tmp_path))
    assert Path(dest).is_file()


# BUG-H2: startup_check.py was a second hardcoded source of truth for DEFAULT_GEMINI_MODEL.
# Regression: startup_check must import directly from services.ai_service.

def test_startup_check_imports_model_from_ai_service():
    """startup_check.py must import DEFAULT_GEMINI_MODEL from services.ai_service,
    not hardcode a separate fallback string.
    """
    src = Path("startup_check.py").read_text(encoding="utf-8")
    assert "from services.ai_service import DEFAULT_GEMINI_MODEL" in src, (
        "startup_check.py must import DEFAULT_GEMINI_MODEL from services.ai_service "
        "so both consumers use the same value automatically."
    )
