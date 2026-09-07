"""Studio pages for the Phase 1–12 feature expansion.

Each page reuses the canonical services (never re-implements them), reads and
writes the shared ProjectState in session state, and reports optional
dependencies honestly (FEATURE UNAVAILABLE) instead of faking results.
"""

from __future__ import annotations

import os
import uuid

import pandas as pd
import streamlit as st

from services.project_model import ProjectState
from services.project_store import ProjectStore

_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
                       ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg", ".webp"}


def _project() -> ProjectState:
    project = st.session_state.get("project")
    if not isinstance(project, ProjectState):
        project = ProjectState()
        st.session_state.project = project
    return project


def _persist() -> None:
    project = st.session_state.get("project")
    if isinstance(project, ProjectState):
        ProjectStore().save(project)


def _output_dir() -> str:
    directory = os.path.join("outputs", _project().project_id)
    os.makedirs(directory, exist_ok=True)
    return directory


def _save_upload(uploaded_file, key_label: str) -> str | None:
    """Store an upload under the project directory with a safe identity."""
    if uploaded_file is None:
        return None
    extension = os.path.splitext(os.path.basename(uploaded_file.name))[1].lower()
    if extension not in _ALLOWED_EXTENSIONS:
        st.error(f"Unsupported upload type: {extension or 'unknown'}")
        return None
    destination = os.path.join(_output_dir(), f"{uuid.uuid4().hex}_{key_label}{extension}")
    with open(destination, "wb") as handle:
        handle.write(uploaded_file.getbuffer())
    return destination


def _card_open(title: str, subtitle: str = "") -> None:
    st.markdown(f"<div class='studio-card'><div class='gf-kicker'>{subtitle}</div>"
                f"<h3>{title}</h3>", unsafe_allow_html=True)


def _card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- Highlights
def render_highlights_page() -> None:
    from services.highlights import detect_highlights, render_highlight, render_highlight_versions
    from services.platform_profiles import PLATFORM_PROFILES

    _card_open("AI Highlights Generator", "Phase 1 — audio-energy detection, canonical trim renderer")
    source = _save_upload(st.file_uploader("Source video", type=["mp4", "mov", "mkv", "avi"], key="hl_video_up"), "highlight_source")
    if source:
        st.session_state.hl_source = source
    source = st.session_state.get("hl_source")
    if not source:
        st.info("Upload a video to detect highlights.")
        _card_close()
        return

    count = st.slider("Candidates to detect", 1, 5, 3, key="hl_count")
    if st.button(":material/search: Detect Highlights", key="btn_hl_detect"):
        with st.spinner("Scoring audio energy windows..."):
            try:
                st.session_state.hl_candidates = detect_highlights(source, count=count)
            except Exception as exc:
                st.error(f"HIGHLIGHT DETECTION UNAVAILABLE: {exc}")
                st.session_state.hl_candidates = []

    candidates = st.session_state.get("hl_candidates") or []
    if candidates:
        # Compact highlight cards: range, score, reason (canonical candidates list).
        for index, candidate in enumerate(candidates):
            st.markdown(
                f"<div class='gf-row-card'><div><div class='gf-row-title'>Highlight {index + 1} · "
                f"{candidate.start:.1f}s → {candidate.end:.1f}s</div>"
                f"<div class='gf-row-sub'>{candidate.reason} · hook: {candidate.hook}</div></div>"
                f"<div class='gf-row-side'><span class='gf-status-tag ok'>score {candidate.score}</span>"
                f"<span class='gf-row-sub'>{candidate.end - candidate.start:.1f}s long</span></div></div>",
                unsafe_allow_html=True,
            )

        selected = st.selectbox("Highlight to render", range(len(candidates)),
                                format_func=lambda i: f"#{i} — {candidates[i].start:.1f}s to {candidates[i].end:.1f}s (score {candidates[i].score})",
                                key="hl_select")
        platforms = st.multiselect("Platform versions", list(PLATFORM_PROFILES), key="hl_platforms")
        preview_encode = st.checkbox("Fast preview encode (review only, not publish quality)",
                                     value=False, key="hl_preview_encode")
        profile = "preview" if preview_encode else "final"
        if st.button(":material/movie: Render Highlight", key="btn_hl_render"):
            with st.spinner("Rendering through the canonical trim pipeline..."):
                try:
                    if platforms:
                        versions = render_highlight_versions(candidates[selected], _output_dir(), platforms,
                                                             profile=profile)
                    else:
                        versions = {"master": render_highlight(candidates[selected], _output_dir(),
                                                               profile=profile)}
                    st.session_state.hl_rendered = versions
                    _project().add_version(versions["master"], analytics={"highlight": candidates[selected].model_dump()})
                    _persist()
                except Exception as exc:
                    st.error(f"RENDER UNAVAILABLE: {exc}")

    rendered = st.session_state.get("hl_rendered")
    if rendered and os.path.isfile(rendered.get("master", "")):
        st.video(rendered["master"])
        for platform, path in rendered.items():
            if platform != "master" and os.path.isfile(path):
                with st.expander(f"{platform} version"):
                    st.video(path)
    _card_close()


# ------------------------------------------------------------- Script Studio
def render_script_page() -> None:
    from services.script_studio import (
        SUPPORTED_PLATFORMS, SUPPORTED_TONES, ScriptRequest,
        generate_script, save_script_version, script_to_voiceover,
    )

    _card_open("AI Script Studio", "Phase 5 — validated Gemini scripts, versioned in the project")
    with st.form("script_form"):
        topic = st.text_input("Topic", key="sc_topic")
        audience = st.text_input("Audience", key="sc_audience")
        col_a, col_b = st.columns(2)
        platform = col_a.selectbox("Platform", SUPPORTED_PLATFORMS, key="sc_platform")
        tone = col_b.selectbox("Tone", SUPPORTED_TONES, key="sc_tone")
        duration = st.number_input("Target duration (s)", 10.0, 3600.0, 60.0, key="sc_duration")
        goal = st.text_input("Goal (optional)", key="sc_goal")
        submitted = st.form_submit_button(":material/edit_note: Generate Script")

    if submitted:
        try:
            request = ScriptRequest(topic=topic, audience=audience, platform=platform,
                                    duration_seconds=duration, tone=tone, goal=goal)
        except ValueError as exc:
            st.error(str(exc))
        else:
            with st.spinner("Writing script..."):
                result = generate_script(request)
            if result["status"] == "generated":
                version = save_script_version(_project(), result["script"], label=f"{platform} draft")
                _persist()
                st.success(f"Script generated and stored (version {version['script_id'][:8]}).")
                script = result["script"]
                st.markdown(f"**Hook:** {script['hook']}\n\n**Intro:** {script['introduction']}\n\n"
                            f"**Body:** {script['body']}\n\n**CTA:** {script['cta']}")
                st.session_state.sc_last_text = script["short_version"]
            else:
                st.warning(result["message"])

    if st.session_state.get("sc_last_text") and st.button(":material/record_voice_over: Render Voiceover", key="btn_sc_tts"):
        destination = os.path.join(_output_dir(), f"{uuid.uuid4().hex}_voiceover.mp3")
        tts_result = script_to_voiceover(st.session_state.sc_last_text, destination)
        if tts_result["status"] == "rendered":
            st.audio(tts_result["path"])
        else:
            st.warning(tts_result["message"])

    scripts = _project().scripts
    if scripts:
        with st.expander(f"Stored script versions ({len(scripts)})"):
            st.dataframe(pd.DataFrame([{
                "Label": entry.get("label"), "Created": entry.get("created_at"),
                "Hook": entry.get("script", {}).get("hook", "")[:80],
            } for entry in scripts]), use_container_width=True)
    _card_close()


# --------------------------------------------------------------- Audio Tools
def render_audio_tools_page() -> None:
    from services.audio_tools import (
        EQ_PRESETS, FadeSpec, apply_eq_preset, apply_fades,
        enhance_voice, reduce_noise, render_waveform_png,
    )

    _card_open("Advanced Audio Tools", "Phase 4 — waveform, denoise, voice enhance, EQ, fades")
    source = _save_upload(st.file_uploader("Audio or video source", type=["mp4", "mov", "mp3", "wav", "m4a"], key="at_source_up"), "audio_source")
    if source:
        st.session_state.at_source = source
    source = st.session_state.get("at_source")
    if not source:
        st.info("Upload an audio or video file to process.")
        _card_close()
        return

    tool = st.radio("Tool", ["Waveform", "Noise Reduction", "Voice Enhance", "EQ Preset", "Fades"],
                    horizontal=True, key="at_tool")
    destination = os.path.join(_output_dir(), f"{uuid.uuid4().hex}_audio")

    if st.button("▶️ Run", key="btn_at_run"):
        try:
            with st.spinner("Processing audio..."):
                if tool == "Waveform":
                    output = destination + ".png"
                    render_waveform_png(source, output)
                    st.image(output)
                elif tool == "Noise Reduction":
                    output = reduce_noise(source, destination + ".mp4")
                    st.video(output)
                elif tool == "Voice Enhance":
                    output = enhance_voice(source, destination + ".mp4")
                    st.video(output)
                elif tool == "EQ Preset":
                    preset = st.session_state.get("at_eq", next(iter(EQ_PRESETS)))
                    output = apply_eq_preset(source, destination + ".mp4", preset)
                    st.video(output)
                else:
                    fade_in = st.session_state.get("at_fade_in", 0.5)
                    fade_out = st.session_state.get("at_fade_out", 0.5)
                    spec = FadeSpec(fade_in=fade_in, fade_out=fade_out)
                    output = apply_fades(source, destination + ".mp4", spec)
                    st.video(output)
            if tool != "Waveform":
                _project().add_version(output, analytics={"audio_tool": tool})
                _persist()
        except Exception as exc:
            st.error(f"AUDIO TOOL UNAVAILABLE: {exc}")

    if tool == "EQ Preset":
        st.selectbox("EQ preset", list(EQ_PRESETS), key="at_eq")
    if tool == "Fades":
        st.slider("Fade in (s)", 0.0, 5.0, 0.5, key="at_fade_in")
        st.slider("Fade out (s)", 0.0, 5.0, 0.5, key="at_fade_out")
    _card_close()


# -------------------------------------------------------------- Campaign Hub
def render_campaign_hub_page() -> None:
    from services.campaign_builder import CampaignBrief, build_campaign
    from services.performance import (
        fetch_platform_metrics, interpret_metrics, measure_local_metrics,
        recommend_next_campaign, record_performance,
    )
    from services.platform_profiles import PLATFORM_PROFILES
    from services.publishing import publish_campaign_assets

    project = _project()
    _card_open("Campaign Hub", "Phase 10–12 — builder, truthful publishing, performance feedback")

    with st.form("campaign_brief"):
        col_a, col_b = st.columns(2)
        brand = col_a.text_input("Brand", key="cb_brand")
        topic = col_b.text_input("Topic / product", key="cb_topic")
        goal = st.text_input("Goal", placeholder="e.g. grow awareness, drive sales", key="cb_goal")
        audience = st.text_input("Audience", key="cb_audience")
        platforms = st.multiselect("Platforms", list(PLATFORM_PROFILES), default=["TikTok", "YouTube"], key="cb_platforms")
        col_c, col_d = st.columns(2)
        posts_per_week = col_c.number_input("Posts per week", 1, 30, 3, key="cb_freq")
        horizon_weeks = col_d.number_input("Horizon (weeks)", 1, 12, 4, key="cb_horizon")
        campaign_video = st.file_uploader("Campaign source video (optional)", type=["mp4", "mov", "mkv"], key="cb_video_up")
        submitted = st.form_submit_button(":material/rocket_launch: Build Campaign")

    if submitted:
        try:
            brief = CampaignBrief(brand=brand, goal=goal, audience=audience, platforms=platforms,
                                  posts_per_week=int(posts_per_week), topic=topic,
                                  horizon_weeks=int(horizon_weeks))
        except ValueError as exc:
            st.error(str(exc))
        else:
            video_path = _save_upload(campaign_video, "campaign_source")
            with st.spinner("Building campaign workspace..."):
                try:
                    campaign = build_campaign(project, brief, video_source=video_path)
                    _persist()
                    st.success(f"Campaign workspace built — status: {campaign['status'].upper()}")
                except Exception as exc:
                    st.error(f"CAMPAIGN BUILD UNAVAILABLE: {exc}")

    campaign = project.campaign
    if campaign:
        tab_plan, tab_assets, tab_publish, tab_perf = st.tabs(
            ["Plan", "Assets", "Publishing", "Performance"])

        with tab_plan:
            st.markdown(f"**CTA:** {campaign['cta']}")
            st.write("**Hashtags:** " + " ".join(campaign["hashtags"]))
            st.dataframe(pd.DataFrame(campaign["pillars"]), use_container_width=True)
            st.dataframe(pd.DataFrame([{
                "Date": entry["date"], "Platform": entry["platform"],
                "Pillar": entry["pillar"], "Topic": entry["content_topic"],
                "Script": entry["script_ref"] or "—",
            } for entry in campaign["calendar"]]), use_container_width=True)

        with tab_assets:
            for kind, entries in campaign["assets"].items():
                with st.expander(f"{kind.title()} ({len(entries)})"):
                    for entry in entries:
                        status = entry.get("status", "planned")
                        if status in ("rendered", "generated"):
                            st.success(f"{kind}: {status}" + (f" — {entry.get('path') or entry.get('script_id') or ''}"))
                        else:
                            st.warning(f"{kind}: {status} — {entry.get('message', 'unavailable')}")

        with tab_publish:
            st.caption("Publishing is only ever reported as confirmed after a real API/webhook acknowledgement.")
            if st.button(":material/cloud_upload: Attempt Publishing", key="btn_pub_run"):
                history = publish_campaign_assets(campaign)
                _persist()
                st.session_state.pub_history = history
            for entry in st.session_state.get("pub_history") or campaign.get("publish_history", []):
                icon = {"published": ":material/check_circle:", "scheduled": ":material/schedule:"}.get(entry["status"], ":material/block:")
                st.write(f"{icon} **{entry['platform']}** — {entry['status'].upper()}: {entry['message']}")

        with tab_perf:
            st.caption("Metrics are only shown where they can really be measured or fetched — never fabricated.")
            rendered_clip = next((clip for clip in campaign["assets"]["clips"]
                                  if clip.get("status") == "rendered" and clip.get("path")), None)
            if rendered_clip and os.path.isfile(rendered_clip["path"]):
                local = measure_local_metrics(rendered_clip["path"])
                st.metric("Clip duration (s)", local["metrics"]["duration"])
                st.metric("File size (KB)", round(local["metrics"]["file_size_bytes"] / 1024, 1))
            if st.button(":material/query_stats: Fetch Platform Metrics", key="btn_perf_run"):
                history = campaign.get("publish_history", [])
                confirmed = [entry for entry in history if entry.get("confirmed")]
                if not confirmed:
                    st.warning("METRICS UNAVAILABLE: no confirmed publications yet — platform analytics "
                               "APIs require official credentials and a published asset.")
                for entry in confirmed:
                    report = fetch_platform_metrics(entry["platform"], entry.get("external_id", ""))
                    if report["status"] == "fetched":
                        record_performance(project, entry, report)
                        interpretation = interpret_metrics(report["metrics"])
                        recommend_next_campaign(project, interpretation)
                        _persist()
                        st.dataframe(pd.DataFrame([report["metrics"]]), use_container_width=True)
                    else:
                        st.warning(report["message"])
    else:
        st.info("Fill in the brief and build a campaign to activate the workspace.")
    _card_close()
