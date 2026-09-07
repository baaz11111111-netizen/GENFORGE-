import shutil
import subprocess
from pathlib import Path

import pytest

from orchestrator import run_editing_agent


def test_orchestrator_writes_to_requested_output_dir(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe unavailable")

    source = tmp_path / "source.mp4"
    output_dir = tmp_path / "project" / "outputs"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=320x240:rate=24", "-t", "0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
        capture_output=True,
    )

    output = run_editing_agent("keep the original video", [str(source)], output_dir=str(output_dir))

    assert output_dir.resolve() in Path(output).resolve().parents
    assert Path(output).is_file()
