from pathlib import Path

import pytest

from advanced_editing import resize_video_aspect, trim_clip


def test_trim_rejects_missing_input(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        trim_clip(str(tmp_path / "missing.mp4"), str(tmp_path / "out.mp4"), 0, 1)


def test_resize_rejects_unknown_ratio(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not media")
    with pytest.raises(ValueError):
        resize_video_aspect(str(source), str(tmp_path / "out.mp4"), "4:3")
