import json
import html
import re
import os

import shutil
import subprocess

from dotenv import load_dotenv
import pandas as pd
from PIL import Image
import requests
import sys
import asyncio
import uuid
import time
import streamlit as st

from ui_components import (
    get_design_system_css,
    card_open, card_close,
    studio_card_open, studio_card_close,
    badge, sys_pill, save_chip,
    project_card_html, row_card_html,
    canvas_empty, empty_state,
    section_label as ui_section_label,
    banner as ui_banner,
    ai_plan_panel,
    stage_bar,
    timeline_track_html, timeline_block_html,
)

# Force Windows to use SelectorEventLoop to prevent WinError 10054 noise
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Optional Lottie Animation Support
try:
    from streamlit_lottie import st_lottie
except ImportError:
    st_lottie = None

# Load environment variables from .env
load_dotenv()

# --- Core Agent Imports ---
from enhancer import analyze_viral_score, auto_enhance_image, auto_enhance_video
from orchestrator import get_video_metadata, run_editing_agent
from services.project_model import ProjectState, TimelineClip
from services.project_store import ProjectStore
from services.telemetry import stage_event
import timeline_logic as _tl
from services.waveform import get_waveform_peaks as _get_waveform_peaks_raw

# ── Custom timeline component — module-level import ───────────────────────────
# Importing here (at module level, inside the Streamlit script execution context)
# means declare_component() runs with a valid ScriptRunContext on EVERY rerun,
# including the first one. This registers the component in the runtime registry
# so the Starlette route handler can serve index.html for the component iframe.
# Importing inside a function would only register it when that function runs
# (e.g. only when the user navigates to Video Studio with media uploaded).
try:
    from components.timeline import (
        timeline_component as _timeline_component_func,
        component_is_available as _timeline_available,
        _COMPONENT_DIR as _TIMELINE_COMPONENT_DIR,
        _INDEX_HTML as _TIMELINE_INDEX_HTML,
    )
    _TIMELINE_COMPONENT_LOADED = True
    _TIMELINE_COMPONENT_ERROR = ""
except Exception as _tce:
    _timeline_component_func = None
    _timeline_available = lambda: False
    _TIMELINE_COMPONENT_LOADED = False
    _TIMELINE_COMPONENT_ERROR = str(_tce)
    _TIMELINE_COMPONENT_DIR = ""
    _TIMELINE_INDEX_HTML = ""

WORKSPACE_OPTIONS = [
    ":material/home: Home", ":material/videocam: Video Studio", ":material/image: Image Studio",
    ":material/hub: Campaign Swarm", ":material/star: Highlights", ":material/description: Script Studio",
    ":material/graphic_eq: Audio Tools", ":material/rocket_launch: Campaign Hub",
    ":material/cloud_upload: Publishing",
]

# --- Graceful Imports for Optional Modules ---
try:
    from image_agent import (
        run_image_agent,
        remove_image_background,
        composite_on_background,
        validate_hex_color,
    )
except ImportError:
    def run_image_agent(prompt: str, image_path: str, output_dir: str = "outputs") -> str:
        return auto_enhance_image(image_path, output_dir=output_dir)
    remove_image_background = None
    composite_on_background = None
    validate_hex_color = None

try:
    from campaign_agent import run_autonomous_campaign
except ImportError:
    def run_autonomous_campaign(
        product_name: str,
        raw_image_path: str,
        target_platform: str,
        raw_video_path: str = None,
        webhook_url: str = "",
    ) -> dict:
        return {
            "campaign_name": product_name,
            "assets": {
                "hero_image": raw_image_path,
                "promo_video": (raw_video_path if raw_video_path else raw_image_path),
            },
            "n8n_payload": {
                "event": "campaign_launch",
                "product_name": product_name,
                "platform": target_platform,
                "webhook": webhook_url or "Not Configured",
            },
            "content_schedule": [
                {"Day": 1, "Platform": target_platform, "Format": "Short Video / Teaser", "Status": "Ready"},
                {"Day": 3, "Platform": target_platform, "Format": "Feature Highlight Carousel", "Status": "Scheduled"},
                {"Day": 7, "Platform": target_platform, "Format": "Community Call-to-Action", "Status": "Draft"},
            ],
        }

try:
    from advanced_video import (
        apply_chroma_key,
        apply_clip_transition,
        apply_audio_ducking,
        apply_voiceover_to_video,
        create_tiktok_ass_subtitles,
    )
except ImportError:
    apply_chroma_key = None
    apply_clip_transition = None
    apply_audio_ducking = None
    apply_voiceover_to_video = None
    create_tiktok_ass_subtitles = None

try:
    from advanced_image import (
        smart_face_crop,
        apply_cinematic_color_grading,
        inpaint_mask_area,
    )
except ImportError:
    smart_face_crop = None
    apply_cinematic_color_grading = None
    inpaint_mask_area = None

try:
    from advanced_ai import generate_expressive_tts, generate_auto_thumbnail, VOICE_PRESETS
except ImportError:
    generate_expressive_tts = None
    generate_auto_thumbnail = None
    VOICE_PRESETS = {
        "narrator_male": "en-US-ChristopherNeural",
        "narrator_female": "en-US-AriaNeural",
        "energetic_male": "en-US-GuyNeural",
        "news_anchor": "en-GB-RyanNeural",
        "casual_female": "en-US-JennyNeural"
    }

try:
    from hackathon_features import analyze_video_emotions_and_hooks, export_omni_platform_suite
except ImportError:
    analyze_video_emotions_and_hooks = None
    export_omni_platform_suite = None

try:
    from production_features import (
        assemble_timeline,
        generate_contact_sheet,
        normalize_audio_lufs,
        trim_clip_for_timeline,
    )
except ImportError:
    assemble_timeline = None
    generate_contact_sheet = None
    normalize_audio_lufs = None
    trim_clip_for_timeline = None

try:
    from prompt_timeline import (
        PromptTimelineError,
        execute_timeline_prompt,
        parse_multi_part_directives,
        parse_multi_part_prompt,
        parse_timeline_prompt,
    )

except ImportError:
    PromptTimelineError = ValueError
    execute_timeline_prompt = None
    parse_multi_part_directives = None
    parse_multi_part_prompt = None
    parse_timeline_prompt = None

try:
    from telemetry_ui import render_agent_telemetry_live, render_media_comparison
except ImportError:
    render_agent_telemetry_live = None
    render_media_comparison = None

try:
    from studio_pages import (
        render_audio_tools_page,
        render_campaign_hub_page,
        render_highlights_page,
        render_script_page,
    )
except Exception:
    render_audio_tools_page = None
    render_campaign_hub_page = None
    render_highlights_page = None
    render_script_page = None

try:
    from publishing_pages import render_publishing_page
except Exception:
    render_publishing_page = None


# --- Streamlit Page Setup ---
st.set_page_config(
    page_title="GENFORGE OS | Autonomous Media Studio",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- CSS Theme Injection ---
# Professional editor design system: dark neutral surfaces, slightly lighter
# panels, clear borders, white/gray typography, and ONE restrained indigo
# accent reserved for the active tool, selected clip, primary action,
# progress/status, and focus states. No gradients, no glassmorphism.

def inject_premium_theme():
    """Inject the selected GENFORGE design system CSS."""
    theme = st.session_state.get("theme", "light")
    st.markdown(get_design_system_css(theme), unsafe_allow_html=True)
    # Inject button layout fix script with auto-run and retry logic
    st.markdown("""
<script>
// Function to fix button layout - can be called from console or events
window.fixProjectButtonLayout = function() {
  const hblocks = document.querySelectorAll('[data-testid="stHorizontalBlock"]');
  hblocks.forEach(hblock => {
    const buttons = hblock.querySelectorAll('button');
    const hasProjectBtn = Array.from(buttons).some(b => 
      b.textContent.includes('Open') || b.textContent.includes('Rename')
    );
    
    if (hasProjectBtn && buttons.length >= 2) {
      // Use setProperty with 'important' to override emotion CSS
      hblock.style.setProperty('display', 'flex', 'important');
      hblock.style.setProperty('flex-direction', 'row', 'important');
      hblock.style.setProperty('flex-wrap', 'nowrap', 'important');
      hblock.style.setProperty('align-items', 'center', 'important');
      hblock.style.setProperty('gap', '8px', 'important');
      hblock.style.setProperty('overflow', 'hidden', 'important');
    }
  });
};

// Attempt 1: Run on Streamlit render event
if (window.parent) {
  window.parent.document.addEventListener('streamlit:rendered', window.fixProjectButtonLayout, true);
}

// Attempt 2: Run when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', window.fixProjectButtonLayout);
} else {
  window.fixProjectButtonLayout();
}

// Attempt 3: Run continuously to catch layout changes
setInterval(window.fixProjectButtonLayout, 400);
</script>
""", unsafe_allow_html=True)


def inject_professional_overrides():
    """No-op kept for backward compatibility — design system is now in inject_premium_theme."""
    pass

# --- System & File Helpers ---

os.makedirs("uploads", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

_FFMPEG_AVAILABLE: bool | None = None  # process-lifetime capability cache

# Maximum file size accepted through save_uploaded_file.
# Streamlit's own maxUploadSize (set in docker/entrypoint.sh) is a separate
# frontend guard; this backend limit is a safety net for direct API callers
# and prevents unbounded disk/memory usage on large media.
_MAX_UPLOAD_BYTES: int = 256 * 1024 * 1024  # 256 MB


def save_uploaded_file(uploaded_file, directory: str = "uploads") -> str:
    """Store an upload under a random identity while retaining its safe extension.

    Raises ValueError for unsupported types or files that exceed _MAX_UPLOAD_BYTES.
    The caller is responsible for surface the error to the user.
    """
    if uploaded_file is None:
        raise ValueError("No uploaded file was provided.")
    extension = os.path.splitext(os.path.basename(uploaded_file.name))[1].lower()
    allowed_extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg", ".webp"}
    if extension not in allowed_extensions:
        raise ValueError(f"Unsupported upload type: {extension or 'unknown'}")
    file_size = uploaded_file.size
    if file_size is not None and file_size > _MAX_UPLOAD_BYTES:
        limit_mb = _MAX_UPLOAD_BYTES // (1024 * 1024)
        actual_mb = file_size // (1024 * 1024)
        raise ValueError(
            f"File is too large ({actual_mb} MB). "
            f"The maximum accepted upload size is {limit_mb} MB."
        )
    os.makedirs(directory, exist_ok=True)
    destination = os.path.join(directory, f"{uuid.uuid4().hex}{extension}")
    with open(destination, "wb") as file_handle:
        file_handle.write(uploaded_file.getbuffer())
    return destination

def check_ffmpeg(refresh: bool = False) -> bool:
    """Cached capability check: spawns `ffmpeg -version` at most once per process.

    Pass refresh=True (or call invalidate_ffmpeg_cache after PATH changes) to
    re-verify, so a newly missing executable is never hidden forever.
    """
    global _FFMPEG_AVAILABLE
    if _FFMPEG_AVAILABLE is None or refresh:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=10)
            _FFMPEG_AVAILABLE = True
        except Exception:
            _FFMPEG_AVAILABLE = False
    return _FFMPEG_AVAILABLE


def invalidate_ffmpeg_cache() -> None:
    global _FFMPEG_AVAILABLE
    _FFMPEG_AVAILABLE = None

def load_lottie_url(url: str):
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def init_session_state():
    defaults = {
        "rendered_output": None,
        "timeline_output": None,
        "original_input": None,
        "thumbnail_output": None,
        "contact_sheet_output": None,
        "output_type": None,
        "campaign_data": None,
        "viral_data": None,
        "omni_outputs": None,
        "vision_analysis": None,
        "bg_color_applied": None,
        "project": None,          # None = no project open; UI shows Home / project picker
        "app_mode": ":material/home: Home",
        "show_create_project_form": False,
        "project_management_notice": None,
        # Visual mode is session-scoped and intentionally defaults to light.
        "theme": "light",
        "theme_selector": "light",
        # Save-status indicator: "saved" | "saving" | "unsaved" | "failed"
        "save_status": "saved",
        "save_error": None,
        # Undo/redo: each entry is {"clip_order": [...], "trims": {...}}
        # Maximum 20 steps retained to bound memory usage.
        "edit_history": [],
        "edit_history_index": -1,
        # Phase 4 — timeline interaction state
        "playhead_position": 0.0,       # current playhead time in seconds
        "timeline_zoom": 1.0,           # 1.0 = fit, >1 = zoom in, <1 = zoom out
        "timeline_snap_enabled": True,  # snap to clip boundaries
        "editor_clip_durations": {},    # {clip_id: float} — cached probe durations
        "editor_clip_meta": {},         # {clip_id: dict} — cached MediaMetadata fields
        "editor_thumbnail_cache": {},   # {clip_id: base64_png_str}
        "editor_waveform_cache": {},    # {clip_id: list[float]} — cached waveform peaks
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _sync_theme_selection() -> None:
    """Copy the single sidebar theme control into the canonical session key."""
    selected = st.session_state.get("theme_selector", "light")
    if selected in ("dark", "light"):
        st.session_state["theme"] = selected


def _toggle_theme() -> None:
    """Toggle the canonical application theme from an event callback."""
    current = st.session_state.get("theme", "light")
    st.session_state["theme"] = "dark" if current == "light" else "light"


def _sync_theme_widget_state() -> None:
    """Align the sidebar widget before it is instantiated for this rerun."""
    st.session_state["theme_selector"] = st.session_state.get("theme", "light")


def _sync_workspace_navigation(widget_key: str) -> None:
    selected = st.session_state.get(widget_key)
    if selected in WORKSPACE_OPTIONS:
        st.session_state.app_mode = selected


def _clear_project_runtime_state() -> None:
    """Clear transient outputs so a project switch cannot leak old results."""
    for data_key in (
        "rendered_output", "timeline_output", "original_input", "thumbnail_output",
        "contact_sheet_output", "output_type", "campaign_data", "viral_data",
        "omni_outputs", "vision_analysis", "bg_color_applied",
        "editor_session_clip_order", "editor_session_trims", "editor_selected_clip",
        # Phase 4 caches — reset on project switch
        "editor_clip_durations", "editor_clip_meta", "editor_thumbnail_cache",
        "editor_waveform_cache",
        "playhead_position",
    ):
        st.session_state.pop(data_key, None)

def _inflate_timeline_from_project(project: "ProjectState") -> None:
    """Re-populate live editor session state from canonical project.timeline."""
    _tl.inflate_timeline_from_project(project.timeline, st.session_state)


def _sync_session_state_to_project(project: "ProjectState") -> None:
    """Write live editor session state back into project.timeline before save."""
    _tl.sync_session_state_to_project(st.session_state, project, TimelineClip)


# ── Phase 4: Media probe helpers ──────────────────────────────────────────────

def _probe_clip(clip_id: str, file_path: str) -> dict:
    """Return cached media metadata dict for a clip.  Never raises — returns {} on failure."""
    cache: dict = st.session_state.get("editor_clip_meta") or {}
    if clip_id in cache:
        return cache[clip_id]
    try:
        from services.media_probe import probe_media
        meta = probe_media(file_path)
        result = {
            "duration": meta.duration,
            "width": meta.width,
            "height": meta.height,
            "fps": meta.fps,
            "has_audio": meta.has_audio,
            "video_codec": meta.video_codec,
            "audio_codec": meta.audio_codec,
            "pixel_format": meta.pixel_format,
        }
    except Exception:
        result = {}
    cache[clip_id] = result
    st.session_state["editor_clip_meta"] = cache
    # Also populate the simpler durations cache
    dur_cache: dict = st.session_state.get("editor_clip_durations") or {}
    dur_cache[clip_id] = result.get("duration", 0.0)
    st.session_state["editor_clip_durations"] = dur_cache
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def _generate_thumbnail_b64(file_path: str) -> str | None:
    """Extract one keyframe thumbnail as a base64 PNG string.

    Cached by Streamlit's data cache (keyed on file_path).  Returns None
    silently on any error so a missing thumbnail never blocks the editor.
    """
    import base64
    import tempfile
    if not file_path or not os.path.isfile(file_path):
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        result = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-ss", "0", "-i", file_path,
             "-vframes", "1", "-vf", "scale=180:-2", tmp_path],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0 and os.path.isfile(tmp_path):
            with open(tmp_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            os.unlink(tmp_path)
            return data
        return None
    except Exception:
        return None


def _get_clip_thumbnail(clip_id: str, file_path: str) -> str | None:
    """Return a cached base64 thumbnail for a clip, generating if needed."""
    cache: dict = st.session_state.get("editor_thumbnail_cache") or {}
    if clip_id in cache:
        return cache[clip_id]
    thumb = _generate_thumbnail_b64(file_path)
    cache[clip_id] = thumb
    st.session_state["editor_thumbnail_cache"] = cache
    return thumb


def _get_clip_waveform(clip_id: str, file_path: str, num_peaks: int = 200) -> list | None:
    """Return cached waveform peaks for a clip.

    Calls services.waveform.get_waveform_peaks() which caches on disk and in
    memory. Returns None when extraction is not possible (no audio, no ffmpeg).
    Only called for clips that probe_media() confirmed have audio.
    """
    wf_cache: dict = st.session_state.get("editor_waveform_cache") or {}
    if clip_id in wf_cache:
        return wf_cache[clip_id] or None
    peaks = _get_waveform_peaks_raw(file_path, num_peaks=num_peaks)
    wf_cache[clip_id] = peaks if peaks else []
    st.session_state["editor_waveform_cache"] = wf_cache
    return peaks if peaks else None


# ── Phase 4: Timeline state math ─────────────────────────────────────────────

def _total_timeline_duration(clip_order: list, trims: dict, durations: dict) -> float:
    """Sum of effective clip durations — delegates to timeline_logic."""
    return _tl.total_timeline_duration(clip_order, trims, durations)


def _split_clip_at_point(
    clip_id: str,
    split_time: float,
    clip_map: dict,
    current_order: list,
    trims: dict,
    durations: dict,
) -> tuple[list, dict, dict]:
    """Split a clip at split_time seconds into the clip — delegates to timeline_logic."""
    return _tl.split_clip_at_point(clip_id, split_time, clip_map, current_order, trims, durations)


def _push_edit_history() -> None:
    """Push the current timeline state onto the undo stack (max 20 entries)."""
    _tl.push_edit_history(st.session_state)


def _undo_edit() -> bool:
    """Restore the previous timeline state. Returns True if undo was possible."""
    return _tl.undo_edit(st.session_state)


def _redo_edit() -> bool:
    """Reapply the next timeline state. Returns True if redo was possible."""
    return _tl.redo_edit(st.session_state)


def create_new_project(name: str) -> ProjectState:
    """Create and immediately persist a fresh named draft project."""
    project = ProjectState(name=name)
    st.session_state.project = project
    _clear_project_runtime_state()
    persist_project()
    st.session_state.app_mode = ":material/videocam: Video Studio"
    return project


def open_project(project_id: str) -> ProjectState:
    """Load one project through ProjectStore and make it the active workspace project."""
    project = ProjectStore().load(project_id)
    st.session_state.project = project
    _clear_project_runtime_state()
    st.session_state.app_mode = ":material/videocam: Video Studio"
    st.session_state["save_status"] = "saved"
    st.session_state["save_error"] = None
    # Phase 4: re-inflate canonical timeline into live editor session state so
    # reloading a project restores clip order and trims without needing a render.
    _inflate_timeline_from_project(project)
    return project


def rename_project(project_id: str, name: str) -> ProjectState:
    """Rename one saved project without changing its internal identity."""
    store = ProjectStore()
    project = store.load(project_id)
    renamed = ProjectState.model_validate({**project.model_dump(), "name": name})
    store.save(renamed)
    if isinstance(st.session_state.get("project"), ProjectState) and st.session_state.project.project_id == project_id:
        st.session_state.project = renamed
    return renamed


def delete_project(project_id: str) -> None:
    """Delete one project through the store and clear it if currently open."""
    ProjectStore().delete(project_id)
    current = st.session_state.get("project")
    if isinstance(current, ProjectState) and current.project_id == project_id:
        st.session_state.project = None
        _clear_project_runtime_state()
        st.session_state.app_mode = ":material/home: Home"
        st.session_state.project_management_notice = "Project deleted."
        st.session_state["save_status"] = "saved"
        st.session_state["save_error"] = None


def delete_all_projects() -> int:
    """Delete every saved project through the existing project store."""
    store = ProjectStore()
    count = store.delete_all()
    st.session_state.project = None
    _clear_project_runtime_state()
    st.session_state.app_mode = ":material/home: Home"
    st.session_state.project_management_notice = f"Deleted {count} project(s)."
    st.session_state["save_status"] = "saved"
    st.session_state["save_error"] = None
    return count

def persist_project() -> None:
    """Atomically save the active project and update the save-status indicator.

    Phase 4: also writes the live editor session state (clip order + trims)
    back into project.timeline so save/reload preserves unsaved edits.
    """
    project = st.session_state.get("project")
    if not isinstance(project, ProjectState):
        return
    st.session_state["save_status"] = "saving"
    st.session_state["save_error"] = None
    try:
        # Phase 4: sync live editor state → canonical timeline before saving
        _sync_session_state_to_project(project)
        project.touch()
        ProjectStore().save(project)
        st.session_state["save_status"] = "saved"
    except Exception as exc:
        st.session_state["save_status"] = "failed"
        st.session_state["save_error"] = str(exc)


def project_output_dir() -> str:
    """Return the active project's isolated artifact directory.

    When no project is open (project=None) a per-session fallback ID is
    generated once and stored in session_state so every call within the same
    render returns the same directory instead of creating a new orphaned
    directory on each invocation.
    """
    project = st.session_state.get("project")
    if isinstance(project, ProjectState):
        project_id = project.project_id
    else:
        # Stable fallback: reuse the same UUID for the lifetime of this session.
        if "session_output_id" not in st.session_state:
            st.session_state["session_output_id"] = uuid.uuid4().hex
        project_id = st.session_state["session_output_id"]
    output_dir = os.path.join("outputs", project_id)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def project_output_path(label: str) -> str:
    """Allocate a unique artifact path inside the active project's output directory."""
    filename = os.path.basename(label)
    if not filename or filename in {".", ".."}:
        raise ValueError("Output label must be a file name")
    return os.path.join(project_output_dir(), f"{uuid.uuid4().hex}_{filename}")


def record_project_result(source_path: str, output_path: str, analytics: dict | None = None) -> None:
    project = st.session_state.get("project")
    if not isinstance(project, ProjectState):
        # No named project is open — create a minimal one so the render
        # is not silently lost.  The user can rename it from the Home page.
        project = ProjectState(name="Untitled Project")
        st.session_state.project = project
    project.add_source(source_path)
    project.analytics = analytics
    project.add_version(output_path, analytics)
    project.telemetry.append(stage_event("render", "completed", time.time(), source_path, output_path))
    persist_project()


def record_project_settings(**settings: object) -> None:
    """Persist project-level settings (format, platform, aspect ratio, etc.).

    Call this whenever a structural pipeline choice is committed so the setting
    survives a Streamlit restart.  Settings are merged — not replaced — so
    callers only need to pass the keys that changed.
    """
    project = st.session_state.get("project")
    if not isinstance(project, ProjectState):
        return
    project.update_settings(**settings)
    persist_project()

def clear_assets():
    """Clear root-level uploaded files without destroying project output directories."""
    uploads_dir = "uploads"
    if os.path.exists(uploads_dir):
        for file in os.listdir(uploads_dir):
            fp = os.path.join(uploads_dir, file)
            try:
                if os.path.isfile(fp):
                    os.unlink(fp)
            except OSError:
                pass

    # Only clear safe data keys, not widget keys
    # Widget keys: video_up, audio_up, img_up, camp_img_up, camp_vid_up, 
    #              chroma_bg_up, transition_clip_up, mask_up (file uploaders)
    #              btn_*, *_prompt, hero_lottie (buttons, text inputs, lottie)
    safe_data_keys = [
        "rendered_output", "timeline_output", "original_input", "thumbnail_output", "contact_sheet_output",
        "output_type", "campaign_data", "viral_data", "omni_outputs", "vision_analysis",
    ]

    for k in safe_data_keys:
        if k in st.session_state:
            try:
                st.session_state[k] = None
            except Exception as e:
                print(f"[Warning] Could not clear session state key '{k}': {e}")

# --- Output Preview Monitor ---
def render_media_preview():
    """Display rendered output with professional feedback.

    - Timeline assembly shown first with download
    - Main render output with before/after comparison
    - Omni-platform tabs
    - Analytics metrics
    - Professional empty state (no balloons, no generic spinner)
    """
    timeline_path = st.session_state.get("timeline_output")
    if timeline_path and os.path.exists(timeline_path):
        with st.expander(":material/view_timeline: Timeline Assembly", expanded=False):
            st.caption("Assembled sequence before AI effects and mastering stages.")
            st.video(timeline_path)
            with open(timeline_path, "rb") as timeline_file:
                st.download_button(
                    label=":material/download: Download Timeline",
                    data=timeline_file,
                    file_name=os.path.basename(timeline_path),
                    mime="video/mp4",
                    key="download_editorial_timeline",
                )

    rendered = st.session_state.get("rendered_output")
    if rendered and os.path.exists(rendered):
        # Before/after comparison
        if st.session_state.get("original_input") and render_media_comparison:
            render_media_comparison(
                st.session_state.original_input,
                rendered,
                is_video=(st.session_state.output_type == "video"),
            )

        if st.session_state.output_type == "video":
            st.video(rendered)
            with open(rendered, "rb") as file:
                st.download_button(
                    label=":material/download: Download Master",
                    data=file,
                    file_name=os.path.basename(rendered),
                    mime="video/mp4",
                    key="download_master_video",
                )

            # Omni-platform suite
            if st.session_state.get("omni_outputs"):
                st.markdown("**Platform Variants**")
                t1, t2, t3 = st.tabs(["9:16 Vertical", "1:1 Square", "16:9 Landscape"])
                with t1:
                    st.video(st.session_state.omni_outputs.get("tiktok_9_16"))
                with t2:
                    st.video(st.session_state.omni_outputs.get("square_1_1"))
                with t3:
                    st.video(st.session_state.omni_outputs.get("youtube_16_9"))

            # Gemini vision analysis
            if st.session_state.get("vision_analysis"):
                v_ana = st.session_state.vision_analysis
                with st.expander(":material/analytics: AI Vision Analysis"):
                    c_a, c_b = st.columns(2)
                    c_a.metric("Hook Rating", v_ana.get("hook_score", "N/A"))
                    c_b.metric("Best Moment", v_ana.get("best_moment", "N/A"))
                    if v_ana.get("summary"):
                        st.info(f"**Notes:** {v_ana['summary']}")

            # Thumbnail
            if st.session_state.get("thumbnail_output") and os.path.exists(st.session_state.thumbnail_output):
                with st.expander(":material/image: Keyframe Thumbnail"):
                    st.image(st.session_state.thumbnail_output, use_container_width=True)

            # Contact sheet
            if st.session_state.get("contact_sheet_output") and os.path.exists(st.session_state.contact_sheet_output):
                with st.expander(":material/grid_view: Contact Sheet"):
                    st.image(st.session_state.contact_sheet_output, use_container_width=True)

        elif st.session_state.output_type == "image":
            st.image(rendered, use_container_width=True)
            with open(rendered, "rb") as file:
                st.download_button(
                    label=":material/download: Download Image",
                    data=file,
                    file_name=os.path.basename(rendered),
                    mime="image/png",
                    key="download_master_image",
                )

        # Analytics
        viral = st.session_state.get("viral_data")
        if viral:
            if viral.get("status") == "unavailable":
                st.caption(
                    f"⚠ AI analysis unavailable — {viral.get('reason', 'check your Gemini API key.')}"
                )
            else:
                with st.expander(":material/bar_chart: Viral Intelligence", expanded=False):
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Viral Score",  viral.get("viral_score", "N/A"))
                    m2.metric("Hook Quality", viral.get("hook_rating", "N/A"))
                    m3.metric("Audio Grade",  viral.get("audio_level", "N/A"))
                    recs = viral.get("recommendations", [])
                    if recs:
                        for rec in recs:
                            st.markdown(f"- {rec}")
    else:
        # Professional empty state — no balloons, no spinner, no generic "nothing here"
        st.markdown(
            canvas_empty(
                icon="🎬",
                title="Preview Monitor",
                hint=(
                    "Upload media in the Asset Vault, configure the pipeline, "
                    "then click Render Pipeline to see your output here."
                ),
            ),
            unsafe_allow_html=True,
        )

# --- View 1: Home — compact project launcher ---

def _time_ago(iso_timestamp: str) -> str:
    """Return a human-readable relative time string for any UTC ISO timestamp.

    Examples: "just now", "3 minutes ago", "2 hours ago", "yesterday", "5 days ago".
    Falls back to the raw date string if the timestamp cannot be parsed.
    """
    try:
        from datetime import datetime, timezone
        then = datetime.fromisoformat(iso_timestamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - then
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "just now"
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if seconds < 172800:
            return "yesterday"
        days = seconds // 86400
        return f"{days} days ago"
    except Exception:
        return iso_timestamp[:16].replace("T", " ") + " UTC"


def _list_recent_projects(limit: int | None = None) -> list[ProjectState]:
    """Return saved projects from the store, newest first."""
    projects = ProjectStore().list_projects()
    return projects[:limit] if limit else projects


def render_welcome_hero():
    """Home workspace — project launcher, recent projects, recent renders."""
    # ── Hero ─────────────────────────────────────────────────────
    st.markdown(
        "<div class='gf-hero' style='padding:8px 0 4px;'>"
        "<div class='gf-hero-title'>Studio Projects</div>"
        "<div class='gf-hero-sub'>"
        "Your creative workspace — open a project to start editing, or create a new one."
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    recent_projects = _list_recent_projects()

    # ── Post-action notice (project created / deleted) ───────────
    if st.session_state.get("project_management_notice"):
        st.markdown(
            ui_banner(st.session_state.project_management_notice, "ok", "✓"),
            unsafe_allow_html=True,
        )
        st.session_state.project_management_notice = None

    action_col, history_col = st.columns([1.0, 1.6], gap="medium")

    # ══════════════════════════════════════════════════════════════
    # LEFT — create / open actions
    # ══════════════════════════════════════════════════════════════
    with action_col:
        # New Project card with accent top bar
        st.markdown(
            "<div class='gf-card-accent' style='margin-bottom:12px;'>"
            "<div style='font-size:.94rem;font-weight:700;color:var(--gf-fg);letter-spacing:-.02em;margin-bottom:3px;'>"
            "New Project</div>"
            "<div style='font-size:.73rem;color:var(--gf-muted);margin-bottom:12px;'>Start fresh with a named project</div>",
            unsafe_allow_html=True,
        )

        if st.button(":material/add: New Project", key="btn_new_project", type="primary",
                     help="Create a new named project"):
            st.session_state.show_create_project_form = True
            st.rerun()

        if st.session_state.get("show_create_project_form"):
            create_submitted = False
            cancel_create = False
            with st.form("create_project_form"):
                project_name = st.text_input(
                    "Project name",
                    key="new_project_name",
                    placeholder="My YouTube Channel",
                    help="Use a descriptive name — you can rename it later.",
                )
                create_col, cancel_col = st.columns(2)
                with create_col:
                    create_submitted = st.form_submit_button(
                        ":material/check: Create Project", type="primary"
                    )
                with cancel_col:
                    cancel_create = st.form_submit_button(":material/close: Cancel")
            if cancel_create:
                st.session_state.show_create_project_form = False
                st.rerun()
            if create_submitted:
                if not project_name or not project_name.strip():
                    st.error("Project name cannot be empty.")
                else:
                    try:
                        create_new_project(project_name)
                        st.session_state.show_create_project_form = False
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

        st.markdown(card_close(), unsafe_allow_html=True)

        # ── Open existing project ────────────────────────────────
        st.markdown(card_open("Open Project", "Continue editing"), unsafe_allow_html=True)

        if recent_projects:
            valid_ids = [p.project_id for p in recent_projects]
            if st.session_state.get("home_open_project_select") not in valid_ids:
                st.session_state.home_open_project_select = valid_ids[0]
            open_choice = st.selectbox(
                "Select project",
                options=valid_ids,
                format_func=lambda pid: next(
                    (f"{p.name} · {_time_ago(p.updated_at)}"
                     for p in recent_projects if p.project_id == pid),
                    pid,
                ),
                key="home_open_project_select",
                label_visibility="collapsed",
            )
            if st.button(":material/folder_open: Open", key="btn_open_project",
                         type="primary"):
                try:
                    open_project(open_choice)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not open project: {exc}")
        else:
            st.caption("No projects yet — create your first one above.")

        st.markdown(card_close(), unsafe_allow_html=True)

        # ── Project Management (destructive, in expander) ────────
        with st.expander(":material/settings: Manage Projects", expanded=False):
            st.caption(
                "Project deletion is permanent. "
                "Localhost and ngrok share the same `projects/` directory."
            )
            if recent_projects:
                n = len(recent_projects)
                st.warning(
                    f"Delete all {n} project{'s' if n != 1 else ''}? This cannot be undone."
                )
                delete_all_confirm = st.checkbox(
                    "I understand all saved projects will be permanently deleted",
                    key="confirm_delete_all",
                )
                if st.button(
                    ":material/delete_forever: Delete All Projects",
                    key="btn_delete_all",
                    disabled=not delete_all_confirm,
                ):
                    delete_all_projects()
                    st.rerun()
            else:
                st.caption("No projects to manage.")

    # ══════════════════════════════════════════════════════════════
    # RIGHT — recent projects grid
    # ══════════════════════════════════════════════════════════════
    with history_col:
        st.markdown(card_open("Recent Projects"), unsafe_allow_html=True)
        project_query = st.text_input(
            "Search projects",
            key="project_search",
            placeholder="Search by project name or ID",
            label_visibility="collapsed",
        ).strip().lower()
        visible_projects = [
            project for project in recent_projects
            if not project_query
            or project_query in project.name.lower()
            or project_query in project.project_id.lower()
        ]

        if visible_projects:
            for project in visible_projects[:6]:
                detail = (
                    f"Updated {_time_ago(project.updated_at)} · "
                    f"{len(project.source_assets)} source{'s' if len(project.source_assets) != 1 else ''} · "
                    f"{len(project.timeline)} clip{'s' if len(project.timeline) != 1 else ''} · "
                    f"{len(project.outputs)} render{'s' if len(project.outputs) != 1 else ''}"
                )
                # Unified project card: one clean HTML block for all display content,
                # followed immediately by a tight action button row.
                _status_lower = project.status.lower()
                if _status_lower == "ready":
                    _badge_html = badge("READY", "ok")
                elif _status_lower == "failed":
                    _badge_html = badge("FAILED", "err")
                elif _status_lower == "processing":
                    _badge_html = badge("PROCESSING", "warn")
                else:
                    _badge_html = badge(project.status.upper(), "draft")

                # Single self-contained card HTML — no split across multiple st.markdown calls
                st.markdown(
                    f"<div class='gf-project-card-wrap'>"
                    f"<div class='gf-pcard-left'>"
                    f"<div class='gf-pcard-icon'>🎬</div>"
                    f"<div class='gf-pcard-meta'>"
                    f"<div class='gf-pcard-name'>{html.escape(project.name)}</div>"
                    f"<div class='gf-pcard-detail'>{html.escape(detail)}</div>"
                    f"</div>"
                    f"</div>"
                    f"<div class='gf-pcard-right'>"
                    f"{_badge_html}"
                    f"<span class='gf-pcard-id'>{project.project_id[:8]}</span>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                # Action row: [Open][Rename][···spacer···][Delete]
                # use_container_width=True makes each button fill its column fully.
                _col_open, _col_rename, _col_spacer, _col_delete = st.columns(
                    [1.2, 1.5, 4.0, 1.2], gap="small"
                )
                with _col_open:
                    open_recent = st.button(
                        ":material/folder_open: Open",
                        key=f"btn_open_recent_{project.project_id}",
                        help="Open this project in the editor",
                        use_container_width=True,
                    )
                with _col_rename:
                    rename_recent = st.button(
                        ":material/edit: Rename",
                        key=f"btn_rename_recent_{project.project_id}",
                        help="Rename this project",
                        use_container_width=True,
                    )
                with _col_delete:
                    delete_recent = st.button(
                        ":material/delete: Delete",
                        key=f"btn_delete_recent_{project.project_id}",
                        help="Permanently delete this project",
                        use_container_width=True,
                    )

                if open_recent:
                    try:
                        open_project(project.project_id)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not open project: {exc}")

                if rename_recent:
                    st.session_state[f"rename_project_{project.project_id}"] = True
                    st.rerun()
                if st.session_state.get(f"rename_project_{project.project_id}"):
                    with st.form(f"rename_form_{project.project_id}"):
                        renamed = st.text_input(
                            "New name", value=project.name,
                            key=f"rename_name_{project.project_id}",
                        )
                        r_save, r_cancel = st.columns(2)
                        with r_save:
                            save_rename = st.form_submit_button(":material/check: Save", type="primary")
                        with r_cancel:
                            cancel_rename = st.form_submit_button(":material/close: Cancel")
                    if cancel_rename:
                        st.session_state.pop(f"rename_project_{project.project_id}", None)
                        st.rerun()
                    if save_rename:
                        try:
                            rename_project(project.project_id, renamed)
                            st.session_state.pop(f"rename_project_{project.project_id}", None)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

                if delete_recent:
                    st.session_state[f"delete_project_{project.project_id}"] = True
                    st.rerun()
                if st.session_state.get(f"delete_project_{project.project_id}"):
                    st.warning(f'**Delete "{html.escape(project.name)}"?** This cannot be undone.')
                    confirm_delete = st.checkbox(
                        "I understand this permanently deletes the project",
                        key=f"confirm_delete_{project.project_id}",
                    )
                    confirm_col, cancel_col = st.columns(2)
                    with confirm_col:
                        delete_confirmed = st.button(
                            ":material/delete_forever: Delete",
                            key=f"confirm_delete_btn_{project.project_id}",
                            disabled=not confirm_delete,
                        )
                    with cancel_col:
                        cancel_delete = st.button(
                            ":material/close: Cancel",
                            key=f"cancel_delete_{project.project_id}",
                        )
                    if cancel_delete:
                        st.session_state.pop(f"delete_project_{project.project_id}", None)
                        st.rerun()
                    if delete_confirmed:
                        delete_project(project.project_id)
                        st.rerun()
        elif recent_projects:
            st.markdown(
                empty_state(
                    "⌕",
                    "No matching projects",
                    "Try a different name or project ID.",
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                empty_state(
                    "🎬",
                    "No projects yet",
                    "Create your first project to start editing and saving your work.",
                ),
                unsafe_allow_html=True,
            )

        st.markdown(card_close(), unsafe_allow_html=True)

    # ── Recent renders ───────────────────────────────────────────
    renders = []
    for project in recent_projects:
        for version in project.outputs:
            renders.append((version.created_at, project.project_id, version))
    renders.sort(key=lambda item: item[0], reverse=True)

    if renders:
        st.markdown(card_open("Recent Renders"), unsafe_allow_html=True)
        for created_at, project_id, version in renders[:4]:
            exists = os.path.exists(version.output_path)
            status_var = "ok" if (version.status == "rendered" and exists) else "err"
            status_label = version.status.upper() if exists else "MISSING"
            st.markdown(
                row_card_html(
                    title=os.path.basename(version.output_path),
                    subtitle=f"{_time_ago(created_at)} · project {project_id[:8]}",
                    status_label=status_label,
                    status_variant=status_var,
                    right_note="on disk" if exists else "file missing",
                ),
                unsafe_allow_html=True,
            )
        st.markdown(card_close(), unsafe_allow_html=True)

# --- Time Ruler ---
def _render_time_ruler(total_dur: float, playhead_pos: float, zoom: float, n_clips: int) -> None:
    """Render a proportional time ruler with tick marks and playhead marker.

    Tick density adapts to total duration and zoom level.
    Shows a small ▼ playhead triangle at the current playhead position.
    """
    if total_dur <= 0:
        # Structural ruler when no durations are known
        st.markdown(
            f"<div class='gf-timeline-ruler'>"
            f"<span>IN</span>"
            f"<span>SEQUENCE · {n_clips} CLIP{'S' if n_clips != 1 else ''}</span>"
            f"<span>OUT</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    # Choose tick interval based on zoom and duration
    effective_dur = total_dur / zoom
    if effective_dur <= 10:
        tick_s = 1
    elif effective_dur <= 30:
        tick_s = 2
    elif effective_dur <= 60:
        tick_s = 5
    elif effective_dur <= 120:
        tick_s = 10
    elif effective_dur <= 300:
        tick_s = 30
    elif effective_dur <= 600:
        tick_s = 60
    else:
        tick_s = 120

    n_ticks = max(2, int(total_dur / tick_s) + 2)
    ticks_html = ""
    for i in range(n_ticks):
        t = i * tick_s
        if t > total_dur + tick_s:
            break
        pct = min(100.0, t / total_dur * 100)
        label = _fmt_time(t)
        ticks_html += (
            f"<div class='gf-ruler-tick' style='left:{pct:.2f}%;'>"
            f"<span>{label}</span></div>"
        )

    # Playhead marker on ruler
    ph_pct = min(100.0, playhead_pos / total_dur * 100)
    ph_marker = (
        f"<div class='gf-ruler-playhead' style='left:{ph_pct:.2f}%;' "
        f"title='Playhead: {_fmt_time(playhead_pos)}'>▼</div>"
    )

    total_label = _fmt_time(total_dur)
    st.markdown(
        f"<div class='gf-ruler-wrap'>"
        f"{ticks_html}"
        f"{ph_marker}"
        f"<div class='gf-ruler-total'>{total_label}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# --- Editor Timeline ---
def render_editor_timeline(uploaded_video, timeline_files):
    """Phase 5 interactive editor timeline.

    Uses the custom timeline component for:
    - Drag-and-drop clip reordering
    - Left/right trim handle dragging
    - Ruler playhead scrubbing
    - Split / duplicate / delete / reset / zoom in the component UI

    Falls back to the pure-HTML/button layout if the component cannot load
    (e.g. first render before component has registered). The rich inspector
    (Phase 4) is kept alongside the component for precise numeric control.
    """
    if not uploaded_video and not timeline_files:
        st.info("Upload a primary video and at least one additional clip to build the timeline.")
        return [], {}

    # ── Custom timeline component ──────────────────────────────────────────────
    # Module-level import (at top of app.py) registered the component.
    # Here we just check availability and use the pre-imported handles.
    _has_component = _TIMELINE_COMPONENT_LOADED and _timeline_available()
    _component_error = _TIMELINE_COMPONENT_ERROR if not _TIMELINE_COMPONENT_LOADED else (
        f"Frontend index.html missing at {_TIMELINE_INDEX_HTML}" if not _timeline_available() else ""
    )

    # ── Build clip_map ────────────────────────────────────────────────────────
    clip_map: dict = {}
    clip_files: dict = {}
    if uploaded_video:
        primary_id = f"primary::{uploaded_video.name}"
        clip_map[primary_id] = {"id": primary_id, "label": uploaded_video.name, "role": "Primary"}
        clip_files[primary_id] = uploaded_video
    for index, uploaded_clip in enumerate(timeline_files or []):
        clip_id = f"clip::{index}::{uploaded_clip.name}"
        clip_map[clip_id] = {"id": clip_id, "label": uploaded_clip.name, "role": "Clip"}
        clip_files[clip_id] = uploaded_clip

    available_ids = list(clip_map.keys())

    # ── Restore / merge session clip order ────────────────────────────────────
    current_order = available_ids.copy()
    prev_order = st.session_state.get("editor_session_clip_order", [])
    if prev_order and all(
        cid in clip_map or cid.startswith(("dup::", "split_a::", "split_b::", "canonical::"))
        for cid in prev_order
    ):
        current_order = [cid for cid in prev_order if cid in clip_map] + \
                        [cid for cid in available_ids if cid not in prev_order]

    # ── Restore trims ─────────────────────────────────────────────────────────
    trims: dict = {}
    prev_trims = st.session_state.get("editor_session_trims", {})
    for clip_id in list(clip_map.keys()):
        trims[clip_id] = prev_trims.get(clip_id, {"start": 0.0, "end": 0.0})

    # ── Probe real durations ──────────────────────────────────────────────────
    for clip_id, f in clip_files.items():
        if clip_id not in (st.session_state.get("editor_clip_durations") or {}):
            try:
                path = save_uploaded_file(f)
                trims[clip_id]["source_path"] = path
                _probe_clip(clip_id, path)
            except Exception:
                pass
    durations: dict = st.session_state.get("editor_clip_durations") or {}

    # ── Per-clip effective duration helper ────────────────────────────────────
    def _clip_effective_dur(cid: str):
        trim = trims.get(cid, {})
        t_s = float(trim.get("start", 0.0))
        t_e = float(trim.get("end", 0.0))
        real = durations.get(cid, 0.0)
        if t_e > t_s:
            return t_e - t_s
        elif real > 0:
            return max(real - t_s, 0.0)
        return None

    total_dur   = _total_timeline_duration(current_order, trims, durations)
    n_clips     = len(current_order)
    playhead_pos = float(st.session_state.get("playhead_position", 0.0))
    zoom         = float(st.session_state.get("timeline_zoom", 1.0))

    # ── Timeline header ───────────────────────────────────────────────────────
    hdr_l, hdr_r = st.columns([3, 2])
    with hdr_l:
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:8px;padding:4px 0;'>"
            f"<span class='gf-section-label' style='margin:0;'>Timeline</span>"
            f"<span class='gf-tl-badge'>{n_clips} clip{'s' if n_clips != 1 else ''}</span>"
            f"{'<span class=\'gf-tl-badge gf-tl-badge-dur\'>' + _fmt_time(total_dur) + '</span>' if total_dur > 0 else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with hdr_r:
        zoom_c, snap_c = st.columns([2, 1])
        with zoom_c:
            new_zoom = st.select_slider(
                "Zoom", options=[0.5, 1.0, 1.5, 2.0, 3.0],
                value=zoom,
                label_visibility="collapsed",
                format_func=lambda v: "Fit" if v == 1.0 else f"×{v}",
            )
            if new_zoom != zoom:
                zoom = new_zoom
                st.session_state["timeline_zoom"] = zoom
        with snap_c:
            st.toggle("Snap", value=st.session_state.get("timeline_snap_enabled", True),
                      key="timeline_snap_enabled")

    # ── Build clip data for component ─────────────────────────────────────────
    thumb_cache: dict = st.session_state.get("editor_thumbnail_cache") or {}
    meta_cache:  dict = st.session_state.get("editor_clip_meta") or {}
    wf_cache:    dict = st.session_state.get("editor_waveform_cache") or {}
    snap_on: bool = bool(st.session_state.get("timeline_snap_enabled", True))

    component_clips = []
    for clip_id in current_order:
        if clip_id not in clip_map:
            continue
        clip  = clip_map[clip_id]
        trim  = trims.get(clip_id, {"start": 0.0, "end": 0.0})
        src   = trim.get("source_path", "")
        meta  = meta_cache.get(clip_id, {})
        has_audio = bool(meta.get("has_audio", False))

        # Trigger thumbnail if not yet cached
        if clip_id not in thumb_cache and src and os.path.isfile(src):
            _get_clip_thumbnail(clip_id, src)

        # Waveform peaks — only for clips with confirmed audio streams
        waveform_peaks = None
        if has_audio and src and os.path.isfile(src):
            if clip_id not in wf_cache:
                # Trigger extraction (cached on disk — fast after first run)
                waveform_peaks = _get_clip_waveform(clip_id, src, num_peaks=200)
            else:
                cached = wf_cache.get(clip_id)
                waveform_peaks = cached if cached else None

        component_clips.append({
            "id":             clip_id,
            "label":          clip.get("label", clip_id),
            "role":           clip.get("role", "Clip"),
            "duration":       float(durations.get(clip_id, 0.0)),
            "trim_start":     float(trim.get("start", 0.0)),
            "trim_end":       float(trim.get("end", 0.0)),
            "thumbnail_b64":  thumb_cache.get(clip_id),
            "has_audio":      has_audio,
            "waveform_peaks": waveform_peaks,
            "transition":     trim.get("transition") or clip.get("transition"),
        })

    selected_now = st.session_state.get("editor_selected_clip")
    if selected_now not in current_order:
        selected_now = current_order[0] if current_order else None

    # ── Render interactive component OR fallback ──────────────────────────────
    comp_result = None
    if _has_component and component_clips:
        comp_result = _timeline_component_func(
            clips=component_clips,
            selected=selected_now,
            playhead=playhead_pos,
            zoom=zoom,
            snap_on=snap_on,
            theme=st.session_state.get("theme", "light"),
            height=260,
            key="genforge_timeline_v1",
        )
    else:
        # Fallback: Phase 4 HTML-only display.
        # Shows a developer-readable diagnostic so the fallback is never silent.
        if _component_error:
            st.caption(
                f":material/warning: Timeline component unavailable — {_component_error}. "
                f"Using HTML fallback."
            )
        _render_time_ruler(total_dur, playhead_pos, zoom, n_clips)
        blocks_html = []
        for position, clip_id in enumerate(current_order, start=1):
            if clip_id not in clip_map:
                continue
            clip = clip_map[clip_id]
            eff_dur = _clip_effective_dur(clip_id)
            dur_label = f"{eff_dur:.1f}s" if eff_dur is not None else "full"
            sel = " selected" if clip_id == selected_now else ""
            blocks_html.append(
                f"<div class='gf-timeline-block{sel}' role='listitem' "
                f"aria-selected='{'true' if sel else 'false'}'>"
                f"<strong>{position:02d}</strong>"
                f"<span>{html.escape(clip['label'])}</span>"
                f"<small style='display:flex;justify-content:space-between;'>"
                f"<span>{html.escape(clip['role'])}</span>"
                f"<span style='color:{'var(--gf-accent)' if sel else 'var(--gf-faint)'};font-weight:700;'>{dur_label}</span>"
                f"</small></div>"
            )
        st.markdown(
            f"<div class='gf-timeline-track' role='list' aria-label='Timeline clips'>"
            + "".join(blocks_html) + "</div>",
            unsafe_allow_html=True,
        )

    # ── Process component events ──────────────────────────────────────────────
    if comp_result and isinstance(comp_result, dict):
        event    = comp_result.get("event", "")
        clip_id  = comp_result.get("clip_id")
        value    = comp_result.get("value")
        new_order = comp_result.get("order", current_order)
        new_trims = comp_result.get("trims", {})
        new_sel   = comp_result.get("selected", selected_now)
        new_ph    = comp_result.get("playhead", playhead_pos)
        new_zoom  = comp_result.get("zoom", zoom)

        rerun_needed = False

        if event in ("reorder", "delete", "duplicate") and new_order != current_order:
            _push_edit_history()
            # Rebuild clip_map for any component-created IDs (dup)
            for cid in new_order:
                if cid not in clip_map:
                    # Find the source this was duplicated from
                    base = cid.rsplit("__dup__", 1)[0]
                    if base in clip_map:
                        clip_map[cid] = dict(clip_map[base])
                        clip_map[cid]["id"] = cid
                        clip_map[cid]["label"] = clip_map[base]["label"] + " (copy)"
            current_order = [cid for cid in new_order if cid in clip_map]
            rerun_needed = True

        if event == "trim" and clip_id and isinstance(value, dict):
            _push_edit_history()
            if clip_id in trims:
                trims[clip_id]["start"] = float(value.get("trim_start", trims[clip_id].get("start", 0.0)))
                trims[clip_id]["end"]   = float(value.get("trim_end",   trims[clip_id].get("end",   0.0)))
            rerun_needed = True

        if event == "select" and clip_id and clip_id in current_order:
            new_sel = clip_id

        if event == "split" and clip_id and value is not None:
            try:
                _push_edit_history()
                new_o, new_t, clip_map = _split_clip_at_point(
                    clip_id, float(value), clip_map, current_order, trims, durations
                )
                current_order = new_o
                trims = {**trims, **new_t}
                new_sel = None
                rerun_needed = True
            except ValueError as e:
                st.error(f"Split failed: {e}")

        if event == "reset":
            _push_edit_history()
            current_order = available_ids.copy()
            rerun_needed = True

        if event == "playhead":
            st.session_state["playhead_position"] = float(new_ph)
            playhead_pos = float(new_ph)

        # Apply new trims from component for non-trim events (reorder preserves trims)
        if event in ("reorder",) and new_trims:
            for cid, t in new_trims.items():
                if cid in trims:
                    trims[cid]["start"] = float(t.get("start", trims[cid].get("start", 0.0)))
                    trims[cid]["end"]   = float(t.get("end",   trims[cid].get("end",   0.0)))

        # Sync selection and zoom back
        st.session_state["editor_selected_clip"] = new_sel
        st.session_state["timeline_zoom"]         = float(new_zoom)
        selected_now = new_sel

        # Handle new Phase 6 events
        if event == "zoom":
            st.session_state["timeline_zoom"] = float(new_zoom)
            zoom = float(new_zoom)
            # Zoom changes don't require a rerun — component manages its own display

        if event == "snap_toggle":
            st.session_state["timeline_snap_enabled"] = bool(value) if value is not None else True

        if event == "select_transition":
            # Transition selected — just update selection; inspector shows details
            if clip_id and clip_id in current_order:
                new_sel = clip_id
                st.session_state["editor_selected_clip"] = new_sel
                selected_now = new_sel

        if rerun_needed:
            st.session_state["editor_session_clip_order"] = current_order
            st.session_state["editor_session_trims"] = trims
            st.session_state["save_status"] = "unsaved"
            st.rerun()

    # ── Clip selector (fallback selectbox for keyboard nav) ───────────────────
    selected_id = st.selectbox(
        "Selected clip",
        options=current_order,
        format_func=lambda cid: (
            f"{current_order.index(cid) + 1:02d} · {clip_map.get(cid, {}).get('label', cid)}"
            f" [{clip_map.get(cid, {}).get('role', '')}]"
        ),
        key="editor_selected_clip",
        label_visibility="collapsed",
        index=current_order.index(selected_now) if selected_now in current_order else 0,
    )
    selected_index = current_order.index(selected_id)

    # ── Fallback op toolbar (kept for keyboard and accessibility) ─────────────
    op_cols = st.columns([1, 1, 1, 1, 1, 1, 2])
    with op_cols[0]:
        if st.button(":material/arrow_back:", disabled=selected_index == 0,
                     key="editor_move_left", help="Move clip earlier (←)"):
            _push_edit_history()
            current_order[selected_index - 1], current_order[selected_index] = (
                current_order[selected_index], current_order[selected_index - 1])
            st.session_state["editor_session_clip_order"] = current_order
            st.rerun()
    with op_cols[1]:
        if st.button(":material/arrow_forward:", disabled=selected_index == len(current_order) - 1,
                     key="editor_move_right", help="Move clip later (→)"):
            _push_edit_history()
            current_order[selected_index + 1], current_order[selected_index] = (
                current_order[selected_index], current_order[selected_index + 1])
            st.session_state["editor_session_clip_order"] = current_order
            st.rerun()
    with op_cols[2]:
        if st.button(":material/content_copy:", key="editor_duplicate_clip",
                     help="Duplicate", disabled=len(current_order) >= 12):
            _push_edit_history()
            new_id = f"dup::{selected_id}::{len(current_order)}"
            clip_map[new_id] = {**clip_map[selected_id], "id": new_id,
                                 "label": clip_map[selected_id]["label"] + " (copy)"}
            current_order.insert(selected_index + 1, new_id)
            trims[new_id] = dict(trims.get(selected_id, {"start": 0.0, "end": 0.0}))
            st.session_state["editor_session_clip_order"] = current_order
            st.session_state["editor_session_trims"] = trims
            st.rerun()
    with op_cols[3]:
        if st.button(":material/delete:", key="editor_delete_clip",
                     help="Delete (Del)", disabled=len(current_order) <= 1):
            _push_edit_history()
            current_order.pop(selected_index)
            trims.pop(selected_id, None)
            st.session_state["editor_session_clip_order"] = current_order
            st.session_state["editor_session_trims"] = trims
            st.session_state.pop("editor_selected_clip", None)
            st.rerun()
    with op_cols[4]:
        clip_dur = _clip_effective_dur(selected_id)
        can_split = clip_dur is not None and clip_dur > 0.2 and durations.get(selected_id, 0.0) > 0
        split_time = max(0.0, playhead_pos - sum(
            _clip_effective_dur(cid) or 0.0 for cid in current_order[:selected_index]
        ))
        if st.button(":material/content_cut:", key="editor_split_clip",
                     help=f"Split at playhead ({_fmt_time(split_time)} into clip)",
                     disabled=not can_split):
            try:
                _push_edit_history()
                new_o, new_t, clip_map = _split_clip_at_point(
                    selected_id, split_time, clip_map, current_order, trims, durations)
                st.session_state["editor_session_clip_order"] = new_o
                st.session_state["editor_session_trims"] = new_t
                st.session_state.pop("editor_selected_clip", None)
                st.rerun()
            except ValueError as e:
                st.error(f"Cannot split: {e}")
    with op_cols[5]:
        if st.button(":material/restart_alt:", key="editor_reset_order", help="Reset order"):
            _push_edit_history()
            st.session_state["editor_session_clip_order"] = available_ids
            st.rerun()

    # ── Rich clip inspector (Phase 4 — precise numeric trim controls) ─────────
    meta = meta_cache.get(selected_id, {})
    real_dur = durations.get(selected_id, 0.0)
    eff_dur_val = _clip_effective_dur(selected_id)
    trim_data = trims.get(selected_id, {"start": 0.0, "end": 0.0})
    src_path  = trim_data.get("source_path", "")
    fps_str   = f"{meta['fps']:.2f} fps" if meta.get("fps") else "—"
    dim_str   = f"{meta['width']}×{meta['height']}" if meta.get("width") else "—"
    audio_str = "Yes" if meta.get("has_audio") else ("No" if meta else "—")
    codec_str = meta.get("video_codec", "—") or "—"
    src_name  = os.path.basename(src_path) if src_path else clip_map.get(selected_id, {}).get("label", "—")
    pos_str   = f"{current_order.index(selected_id) + 1} of {n_clips}"
    real_dur_s = f"{real_dur:.2f}s" if real_dur > 0 else "—"
    eff_dur_s  = f"{eff_dur_val:.2f}s" if eff_dur_val is not None else "full"

    st.markdown(
        f"<div class='gf-inspector'>"
        f"<div class='gf-inspector-header'>"
        f"<span class='gf-inspector-title'>Inspector</span>"
        f"<span class='gf-inspector-clip'>"
        f"{html.escape(clip_map.get(selected_id, {}).get('label', selected_id))}</span>"
        f"</div>"
        f"<div class='gf-inspector-grid'>"
        f"<span class='gf-inspector-key'>Position</span>"
        f"<span class='gf-inspector-val'>{pos_str}</span>"
        f"<span class='gf-inspector-key'>Source dur</span>"
        f"<span class='gf-inspector-val'>{real_dur_s}</span>"
        f"<span class='gf-inspector-key'>Active dur</span>"
        f"<span class='gf-inspector-val'>{eff_dur_s}</span>"
        f"<span class='gf-inspector-key'>Dimensions</span>"
        f"<span class='gf-inspector-val'>{dim_str}</span>"
        f"<span class='gf-inspector-key'>Frame rate</span>"
        f"<span class='gf-inspector-val'>{fps_str}</span>"
        f"<span class='gf-inspector-key'>Codec</span>"
        f"<span class='gf-inspector-val'>{codec_str}</span>"
        f"<span class='gf-inspector-key'>Audio</span>"
        f"<span class='gf-inspector-val'>{audio_str}</span>"
        f"<span class='gf-inspector-key'>Source</span>"
        f"<span class='gf-inspector-val' title='{html.escape(src_path)}'>"
        f"{html.escape(src_name)}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Trim number inputs (complement to drag handles for precision)
    old_trim = trims.get(selected_id, {"start": 0.0, "end": 0.0})
    max_val  = max(real_dur, old_trim.get("end", 0.0), 9999.0)
    trim_l, trim_r = st.columns(2)
    with trim_l:
        trim_start = st.number_input(
            "Trim in (s)", min_value=0.0, max_value=float(max_val),
            value=float(old_trim.get("start", 0.0)), step=0.1,
            key=f"timeline_trim_start_{selected_id}",
            help="In-point: 0 = beginning of clip",
        )
    with trim_r:
        trim_end = st.number_input(
            "Trim out (s)", min_value=0.0, max_value=float(max_val),
            value=float(old_trim.get("end", 0.0)), step=0.1,
            key=f"timeline_trim_end_{selected_id}",
            help="Out-point: 0 = use full clip",
        )

    if trim_end > 0 and trim_end <= trim_start:
        st.error("Trim out must be greater than trim in.")
    elif trim_end > trim_start:
        st.markdown(
            f"<div class='gf-inspector-dur-ok'>Active: {trim_end - trim_start:.2f}s</div>",
            unsafe_allow_html=True,
        )
    elif trim_start > 0 and real_dur > 0:
        st.markdown(
            f"<div class='gf-inspector-dur-warn'>Starts at {trim_start:.1f}s · "
            f"{max(real_dur - trim_start, 0):.1f}s remaining</div>",
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    if old_trim.get("start") != trim_start or old_trim.get("end") != trim_end:
        _push_edit_history()

    trims[selected_id] = {
        **trims.get(selected_id, {}),
        "start": float(trim_start),
        "end":   float(trim_end),
    }

    # ── Persist ───────────────────────────────────────────────────────────────
    st.session_state["editor_session_clip_order"] = current_order
    st.session_state["editor_session_trims"]      = trims
    return current_order, trims
    if not uploaded_video and not timeline_files:
        st.info("Upload a primary video and at least one additional clip to build the timeline.")
        return [], {}

    # ── Build clip_map ────────────────────────────────────────────────────────
    clip_map = {}
    clip_files: dict[str, object] = {}  # clip_id → UploadedFile (for preview)
    if uploaded_video:
        primary_id = f"primary::{uploaded_video.name}"
        clip_map[primary_id] = {"id": primary_id, "label": uploaded_video.name, "role": "Primary"}
        clip_files[primary_id] = uploaded_video
    for index, uploaded_clip in enumerate(timeline_files or []):
        clip_id = f"clip::{index}::{uploaded_clip.name}"
        clip_map[clip_id] = {"id": clip_id, "label": uploaded_clip.name, "role": "Clip"}
        clip_files[clip_id] = uploaded_clip

    available_ids = list(clip_map.keys())

    # ── Restore / merge session clip order ───────────────────────────────────
    current_order = available_ids.copy()
    prev_order = st.session_state.get("editor_session_clip_order", [])
    if prev_order and all(cid in clip_map or cid.startswith(("dup::", "split_a::", "split_b::")) for cid in prev_order):
        # Keep any duplicated/split clips that exist in clip_map
        current_order = [cid for cid in prev_order if cid in clip_map] + \
                        [cid for cid in available_ids if cid not in prev_order]

    # ── Restore trims ─────────────────────────────────────────────────────────
    trims: dict = {}
    prev_trims = st.session_state.get("editor_session_trims", {})
    for clip_id in list(clip_map.keys()):
        if clip_id in prev_trims:
            trims[clip_id] = prev_trims[clip_id]
        else:
            trims[clip_id] = {"start": 0.0, "end": 0.0}

    # ── Probe real durations (cached — no blocking on rerun) ──────────────────
    for clip_id, f in clip_files.items():
        if clip_id not in (st.session_state.get("editor_clip_durations") or {}):
            try:
                path = save_uploaded_file(f)
                # Save path into the trim dict so persist_project() can write it
                trims[clip_id]["source_path"] = path
                _probe_clip(clip_id, path)
            except Exception:
                pass
    durations: dict = st.session_state.get("editor_clip_durations") or {}

    # ── Build per-clip display data ───────────────────────────────────────────
    def _clip_effective_dur(clip_id: str) -> float | None:
        trim = trims.get(clip_id, {})
        t_s = float(trim.get("start", 0.0))
        t_e = float(trim.get("end", 0.0))
        real = durations.get(clip_id, 0.0)
        if t_e > t_s:
            return t_e - t_s
        elif real > 0:
            return max(real - t_s, 0.0)
        return None

    total_dur = _total_timeline_duration(current_order, trims, durations)
    n_clips = len(current_order)
    playhead_pos = float(st.session_state.get("playhead_position", 0.0))
    zoom = float(st.session_state.get("timeline_zoom", 1.0))

    # ── Timeline section header ───────────────────────────────────────────────
    hdr_l, hdr_r = st.columns([3, 2])
    with hdr_l:
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:8px;padding:4px 0;'>"
            f"<span class='gf-section-label' style='margin:0;'>Timeline</span>"
            f"<span class='gf-tl-badge'>{n_clips} clip{'s' if n_clips != 1 else ''}</span>"
            f"{'<span class=\'gf-tl-badge gf-tl-badge-dur\'>' + _fmt_time(total_dur) + '</span>' if total_dur > 0 else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with hdr_r:
        zoom_c, snap_c = st.columns([2, 1])
        with zoom_c:
            new_zoom = st.select_slider(
                "Zoom", options=[0.5, 1.0, 1.5, 2.0, 3.0],
                value=zoom,
                label_visibility="collapsed",
                format_func=lambda v: "Fit" if v == 1.0 else f"×{v}",
                help="Timeline zoom (1× = fit)",
            )
            if new_zoom != zoom:
                zoom = new_zoom
                st.session_state["timeline_zoom"] = zoom
        with snap_c:
            st.toggle("Snap", value=st.session_state.get("timeline_snap_enabled", True),
                      key="timeline_snap_enabled",
                      help="Snap trim handles and playhead to clip boundaries")

    # ── Time ruler ────────────────────────────────────────────────────────────
    _render_time_ruler(total_dur, playhead_pos, zoom, n_clips)

    # ── Build timeline track HTML ─────────────────────────────────────────────
    selected_now = st.session_state.get("editor_selected_clip")
    if selected_now not in current_order:
        selected_now = current_order[0] if current_order else None

    blocks_html: list[str] = []
    for position, clip_id in enumerate(current_order, start=1):
        if clip_id not in clip_map:
            continue
        clip = clip_map[clip_id]
        eff_dur = _clip_effective_dur(clip_id)
        real_dur = durations.get(clip_id, 0.0)
        trim = trims.get(clip_id, {})
        t_start = float(trim.get("start", 0.0))
        t_end = float(trim.get("end", 0.0))

        # Duration label
        if eff_dur is not None:
            dur_label = f"{eff_dur:.1f}s"
        else:
            dur_label = "full"

        # Real duration label for tooltip
        real_label = f"{real_dur:.1f}s" if real_dur > 0 else "?"

        # Clip width based on zoom + proportional duration
        if total_dur > 0 and eff_dur is not None:
            proportion = eff_dur / total_dur
            min_w = max(120, int(proportion * 600 * zoom))
        else:
            min_w = max(140, int(160 * zoom))

        sel_class = " selected" if clip_id == selected_now else ""

        # Thumbnail strip
        thumb_b64 = st.session_state.get("editor_thumbnail_cache", {}).get(clip_id)
        thumb_html = ""
        if thumb_b64:
            thumb_html = (
                f"<div class='gf-tl-thumb' style='background-image:url(data:image/png;base64,{thumb_b64});'></div>"
            )
        else:
            # Trigger async thumbnail generation — non-blocking
            src_path = trim.get("source_path", "")
            if src_path and os.path.isfile(src_path):
                _get_clip_thumbnail(clip_id, src_path)

        # Transition marker (left side of block, if prev clip has transition set)
        trans_html = ""
        if position > 1:
            prev_id = current_order[position - 2]
            prev_trim = trims.get(prev_id, {})
            trans = prev_trim.get("transition") or (clip_map.get(prev_id, {}).get("transition"))
            if trans:
                trans_html = (
                    f"<div class='gf-tl-transition' title='Transition: {html.escape(str(trans))}'>"
                    f"<span>◇</span></div>"
                )

        # Waveform / audio stub
        has_audio = (st.session_state.get("editor_clip_meta") or {}).get(clip_id, {}).get("has_audio")
        audio_bar = ""
        if has_audio:
            audio_bar = "<div class='gf-tl-audio-bar'></div>"

        block = (
            f"{trans_html}"
            f"<div class='gf-timeline-block{sel_class}' role='listitem' "
            f"aria-selected='{'true' if clip_id == selected_now else 'false'}' "
            f"style='min-width:{min_w}px;' "
            f"title='{html.escape(clip['label'])} · {real_label} source · {dur_label} active'>"
            f"{thumb_html}"
            f"<strong>{position:02d}</strong>"
            f"<span title='{html.escape(clip['label'])}'>{html.escape(clip['label'])}</span>"
            f"<small style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='color:var(--gf-muted);'>{html.escape(clip['role'])}</span>"
            f"<span style='color:{'var(--gf-accent)' if clip_id == selected_now else 'var(--gf-faint)'};"
            f"font-weight:700;font-variant-numeric:tabular-nums;'>{dur_label}</span>"
            f"</small>"
            f"{audio_bar}"
            f"</div>"
        )
        blocks_html.append(block)

    # Playhead overlay (pixel-positioned over the track)
    ph_pct = min(100.0, (playhead_pos / total_dur * 100) if total_dur > 0 else 0.0)
    ph_overlay = (
        f"<div class='gf-tl-playhead' style='left:{ph_pct:.2f}%;' "
        f"title='Playhead: {_fmt_time(playhead_pos)}'>"
        f"<div class='gf-tl-playhead-head'></div>"
        f"</div>"
    )

    track_html = (
        f"<div class='gf-timeline-track-wrap' style='--gf-zoom:{zoom};'>"
        f"<div class='gf-timeline-track' role='list' aria-label='Timeline clips'>"
        + "".join(blocks_html)
        + f"</div>"
        + ph_overlay
        + f"</div>"
    )
    st.markdown(track_html, unsafe_allow_html=True)

    # ── Clip selector (drives selected_now) ───────────────────────────────────
    selected_id = st.selectbox(
        "Selected clip",
        options=current_order,
        format_func=lambda cid: (
            f"{current_order.index(cid) + 1:02d} · {clip_map.get(cid, {}).get('label', cid)}"
            f" [{clip_map.get(cid, {}).get('role', '')}]"
        ),
        key="editor_selected_clip",
        label_visibility="collapsed",
        index=current_order.index(selected_now) if selected_now in current_order else 0,
    )
    selected_index = current_order.index(selected_id)

    # ── Clip operation toolbar ────────────────────────────────────────────────
    op_cols = st.columns([1, 1, 1, 1, 1, 1, 2])
    with op_cols[0]:
        if st.button(":material/arrow_back:", disabled=selected_index == 0,
                     key="editor_move_left", help="Move clip earlier (←)"):
            _push_edit_history()
            current_order[selected_index - 1], current_order[selected_index] = (
                current_order[selected_index], current_order[selected_index - 1])
            st.session_state["editor_session_clip_order"] = current_order
            st.rerun()
    with op_cols[1]:
        if st.button(":material/arrow_forward:", disabled=selected_index == len(current_order) - 1,
                     key="editor_move_right", help="Move clip later (→)"):
            _push_edit_history()
            current_order[selected_index + 1], current_order[selected_index] = (
                current_order[selected_index], current_order[selected_index + 1])
            st.session_state["editor_session_clip_order"] = current_order
            st.rerun()
    with op_cols[2]:
        if st.button(":material/content_copy:", key="editor_duplicate_clip",
                     help="Duplicate selected clip", disabled=len(current_order) >= 12):
            _push_edit_history()
            new_id = f"dup::{selected_id}::{len(current_order)}"
            clip_map[new_id] = dict(clip_map[selected_id])
            clip_map[new_id]["id"] = new_id
            clip_map[new_id]["label"] = clip_map[selected_id]["label"] + " (copy)"
            current_order.insert(selected_index + 1, new_id)
            trims[new_id] = dict(trims.get(selected_id, {"start": 0.0, "end": 0.0}))
            st.session_state["editor_session_clip_order"] = current_order
            st.session_state["editor_session_trims"] = trims
            st.rerun()
    with op_cols[3]:
        if st.button(":material/delete:", key="editor_delete_clip",
                     help="Remove selected clip (Delete key)", disabled=len(current_order) <= 1):
            _push_edit_history()
            current_order.pop(selected_index)
            trims.pop(selected_id, None)
            st.session_state["editor_session_clip_order"] = current_order
            st.session_state["editor_session_trims"] = trims
            st.session_state.pop("editor_selected_clip", None)
            st.rerun()
    with op_cols[4]:
        # Split at playhead
        clip_dur = _clip_effective_dur(selected_id)
        can_split = (clip_dur is not None and clip_dur > 0.2 and
                     durations.get(selected_id, 0.0) > 0)
        split_time_in_clip = max(0.0, playhead_pos - sum(
            _clip_effective_dur(cid) or 0.0
            for cid in current_order[:selected_index]
        ))
        if st.button(":material/content_cut:", key="editor_split_clip",
                     help=f"Split at playhead ({_fmt_time(split_time_in_clip)} into clip)",
                     disabled=not can_split):
            try:
                _push_edit_history()
                new_order, new_trims, clip_map = _split_clip_at_point(
                    selected_id, split_time_in_clip, clip_map, current_order, trims, durations
                )
                st.session_state["editor_session_clip_order"] = new_order
                st.session_state["editor_session_trims"] = new_trims
                st.session_state.pop("editor_selected_clip", None)
                st.rerun()
            except ValueError as split_err:
                st.error(f"Cannot split: {split_err}")
    with op_cols[5]:
        if st.button(":material/restart_alt:", key="editor_reset_order",
                     help="Reset clip order to upload order"):
            _push_edit_history()
            st.session_state["editor_session_clip_order"] = available_ids
            st.rerun()

    # ── Rich clip inspector ───────────────────────────────────────────────────
    meta = (st.session_state.get("editor_clip_meta") or {}).get(selected_id, {})
    real_dur = durations.get(selected_id, 0.0)
    eff_dur_val = _clip_effective_dur(selected_id)
    trim_data = trims.get(selected_id, {"start": 0.0, "end": 0.0})
    src_path = trim_data.get("source_path", "")
    fps_str = f"{meta['fps']:.2f} fps" if meta.get("fps") else "—"
    dim_str = f"{meta['width']}×{meta['height']}" if meta.get("width") else "—"
    audio_str = "Yes" if meta.get("has_audio") else ("No" if meta else "—")
    codec_str = meta.get("video_codec", "—") or "—"
    src_name = os.path.basename(src_path) if src_path else clip_map.get(selected_id, {}).get("label", "—")
    position_str = f"{current_order.index(selected_id) + 1} of {len(current_order)}"
    real_dur_str = f"{real_dur:.2f}s" if real_dur > 0 else "—"
    eff_dur_str = f"{eff_dur_val:.2f}s" if eff_dur_val is not None else "full"

    st.markdown(
        f"<div class='gf-inspector'>"
        f"<div class='gf-inspector-header'>"
        f"<span class='gf-inspector-title'>Inspector</span>"
        f"<span class='gf-inspector-clip'>{html.escape(clip_map.get(selected_id, {}).get('label', selected_id))}</span>"
        f"</div>"
        f"<div class='gf-inspector-grid'>"
        f"<span class='gf-inspector-key'>Position</span><span class='gf-inspector-val'>{position_str}</span>"
        f"<span class='gf-inspector-key'>Source dur</span><span class='gf-inspector-val'>{real_dur_str}</span>"
        f"<span class='gf-inspector-key'>Active dur</span><span class='gf-inspector-val'>{eff_dur_str}</span>"
        f"<span class='gf-inspector-key'>Dimensions</span><span class='gf-inspector-val'>{dim_str}</span>"
        f"<span class='gf-inspector-key'>Frame rate</span><span class='gf-inspector-val'>{fps_str}</span>"
        f"<span class='gf-inspector-key'>Codec</span><span class='gf-inspector-val'>{codec_str}</span>"
        f"<span class='gf-inspector-key'>Audio</span><span class='gf-inspector-val'>{audio_str}</span>"
        f"<span class='gf-inspector-key'>Source</span><span class='gf-inspector-val' "
        f"title='{html.escape(src_path)}'>{html.escape(src_name)}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Trim controls inside inspector
    trim_l, trim_r = st.columns(2)
    old_trim = trims.get(selected_id, {"start": 0.0, "end": 0.0})
    max_val = max(real_dur, old_trim.get("end", 0.0), 9999.0)
    with trim_l:
        trim_start = st.number_input(
            "Trim in (s)", min_value=0.0, max_value=float(max_val),
            value=float(old_trim.get("start", 0.0)), step=0.1,
            key=f"timeline_trim_start_{selected_id}",
            help="In-point: 0 = beginning of clip",
        )
    with trim_r:
        trim_end = st.number_input(
            "Trim out (s)", min_value=0.0, max_value=float(max_val),
            value=float(old_trim.get("end", 0.0)), step=0.1,
            key=f"timeline_trim_end_{selected_id}",
            help="Out-point: 0 = use full clip",
        )

    # Validation and live derived duration
    if trim_end > 0 and trim_end <= trim_start:
        st.error("Trim out must be greater than trim in.")
    elif trim_end > trim_start:
        dur_active = trim_end - trim_start
        st.markdown(
            f"<div class='gf-inspector-dur-ok'>Active: {dur_active:.2f}s</div>",
            unsafe_allow_html=True,
        )
    elif trim_start > 0 and real_dur > 0:
        remaining = max(real_dur - trim_start, 0.0)
        st.markdown(
            f"<div class='gf-inspector-dur-warn'>Starts at {trim_start:.1f}s · "
            f"{remaining:.1f}s remaining</div>",
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)  # close gf-inspector

    if old_trim.get("start") != trim_start or old_trim.get("end") != trim_end:
        _push_edit_history()

    trims[selected_id] = {
        **trims.get(selected_id, {}),
        "start": float(trim_start),
        "end": float(trim_end),
    }

    # ── Persist timeline session state ────────────────────────────────────────
    st.session_state["editor_session_clip_order"] = current_order
    st.session_state["editor_session_trims"] = trims
    return current_order, trims


def render_multi_segment_editor(uploaded_video):
    """Build editable source-video segments and return their selection state."""
    if not uploaded_video:
        st.info("Upload a primary video to create multiple editable parts.")
        return []

    source_path = save_uploaded_file(uploaded_video)
    try:
        total_duration = float(get_video_metadata(source_path)[0])
    except Exception:
        total_duration = 60.0

    st.markdown("#### :material/content_cut: Multi-Part Source Editor")
    st.caption("Split one source video into ranges, select several ranges, and apply the same edit directive to all selected parts.")
    segment_count = int(st.number_input("Number of source parts", min_value=2, max_value=12, value=3, step=1, key="multi_segment_count"))
    specs = []
    for index in range(segment_count):
        default_start = round((total_duration / segment_count) * index, 2)
        default_end = round((total_duration / segment_count) * (index + 1), 2)
        selected_col, name_col, start_col, end_col = st.columns([0.7, 1.5, 1, 1])
        with selected_col:
            selected = st.checkbox("Use", value=True, key=f"segment_selected_{index}", label_visibility="visible")
        with name_col:
            label = st.text_input("Part", value=f"Part {index + 1}", key=f"segment_label_{index}", label_visibility="collapsed")
        with start_col:
            start_time = st.number_input("In", min_value=0.0, max_value=max(total_duration, 0.1), value=min(default_start, total_duration), step=0.1, key=f"segment_start_{index}")
        with end_col:
            end_time = st.number_input("Out", min_value=0.0, max_value=max(total_duration, 0.1), value=min(default_end, total_duration), step=0.1, key=f"segment_end_{index}")
        if end_time <= start_time:
            st.error(f"{label or f'Part {index + 1}'}: Out must be greater than In.")
        specs.append({"id": f"source_segment_{index}", "label": label or f"Part {index + 1}", "start": float(start_time), "end": float(end_time), "selected": bool(selected)})

    selected_count = sum(1 for spec in specs if spec["selected"])
    st.info(f"{selected_count} of {len(specs)} parts selected for the batch edit.")
    return specs


def _preview_director_changes(prompt: str) -> list[str]:
    """Preview parsed edit operations using the existing prompt parsers only."""
    proposals: list[str] = []
    if not parse_timeline_prompt:
        return proposals
    has_parts = bool(re.search(
        r"\bpart\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
        prompt or "",
        re.IGNORECASE,
    ))
    directives: dict = {}
    if has_parts and parse_multi_part_directives:
        try:
            directives = parse_multi_part_directives(prompt, part_count=12)
        except PromptTimelineError:
            directives = {}
    try:
        if directives:
            for part_index, directive in sorted(directives.items()):
                try:
                    operations = parse_timeline_prompt(directive)
                except PromptTimelineError:
                    operations = []
                for operation in operations:
                    proposals.append(
                        f"Part {part_index + 1}: {operation.effect} from "
                        f"{operation.start_time:g}s to {operation.end_time:g}s"
                    )
        else:
            for operation in parse_timeline_prompt(prompt):
                proposals.append(f"{operation.effect} from {operation.start_time:g}s to {operation.end_time:g}s")
    except PromptTimelineError:
        pass
    return proposals


# --- Keyboard shortcuts ---
def _inject_keyboard_shortcuts() -> None:
    """Inject JS for editor keyboard shortcuts.

    Ctrl/Cmd+S  → Save
    Ctrl/Cmd+Z  → Undo
    Ctrl/Cmd+Shift+Z → Redo
    Delete/Backspace → Delete selected clip (when not in input)
    Space       → scroll-to-playhead (placeholder — no playback control possible
                  without a custom component)
    Arrow keys  → move playhead ±1 second via a hidden Streamlit button click

    All guards are in place:
    - _gfKeyboardInit prevents duplicate listeners
    - Input/textarea/select focus is checked before Delete/Space
    - Modifier conflicts with browser defaults are avoided
    """
    js = """
    <script>
    (function() {
        if (window._gfKeyboardInit) return;
        window._gfKeyboardInit = true;
        function isEditing() {
            var tag = document.activeElement && document.activeElement.tagName;
            return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
        }
        function clickBtn(textFragment, excludes) {
            excludes = excludes || [];
            var btns = Array.from(document.querySelectorAll('button'));
            var btn = btns.find(function(b) {
                var t = b.textContent.trim();
                if (b.disabled) return false;
                if (!t.includes(textFragment)) return false;
                return !excludes.some(function(ex) { return t.includes(ex); });
            });
            if (btn) { btn.click(); return true; }
            return false;
        }
        function clickByKey(dataKey) {
            var el = document.querySelector('[data-testid="' + dataKey + '"]');
            if (el) { el.click(); return true; }
            return false;
        }
        document.addEventListener('keydown', function(e) {
            var isCtrl = e.ctrlKey || e.metaKey;
            // Ctrl/Cmd+K -> open the native command palette popover.
            if (isCtrl && !e.shiftKey && e.key.toLowerCase() === 'k') {
                if (!isEditing()) {
                    e.preventDefault();
                    clickBtn('Command palette', []);
                }
                return;
            }
            // Ctrl+S → Save
            if (isCtrl && !e.shiftKey && e.key === 's') {
                e.preventDefault();
                clickBtn('Save', ['Delete', 'Rename', 'Cancel']);
                return;
            }
            // Ctrl+Z → Undo
            if (isCtrl && !e.shiftKey && e.key === 'z') {
                if (!isEditing()) {
                    e.preventDefault();
                    clickBtn('Undo', []);
                }
                return;
            }
            // Ctrl+Shift+Z → Redo
            if (isCtrl && e.shiftKey && (e.key === 'z' || e.key === 'Z')) {
                if (!isEditing()) {
                    e.preventDefault();
                    clickBtn('Redo', []);
                }
                return;
            }
            // Delete/Backspace → Delete selected clip
            if ((e.key === 'Delete' || e.key === 'Backspace') && !isEditing()) {
                e.preventDefault();
                // Click the Delete clip button (icon-only, no text match needed)
                var btns = Array.from(document.querySelectorAll('button'));
                // The delete clip button is keyed 'editor_delete_clip' — find via aria or proximity
                var del = btns.find(function(b) {
                    return !b.disabled && b.getAttribute('aria-label') === 'Delete clip';
                });
                if (!del) {
                    // Fallback: find button with delete icon material symbol in key scope
                    del = btns.find(function(b) {
                        return !b.disabled && b.closest('[data-testid]') &&
                               b.closest('[data-testid]').dataset.testid === 'editor_delete_clip';
                    });
                }
                if (del) del.click();
                return;
            }
            // ArrowLeft → move playhead back 1s (click hidden btn_playhead_back)
            if (e.key === 'ArrowLeft' && !isEditing() && !isCtrl) {
                e.preventDefault();
                clickBtn('playhead_back', []);
                return;
            }
            // ArrowRight → move playhead forward 1s (click hidden btn_playhead_fwd)
            if (e.key === 'ArrowRight' && !isEditing() && !isCtrl) {
                e.preventDefault();
                clickBtn('playhead_fwd', []);
                return;
            }
        }, true);
    })();
    </script>
    """
    st.html(js)


def _render_command_palette() -> None:
    """Render a small native command palette using existing app actions."""
    with st.popover(":material/search: Command palette", use_container_width=False):
        st.caption("Navigate and act without leaving the keyboard.")
        st.markdown("**Workspace**")
        palette_cols = st.columns(2)
        for index, workspace in enumerate(WORKSPACE_OPTIONS):
            with palette_cols[index % 2]:
                if st.button(
                    workspace,
                    key=f"palette_{index}",
                    use_container_width=True,
                ):
                    st.session_state.app_mode = workspace
                    st.rerun()
        st.markdown("**Actions**")
        if st.button(":material/add: New project", key="palette_new_project", use_container_width=True):
            st.session_state.app_mode = ":material/home: Home"
            st.session_state.show_create_project_form = True
            st.rerun()
        st.button(
            ":material/contrast: Toggle theme",
            key="palette_toggle_theme",
            on_click=_toggle_theme,
            use_container_width=True,
        )
        if st.button(":material/save: Save project", key="palette_save", use_container_width=True):
            persist_project()
            st.rerun()


# --- Editor Toolbar ---
def _fmt_time(seconds: float) -> str:
    """Format seconds as MM:SS.cc — delegates to timeline_logic."""
    return _tl.fmt_time(seconds)


def _render_editor_toolbar() -> None:
    """Professional editor toolbar with project context, save, and undo/redo."""
    _inject_keyboard_shortcuts()
    project = st.session_state.get("project")
    save_status = st.session_state.get("save_status", "saved")
    has_project = isinstance(project, ProjectState)
    history: list = st.session_state.get("edit_history") or []
    idx: int = st.session_state.get("edit_history_index", -1)
    can_undo = idx > 0 and len(history) > 1
    can_redo = idx < len(history) - 1

    # Save chip display
    save_icons = {
        "saved":   ("✓ Saved",           "color:var(--gf-good);"),
        "saving":  ("↻ Saving…",         "color:var(--gf-warn);"),
        "unsaved": ("● Unsaved changes",  "color:var(--gf-warn);"),
        "failed":  ("✕ Save failed",      "color:var(--gf-bad);"),
    }
    save_label, save_style = save_icons.get(save_status, ("", ""))

    project_name = html.escape(project.name) if has_project else "No project"
    project_chip = (
        f"<span style='font-size:.75rem;font-weight:600;color:var(--gf-muted);"
        f"background:var(--gf-panel-2);border:1px solid var(--gf-border-2);padding:3px 10px;"
        f"border-radius:6px;letter-spacing:-.01em;'>"
        f"<span style='color:var(--gf-faint);margin-right:4px;'>▸</span>"
        f"{project_name}</span>"
    )
    save_chip_html = (
        f"<span style='font-size:.71rem;font-weight:600;{save_style}"
        f"background:transparent;padding:3px 8px;'>{save_label}</span>"
        if save_label else ""
    )

    st.markdown(
        f"<div style='display:flex;align-items:center;gap:8px;padding:7px 14px;"
        f"background:var(--gf-card-grad);"
        f"border:1px solid var(--gf-border);border-radius:10px;margin-bottom:10px;"
        f"box-shadow:var(--gf-shadow-md);'>"
        f"{project_chip}"
        f"<span style='flex:1;'></span>"
        f"{save_chip_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    tool_c1, tool_c2, tool_c3, tool_c4, tool_spacer = st.columns([1, 1, 1, 1.5, 3])
    with tool_c1:
        if st.button(
            ":material/undo: Undo",
            key="btn_undo",
            disabled=not can_undo,
            help=(
                f"Undo last timeline change ({idx} / {len(history)-1} in history)"
                if can_undo else "Nothing to undo"
            ),
        ):
            if _undo_edit():
                st.rerun()
    with tool_c2:
        if st.button(
            ":material/redo: Redo",
            key="btn_redo",
            disabled=not can_redo,
            help="Redo last undone change",
        ):
            if _redo_edit():
                st.rerun()
    with tool_c3:
        if st.button(
            ":material/save: Save",
            key="btn_editor_save",
            type="primary" if save_status == "unsaved" else "secondary",
            help="Save project to disk (Ctrl+S)",
            disabled=not has_project,
        ):
            persist_project()
            st.rerun()
    with tool_c4:
        if st.session_state.get("ai_director_applied"):
            st.markdown(
                "<span style='font-size:.72rem;color:var(--gf-accent);font-weight:600;"
                "background:var(--gf-accent-soft);border:1px solid var(--gf-border-accent);"
                "padding:3px 8px;border-radius:6px;'>"
                "⬢ AI command queued</span>",
                unsafe_allow_html=True,
            )
    # Phase 4: playhead transport controls (hidden label buttons used by keyboard JS)
    ph_pos = float(st.session_state.get("playhead_position", 0.0))
    ph_c1, ph_c2, ph_c3, ph_spacer = st.columns([1, 1, 2, 4])
    with ph_c1:
        if st.button("⏮", key="btn_playhead_back",
                     help="Move playhead back 1 second (←)"):
            st.session_state["playhead_position"] = max(0.0, ph_pos - 1.0)
            st.rerun()
    with ph_c2:
        if st.button("⏭", key="btn_playhead_fwd",
                     help="Move playhead forward 1 second (→)"):
            st.session_state["playhead_position"] = ph_pos + 1.0
            st.rerun()
    with ph_c3:
        st.markdown(
            f"<span style='font-size:.72rem;color:var(--gf-muted);font-weight:600;"
            f"font-variant-numeric:tabular-nums;'>"
            f"⏱ {_fmt_time(ph_pos)}</span>",
            unsafe_allow_html=True,
        )


# --- Phase 4: Pre-render validation ---
def _validate_render_inputs(
    uploaded_video: object,
    timeline_files: list,
    editor_order: list,
    editor_trims: dict,
) -> None:
    """Delegate to timeline_logic.validate_render_inputs."""
    _tl.validate_render_inputs(
        has_video=bool(uploaded_video),
        has_files=bool(timeline_files),
        clip_order=editor_order,
        trims=editor_trims,
    )


# --- Phase 4: Clip Preview Monitor ---
def _render_clip_preview_monitor() -> None:
    """Show preview of selected clip when no render output exists yet.

    When a render output is present, this is a no-op (render_media_preview handles it).
    When a clip is selected in the timeline, its source file is shown via st.video()
    so the user can see the clip content without rendering first.
    """
    if st.session_state.get("rendered_output"):
        return  # render_media_preview() will handle the output display
    selected_id = st.session_state.get("editor_selected_clip")
    trims = st.session_state.get("editor_session_trims") or {}
    trim = trims.get(selected_id, {}) if selected_id else {}
    src_path = trim.get("source_path", "") if trim else ""
    durations = st.session_state.get("editor_clip_durations") or {}
    real_dur = durations.get(selected_id, 0.0) if selected_id else 0.0

    if src_path and os.path.isfile(src_path):
        st.markdown(
            f"<div style='font-size:.7rem;color:var(--gf-muted);margin-bottom:4px;"
            f"font-weight:600;letter-spacing:.04em;'>SELECTED CLIP PREVIEW</div>",
            unsafe_allow_html=True,
        )
        t_start = float(trim.get("start", 0.0))
        t_end = float(trim.get("end", 0.0))
        if t_start > 0 or (t_end > 0 and t_end > t_start):
            # Show trim info
            dur_str = f"{t_end - t_start:.1f}s" if t_end > t_start else f"{max(real_dur - t_start, 0):.1f}s"
            st.markdown(
                f"<div style='font-size:.67rem;color:var(--gf-muted);margin-bottom:4px;'>"
                f"Trim: {t_start:.1f}s → {'end' if t_end == 0 else f'{t_end:.1f}s'} "
                f"({dur_str})</div>",
                unsafe_allow_html=True,
            )
        st.video(src_path, start_time=int(t_start))
    else:
        # No clip selected or no source path yet — show placeholder
        from ui_components import canvas_empty as _ce
        st.markdown(
            _ce(
                icon="🎬",
                title="Preview Monitor",
                hint="Select a clip in the timeline to preview it here, "
                     "or click Render Pipeline to generate your output.",
            ),
            unsafe_allow_html=True,
        )


# --- View 2: Video Workstation ---
def render_video_studio(uploaded_video, uploaded_audio, uploaded_image):

    # ── Editor toolbar strip ──────────────────────────────────────────────────
    _render_editor_toolbar()

    # Editor layout: preview dominant (wider left), properties rail (right).
    col_monitor, col_props = st.columns([1.65, 1.0], gap="medium")

    with col_props:
        st.markdown('<div class="studio-card">', unsafe_allow_html=True)
        st.markdown(
            "<div style='display:flex;align-items:center;gap:8px;margin-bottom:12px;"
            "padding-bottom:10px;border-bottom:1px solid #18202E;'>"
            "<span style='font-size:.78rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;"
            "color:var(--gf-fg);'>Pipeline Controls</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        # ── PRIMARY ACTIONS — visible at top, no scrolling required ──
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            one_click_v = st.button(
                ":material/auto_fix_high: One-Click Enhance",
                key="btn_one_click_v",
                help="AI-powered one-click video enhancement (no prompt required)",
                type="primary",
            )
        with btn_col2:
            render_btn = st.button(
                ":material/smart_display: Render Pipeline",
                key="btn_v_render",
                help="Execute the full render pipeline with the settings below",
            )

        st.markdown("---")

        tab_prompt, tab_pipe, tab_fx, tab_voice, tab_master = st.tabs([
            "AI Director",
            "Pipeline",
            "FX & Transitions",
            "Voiceover",
            "Mastering",
        ])

        with tab_pipe:
            p_col1, p_col2 = st.columns(2)
            with p_col1:
                auto_silence = st.checkbox("Remove silent pauses", value=True)
                auto_caps = st.checkbox("Auto burn-in captions", value=True)
            with p_col2:
                auto_highlight = st.checkbox("Extract top highlights")
                auto_resize = st.selectbox("Target format", ["Original", "9:16 (Shorts/TikTok)", "1:1 (Square)", "16:9 (Landscape)"])

            st.markdown("---")
            enable_omni_export = st.checkbox("Export omni-platform suite (9:16, 1:1, 16:9)", value=True)
            enable_gemini_vision = st.checkbox("Deep Gemini Vision keyframe analysis", value=True)

        with tab_voice:
            enable_tts = st.checkbox("Generate AI voiceover narration")
            tts_text = st.text_area("Voiceover Script:", value="Welcome to GENFORGE, the next generation autonomous media engine.", height=80)
            voice_choice = st.selectbox("Voice Profile", list(VOICE_PRESETS.keys()))
            enable_ducking = st.checkbox("Auto-duck BGM under narration")

        with tab_fx:
            enable_chroma = st.checkbox("Chroma key (green screen removal)")
            chroma_color = st.color_picker("Key Color", "#00FF00")
            chroma_bg_file = st.file_uploader("Background Media", type=["mp4", "mov", "png", "jpg"], key="chroma_bg_up")
            
            st.markdown("---")
            enable_transition = st.checkbox("Apply clip transition")
            transition_type = st.selectbox("Transition Effect", ["wipeleft", "dissolve", "circlecrop", "slideup"])
            second_clip_file = st.file_uploader("Secondary Clip", type=["mp4", "mov"], key="transition_clip_up")
            
            st.markdown("---")
            gen_thumbnail = st.checkbox("Auto-generate thumbnail keyframe")
            thumb_title = st.text_input("Thumbnail Overlay", value="VIRAL HIGHLIGHT!")

        with tab_master:
            enable_timeline = st.checkbox("Enable editorial timeline", value=True)
            timeline_mode = st.radio(
                "Timeline source",
                ["Multi-clip sequence", "Multi-part source video"],
                horizontal=True,
                disabled=not enable_timeline,
            )
            timeline_files = st.file_uploader(
                "Additional clips",
                type=["mp4", "mov", "mkv", "avi", "webm", "m4v"],
                accept_multiple_files=True,
                key="timeline_clips_up",
                disabled=not enable_timeline or timeline_mode != "Multi-clip sequence",
            )
            enable_mastering = st.checkbox("Master final audio to LUFS")

            target_lufs = st.slider(
                "Integrated loudness target",
                min_value=-24.0,
                max_value=-9.0,
                value=-16.0,
                step=0.5,
                disabled=not enable_mastering,
            )
            enable_contact_sheet = st.checkbox("Generate contact sheet for review")

        with tab_prompt:
            st.caption(
                "Command the AI Director with natural language. "
                "Target clips by position: `Part 1: blur from 0 to 2`."
            )
            user_prompt = st.text_area(
                "AI Command",
                value="Part 1: blur from 0 to 2; Part 2: grayscale from 0 to 2; Part 3: mirror from 0 to 1",
                height=96, key="v_prompt",
                help="Use 'Part N: effect from T to T' syntax. Each part targets the corresponding timeline clip.",
                label_visibility="collapsed",
            )

            preview_col, apply_col = st.columns([1, 1])
            with preview_col:
                if st.button(":material/visibility: Preview Changes", key="btn_ai_preview",
                             help="Parse the command and show what will be changed without executing"):
                    st.session_state.ai_director_preview = True
            with apply_col:
                if st.session_state.get("ai_director_applied"):
                    st.markdown(
                        badge("Command queued", "ok"),
                        unsafe_allow_html=True,
                    )

            if st.session_state.get("ai_director_preview"):
                proposals = _preview_director_changes(user_prompt)
                if proposals:
                    # Phase 10: use the AI plan panel for a professional review UX
                    st.markdown(
                        ai_plan_panel("Proposed Changes", proposals, animated=False),
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("No parseable operations in this command — check syntax.")

                act_col, edit_col, cancel_col = st.columns(3)
                with act_col:
                    if st.button(":material/check: Apply", key="btn_ai_apply", type="primary"):
                        st.session_state.ai_director_applied = user_prompt
                with edit_col:
                    if st.button(":material/edit: Edit", key="btn_ai_edit"):
                        st.session_state.ai_director_preview = False
                        st.session_state.pop("ai_director_applied", None)
                with cancel_col:
                    if st.button(":material/close: Cancel", key="btn_ai_cancel"):
                        st.session_state.ai_director_preview = False
                        st.session_state.pop("ai_director_applied", None)

            if enable_timeline:
                st.caption(
                    "**Tip:** `Part 1: blur from 0 to 2; Part 2: grayscale from 0 to 3`"
                    " — each part maps to its position in the editor order above."
                )

        st.markdown("</div>", unsafe_allow_html=True)

    # --- Canonical timeline: prominent, full width under the workspace split ---
    editor_order, editor_trims = ([], {})
    source_segments = []
    if enable_timeline:
        st.markdown('<div class="studio-card">', unsafe_allow_html=True)
        if timeline_mode == "Multi-clip sequence":
            editor_order, editor_trims = render_editor_timeline(uploaded_video, timeline_files)
        else:
            source_segments = render_multi_segment_editor(uploaded_video)
        st.markdown("</div>", unsafe_allow_html=True)

    with col_monitor:
        st.markdown('<div class="studio-card">', unsafe_allow_html=True)
        st.markdown("#### :material/smart_display: Preview")

        # Phase 4: Preview selected clip from timeline when no render output exists
        _render_clip_preview_monitor()

        if one_click_v:
            if not uploaded_video:
                st.error("Please upload a video file in the Asset Vault (Sidebar) first.")
            else:
                if render_agent_telemetry_live:
                    render_agent_telemetry_live()
                with st.spinner("✨ Running AI Video Auto-Enhancement..."):
                    try:
                        video_path = save_uploaded_file(uploaded_video)
                        st.session_state.original_input = video_path
                        out_path = auto_enhance_video(video_path, output_dir=project_output_dir())
                        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
                            raise RuntimeError("Video enhancement produced no usable output.")
                        st.session_state.rendered_output = out_path
                        st.session_state.output_type = "video"
                        try:
                            st.session_state.viral_data = analyze_viral_score(out_path, "Video")
                        except Exception:
                            st.session_state.viral_data = {"status": "unavailable", "reason": "Analysis failed after render"}
                        record_project_result(video_path, out_path, st.session_state.viral_data)
                        if export_omni_platform_suite:
                            try:
                                st.session_state.omni_outputs = export_omni_platform_suite(out_path, project_output_dir())
                            except Exception as export_err:
                                st.warning(f"Omni-platform export skipped: {export_err}")

                        st.success(":material/check_circle: Video enhancement complete.")
                    except Exception as e:
                        st.error(f"Video Enhancement Failed: {e}")

        if render_btn:
            if render_agent_telemetry_live:
                render_agent_telemetry_live()
            if not uploaded_video:
                st.error("Please upload a video file in the Asset Vault (Sidebar) first.")
            else:
                with st.status("Executing render pipeline…", expanded=True) as _render_status:
                    st.write("Validating inputs and building pipeline…")
                    try:
                        # Phase 4: pre-render canonical state validation
                        _validate_render_inputs(uploaded_video, timeline_files, editor_order, editor_trims)
                        video_path = save_uploaded_file(uploaded_video)
                        st.session_state.original_input = video_path
                        st.session_state.timeline_output = None
                        st.session_state.rendered_output = None
                        pipeline_video_path = video_path
                        ui_pipeline_options = {
                            "auto_silence": auto_silence,
                            "auto_caps": auto_caps,
                            "auto_highlight": auto_highlight,
                            "auto_resize": auto_resize,
                        }
                        pipeline_prompt = user_prompt
                        has_part_specific_prompt = False

                        if enable_timeline and timeline_mode == "Multi-part source video":
                            if not assemble_timeline or not trim_clip_for_timeline:
                                raise RuntimeError("Timeline engine is unavailable. Check production_features.py and its dependencies.")
                            selected_segments = [segment for segment in source_segments if segment["selected"]]
                            if not selected_segments:
                                raise ValueError("Select at least one source part for the batch edit.")
                            selected_indexes = [index for index, segment in enumerate(source_segments) if segment["selected"]]
                            part_operations = {}
                            part_directives = {}
                            if parse_multi_part_directives:
                                try:
                                    part_directives = parse_multi_part_directives(
                                        user_prompt,
                                        part_count=len(source_segments),
                                        selected_parts=selected_indexes,
                                    )
                                except PromptTimelineError:
                                    part_directives = {index: user_prompt for index in selected_indexes}
                            if parse_multi_part_prompt:
                                for part_index, directive in part_directives.items():
                                    try:
                                        part_operations[part_index] = parse_timeline_prompt(directive) if parse_timeline_prompt else []
                                    except PromptTimelineError:
                                        part_operations[part_index] = []
                            has_part_specific_prompt = bool(part_directives) and bool(re.search(r"\bpart\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", user_prompt, re.IGNORECASE))
                            if has_part_specific_prompt:
                                pipeline_prompt = "Preserve the assembled timeline exactly; only apply the selected global pipeline options."
                            segment_paths = []
                            for position, segment in enumerate(selected_segments, start=1):
                                if segment["end"] <= segment["start"]:
                                    raise ValueError(f"{segment['label']}: Out must be greater than In.")
                                segment_output = project_output_path(f"source_segment_{position}.mp4")
                                segment_path = trim_clip_for_timeline(
                                    video_path,
                                    segment_output,
                                    segment["start"],
                                    segment["end"],
                                )
                                original_index = selected_indexes[position - 1]
                                operations = part_operations.get(original_index, [])
                                directive = part_directives.get(original_index, user_prompt)
                                if operations and execute_timeline_prompt:
                                    edited_segment_path = project_output_path(f"source_segment_{position}_edited.mp4")
                                    segment_path = execute_timeline_prompt(
                                        segment_path,
                                        directive,
                                        edited_segment_path,
                                        operations=operations,
                                    )
                                elif has_part_specific_prompt and directive and directive != user_prompt:
                                    edited_segment_path = project_output_path(f"source_segment_{position}_edited.mp4")
                                    segment_path = run_editing_agent(
                                        directive,
                                        [segment_path],
                                        ui_options=ui_pipeline_options,
                                        output_dir=project_output_dir(),
                                    )
                                segment_paths.append(segment_path)
                            pipeline_video_path = assemble_timeline(
                                segment_paths,
                                project_output_path("multi_part_timeline.mp4"),
                            )
                            st.session_state.timeline_output = pipeline_video_path
                            st.info(f"Batch timeline assembled from {len(segment_paths)} selected parts of the same source video.")

                        elif enable_timeline and timeline_mode == "Multi-clip sequence":
                            if not assemble_timeline or not trim_clip_for_timeline:
                                raise RuntimeError("Timeline engine is unavailable. Check production_features.py and its dependencies.")
                            if len(editor_order) < 2:
                                raise ValueError("Add at least one additional clip to build an editorial timeline.")

                            upload_map = {f"primary::{uploaded_video.name}": (uploaded_video, video_path)}
                            for index, timeline_file in enumerate(timeline_files or []):
                                clip_id = f"clip::{index}::{timeline_file.name}"
                                upload_map[clip_id] = (timeline_file, save_uploaded_file(timeline_file))

                            has_sequence_part_prompt = bool(re.search(
                                r"\bpart\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
                                user_prompt,
                                re.IGNORECASE,
                            ))
                            sequence_directives = {}
                            sequence_operations = {}
                            if has_sequence_part_prompt and parse_multi_part_directives:
                                sequence_directives = parse_multi_part_directives(
                                    user_prompt,
                                    part_count=len(editor_order),
                                    selected_parts=list(range(len(editor_order))),
                                )
                                for sequence_index, directive in sequence_directives.items():
                                    try:
                                        sequence_operations[sequence_index] = parse_timeline_prompt(directive) if parse_timeline_prompt else []
                                    except PromptTimelineError:
                                        sequence_operations[sequence_index] = []
                                has_part_specific_prompt = True
                                pipeline_prompt = "Preserve the assembled clip sequence exactly; only apply the selected global pipeline options."

                            timeline_paths = []
                            for position, clip_id in enumerate(editor_order):
                                if clip_id not in upload_map:
                                    continue
                                upload_file, source_path = upload_map[clip_id]
                                if source_path != video_path:
                                    with open(source_path, "wb") as clip_handle:
                                        clip_handle.write(upload_file.getbuffer())
                                trim = editor_trims.get(clip_id, {"start": 0.0, "end": 0.0})
                                trim_start = float(trim.get("start", 0.0))
                                trim_end = float(trim.get("end", 0.0))
                                if trim_start > 0.0 or trim_end > 0.0:
                                    trimmed_path = project_output_path(f"timeline_editor_clip_{position + 1}.mp4")
                                    source_path = trim_clip_for_timeline(source_path, trimmed_path, trim_start, trim_end)
                                directive = sequence_directives.get(position - 1, "")
                                operations = sequence_operations.get(position - 1, [])
                                if operations and execute_timeline_prompt:
                                    edited_path = project_output_path(f"sequence_clip_{position + 1}_edited.mp4")
                                    source_path = execute_timeline_prompt(
                                        source_path,
                                        directive,
                                        edited_path,
                                        operations=operations,
                                    )
                                elif has_sequence_part_prompt and directive and directive != user_prompt:
                                    source_path = run_editing_agent(
                                        directive,
                                        [source_path],
                                        ui_options=ui_pipeline_options,
                                        output_dir=project_output_dir(),
                                    )
                                timeline_paths.append(source_path)

                            if len(timeline_paths) < 2:
                                raise ValueError("The timeline needs at least two valid clips.")
                            canonical_clips = []
                            for order, (clip_id, source_path) in enumerate(zip(editor_order, timeline_paths)):
                                trim = editor_trims.get(clip_id, {"start": 0.0, "end": 0.0})
                                canonical_clips.append(
                                    TimelineClip(
                                        source_path=source_path,
                                        order=order,
                                        trim_start=float(trim.get("start", 0.0)),
                                        trim_end=(float(trim["end"]) if float(trim.get("end", 0.0)) > 0 else None),
                                    )
                                )
                            # Guard: ensure a project is open before writing timeline.
                            if not isinstance(st.session_state.get("project"), ProjectState):
                                st.session_state.project = ProjectState(name="Untitled Project")
                            st.session_state.project.set_timeline(canonical_clips)
                            persist_project()
                            pipeline_video_path = assemble_timeline(
                                timeline_paths,
                                project_output_path("timeline_assembled.mp4"),
                            )
                            st.session_state.timeline_output = pipeline_video_path
                            st.info(f"Editorial timeline assembled from {len(timeline_paths)} clips in your editor order.")

                        saved_paths = [pipeline_video_path]

                        if uploaded_audio:
                            # Save once; reuse audio_path for both the pipeline and any TTS ducking.
                            audio_path = save_uploaded_file(uploaded_audio)
                            saved_paths.append(audio_path)
                        else:
                            audio_path = None

                        if uploaded_image:
                            logo_path = save_uploaded_file(uploaded_image)
                            saved_paths.append(logo_path)

                        # Persist pipeline settings before the heavy render so
                        # they survive a restart even if the render is interrupted.
                        record_project_settings(
                            target_format=auto_resize,
                            auto_silence=auto_silence,
                            auto_captions=auto_caps,
                            auto_highlight=auto_highlight,
                        )

                        out_path = run_editing_agent(
                            pipeline_prompt,
                            saved_paths,
                            ui_options=ui_pipeline_options,
                            output_dir=project_output_dir(),
                        )

                        if not has_part_specific_prompt and parse_timeline_prompt and execute_timeline_prompt:

                            try:
                                timeline_operations = parse_timeline_prompt(user_prompt)
                            except PromptTimelineError:
                                timeline_operations = []
                            if timeline_operations:
                                out_path = execute_timeline_prompt(
                                    out_path,
                                    user_prompt,
                                    project_output_path("prompt_timeline_render.mp4"),
                                    operations=timeline_operations,
                                )

                        if enable_chroma and chroma_bg_file and apply_chroma_key:
                            chroma_bg_path = save_uploaded_file(chroma_bg_file)
                            out_path = apply_chroma_key(out_path, chroma_bg_path, project_output_path("chroma_out.mp4"), key_color_hex=chroma_color)

                        if enable_transition and second_clip_file and apply_clip_transition:
                            second_clip_path = save_uploaded_file(second_clip_file)
                            out_path = apply_clip_transition(out_path, second_clip_path, project_output_path("trans_out.mp4"), transition_type=transition_type)

                        if enable_tts:
                            if not generate_expressive_tts or not apply_voiceover_to_video:
                                raise RuntimeError("Voiceover dependencies are unavailable. Install edge-tts and gTTS, then restart the app.")
                            if not tts_text.strip():
                                raise ValueError("Please enter a voiceover script before rendering.")
                            tts_audio_path = project_output_path("tts_narrative.mp3")
                            generate_expressive_tts(tts_text, voice_choice, tts_audio_path)
                            background_music_path = None
                            if uploaded_audio:
                                background_music_path = audio_path  # reuse already-saved path
                            voiceover_video_path = project_output_path("voiceover_master.mp4")
                            out_path = apply_voiceover_to_video(
                                out_path,
                                tts_audio_path,
                                voiceover_video_path,
                                background_music=background_music_path,
                                duck_background=bool(enable_ducking),
                            )
                            st.info("Voiceover was generated and mixed into the final video.")

                        if gen_thumbnail and generate_auto_thumbnail:
                            thumb_path = project_output_path("auto_thumbnail.jpg")
                            generate_auto_thumbnail(out_path, thumb_path, title_text=thumb_title)
                            st.session_state.thumbnail_output = thumb_path

                        if enable_mastering and normalize_audio_lufs:
                            out_path = normalize_audio_lufs(
                                out_path,
                                project_output_path("mastered_final.mp4"),
                                target_lufs=target_lufs,
                            )

                        if enable_contact_sheet and generate_contact_sheet:
                            st.session_state.contact_sheet_output = generate_contact_sheet(
                                out_path,
                                project_output_path("contact_sheet.jpg"),
                            )

                        if enable_omni_export and export_omni_platform_suite:
                            st.session_state.omni_outputs = export_omni_platform_suite(out_path, project_output_dir())

                        if enable_gemini_vision and analyze_video_emotions_and_hooks:
                            st.session_state.vision_analysis = analyze_video_emotions_and_hooks(out_path)

                        st.session_state.rendered_output = out_path
                        st.session_state.output_type = "video"
                        try:
                            st.session_state.viral_data = analyze_viral_score(out_path, "Video")
                        except Exception:
                            st.session_state.viral_data = {"status": "unavailable", "reason": "Analysis failed after render"}
                        record_project_result(video_path, out_path, st.session_state.viral_data)

                        st.markdown(stage_bar(["Validate","Assemble","Effects","Audio","Encode","Verify"],current=-1,completed=5), unsafe_allow_html=True)
                        _render_status.update(label="Render complete", state="complete", expanded=False)
                        st.success(":material/check_circle: Render complete — output ready below.")

                    except Exception as e:
                        _render_status.update(label="Render failed", state="error", expanded=True)
                        st.error(f"Execution Error: {e}")

        render_media_preview()
        st.markdown("</div>", unsafe_allow_html=True)

# --- View 3: Image Workstation ---
def render_image_studio(uploaded_image):
    # Creative-tool layout: tools/properties rail beside a dominant canvas.
    col_tools, col_canvas = st.columns([1.0, 1.45], gap="medium")

    with col_tools:
        st.markdown('<div class="studio-card">', unsafe_allow_html=True)
        st.markdown("#### :material/tune: Tools & Properties")
        
        tab_tools, tab_bg, tab_mask, tab_prompt = st.tabs(["Crop & LUT", "Background", "Inpainting", "Edit Prompt"])

        with tab_tools:
            enable_smart_crop = st.checkbox("Face-aware smart crop")
            crop_target_ratio = st.selectbox("Aspect Ratio", ["9:16", "1:1", "16:9", "4:5"])
            lut_preset = st.selectbox("Cinematic LUT grading", ["None", "teal_orange", "vintage_film", "cyberpunk"])

        with tab_bg:
            enable_bg_removal = st.checkbox("Remove background", key="bg_removal_toggle")
            bg_mode = st.radio(
                "Background Mode",
                ["Transparent", "Solid Color", "Image Background"],
                horizontal=True,
                key="bg_mode",
            )
            bg_hex_input = ""
            bg_image_file = None
            if bg_mode == "Solid Color":
                picked_color = st.color_picker("Choose Background Color", value="#FFFFFF", key="bg_color_picker")
                bg_hex_input = picked_color
                bg_hex_manual = st.text_input(
                    "Or enter HEX value:",
                    value=picked_color,
                    key="bg_hex_manual",
                    help="Accepts #RGB, #RRGGBB, or #RRGGBBAA formats.",
                )
                if bg_hex_manual.strip() != picked_color:
                    bg_hex_input = bg_hex_manual.strip()
                if validate_hex_color and not validate_hex_color(bg_hex_input):
                    st.error(f"Invalid HEX color '{bg_hex_input}'. Accepted formats: #RGB, #RRGGBB, #RRGGBBAA. Falling back to the picker color on render.")
                # Color preview swatch
                st.markdown(
                    f'<div style="background-color:{bg_hex_input};width:100%;height:32px;'
                    f'border-radius:6px;border:1px solid #555;display:flex;align-items:center;'
                    f'justify-content:center;color:#000;font-size:13px;">Preview: {bg_hex_input}</div>',
                    unsafe_allow_html=True,
                )
            elif bg_mode == "Image Background":
                bg_image_file = st.file_uploader("Background Image", type=["png", "jpg", "jpeg"], key="bg_image_up")

        with tab_mask:
            mask_file = st.file_uploader("Inpainting Mask (.png)", type=["png", "jpg"], key="mask_up")

        with tab_prompt:
            user_prompt = st.text_area(
                "Natural Language Edit Directive:",
                value="Remove background, set background to solid blue (#0000FF), crop to 9:16, increase contrast, and add soft vignette.",
                height=110, key="i_prompt"
            )

        st.markdown("</div>", unsafe_allow_html=True)

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            one_click_i = st.button(":material/auto_fix_high: One-Click AI Enhance", key="btn_one_click_i")
        with btn_col2:
            render_btn = st.button(":material/smart_display: Render Image", key="btn_i_render")

    with col_canvas:
        st.markdown('<div class="studio-card">', unsafe_allow_html=True)
        st.markdown("#### :material/image: Canvas")

        if one_click_i:
            if not uploaded_image:
                st.error("Please upload an image in the Asset Vault (Sidebar) first.")
            else:
                if render_agent_telemetry_live:
                    render_agent_telemetry_live()
                with st.spinner("✨ Running AI Image Auto-Enhancement..."):
                    try:
                        img_path = save_uploaded_file(uploaded_image)
                        st.session_state.original_input = img_path
                        out_path = auto_enhance_image(img_path, output_dir=project_output_dir())
                        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
                            raise RuntimeError("Image enhancement produced no usable output.")
                        st.session_state.rendered_output = out_path
                        st.session_state.output_type = "image"
                        try:
                            st.session_state.viral_data = analyze_viral_score(out_path, "Image")
                        except Exception:
                            st.session_state.viral_data = {"status": "unavailable", "reason": "Analysis failed after render"}
                        record_project_result(img_path, out_path, st.session_state.viral_data)

                        st.success(":material/check_circle: Image enhancement complete.")
                    except Exception as e:
                        st.error(f"Image Enhancement Failed: {e}")

        if render_btn:
            if render_agent_telemetry_live:
                render_agent_telemetry_live()
            if not uploaded_image:
                st.error("Please upload an image in the Asset Vault (Sidebar) first.")
            else:
                with st.spinner("Processing image agent pipeline..."):
                    try:
                        img_path = save_uploaded_file(uploaded_image)
                        st.session_state.original_input = img_path

                        # Persist image pipeline settings before the render.
                        record_project_settings(
                            bg_mode=bg_mode,
                            lut_preset=lut_preset,
                            crop_target_ratio=crop_target_ratio,
                        )

                        out_path = run_image_agent(user_prompt, img_path, output_dir=project_output_dir())

                        # Background Removal + Replacement Pipeline
                        if enable_bg_removal and remove_image_background and composite_on_background:
                            cutout_path = project_output_path("bg_cutout.png")
                            try:
                                remove_image_background(out_path, cutout_path)
                                if bg_mode == "Transparent":
                                    out_path = composite_on_background(cutout_path, "transparent", project_output_path("bg_result.png"))
                                elif bg_mode == "Solid Color":
                                    if validate_hex_color and validate_hex_color(bg_hex_input):
                                        hex_val = bg_hex_input
                                    else:
                                        hex_val = picked_color
                                        st.warning(f"Invalid HEX '{bg_hex_input}'; used picker color {picked_color} instead.")
                                    out_path = composite_on_background(cutout_path, hex_val, project_output_path("bg_result.png"))
                                elif bg_mode == "Image Background" and bg_image_file:
                                    bg_img_path = save_uploaded_file(bg_image_file)
                                    out_path = composite_on_background(cutout_path, bg_img_path, project_output_path("bg_result.png"))
                                # hex_val is only defined when bg_mode=="Solid Color"; guard the assignment.
                                st.session_state.bg_color_applied = (
                                    hex_val if bg_mode == "Solid Color" else bg_mode.lower()
                                )
                            except RuntimeError as bg_err:
                                st.warning(f"Background removal unavailable: {bg_err}")
                        elif enable_bg_removal and not remove_image_background:
                            st.warning("Background removal requires the 'rembg' package. Install with: pip install rembg")

                        if mask_file and inpaint_mask_area:
                            mask_path = save_uploaded_file(mask_file)
                            out_path = inpaint_mask_area(out_path, mask_path, project_output_path("inpainted.png"))

                        if enable_smart_crop and smart_face_crop:
                            out_path = smart_face_crop(out_path, project_output_path("smart_cropped.png"), target_ratio=crop_target_ratio)

                        if lut_preset != "None" and apply_cinematic_color_grading:
                            out_path = apply_cinematic_color_grading(out_path, project_output_path("lut_graded.png"), preset=lut_preset)

                        st.session_state.rendered_output = out_path
                        st.session_state.output_type = "image"
                        try:
                            st.session_state.viral_data = analyze_viral_score(out_path, "Image")
                        except Exception:
                            st.session_state.viral_data = {"status": "unavailable", "reason": "Analysis failed after render"}
                        record_project_result(img_path, out_path, st.session_state.viral_data)

                        st.success(":material/check_circle: Image render complete.")

                    except Exception as e:
                        st.error(f"Execution Error: {e}")

        render_media_preview()
        st.markdown("</div>", unsafe_allow_html=True)

# --- View 4: Campaign Swarm Workstation ---
def render_campaign_factory():
    col1, col2 = st.columns([1.0, 1.45], gap="medium")
    
    with col1:
        st.markdown('<div class="studio-card">', unsafe_allow_html=True)
        st.markdown("#### :material/hub: Campaign Setup")
        campaign_name = st.text_input("Project / Product Name", value="anim8 3D Launch")
        target_platform = st.selectbox("Target Platform", ["YouTube Shorts / TikTok", "Instagram Carousel", "LinkedIn Showcase"])

        c_up1, c_up2 = st.columns(2)
        with c_up1:
            campaign_image = st.file_uploader("Raw Product Image", type=["png", "jpg", "jpeg"], key="camp_img_up")
        with c_up2:
            campaign_video = st.file_uploader("Source Video (Opt)", type=["mp4", "mov", "avi"], key="camp_vid_up")

        webhook_url = st.text_input("n8n Webhook Endpoint", value="", placeholder="https://n8n.instance.com/webhook/...")
        launch_btn = st.button(":material/rocket_launch: Deploy Agent Swarm", key="btn_campaign_launch")
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="studio-card">', unsafe_allow_html=True)
        st.markdown("#### :material/terminal: Execution Console")

        if launch_btn:
            if not campaign_image and not campaign_video:
                st.error("Please upload at least an image or a video for the campaign.")
            else:
                if render_agent_telemetry_live:
                    render_agent_telemetry_live()

                with st.status("Agent swarm executing...", expanded=True) as status:
                    try:
                        st.write("Initializing Gemini Director Agent...")
                        img_path = os.path.join("uploads", "default_placeholder.png")
                        if campaign_image:
                            img_path = save_uploaded_file(campaign_image)
                        else:
                            if not os.path.exists(img_path):
                                Image.new("RGB", (800, 800), color=(50, 50, 50)).save(img_path)

                        vid_path = None
                        if campaign_video:
                            vid_path = save_uploaded_file(campaign_video)

                        st.write("Synthesizing multi-platform campaign assets...")
                        blueprint = run_autonomous_campaign(
                            product_name=campaign_name,
                            raw_image_path=img_path,
                            target_platform=target_platform,
                            raw_video_path=vid_path,
                            webhook_url=webhook_url,
                            output_dir=project_output_dir(),
                        )

                        st.session_state.campaign_data = blueprint
                        try:
                            st.session_state.viral_data = analyze_viral_score(img_path, "Campaign")
                        except Exception:
                            st.session_state.viral_data = {"status": "unavailable", "reason": "Campaign analysis unavailable"}
                        status.update(label="Campaign compiled successfully", state="complete", expanded=False)

                        st.success(":material/check_circle: Campaign assets generated.")
                    except Exception as campaign_err:
                        status.update(label="❌ Campaign Failed", state="error", expanded=True)
                        st.error(f"Campaign Swarm Failed: {campaign_err}")

        if st.session_state.campaign_data:
            data = st.session_state.campaign_data
            st.success(f"Campaign Package Ready: {data.get('campaign_name')}")

            col_a, col_b = st.columns(2)
            with col_a:
                hero_img = data.get("assets", {}).get("hero_image", "")
                if hero_img and os.path.exists(hero_img):
                    st.image(hero_img, caption="Hero Visual Asset", use_container_width=True)
            with col_b:
                promo_vid = data.get("assets", {}).get("promo_video", "")
                if promo_vid and os.path.exists(promo_vid) and promo_vid.endswith((".mp4", ".mov", ".mkv")):
                    st.video(promo_vid)

            st.markdown("##### 7-Day Asset Distribution Schedule")
            df = pd.DataFrame(data.get("content_schedule", []))
            st.dataframe(df, use_container_width=True)

            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button("📥 Download Schedule (.csv)", data=csv, file_name=f"{campaign_name}_schedule.csv", mime="text/csv")
            with col_btn2:
                json_str = json.dumps(data.get("n8n_payload", {}), indent=2)
                st.download_button("🔗 Export n8n Workflow JSON", data=json_str, file_name=f"{campaign_name}_n8n.json", mime="application/json")
        else:
            st.info("Configure campaign parameters on the left to activate execution.")
        
        st.markdown("</div>", unsafe_allow_html=True)

# --- Application Entry Router ---
def render_workspace_header(app_mode: str, gemini_connected: bool, ffmpeg_connected: bool):
    """Render the persistent top bar across all workspaces.

    Phase 5: Single coherent shell row.
    Left: ☰ nav trigger + GENFORGE brand
    Centre: workspace title + active project tag + subtitle
    Right: save status + system chips

    The ☰ button is a real Streamlit button injected via columns so it stays
    keyboard-accessible and works with Streamlit's sidebar toggle.
    """
    page_names = {
        ":material/home: Home":                   ("Home",           "Project launcher — open, create, or manage projects."),
        ":material/videocam: Video Studio":        ("Video Studio",   "Timeline, AI editing, transitions, and render pipeline."),
        ":material/image: Image Studio":           ("Image Studio",   "Canvas, background removal, grading, and export."),
        ":material/hub: Campaign Swarm":           ("Campaign Swarm", "Multi-platform asset generation and n8n export."),
        ":material/star: Highlights":              ("AI Highlights",  "Audio-energy highlight detection and platform rendering."),
        ":material/description: Script Studio":    ("Script Studio",  "AI-generated scripts, versions, and voiceover hand-off."),
        ":material/graphic_eq: Audio Tools":       ("Audio Tools",    "Waveforms, EQ, denoise, fades, and level control."),
        ":material/rocket_launch: Campaign Hub":   ("Campaign Hub",   "Campaign strategy, thumbnails, and performance feedback."),
        ":material/cloud_upload: Publishing":      ("Publishing",     "Validate, schedule, and track platform uploads."),
    }
    title, subtitle = page_names.get(app_mode, ("Studio", "Autonomous media production workspace."))

    project = st.session_state.get("project")
    project_name = html.escape(project.name) if isinstance(project, ProjectState) else ""
    project_id_short = project.project_id[:8] if isinstance(project, ProjectState) else ""
    project_tag_html = (
        f"<span class='gf-project-tag'>"
        f"<span aria-label='Active project'>{project_name}</span>"
        f"<span style='color:var(--gf-faint);font-weight:400;'> · {project_id_short}</span>"
        f"</span>"
        if isinstance(project, ProjectState)
        else ""
    )

    save_html = ""
    if isinstance(project, ProjectState):
        save_status = st.session_state.get("save_status", "saved")
        save_error  = st.session_state.get("save_error")
        save_html   = save_chip(save_status, save_error)

    ai_chip     = (
        f"<span class='gf-status-chip {'chip-on' if gemini_connected else 'chip-off'}' "
        f"title='{'Gemini connected' if gemini_connected else 'GEMINI_API_KEY not set'}' "
        f"aria-label='Gemini: {'on' if gemini_connected else 'off'}'>Gemini</span>"
    )
    engine_chip = (
        f"<span class='gf-status-chip {'chip-on' if ffmpeg_connected else 'chip-off'}' "
        f"title='{'FFmpeg on PATH' if ffmpeg_connected else 'FFmpeg missing'}' "
        f"aria-label='FFmpeg: {'active' if ffmpeg_connected else 'missing'}'>FFmpeg</span>"
    )

    # Shell: header HTML (single full-width block — the brand+nav+status are all inside the gf-app-header div)
    st.markdown(
        f"<div class='gf-app-header' role='banner'>"
        # Brand cluster
        f"<div class='gf-topbar-left'>"
        f"<div class='gf-brand'><span class='gf-brand-glyph' aria-hidden='true'>\u25C8</span> GENFORGE</div>"
        f"<div class='gf-kicker'>AI media studio</div>"
        f"</div>"
        # Centre: workspace title + project chip
        f"<div class='gf-header-center'>"
        f"<div style='display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;'>"
        f"<span style='font-size:.92rem;font-weight:700;color:var(--gf-fg);letter-spacing:-.022em;'>"
        f"{html.escape(title)}</span>"
        f"{project_tag_html}"
        f"</div>"
        f"<div class='gf-page-note'>{html.escape(subtitle)}</div>"
        f"</div>"
        # Right: save + status chips
        f"<div class='gf-header-status'>"
        f"{save_html}"
        f"{ai_chip}"
        f"{engine_chip}"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def main():
    init_session_state()
    inject_premium_theme()
    inject_professional_overrides()

    gemini_connected = bool(os.getenv("GEMINI_API_KEY"))
    ffmpeg_connected = check_ffmpeg()
    app_mode = st.session_state.app_mode
    st.session_state["workspace_navigation_widget"] = app_mode
    _sync_theme_widget_state()

    with st.sidebar:
        # ── Brand ────────────────────────────────────────────────
        st.markdown(
            "<div style='padding:4px 2px 18px;'>"
            "<div class='gf-brand'>"
            "<span class='gf-brand-glyph' aria-hidden='true'>\u25C8</span> GENFORGE"
            "</div>"
            "<div class='gf-kicker'>AI Media Studio</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        # ── Workspace navigation ─────────────────────────────────
        st.markdown("<div class='gf-section-label'>Workspace</div>", unsafe_allow_html=True)
        app_mode = st.radio(
            "Workspace Navigation",
            WORKSPACE_OPTIONS,
            label_visibility="collapsed",
            key="workspace_navigation_widget",
            on_change=_sync_workspace_navigation,
            args=("workspace_navigation_widget",),
        )
        st.markdown("<div class='gf-section-label'>Appearance</div>", unsafe_allow_html=True)
        st.radio(
            "Theme",
            ["dark", "light"],
            format_func=lambda value: "🌙 Dark" if value == "dark" else "☀️ Light",
            key="theme_selector",
            on_change=_sync_theme_selection,
            horizontal=True,
            label_visibility="collapsed",
        )
        # ── System status ────────────────────────────────────────
        st.markdown("<div class='gf-section-label'>System</div>", unsafe_allow_html=True)
        st.markdown(
            sys_pill("Gemini API: Connected" if gemini_connected else "Gemini API: Key Missing", gemini_connected) +
            sys_pill("FFmpeg: Active" if ffmpeg_connected else "FFmpeg: Missing", ffmpeg_connected),
            unsafe_allow_html=True,
        )
        # ── Asset vault ──────────────────────────────────────────
        st.markdown("<div class='gf-section-label'>Asset Vault</div>", unsafe_allow_html=True)
        uploaded_video = st.file_uploader("Primary Video", type=["mp4", "mov", "avi", "mkv"], key="video_up")
        uploaded_audio = st.file_uploader("Audio / BGM", type=["mp3", "wav", "m4a"], key="audio_up")
        uploaded_image = st.file_uploader("Watermark / Image", type=["png", "jpg", "jpeg", "webp"], key="img_up")
        if st.button(":material/delete_sweep: Clear Vault", key="btn_clear",
                     help="Remove all uploaded files from the current session"):
            clear_assets()
            st.rerun()

    _render_command_palette()

    render_workspace_header(app_mode, gemini_connected, ffmpeg_connected)

    if app_mode == ":material/home: Home":
        render_welcome_hero()
    elif app_mode == ":material/hub: Campaign Swarm":
        render_campaign_factory()
    elif app_mode == ":material/videocam: Video Studio":
        render_video_studio(uploaded_video, uploaded_audio, uploaded_image)
    elif app_mode == ":material/image: Image Studio":
        render_image_studio(uploaded_image)
    elif app_mode == ":material/star: Highlights":
        if render_highlights_page:
            render_highlights_page()
        else:
            st.warning("**Highlights unavailable** — module could not be loaded.")
    elif app_mode == ":material/description: Script Studio":
        if render_script_page:
            render_script_page()
        else:
            st.warning("**Script Studio unavailable** — module could not be loaded.")
    elif app_mode == ":material/graphic_eq: Audio Tools":
        if render_audio_tools_page:
            render_audio_tools_page()
        else:
            st.warning("**Audio Tools unavailable** — module could not be loaded.")
    elif app_mode == ":material/rocket_launch: Campaign Hub":
        if render_campaign_hub_page:
            render_campaign_hub_page()
        else:
            st.warning("**Campaign Hub unavailable** — module could not be loaded.")
    elif app_mode == ":material/cloud_upload: Publishing":
        if render_publishing_page:
            render_publishing_page()
        else:
            st.warning("**Publishing unavailable** — module could not be loaded.")

if __name__ == "__main__":
    main()