"""Phase 9 — Thumbnail Studio regression tests."""
import subprocess
from pathlib import Path

import pytest

from services.project_model import ProjectState
from services.thumbnail_studio import (
    add_thumbnails_to_project,
    extract_candidate_frames,
    generate_thumbnail_variants,
    render_thumbnail,
    select_best_frame,
    select_frame_at,
    select_preferred_thumbnail,
)


def _make_video(path: Path, duration=2.0):
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path),
    ], check=True, capture_output=True)
    return path


class TestFrameSelection:
    def test_candidate_frames_scored(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        candidates = extract_candidate_frames(str(video), count=5)
        assert len(candidates) >= 4
        assert all(c["sharpness"] >= 0 for c in candidates)
        assert all(c["image"].shape[2] == 3 for c in candidates)

    def test_best_frame_is_sharpest(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        candidates = extract_candidate_frames(str(video), count=6)
        best = select_best_frame(candidates)
        assert best["sharpness"] == max(c["sharpness"] for c in candidates)

    def test_manual_frame_selection(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        frame = select_frame_at(str(video), 1.0)
        assert frame["time"] == 1.0 and frame["image"].shape[0] == 240

    def test_negative_timestamp_rejected(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        with pytest.raises(ValueError, match="negative"):
            select_frame_at(str(video), -1.0)

    def test_count_bounds(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        with pytest.raises(ValueError):
            extract_candidate_frames(str(video), count=0)

    def test_missing_video_rejected(self):
        with pytest.raises(FileNotFoundError):
            extract_candidate_frames("missing.mp4")


class TestRender:
    def test_thumbnail_with_title_rendered(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        best = select_best_frame(extract_candidate_frames(str(video)))
        from PIL import Image
        out = render_thumbnail(Image.fromarray(best["image"]), str(tmp_path / "t.png"), title="Big Reveal")
        image = Path(out)
        assert image.stat().st_size > 0
        from PIL import Image as PILImage
        assert PILImage.open(out).size == (320, 240)

    def test_every_placement_renders(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        best = select_best_frame(extract_candidate_frames(str(video)))
        from PIL import Image
        for placement in ("bottom_bar", "top_left", "top_right", "auto"):
            out = render_thumbnail(Image.fromarray(best["image"]),
                                   str(tmp_path / f"{placement}.png"), title="X", placement=placement)
            assert Path(out).stat().st_size > 0

    def test_unknown_placement_rejected(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        best = select_best_frame(extract_candidate_frames(str(video)))
        from PIL import Image
        with pytest.raises(ValueError, match="Unknown placement"):
            render_thumbnail(Image.fromarray(best["image"]), str(tmp_path / "x.png"), placement="diagonal")


class TestVariantsAndProject:
    def test_variants_generated_per_title(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        variants = generate_thumbnail_variants(str(video), str(tmp_path / "thumbs"),
                                               titles=["Hook A", "Hook B"])
        assert len(variants) == 4  # 2 titles x (auto + first-frame)
        assert all(Path(v["path"]).is_file() for v in variants)

    def test_project_storage_and_selection(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        project = ProjectState()
        variants = generate_thumbnail_variants(str(video), str(tmp_path / "thumbs"), titles=["Only"])
        add_thumbnails_to_project(project, variants)
        assert len(project.thumbnails) == 2

        chosen = select_preferred_thumbnail(project, variants[0]["thumbnail_id"])
        selected = [entry for entry in project.thumbnails if entry["selected"]]
        assert len(selected) == 1 and selected[0]["thumbnail_id"] == chosen["thumbnail_id"]

    def test_selection_of_unknown_thumbnail_raises(self):
        with pytest.raises(KeyError):
            select_preferred_thumbnail(ProjectState(), "missing")

    def test_empty_variants_rejected(self):
        with pytest.raises(ValueError):
            add_thumbnails_to_project(ProjectState(), [])

    def test_thumbnails_survive_project_roundtrip(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        project = ProjectState()
        variants = generate_thumbnail_variants(str(video), str(tmp_path / "thumbs"), titles=["T"])
        add_thumbnails_to_project(project, variants)
        restored = ProjectState.model_validate_json(project.model_dump_json())
        assert len(restored.thumbnails) == 2
        assert "thumbnails" in restored.ai_context()
