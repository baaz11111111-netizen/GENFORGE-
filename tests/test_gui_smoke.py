"""Headless UI regression for the professional-editor GUI.

Renders every workspace view through ``streamlit.testing.v1.AppTest`` and
exercises two functional state flows (AI Director preview, New Project).

A fresh ``AppTest`` instance is used per view: AppTest retains stale widget
nodes across radio-driven view switches (real browsers clear them via
deltas), which can raise ``KeyError`` for purged widget keys when one
instance walks many views.
"""

import os

import pytest

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
)

VIEWS = [
    ":material/home: Home",
    ":material/videocam: Video Studio",
    ":material/image: Image Studio",
    ":material/hub: Campaign Swarm",
    ":material/star: Highlights",
    ":material/description: Script Studio",
    ":material/graphic_eq: Audio Tools",
    ":material/rocket_launch: Campaign Hub",
    ":material/cloud_upload: Publishing",
]


def _render_view(view: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception, f"boot failed: {[str(e.value) for e in at.exception]}"
    at.sidebar.radio[0].set_value(view).run()
    assert not at.exception, f"{view} raised: {[str(e.value) for e in at.exception]}"
    return at


@pytest.mark.parametrize("view", VIEWS)
def test_workspace_view_renders(view):
    """Every workspace view renders without script exceptions."""
    _render_view(view)


def test_navigation_uses_icon_labels_without_emoji():
    """Sidebar navigation exposes all nine workspaces via icon+label entries."""
    at = _render_view(":material/home: Home")
    options = list(at.sidebar.radio[0].options)
    assert options == VIEWS
    assert all(option.startswith(":material/") for option in options)


def test_main_area_nav_button_is_removed_but_palette_navigation_remains():
    """Quick navigation uses the command palette, not a duplicate Nav button."""
    at = _render_view(VIEWS[0])
    assert not any(b.key == "btn_open_navigation" for b in at.button)
    assert not any(s.key == "compact_workspace_navigation" for s in at.selectbox)
    assert any(b.key == "palette_1" for b in at.button)
    palette_video = [b for b in at.button if b.key == "palette_1"][0]
    palette_video.click().run()
    assert not at.exception
    assert at.session_state["app_mode"] == VIEWS[1]


def test_command_palette_registers_existing_actions_without_replacing_navigation():
    """The palette exposes existing workspace and project actions."""
    at = _render_view(VIEWS[0])
    assert any(b.key == "palette_1" for b in at.button)
    assert any(b.key == "palette_new_project" for b in at.button)
    assert any(b.key == "palette_toggle_theme" for b in at.button)
    assert any(b.key == "palette_save" for b in at.button)


def test_command_palette_toggle_theme_updates_application_state():
    """Palette theme action toggles canonical state without a widget exception."""
    at = _render_view(VIEWS[0])
    assert at.session_state["theme"] == "light"
    toggle = [b for b in at.button if b.key == "palette_toggle_theme"]
    assert toggle
    toggle[0].click().run()
    assert not at.exception
    assert at.session_state["theme"] == "dark"
    assert at.session_state["theme_selector"] == "dark"
    toggle = [b for b in at.button if b.key == "palette_toggle_theme"]
    toggle[0].click().run()
    assert not at.exception
    assert at.session_state["theme"] == "light"
    assert at.session_state["theme_selector"] == "light"


def test_video_target_format_options_are_complete():
    """Target format choices remain complete instead of clipped abbreviations."""
    at = _render_view(":material/videocam: Video Studio")
    target_format = [s for s in at.selectbox if s.label == "Target format"]
    assert target_format, "Target format selector missing"
    assert list(target_format[0].options) == [
        "Original",
        "9:16 (Shorts/TikTok)",
        "1:1 (Square)",
        "16:9 (Landscape)",
    ]
    assert all("..." not in option for option in target_format[0].options)


def test_ai_director_preview_flow():
    """AI Director panel parses the command and flags the preview state."""
    at = _render_view(":material/videocam: Video Studio")
    preview = [b for b in at.button if b.key == "btn_ai_preview"]
    assert preview, "AI Director preview button missing"
    preview[0].click().run()
    assert not at.exception
    assert "ai_director_preview" in at.session_state
    assert at.session_state["ai_director_preview"] is True


def test_new_project_creates_fresh_state():
    """Home -> named New Project persists and opens a fresh ProjectState."""
    at = _render_view(":material/home: Home")
    # project is None until the user explicitly creates one — that's correct.
    assert at.session_state["project"] is None
    new_project = [b for b in at.button if b.key == "btn_new_project"]
    assert new_project, "New Project button missing"
    new_project[0].click().run()
    at.text_input(key="new_project_name").set_value("My Test Project")
    create = [b for b in at.button if "Create Project" in b.label]
    assert create, "Create Project button missing"
    create[0].click().run()
    assert not at.exception
    assert at.session_state["project"] is not None
    assert at.session_state["project"].name == "My Test Project"
    assert at.session_state["app_mode"] == ":material/videocam: Video Studio"

    project_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "projects", at.session_state["project"].project_id, "project.json",
    )
    assert os.path.isfile(project_path)


def test_new_project_requires_a_name():
    """New Project opens a form and does not create an anonymous project."""
    at = _render_view(":material/home: Home")
    # No project is open before any creation — verify None state is stable.
    assert at.session_state["project"] is None
    [b for b in at.button if b.key == "btn_new_project"][0].click().run()
    [b for b in at.button if "Create Project" in b.label][0].click().run()
    assert not at.exception
    # No project should have been created for a blank name.
    assert at.session_state["project"] is None
    assert "Project name cannot be empty" in " ".join(e.value for e in at.error)


def test_project_search_has_explicit_no_match_state():
    """Recent projects can be filtered without changing persisted projects."""
    at = _render_view(VIEWS[0])
    search = at.text_input(key="project_search")
    assert search, "Project search control missing"
    search.set_value("definitely-no-project-match").run()
    assert not at.exception
    assert any("No matching projects" in (item.value or "") for item in at.markdown)


def test_open_project_switches_to_video_studio():
    """Home Open Project loads the selected durable project and changes workspace."""
    at = _render_view(":material/home: Home")
    # Create a fresh project so we have something to open.
    unique_name = f"Open Me {__import__('uuid').uuid4().hex[:8]}"
    new_project = [b for b in at.button if b.key == "btn_new_project"]
    assert new_project
    new_project[0].click().run()
    at.text_input(key="new_project_name").set_value(unique_name)
    [b for b in at.button if "Create Project" in b.label][0].click().run()
    assert not at.exception
    project = at.session_state["project"]
    at.sidebar.radio[0].set_value(":material/home: Home").run()
    assert not at.exception
    open_project = [b for b in at.button if b.key == "btn_open_project"]
    assert open_project
    selector = at.selectbox(key="home_open_project_select")
    selected_label = next(
        option for option in selector.options if option.startswith(unique_name)
    )
    selector.set_value(selected_label).run()
    assert not at.exception
    open_project = [b for b in at.button if b.key == "btn_open_project"]
    open_project[0].click().run()
    assert not at.exception
    assert at.session_state["app_mode"] == ":material/videocam: Video Studio"
    assert at.session_state["project"].project_id == project.project_id
