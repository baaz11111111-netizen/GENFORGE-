"""Phase 6 — AI Auto-Editor workflow regression tests."""
import subprocess
from pathlib import Path

import pytest

from services.auto_editor import auto_optimize, default_optimizing_editor, diagnose_video
from services.project_model import ProjectState


def _make_video(path: Path, duration=6.0, with_audio=True, size="320x240"):
    command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24"]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    command += ["-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    command += ["-c:a", "aac"] if with_audio else ["-an"]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True)
    return path


class TestDiagnosis:
    def test_deterministic_problems_without_ai(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", with_audio=False, size="320x240")
        report = diagnose_video(str(video))
        assert report["status"] == "analyzed"
        assert any("No audio" in p for p in report["problems"])
        assert any("Low resolution" in p for p in report["problems"])
        assert report["recommendations"]

    def test_clean_video_has_no_structural_problems(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=8.0, size="1280x720")
        report = diagnose_video(str(video))
        assert report["problems"] == []

    def test_unavailable_ai_reported_honestly(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4")
        report = diagnose_video(str(video), analyzer=lambda p: {"status": "unavailable"})
        assert "unavailable" in report["ai_summary"]

    def test_low_ai_scores_become_problems(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", size="1280x720")
        report = diagnose_video(str(video), analyzer=lambda p: {"hook_score": 40.0, "pacing_score": 90.0})
        assert any("Weak hook" in p for p in report["problems"])
        assert report["scores"]["hook_score"] == 40.0

    def test_missing_file_rejected(self):
        with pytest.raises(FileNotFoundError):
            diagnose_video("does_not_exist.mp4")


class TestDefaultEditor:
    def test_lufs_mastering_path(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=3.0)
        out = default_optimizing_editor(str(video), {}, output_dir=str(tmp_path / "opt"))
        assert Path(out).stat().st_size > 0

    def test_silent_video_grade_path(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=2.0, with_audio=False)
        out = default_optimizing_editor(str(video), {}, output_dir=str(tmp_path / "opt"))
        assert Path(out).stat().st_size > 0


class TestAutoOptimize:
    def test_improvement_selected_and_versioned(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        project = ProjectState()
        candidate = str(tmp_path / "candidate.mp4")
        Path(candidate).write_bytes(Path(video).read_bytes())
        scores = {str(video): 60.0, candidate: 75.0}
        result = auto_optimize(
            project, str(video),
            analyzer=lambda p: {"hook_score": scores[p]},
            editor=lambda p, a: candidate,
        )
        assert result["status"] == "improved"
        assert result["selected_path"] == candidate
        assert len(project.outputs) == 1
        assert project.outputs[0].analytics["auto_optimized"] is True

    def test_worse_candidate_never_selected(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        project = ProjectState()
        candidate = str(tmp_path / "candidate.mp4")
        scores = {str(video): 80.0, candidate: 50.0}
        result = auto_optimize(
            project, str(video),
            analyzer=lambda p: {"hook_score": scores[p]},
            editor=lambda p, a: candidate,
        )
        assert result["status"] == "kept_original"
        assert result["selected_path"] == str(video)
        assert project.outputs == []

    def test_unavailable_analysis_honest(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        project = ProjectState()
        result = auto_optimize(project, str(video), analyzer=lambda p: {"status": "unavailable"})
        assert result["status"] == "analysis_unavailable"
        assert project.outputs == []

    def test_iteration_bounds_enforced(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        with pytest.raises(ValueError):
            auto_optimize(ProjectState(), str(video), analyzer=lambda p: {}, max_iterations=99)

    def test_multiple_iterations_bounded(self, tmp_path):
        video = _make_video(tmp_path / "v.mp4", duration=2.0)
        project = ProjectState()
        calls = {"editor": 0}

        def editor(path, analytics):
            calls["editor"] += 1
            candidate = str(tmp_path / f"c{calls['editor']}.mp4")
            Path(candidate).write_bytes(Path(video).read_bytes())
            return candidate

        scores = {str(video): 50.0}
        analyzer = lambda p: {"hook_score": scores.get(p, 90.0)}
        result = auto_optimize(project, str(video), analyzer=analyzer, editor=editor, max_iterations=3)
        assert calls["editor"] == 3  # no infinite loop, exact bound
        assert result["status"] == "improved"
