"""Regression tests for the single GENFORGE theme source of truth."""

import pytest
from types import SimpleNamespace
from pathlib import Path
import inspect

from ui_components import THEME_DARK, THEME_LIGHT, get_design_system_css, theme_tokens


CRITICAL_TOKENS = {
    "bg", "app_bg", "s1", "s2", "sidebar", "editor_bg", "card", "panel",
    "fg", "muted", "faint", "border", "accent", "accent_soft", "good",
    "warn", "bad", "info", "shadow", "grad_primary", "grad_brand", "input_bg",
    "button_bg", "disabled_bg", "focus_ring", "selected_bg", "hover_bg",
    "active_bg", "table_header", "overlay",
    "uploader_bg", "uploader_fg", "uploader_muted", "uploader_border",
    "uploader_hover_bg", "uploader_hover_border", "uploader_icon",
    "uploader_button_bg", "uploader_button_fg",
}


def test_theme_token_sets_are_complete_and_symmetric():
    assert set(THEME_DARK) == set(THEME_LIGHT)
    assert CRITICAL_TOKENS <= set(THEME_DARK)
    assert all(THEME_DARK[key] for key in CRITICAL_TOKENS)
    assert all(THEME_LIGHT[key] for key in CRITICAL_TOKENS)


def test_theme_tokens_selects_expected_theme_and_rejects_invalid_values():
    assert theme_tokens("dark") is THEME_DARK
    assert theme_tokens("light") is THEME_LIGHT
    with pytest.raises(ValueError):
        theme_tokens("sepia")


def test_light_is_the_default_theme():
    assert theme_tokens() is THEME_LIGHT
    assert get_design_system_css() == get_design_system_css("light")


def test_explicit_theme_switches_are_available():
    assert theme_tokens("dark") is THEME_DARK
    assert theme_tokens("light") is THEME_LIGHT


def test_session_theme_defaults_to_light_and_preserves_manual_switches(monkeypatch):
    import app

    fake_streamlit = SimpleNamespace(session_state={})
    monkeypatch.setattr(app, "st", fake_streamlit)

    app.init_session_state()
    assert fake_streamlit.session_state["theme"] == "light"
    assert fake_streamlit.session_state["theme_selector"] == "light"

    fake_streamlit.session_state["theme_selector"] = "dark"
    app._sync_theme_selection()
    assert fake_streamlit.session_state["theme"] == "dark"

    fake_streamlit.session_state["theme_selector"] = "light"
    app._sync_theme_selection()
    assert fake_streamlit.session_state["theme"] == "light"

    fake_streamlit.session_state["theme"] = "dark"
    app._sync_workspace_navigation(app.WORKSPACE_OPTIONS[0])
    assert fake_streamlit.session_state["theme"] == "dark"


def test_command_palette_theme_callback_toggles_canonical_state(monkeypatch):
    import app

    fake_streamlit = SimpleNamespace(session_state={"theme": "light"})
    monkeypatch.setattr(app, "st", fake_streamlit)

    app._toggle_theme()
    assert fake_streamlit.session_state["theme"] == "dark"
    app._toggle_theme()
    assert fake_streamlit.session_state["theme"] == "light"


def test_theme_selector_is_not_mutated_by_application_body():
    import app

    palette_source = inspect.getsource(app._render_command_palette)
    assert 'st.session_state["theme_selector"] =' not in palette_source
    assert "_toggle_theme" in palette_source


def test_generated_css_is_theme_specific_and_exposes_complete_variables():
    dark_css = get_design_system_css("dark")
    light_css = get_design_system_css("light")

    assert dark_css != light_css
    assert "--gf-bg: #070A0E" in dark_css
    assert "--gf-bg: #F8FAFC" in light_css
    assert "--gf-sidebar: #0A0D12" in dark_css
    assert "--gf-sidebar: #FFFFFF" in light_css
    assert "--gf-grad-hero:" in dark_css and "--gf-grad-hero:" in light_css
    assert "--gf-disabled-border:" in dark_css and "--gf-disabled-border:" in light_css
    assert "--gf-table-header:" in dark_css and "--gf-table-header:" in light_css
    for css in (dark_css, light_css):
        for token in (
            "--gf-button-bg:", "--gf-button-fg:", "--gf-button-border:",
            "--gf-button-hover:", "--gf-button-hover-fg:",
            "--gf-button-active-bg:", "--gf-button-active-fg:",
            "--gf-button-disabled-bg:", "--gf-button-disabled-fg:",
        ):
            assert token in css


def test_native_controls_and_custom_surfaces_consume_theme_variables():
    css = get_design_system_css("light")

    for selector in (
        ".stTextInput input", ".stTextArea textarea", ".stNumberInput input",
        '[data-baseweb="select"] > div', '[data-testid="stFileUploader"]',
        '[data-testid="stMetric"]', '[data-testid="stAlert"]',
        '[data-testid="stDataFrame"]', '.stTabs [data-baseweb="tab-list"]',
        ".gf-project-card", ".gf-editor-panel", ".gf-status-bar",
    ):
        assert selector in css
    assert "background: var(--gf-input-bg) !important" in css
    assert "color: var(--gf-fg) !important" in css
    assert "background: var(--gf-selected-bg) !important" in css
    assert "outline: 2px solid var(--gf-accent) !important" in css


def test_uploader_tokens_and_descendants_are_theme_aware():
    dark_css = get_design_system_css("dark")
    light_css = get_design_system_css("light")

    for css in (dark_css, light_css):
        for token in (
            "--gf-uploader-bg:", "--gf-uploader-fg:", "--gf-uploader-muted:",
            "--gf-uploader-border:", "--gf-uploader-hover-bg:",
            "--gf-uploader-hover-border:", "--gf-uploader-icon:",
            "--gf-uploader-button-bg:", "--gf-uploader-button-fg:",
        ):
            assert token in css
        for selector in (
            '[data-testid="stFileUploader"]',
            '[data-testid="stFileUploaderDropzone"]',
            '[data-testid="stFileUploaderDropzoneInstructions"]',
            '[data-testid="stFileUploader"] [data-testid="stIconMaterial"]',
            '[data-testid="stFileUploader"] button[data-testid^="stBaseButton-"]',
            '[data-testid="stFileUploader"] [data-testid="stFileUploaderFileName"]',
            '[data-testid="stFileUploader"] [data-testid="stFileUploaderFileDetails"]',
        ):
            assert selector in css
    assert "color: var(--gf-uploader-fg) !important" in light_css
    assert "color: var(--gf-uploader-muted) !important" in light_css
    assert "color: var(--gf-uploader-button-fg) !important" in light_css


def test_button_tokens_have_contrasting_foregrounds_in_both_themes():
    def luminance(hex_color):
        channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

    def contrast(first, second):
        high, low = sorted((luminance(first), luminance(second)), reverse=True)
        return (high + .05) / (low + .05)

    for tokens in (THEME_DARK, THEME_LIGHT):
        assert contrast(tokens["button_bg"], tokens["button_fg"]) >= 4.5
        assert contrast(tokens["button_hover"], tokens["button_hover_fg"]) >= 4.5
        assert contrast(tokens["button_active_bg"], tokens["button_active_fg"]) >= 4.5
        assert contrast(tokens["button_disabled_bg"], tokens["button_disabled_fg"]) >= 3.0
        assert contrast(tokens["uploader_bg"], tokens["uploader_fg"]) >= 4.5
        assert contrast(tokens["uploader_bg"], tokens["uploader_muted"]) >= 4.5
        assert contrast(tokens["uploader_button_bg"], tokens["uploader_button_fg"]) >= 4.5


def test_button_variants_and_streamlit_chrome_use_theme_tokens():
    css = get_design_system_css("light")

    for selector in (
        'button[data-testid^="btn_open_recent_"]',
        'button[data-testid^="btn_rename_recent_"]',
        'button[data-testid^="btn_delete_recent_"]',
        '[data-testid="stDeployButton"] button',
        '[data-testid="stToolbar"] button',
        'button[data-testid^="stBaseButton-"]',
        'button[data-testid="stBaseButton-primary"]',
        ".stButton > button:hover",
        ".stButton > button:active",
        ".stButton > button:disabled",
    ):
        assert selector in css
    assert ".stButton > button *" in css
    assert 'button[data-testid^="stBaseButton-"] *' in css
    assert "color: inherit !important" in css
    assert "background: var(--gf-accent-soft) !important" in css
    assert "background: var(--gf-bad-bg) !important" in css


def test_light_mode_regressions_have_light_safe_values():
    css = get_design_system_css("light")

    assert "background: var(--gf-app-bg) !important" in css
    assert "background: var(--gf-card-grad) !important" in css
    assert "background: var(--gf-grad-primary) !important" in css
    assert "color: var(--gf-button-primary-fg) !important" in css
    assert "background-image: var(--gf-grad-hero) !important" in css
    assert "background: var(--gf-selected-bg) !important" in css


def test_theme_switching_does_not_mutate_token_dictionaries():
    dark_before = dict(THEME_DARK)
    light_before = dict(THEME_LIGHT)
    get_design_system_css("light")
    get_design_system_css("dark")
    assert THEME_DARK == dark_before
    assert THEME_LIGHT == light_before