import streamlit as st

try:
    from streamlit_image_comparison import image_comparison
except ImportError:
    image_comparison = None

# ---------------------------------------------------------
# FEATURE A: REAL-TIME AGENT TELEMETRY STEPPER
# ---------------------------------------------------------
def render_agent_telemetry_live():
    """Render honest job telemetry: real recorded stage timings only.

    No simulated sleeps and no fake percentages — this displays what the
    pipeline actually measured (stage name, status, real seconds). When no
    job has run yet it says so plainly.
    """
    import pandas as pd
    from services.stage_telemetry import JOB_STAGES, stage_timings

    st.markdown("### 🤖 Live Job Telemetry")
    records = stage_timings()
    if not records:
        st.caption("No render stages recorded yet. Run a job to see real stage timings.")
        return
    stages_done = [r["stage"] for r in records if r["status"] == "completed"]
    last = records[-1]
    st.caption(
        "Pipeline stages: " + " → ".join(JOB_STAGES)
        + f" — last stage: **{last['stage']}** ({last['status']}, {last['seconds']}s)"
    )
    st.dataframe(pd.DataFrame([
        {"Stage": r["stage"], "Status": r["status"], "Seconds": r["seconds"], "At": r["at"]}
        for r in records[-12:]
    ]), use_container_width=True)
    st.caption(f"Stages completed this session: {len(stages_done)}")



# ---------------------------------------------------------
# FEATURE C: BEFORE & AFTER COMPARISON SLIDER
# ---------------------------------------------------------
def render_media_comparison(original_path: str, enhanced_path: str, is_video: bool = False):
    """Renders interactive before/after media comparison."""
    st.markdown("---")
    st.markdown("### 🎚️ Interactive Original vs AI Enhanced Comparison")

    if not is_video and image_comparison:
        image_comparison(
            img1=original_path,
            img2=enhanced_path,
            label1="Original Raw Input",
            label2="GENFORGE AI Enhanced",
            width=700
        )
    else:
        # Side-by-side player fallback for video/media
        col_before, col_after = st.columns(2)
        with col_before:
            st.caption("🔴 Original Asset")
            if is_video:
                st.video(original_path)
            else:
                st.image(original_path, use_container_width=True)
        with col_after:
            st.caption("🟢 GENFORGE AI Enhanced")
            if is_video:
                st.video(enhanced_path)
            else:
                st.image(enhanced_path, use_container_width=True)