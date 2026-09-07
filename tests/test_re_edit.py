from services.re_edit import improve_once


def test_unavailable_analysis_does_not_edit():
    calls = []
    result = improve_once("source.mp4", lambda _: {"status": "unavailable"}, lambda path, _: calls.append(path))
    assert result["status"] == "analysis_unavailable"
    assert calls == []


def test_re_edit_selects_only_measurable_improvement():
    scores = {"source.mp4": 50, "candidate.mp4": 54}
    result = improve_once(
        "source.mp4",
        lambda path: {"hook_score": scores[path], "pacing_score": scores[path]},
        lambda _, __: "candidate.mp4",
        minimum_improvement=2,
    )
    assert result["selected_path"] == "candidate.mp4"
    assert result["iterations"] == 1
