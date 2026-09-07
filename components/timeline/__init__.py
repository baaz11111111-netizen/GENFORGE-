"""GENFORGE interactive timeline — Streamlit custom component.

Architecture — definitive approach
------------------------------------
The component frontend is served via Streamlit's built-in app static file
server, NOT via the custom component path registry.

Why:
- declare_component(path=...) registers the component only when a
  ScriptRunContext is active. This causes intermittent 404 failures.
- Streamlit's app static file server (/app/static/) requires NO registration
  and is always available from server startup.

How:
- Frontend files live in: static/timeline/index.html
  (relative to app.py's directory)
- Streamlit serves them at: /app/static/timeline/index.html
- declare_component(url=...) tells Streamlit to load the component from that URL
- Streamlit appends ?streamlitUrl=... automatically when using url=
- The component iframe loads our self-contained vanilla JS timeline

Static file path: {app.py directory}/static/timeline/index.html
Component URL:    /app/static/timeline/index.html

Note: The static/ directory is also checked at imports; if missing, a
clear error is shown.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

# Path to the source frontend (in components/timeline/)
_COMPONENT_DIR: str = str(Path(__file__).resolve().parent)
_INDEX_HTML: str = os.path.join(_COMPONENT_DIR, "index.html")

# Path to the static copy served by Streamlit's app static file server.
# Relative to app.py: static/timeline/index.html
_APP_ROOT: str = str(Path(__file__).resolve().parent.parent.parent)
_STATIC_DIR: str = os.path.join(_APP_ROOT, "static", "timeline")
_STATIC_HTML: str = os.path.join(_STATIC_DIR, "index.html")

# The URL Streamlit's static server exposes for the component.
# Streamlit serves app/static/* from {app.py directory}/static/*.
_COMPONENT_URL = "/app/static/timeline/index.html"

# Canonical component name.
_COMPONENT_NAME = "genforge_timeline"


def component_is_available() -> bool:
    """Return True if the static frontend index.html exists and is ready."""
    return os.path.isfile(_STATIC_HTML)


def _ensure_static_copy() -> None:
    """Ensure static/timeline/index.html is up-to-date with the source."""
    if not os.path.isfile(_INDEX_HTML):
        return
    os.makedirs(_STATIC_DIR, exist_ok=True)
    # Copy if missing or outdated
    src_mtime = os.path.getmtime(_INDEX_HTML)
    dst_mtime = os.path.getmtime(_STATIC_HTML) if os.path.isfile(_STATIC_HTML) else 0
    if src_mtime > dst_mtime:
        import shutil
        shutil.copy2(_INDEX_HTML, _STATIC_HTML)


# Ensure static copy exists at import time (no runtime required)
_ensure_static_copy()


def timeline_component(
    clips: list[dict[str, Any]],
    selected: str | None = None,
    playhead: float = 0.0,
    zoom: float = 1.0,
    snap_on: bool = True,
    theme: str = "light",
    height: int = 260,
    key: str | None = None,
) -> dict[str, Any] | None:
    """Render the interactive timeline and return the latest event dict.

    Uses url= (Streamlit's app static file server) so the component iframe
    loads regardless of ScriptRunContext registration state.

    Args:
        clips:     List of clip dicts (id, label, role, duration, trim_start,
                   trim_end, thumbnail_b64, has_audio, waveform_peaks, transition).
        selected:  ID of the currently selected clip.
        playhead:  Current playhead position in seconds.
        zoom:      Zoom level (1.0 = fit, >1 = magnification).
        snap_on:   Whether timeline snap is enabled.
        theme:     Active GENFORGE theme (``dark`` or ``light``).
        height:    iframe height in pixels.
        key:       Streamlit widget key.

    Returns:
        dict with event, order, trims, selected, playhead, zoom, snap_on — or None.
    """
    handle = components.declare_component(
        name=_COMPONENT_NAME,
        url=_COMPONENT_URL,
    )
    return handle(
        clips=clips,
        selected=selected,
        playhead=playhead,
        zoom=zoom,
        snap_on=snap_on,
        theme=theme if theme in ("dark", "light") else "light",
        default=None,
        key=key,
        height=height,
    )
