from pathlib import Path

import pytest

from services.project_model import ProjectState
from services.project_store import ProjectStore


def test_project_versions_round_trip(tmp_path: Path):
    project = ProjectState()
    project.add_source(str(tmp_path / "source.mp4"))
    version = project.add_version(str(tmp_path / "render.mp4"), {"status": "unavailable"})
    store = ProjectStore(tmp_path / "projects")
    store.save(project)
    loaded = store.load(project.project_id)
    assert loaded.project_id == project.project_id
    assert loaded.outputs[0].version_id == version.version_id
    assert loaded.analytics["status"] == "unavailable"


def test_project_id_path_traversal_is_rejected(tmp_path: Path):
    store = ProjectStore(tmp_path)
    with pytest.raises(ValueError):
        store.path_for("..")
    with pytest.raises(ValueError):
        store.path_for("nested/project")


def test_ai_context_reflects_current_timeline(tmp_path: Path):
    project = ProjectState()
    from services.project_model import TimelineClip

    project.set_timeline([TimelineClip(source_path=str(tmp_path / "clip.mp4"), order=0)])
    project.update_clip(project.timeline[0].clip_id, speed=1.5, operations=[{"type": "blur"}])

    context = project.ai_context()

    assert context["timeline"][0]["speed"] == 1.5
    assert context["timeline"][0]["operations"] == [{"type": "blur"}]


def test_new_projects_are_persisted_and_isolated(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    first = ProjectState()
    second = ProjectState()
    store.save(first)
    store.save(second)

    assert first.project_id != second.project_id
    assert store.path_for(first.project_id).is_file()
    assert store.path_for(second.project_id).is_file()


def test_project_state_round_trip_preserves_sources_versions_and_analytics(tmp_path: Path):
    project = ProjectState(name="My YouTube Channel")
    project.add_source(str(tmp_path / "source.mp4"))
    project.add_version(str(tmp_path / "render.mp4"), {"score": 0.91})
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    reopened = store.load(project.project_id)
    assert reopened.project_id == project.project_id
    assert reopened.source_assets == project.source_assets
    assert reopened.outputs[0].output_path == project.outputs[0].output_path
    assert reopened.analytics == {"score": 0.91}
    assert reopened.name == "My YouTube Channel"


@pytest.mark.parametrize("name", ["", "   ", "bad/name", "..", "x" * 121])
def test_project_name_validation_rejects_invalid_names(name: str):
    with pytest.raises(ValueError):
        ProjectState(name=name)


def test_project_names_can_duplicate_but_ids_remain_unique():
    first = ProjectState(name="My Video")
    second = ProjectState(name="My Video")
    assert first.name == second.name
    assert first.project_id != second.project_id


def test_project_name_is_trimmed_and_rename_preserves_identity(tmp_path: Path):
    project = ProjectState(name="  Launch Plan  ")
    project.add_source(str(tmp_path / "source.mp4"))
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    loaded = store.load(project.project_id)
    renamed = ProjectState.model_validate({**loaded.model_dump(), "name": "  Final Launch  "})
    store.save(renamed)
    reopened = store.load(project.project_id)

    assert project.name == "Launch Plan"
    assert reopened.name == "Final Launch"
    assert reopened.project_id == project.project_id
    assert reopened.source_assets == project.source_assets


def test_store_lists_and_deletes_only_selected_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    output_root = tmp_path / "outputs"
    first = ProjectState(name="First")
    second = ProjectState(name="Second")
    store.save(first)
    store.save(second)
    (output_root / first.project_id).mkdir(parents=True)
    (output_root / second.project_id).mkdir(parents=True)
    (output_root / "unrelated").mkdir(parents=True)

    store.delete(first.project_id, output_root=output_root)

    assert not store.path_for(first.project_id).exists()
    assert store.path_for(second.project_id).is_file()
    assert not (output_root / first.project_id).exists()
    assert (output_root / second.project_id).is_dir()
    assert (output_root / "unrelated").is_dir()


# ---------------------------------------------------------------------------
# Extended persistent-project-memory tests (spec §27)
# ---------------------------------------------------------------------------

import time as _time
from datetime import datetime, timezone


# --- 1. Create named project ------------------------------------------------

def test_create_named_project_stores_name_and_unique_id(tmp_path: Path):
    """A project created with a name retains that name after a round-trip."""
    project = ProjectState(name="My YouTube Channel")
    store = ProjectStore(tmp_path / "projects")
    store.save(project)
    loaded = store.load(project.project_id)
    assert loaded.name == "My YouTube Channel"
    assert loaded.project_id == project.project_id


# --- 2. Blank name rejection -------------------------------------------------

def test_blank_name_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        ProjectState(name="")


# --- 3. Whitespace-only name rejection ----------------------------------------

def test_whitespace_only_name_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        ProjectState(name="   ")


# --- 4. Unique project ID ----------------------------------------------------

def test_every_new_project_receives_a_unique_id():
    ids = {ProjectState(name=f"P{i}").project_id for i in range(10)}
    assert len(ids) == 10


# --- 5. Immediate persistence ------------------------------------------------

def test_project_exists_on_disk_immediately_after_save(tmp_path: Path):
    """A project must be on disk right after creation — not only after a render."""
    project = ProjectState(name="Instant Save")
    store = ProjectStore(tmp_path / "projects")
    path = store.save(project)
    assert path.is_file()
    assert path.stat().st_size > 0


# --- 6. Project appears in list after save -----------------------------------

def test_saved_project_appears_in_list_projects(tmp_path: Path):
    project = ProjectState(name="Listed Project")
    store = ProjectStore(tmp_path / "projects")
    store.save(project)
    ids = [p.project_id for p in store.list_projects()]
    assert project.project_id in ids


# --- 7. Open (load) project --------------------------------------------------

def test_load_restores_full_project_state(tmp_path: Path):
    project = ProjectState(name="Loadable")
    from services.project_model import TimelineClip
    project.set_timeline([TimelineClip(source_path="/tmp/clip.mp4", order=0)])
    project.add_source("/tmp/source.mp4")
    project.add_version("/tmp/render.mp4", {"score": 0.85})
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    loaded = store.load(project.project_id)
    assert loaded.name == "Loadable"
    assert len(loaded.timeline) == 1
    assert loaded.source_assets == project.source_assets
    assert len(loaded.outputs) == 1
    assert loaded.outputs[0].analytics == {"score": 0.85}


# --- 8. Rename project -------------------------------------------------------

def test_rename_changes_name_on_disk(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = ProjectState(name="Old Name")
    store.save(project)

    renamed = ProjectState.model_validate({**project.model_dump(), "name": "New Name"})
    store.save(renamed)

    reloaded = store.load(project.project_id)
    assert reloaded.name == "New Name"


# --- 9. Project ID unchanged after rename ------------------------------------

def test_project_id_is_unchanged_after_rename(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    original_id = ProjectState(name="Before").project_id
    project = ProjectState(name="Before")
    # Force same id by constructing with model_validate
    store.save(project)
    renamed = ProjectState.model_validate({**project.model_dump(), "name": "After"})
    store.save(renamed)
    reloaded = store.load(project.project_id)
    assert reloaded.project_id == project.project_id


# --- 10. Delete one project --------------------------------------------------

def test_delete_one_project_removes_only_that_project(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    keep = ProjectState(name="Keep Me")
    gone = ProjectState(name="Delete Me")
    store.save(keep)
    store.save(gone)

    store.delete(gone.project_id, output_root=tmp_path / "outputs")

    assert store.path_for(keep.project_id).is_file()
    assert not store.path_for(gone.project_id).exists()


# --- 11. Delete current project (isolation) ----------------------------------

def test_delete_removes_project_dir_but_not_store_root(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = ProjectState(name="Current")
    store.save(project)
    store.delete(project.project_id, output_root=tmp_path / "outputs")
    assert not store.path_for(project.project_id).exists()
    # Store root itself must survive
    assert store.root.is_dir()


# --- 12. Delete all projects -------------------------------------------------

def test_delete_all_removes_every_project_and_returns_count(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    for i in range(5):
        store.save(ProjectState(name=f"Project {i}"))
    count = store.delete_all(output_root=tmp_path / "outputs")
    assert count == 5
    assert store.list_projects() == []


# --- 13. Delete confirmation guard (path validation) -------------------------

def test_delete_all_leaves_zero_projects(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    store.save(ProjectState(name="A"))
    store.save(ProjectState(name="B"))
    store.delete_all(output_root=tmp_path / "outputs")
    remaining = store.list_projects()
    assert remaining == []


# --- 14. Restart persistence (simulate process restart) ----------------------

def test_projects_survive_new_store_instance(tmp_path: Path):
    """Simulate a Streamlit restart by constructing a fresh ProjectStore instance."""
    root = tmp_path / "projects"
    ProjectStore(root).save(ProjectState(name="My Persistent Project"))

    # New Python object — same root — simulates a process restart.
    fresh_store = ProjectStore(root)
    names = [p.name for p in fresh_store.list_projects()]
    assert "My Persistent Project" in names


# --- 15. Timeline persistence ------------------------------------------------

def test_timeline_clips_survive_save_and_reload(tmp_path: Path):
    from services.project_model import TimelineClip
    project = ProjectState(name="Timeline Test")
    clips = [
        TimelineClip(source_path="/tmp/a.mp4", order=0, trim_start=1.5, trim_end=10.0),
        TimelineClip(source_path="/tmp/b.mp4", order=1, speed=2.0),
    ]
    project.set_timeline(clips)
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    loaded = store.load(project.project_id)
    assert len(loaded.timeline) == 2
    assert loaded.timeline[0].trim_start == 1.5
    assert loaded.timeline[0].trim_end == 10.0
    assert loaded.timeline[1].speed == 2.0


# --- 16. Asset persistence ---------------------------------------------------

def test_source_assets_survive_save_and_reload(tmp_path: Path):
    project = ProjectState(name="Asset Test")
    project.add_source(str(tmp_path / "video.mp4"))
    project.add_source(str(tmp_path / "audio.mp3"))
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    loaded = store.load(project.project_id)
    assert str((tmp_path / "video.mp4").resolve()) in loaded.source_assets
    assert str((tmp_path / "audio.mp3").resolve()) in loaded.source_assets


# --- 17. Version persistence -------------------------------------------------

def test_multiple_versions_all_survive_reload(tmp_path: Path):
    project = ProjectState(name="Versioned")
    for i in range(3):
        project.add_version(str(tmp_path / f"render_v{i}.mp4"), {"iteration": i})
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    loaded = store.load(project.project_id)
    assert len(loaded.outputs) == 3
    iterations = {v.analytics["iteration"] for v in loaded.outputs}
    assert iterations == {0, 1, 2}


# --- 18. Render reference persistence ----------------------------------------

def test_render_metadata_is_preserved_not_just_scanned(tmp_path: Path):
    """Render metadata (version_id, path, status, analytics) must be stored
    in project.json — not derived by scanning the outputs directory."""
    project = ProjectState(name="Render Refs")
    version = project.add_version(str(tmp_path / "final.mp4"), {"viral_score": 0.92})
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    # Remove the physical file — the metadata must still load correctly.
    loaded = store.load(project.project_id)
    assert loaded.outputs[0].version_id == version.version_id
    assert loaded.outputs[0].analytics == {"viral_score": 0.92}
    assert loaded.outputs[0].status == "rendered"


# --- 19. Project settings persistence ----------------------------------------

def test_project_settings_survive_reload(tmp_path: Path):
    project = ProjectState(name="Settings Test")
    project.update_settings(target_format="9:16 (Shorts/TikTok)", platform="TikTok")
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    loaded = store.load(project.project_id)
    assert loaded.settings["target_format"] == "9:16 (Shorts/TikTok)"
    assert loaded.settings["platform"] == "TikTok"


# --- 20. Project isolation ---------------------------------------------------

def test_two_projects_do_not_share_state(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    alpha = ProjectState(name="Alpha")
    beta = ProjectState(name="Beta")
    alpha.add_source(str(tmp_path / "alpha_clip.mp4"))
    beta.add_source(str(tmp_path / "beta_clip.mp4"))
    store.save(alpha)
    store.save(beta)

    loaded_alpha = store.load(alpha.project_id)
    loaded_beta = store.load(beta.project_id)
    assert loaded_alpha.source_assets != loaded_beta.source_assets
    assert loaded_alpha.project_id != loaded_beta.project_id


# --- 21. Corrupted project handling ------------------------------------------

def test_corrupted_project_json_does_not_crash_list(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    good = ProjectState(name="Good")
    store.save(good)

    # Inject a corrupt JSON file that looks like a valid project directory.
    bad_dir = store.root / "deadbeef00000000000000000000000a"
    bad_dir.mkdir()
    (bad_dir / "project.json").write_text("{not valid json", encoding="utf-8")

    # list_projects must silently skip the corrupt entry and still return the good one.
    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0].project_id == good.project_id


def test_loading_corrupted_project_raises_runtime_error(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    bad_dir = store.root / "deadbeef00000000000000000000000b"
    bad_dir.mkdir()
    (bad_dir / "project.json").write_text("[[not json]]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Could not load project"):
        store.load("deadbeef00000000000000000000000b")


# --- 22. Atomic save behaviour -----------------------------------------------

def test_atomic_save_does_not_leave_tmp_file(tmp_path: Path):
    """After a successful save no .tmp file should remain alongside project.json."""
    project = ProjectState(name="Atomic")
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    project_dir = store.root / project.project_id
    tmp_files = list(project_dir.glob("*.tmp"))
    assert tmp_files == [], f"Stale .tmp file found: {tmp_files}"


def test_atomic_save_produces_valid_json(tmp_path: Path):
    """The written project.json must be valid JSON and round-trip cleanly."""
    import json as _json
    project = ProjectState(name="Valid JSON")
    store = ProjectStore(tmp_path / "projects")
    path = store.save(project)
    raw = path.read_text(encoding="utf-8")
    parsed = _json.loads(raw)
    assert parsed["project_id"] == project.project_id
    assert parsed["name"] == "Valid JSON"


# --- 23. updated_at / touch / settings logic ---------------------------------

def test_updated_at_is_stamped_by_touch(tmp_path: Path):
    project = ProjectState(name="Touch Test")
    before = project.updated_at
    _time.sleep(0.01)
    project.touch()
    assert project.updated_at > before


def test_update_settings_merges_and_stamps_updated_at(tmp_path: Path):
    project = ProjectState(name="Settings Merge")
    project.update_settings(platform="YouTube", aspect_ratio="16:9")
    project.update_settings(aspect_ratio="9:16", quality="high")
    # Old key retained; new key added; changed key updated.
    assert project.settings["platform"] == "YouTube"
    assert project.settings["aspect_ratio"] == "9:16"
    assert project.settings["quality"] == "high"
    # updated_at must have been bumped.
    assert project.updated_at >= project.created_at


def test_list_projects_sorted_by_updated_at_most_recent_first(tmp_path: Path):
    """list_projects() must order by updated_at, not created_at."""
    store = ProjectStore(tmp_path / "projects")
    older = ProjectState(name="Older")
    store.save(older)
    _time.sleep(0.02)
    newer = ProjectState(name="Newer")
    store.save(newer)

    projects = store.list_projects()
    assert projects[0].project_id == newer.project_id
    assert projects[1].project_id == older.project_id


def test_delete_all_returns_correct_count_when_store_is_empty(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    assert store.delete_all(output_root=tmp_path / "outputs") == 0


def test_project_with_no_updated_at_field_loads_via_default(tmp_path: Path):
    """Old project.json files without updated_at must load without error,
    receiving a sensible default rather than crashing."""
    import json as _json
    project = ProjectState(name="Legacy")
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    # Strip updated_at to simulate a file written by the old schema.
    path = store.path_for(project.project_id)
    data = _json.loads(path.read_text(encoding="utf-8"))
    del data["updated_at"]
    path.write_text(_json.dumps(data), encoding="utf-8")

    loaded = store.load(project.project_id)
    assert loaded.project_id == project.project_id
    assert isinstance(loaded.updated_at, str) and loaded.updated_at  # not empty


def test_project_with_no_settings_field_loads_as_empty_dict(tmp_path: Path):
    """Old project.json files without settings must load as an empty dict."""
    import json as _json
    project = ProjectState(name="No Settings")
    store = ProjectStore(tmp_path / "projects")
    store.save(project)

    path = store.path_for(project.project_id)
    data = _json.loads(path.read_text(encoding="utf-8"))
    del data["settings"]
    path.write_text(_json.dumps(data), encoding="utf-8")

    loaded = store.load(project.project_id)
    assert loaded.settings == {}
