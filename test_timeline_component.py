"""Minimal standalone test for the genforge_timeline component.

Run with:
    python -m streamlit run test_timeline_component.py

This page renders ONLY the timeline component with one test clip.
If the component loads correctly here, GENFORGE integration is the issue.
If it still shows the warning, the issue is in the component itself.
"""
import streamlit as st
from components.timeline import timeline_component, component_is_available, _COMPONENT_DIR, _INDEX_HTML
import os

st.set_page_config(page_title="Timeline Component Test", layout="wide")
st.title("GENFORGE Timeline — Component Test")

st.write(f"**Component dir:** `{_COMPONENT_DIR}`")
st.write(f"**index.html exists:** `{os.path.isfile(_INDEX_HTML)}`")
st.write(f"**component_is_available():** `{component_is_available()}`")

st.divider()

if not component_is_available():
    st.error(f"Component frontend missing! Expected: {_INDEX_HTML}")
    st.stop()

st.write("Rendering component with 2 test clips:")

result = timeline_component(
    clips=[
        {
            "id": "test-clip-1",
            "label": "Test Clip A.mp4",
            "role": "Primary",
            "duration": 10.0,
            "trim_start": 0.0,
            "trim_end": 0.0,
            "thumbnail_b64": None,
            "has_audio": True,
            "transition": None,
        },
        {
            "id": "test-clip-2",
            "label": "Test Clip B.mp4",
            "role": "Clip",
            "duration": 7.5,
            "trim_start": 1.0,
            "trim_end": 6.5,
            "thumbnail_b64": None,
            "has_audio": False,
            "transition": "crossfade",
        },
    ],
    selected="test-clip-1",
    playhead=0.0,
    zoom=1.0,
    height=260,
    key="test_timeline",
)

st.divider()
if result:
    st.success(f"✓ Component event received!")
    st.json(result)
else:
    st.info("Waiting for first component event (interact with the timeline above)...")
