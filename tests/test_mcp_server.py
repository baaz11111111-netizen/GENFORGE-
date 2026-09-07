from pathlib import Path

import pytest

import mcp_server


def test_trim_clip_rejects_missing_input(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        mcp_server.trim_clip(str(tmp_path / "missing.mp4"), str(tmp_path / "out.mp4"), 0, 1)


def test_trim_clip_delegates_to_canonical_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")
    output = tmp_path / "nested" / "out.mp4"
    calls: dict[str, object] = {}

    def fake_trim(input_path: str, output_path: str, start_time: float, end_time: float) -> str:
        calls.update(
            input_path=input_path,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
        )
        return output_path

    monkeypatch.setattr(mcp_server, "_trim_clip", fake_trim)

    result = mcp_server.trim_clip(str(source), str(output), 1.5, 3.0)

    assert result == str(output.resolve())
    assert calls == {
        "input_path": str(source.resolve()),
        "output_path": str(output.resolve()),
        "start_time": 1.5,
        "end_time": 3.0,
    }
