"""Publishing workspace UI (§28).

Tabs: Connected Accounts · Publish & Schedule · Queue · History.

Rules honored in this UI:

* Unsupported controls are HIDDEN per the capability matrix (§5).
* Tokens are masked everywhere; secrets never render in the page (§6/§24).
* The checklist + preview + explicit confirmation gate every publish (§29/§30).
* AI suggestions are suggestions only — the user confirms, then publishes (§31).
* Until Phase 10 lands the official adapters, publishing runs against the
  scripted mock provider and the page says so plainly. No fake success (§39).
"""

from __future__ import annotations

import datetime as dt
import glob
import os

import streamlit as st

from services.publishing.accounts import AccountStore, TokenStore, mask_token
from services.publishing.batch import build_batch, pairs_for_campaign, pairs_for_project, queue_batch
from services.publishing.capabilities import PLATFORM_CAPABILITIES, capabilities_for
from services.publishing.history import PublishingStore
from services.publishing.manager import PublishingManager
from services.publishing.mock import MockPlatformProvider
from services.publishing.models import PublishingJob
from services.publishing.validation import METADATA_LIMITS, pre_publish_checklist

_STATE_BADGES = {
    "connected": "connected",
    "disconnected": "disconnected",
    "expired": "expired",
    "needs_reauthorization": "needs reauthorization",
}


@st.cache_resource
def _stores() -> tuple[AccountStore, TokenStore]:
    return AccountStore(), TokenStore()


def _jobs() -> list[PublishingJob]:
    if "pub_jobs" not in st.session_state:
        st.session_state.pub_jobs = []
    return st.session_state.pub_jobs


def _persist_job(job: PublishingJob) -> None:
    """§41: terminal results land in project-scoped storage (no tokens stored)."""
    project = st.session_state.get("project")
    project_id = getattr(project, "project_id", "") if project is not None else ""
    if project_id and job.project_id in ("", project_id):
        job.project_id = project_id
        PublishingStore(project_id).record_result(job)


def _asset_choices() -> list[str]:
    """Final assets produced by the pipeline (§1: project → final asset)."""
    found = set()
    for pattern in ("outputs/**/*.mp4", "outputs/**/*.png"):
        found.update(glob.glob(pattern, recursive=True))
    return sorted(found)


def _suggest_caption(title: str, platform: str) -> str:
    """§12 assistant: local suggestion only — never auto-publishes, no fake AI."""
    base = title.strip() or "New drop"
    hooks = {
        "TikTok": "Wait for the end 👀",
        "YouTube Shorts": "You need to see this ⚡",
        "Instagram Reels": "Save this for later 📌",
        "YouTube": f"{base} — full breakdown inside",
        "LinkedIn": f"{base} | lessons and takeaways below",
    }
    hook = hooks.get(platform, base)
    return f"{hook}\n\n{base} — made with GENFORGE.\n#contentcreation #genforge"


# --------------------------------------------------------------- accounts
def _render_accounts_tab() -> None:
    accounts_store, tokens = _stores()
    st.subheader("Connected accounts")
    accounts = accounts_store.list()
    if not accounts:
        st.info("No accounts connected yet. Add one below.")
    for account in accounts:
        badge = _STATE_BADGES.get(account.state, account.state)
        masked = mask_token(tokens.resolve(account.token_reference)) if account.token_reference else "no token"
        with st.container():
            col_a, col_b, col_c = st.columns([3, 2, 1])
            col_a.markdown(f"**{account.platform}** — {account.display_name}")
            col_b.markdown(f"`{badge}` · token `{masked}`")
            if col_c.button("Disconnect", key=f"dis_{account.account_id}"):
                accounts_store.disconnect(account.account_id)
                st.rerun()
        st.caption(f"Token reference: `{account.token_reference or '—'}` (the secret itself is never shown)")

    st.divider()
    st.subheader("Connect an account")
    st.caption("OAuth flows require registered platform apps (§6). Until then, tokens are provided "
               "manually and stored only in the local secret store or environment — never in project files.")
    with st.form("connect_account"):
        platform = st.selectbox("Platform", sorted(PLATFORM_CAPABILITIES), key="acc_platform")
        display_name = st.text_input("Display name (e.g. Main channel)", key="acc_name")
        token_source = st.radio("Token source", ["Paste token now (stored locally)",
                                                 "Environment variable name"], key="acc_source")
        secret = st.text_input("Token value or env var name", type="password", key="acc_secret")
        if st.form_submit_button("Connect"):
            if not display_name or not secret:
                st.error("Display name and token are required.")
            else:
                try:
                    if token_source.startswith("Paste"):
                        key = f"{platform.lower().replace(' ', '_')}:{display_name.lower().replace(' ', '_')}"
                        reference = tokens.store(key, secret)
                    else:
                        reference = f"env:{secret}"
                    accounts_store.connect(platform, display_name, token_reference=reference)
                    st.success(f"Account connected: {display_name}")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


# ------------------------------------------------- publish & schedule tab
def _render_publish_tab() -> None:
    accounts_store, _ = _stores()
    st.info("Demo provider mode: publishing runs against GENFORGE's scripted mock platform. "
            "Real official-API adapters ship in Phase 10 — this page will never claim a real post "
            "until the platform itself confirms it.")

    assets = _asset_choices()
    if not assets:
        st.warning("No final assets found in outputs/. Render something in the studios first.")
        return

    col1, col2 = st.columns(2)
    platform = col1.selectbox("Platform", sorted(PLATFORM_CAPABILITIES), key="pub_platform")
    caps = capabilities_for(platform)
    accounts = accounts_store.list(platform=platform)
    connected = [a for a in accounts if a.state == "connected"]
    account_label = col2.selectbox(
        "Account", [f"{a.display_name} ({a.account_id[:6]})" for a in connected] or ["— none connected —"],
        key="pub_account")
    if not connected:
        st.warning(f"No connected {platform} account. Connect one in the Accounts tab (or proceed in demo mode).")

    asset_path = st.selectbox("Final asset", assets, key="pub_asset")
    if asset_path.endswith(".mp4"):
        st.video(asset_path)
    elif asset_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        st.image(asset_path)

    st.subheader("Metadata (fully editable — §11)")
    limits = METADATA_LIMITS.get(platform, {})
    title = st.text_input("Title", key="pub_title",
                          max_chars=limits.get("title") or None,
                          help=None if not limits.get("title") else f"{platform} limit: {limits['title']} chars")
    description = st.text_area("Description / caption", key="pub_desc", height=120,
                               help=f"{platform} limit: {limits.get('description')} chars" if limits.get("description") else None)
    hashtags = st.text_input("Hashtags (comma separated)", key="pub_tags")

    if st.button(":material/auto_fix_high: Suggest caption (AI assists, you decide)", key="pub_suggest"):
        st.session_state.pub_suggested = _suggest_caption(title or os.path.basename(asset_path), platform)
    if st.session_state.get("pub_suggested"):
        st.caption("Suggestion (edit freely, nothing is posted automatically):")
        st.code(st.session_state.pub_suggested, language=None)
        if st.button("Use suggestion", key="pub_use_suggestion"):
            st.session_state.pub_desc = st.session_state.pub_suggested
            st.session_state.pub_suggested = ""
            st.rerun()

    # §5: hide controls the platform officially does not support
    scheduled_iso = ""
    if caps.scheduling:
        with st.expander("⏰ Schedule (timezone-aware)"):
            s_date = st.date_input("Date", value=dt.date.today() + dt.timedelta(days=1), key="pub_date")
            s_time = st.time_input("Time", key="pub_time")
            s_tz = st.selectbox("Timezone offset", ["UTC", "+01:00", "+02:00", "-05:00", "-08:00", "+05:30"], key="pub_tz")
            offset = dt.timedelta(hours=0) if s_tz == "UTC" else dt.timedelta(
                hours=int(s_tz.split(":")[0]), minutes=int(s_tz.split(":")[1]))
            scheduled_iso = dt.datetime.combine(s_date, s_time, tzinfo=dt.timezone(offset)).isoformat()
            st.caption("Never silently converted: the timestamp is sent to the platform exactly as shown.")
    else:
        st.caption(f"ℹ️ Platform scheduling unsupported for {platform} — publishing is immediate only.")
    if not caps.thumbnail:
        st.caption(f"ℹ️ {platform} does not support custom thumbnails.")

    job = PublishingJob(platform=platform, asset_path=asset_path, title=title,
                        description=description,
                        hashtags=[t.strip() for t in hashtags.split(",") if t.strip()],
                        scheduled_at=scheduled_iso,
                        account_id=connected[0].account_id if connected else "")

    st.subheader("Pre-publish checklist (§29)")
    for item in pre_publish_checklist(job):
        icon = ":material/check_circle:" if item["passed"] else ":material/cancel:"
        extra = " · *asset requires adaptation*" if item.get("requires_adaptation") else ""
        st.markdown(f"{icon} **{item['label']}** — {item['detail']}{extra}")

    st.divider()
    action = "Schedule" if scheduled_iso else "Publish now"
    confirm = st.checkbox(f"I reviewed the preview and confirm: {action} to {platform}", key="pub_confirm")
    if st.button(f":material/cloud_upload: {action}", disabled=not confirm, key="pub_go", type="primary"):
        provider = MockPlatformProvider(platform=platform)
        manager = PublishingManager(provider, sleep_fn=lambda _s: None)
        entry = manager.queue_job(job)
        if entry["state"] == "failed":
            st.error(f"Queue rejected the job: {entry['reason']}")
        else:
            with st.spinner(f"{action}… waiting for platform confirmation"):
                manager.run_queue()
            _jobs().append(job)
            _persist_job(job)
            if job.status == "PUBLISHED":
                st.success(f"Platform confirmed publication: {job.external_url}")
            elif job.status == "SCHEDULED":
                st.success(f"Platform confirmed schedule: {job.external_url}")
            else:
                st.error(f"{job.status}: {job.error}")


# ------------------------------------------------------------------ queue
def _render_batch_preview() -> None:
    """§21: READY / WARNING / ERROR preview BEFORE anything is queued."""
    st.subheader("Batch publishing")
    project = st.session_state.get("project")
    campaign = getattr(project, "campaign", None) if project is not None else None
    platforms = st.multiselect("Target platforms", sorted(PLATFORM_CAPABILITIES),
                               default=["YouTube"], key="batch_platforms")
    if not platforms:
        st.caption("Pick at least one platform.")
        return
    if campaign:
        pairs = pairs_for_campaign(campaign, platforms)
        source = "campaign assets"
    elif project is not None:
        pairs = pairs_for_project(project, platforms)
        source = "latest project version"
    else:
        pairs = []
        source = "no project loaded"
    if not pairs:
        st.info(f"No publishable assets found ({source}). Render a version or run a campaign first.")
        return
    items = build_batch(pairs, project=project)
    st.dataframe([{"Platform": i.platform, "Asset": os.path.basename(i.asset_path),
                   "Verdict": i.verdict, "Why": "; ".join(i.reasons) or "OK"} for i in items],
                 use_container_width=True, hide_index=True)
    confirmed = st.checkbox("I reviewed the batch preview and confirm queueing", key="batch_confirm")
    if st.button("Queue batch", disabled=not confirmed, key="batch_go"):
        by_platform: dict[str, list] = {}
        for item in items:
            by_platform.setdefault(item.platform, []).append(item)
        totals = {"READY": 0, "WARNING": 0, "ERROR": 0, "queued": 0, "rejected": 0}
        for platform, group in by_platform.items():
            manager = PublishingManager(MockPlatformProvider(platform=platform), sleep_fn=lambda _s: None)
            summary = queue_batch(manager, group, confirmed=True)
            manager.run_queue()
            for key, value in summary.items():
                totals[key] = totals.get(key, 0) + value
        for item in items:
            if item.job is not None:
                _jobs().append(item.job)
                _persist_job(item.job)
        st.success(f"Batch summary: {totals['queued']} queued, {totals['rejected']} rejected "
                   f"(READY {totals['READY']} / WARNING {totals['WARNING']} / ERROR {totals['ERROR']})")


def _render_queue_tab() -> None:
    st.subheader("Publishing queue")
    jobs = _jobs()
    if not jobs:
        st.info("Nothing has been queued yet this session.")
        return
    rows = [{"Job": j.job_id[:8], "Platform": j.platform, "Status": j.status,
             "Retries": j.retry_count, "Post": j.external_url or "—",
             "Error": j.error or "—"} for j in jobs]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("Queue processing is bounded and ordered (§22). Failed jobs keep their honest error — "
               "no invented success.")


# ---------------------------------------------------------------- history
def _render_history_tab() -> None:
    st.subheader("Publication history")
    project = st.session_state.get("project")
    project_id = getattr(project, "project_id", "") if project is not None else ""
    if project_id:
        stored = PublishingStore(project_id).load_history()
        if stored:
            st.caption(f"Project-scoped records ({project_id[:8]}…):")
            st.dataframe([{"Platform": e["platform"], "Status": e["status"],
                           "Post": e["external_url"] or "—", "Event": e["event"],
                           "Recorded": e["recorded_at"][:19]} for e in stored],
                         use_container_width=True, hide_index=True)
    jobs = [j for j in _jobs() if j.status in ("PUBLISHED", "SCHEDULED", "FAILED", "CANCELLED", "UNKNOWN")]
    if not jobs:
        st.info("No completed publications yet.")
        return
    for job in jobs:
        icon = {"PUBLISHED": ":material/check_circle:", "SCHEDULED": ":material/schedule:", "FAILED": ":material/cancel:"}.get(job.status, ":material/warning:")
        st.markdown(f"{icon} **{job.platform}** · `{job.job_id[:8]}` · {job.status} · updated {job.updated_at[:19]}")
        if job.external_url:
            st.markdown(f"→ {job.external_url}")
        if job.error:
            st.caption(job.error)
    st.caption("Version-pinned records are never rewritten (§40). Persistent project history lands in Phase 11.")


def render_publishing_page() -> None:
    tab_accounts, tab_publish, tab_queue, tab_history = st.tabs(
        ["Accounts", "Publish & Schedule", "Queue", "History"])
    with tab_accounts:
        _render_accounts_tab()
    with tab_publish:
        _render_publish_tab()
        st.divider()
        _render_batch_preview()
    with tab_queue:
        _render_queue_tab()
    with tab_history:
        _render_history_tab()


__all__ = ["render_publishing_page"]
