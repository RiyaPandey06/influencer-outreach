from __future__ import annotations

import hmac
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Influencer Outreach Dashboard", page_icon="📣", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "output"
FILES = {
    "Influencer dataset": "influencer_dataset.csv",
    "Personalized messages": "personalized_messages.csv",
    "Outreach tracker": "outreach_tracker.csv",
    "Instagram DM queue": "instagram_dm_queue.csv",
}


def require_password() -> None:
    try:
        expected = str(st.secrets.get("DASHBOARD_PASSWORD", ""))
    except Exception:
        expected = ""

    if not expected:
        st.error("Dashboard access is locked. Add DASHBOARD_PASSWORD in your Streamlit app Secrets.")
        st.code('DASHBOARD_PASSWORD = "choose-a-long-unique-password"', language="toml")
        st.stop()

    if st.session_state.get("authenticated", False):
        return

    st.title("🔐 Influencer Outreach Dashboard")
    password = st.text_input("Dashboard password", type="password")
    if st.button("Unlock dashboard", type="primary"):
        if hmac.compare_digest(password, expected):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password. Try again.")
    st.stop()


def load_csvs() -> dict[str, pd.DataFrame]:
    uploaded = st.file_uploader(
        "Upload the CSV files downloaded from your GitHub Actions artifact",
        type=["csv"],
        accept_multiple_files=True,
        help="Select all four CSV files together. Uploaded files are used for this session.",
    )
    data: dict[str, pd.DataFrame] = {}
    uploaded_by_name = {Path(f.name).name: f for f in uploaded}

    for label, filename in FILES.items():
        try:
            if filename in uploaded_by_name:
                data[label] = pd.read_csv(uploaded_by_name[filename]).fillna("")
            elif (OUTPUT_DIR / filename).exists():
                data[label] = pd.read_csv(OUTPUT_DIR / filename).fillna("")
        except Exception as exc:
            st.warning(f"Could not read {filename}: {exc}")
    return data


require_password()
st.title("📣 Influencer Outreach Dashboard")
st.caption("Fashion & Beauty · YouTube micro-influencer discovery and outreach review")
st.info(
    "Upload the CSV files from your latest GitHub Actions run below. "
    "The dashboard does not automatically fetch GitHub Actions artifacts."
)

data = load_csvs()
if not data:
    st.warning(
        "No result files loaded yet. Download influencer-outreach-results from "
        "GitHub → Actions → latest successful run, extract it, then upload the CSV files here."
    )
    st.stop()

influencers = data.get("Influencer dataset", pd.DataFrame())
messages = data.get("Personalized messages", pd.DataFrame())
tracker = data.get("Outreach tracker", pd.DataFrame())
dm_queue = data.get("Instagram DM queue", pd.DataFrame())

passed = 0
if not influencers.empty and "Status" in influencers.columns:
    passed = int((influencers["Status"].astype(str).str.lower() == "passed").sum())

sent = 0
if not tracker.empty and "Sent" in tracker.columns:
    sent = int((tracker["Sent"].astype(str).str.lower() == "yes").sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Discovered channels", f"{len(influencers):,}")
c2.metric("Shortlisted", f"{passed:,}")
c3.metric("Personalized messages", f"{len(messages):,}")
c4.metric("Emails sent", f"{sent:,}")

st.divider()
tab_overview, tab_influencers, tab_messages, tab_tracker, tab_dm = st.tabs(
    ["Overview", "Influencers", "Messages", "Outreach tracker", "Instagram DM queue"]
)

with tab_overview:
    left, right = st.columns(2)
    with left:
        st.subheader("Filtering results")
        if not influencers.empty and "Status" in influencers.columns:
            st.bar_chart(influencers["Status"].replace("", "Unknown").value_counts())
        else:
            st.caption("The influencer dataset is not available.")
    with right:
        st.subheader("Files loaded")
        for label, df in data.items():
            st.write(f"**{label}:** {len(df):,} rows")
    if not tracker.empty and "Status" in tracker.columns:
        st.subheader("Outreach status")
        st.bar_chart(tracker["Status"].replace("", "Unknown").value_counts())

with tab_influencers:
    st.subheader("Discovered influencers")
    if influencers.empty:
        st.info("Upload influencer_dataset.csv to view creator records.")
    else:
        view = influencers.copy()
        if "Status" in view.columns:
            statuses = sorted(view["Status"].astype(str).replace("", "Unknown").unique())
            selected = st.multiselect("Filter by status", statuses, default=statuses)
            view = view[view["Status"].astype(str).replace("", "Unknown").isin(selected)]
        if "Niche" in view.columns:
            niches = sorted(view["Niche"].astype(str).replace("", "Unknown").unique())
            selected_niches = st.multiselect("Filter by niche", niches, default=niches)
            view = view[view["Niche"].astype(str).replace("", "Unknown").isin(selected_niches)]
        show_contact = st.checkbox("Show email addresses and contact links", value=False)
        if not show_contact:
            view = view.drop(columns=[c for c in ["Email", "Instagram", "TikTok", "Website"] if c in view.columns])
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button(
            "Download filtered influencer CSV",
            view.to_csv(index=False).encode("utf-8-sig"),
            "filtered_influencers.csv",
            "text/csv",
        )

with tab_messages:
    st.subheader("Personalized outreach messages")
    if messages.empty:
        st.info("Upload personalized_messages.csv to view generated messages.")
    else:
        show_contact = st.checkbox("Show email addresses in message table", value=False, key="message_contacts")
        view = messages.copy()
        if not show_contact:
            view = view.drop(columns=[c for c in ["Email"] if c in view.columns])
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button(
            "Download messages CSV",
            messages.to_csv(index=False).encode("utf-8-sig"),
            "personalized_messages.csv",
            "text/csv",
        )

with tab_tracker:
    st.subheader("Outreach tracking")
    if tracker.empty:
        st.info("Upload outreach_tracker.csv to view outreach activity.")
    else:
        st.dataframe(tracker, use_container_width=True, hide_index=True)
        st.download_button(
            "Download tracker CSV",
            tracker.to_csv(index=False).encode("utf-8-sig"),
            "outreach_tracker.csv",
            "text/csv",
        )

with tab_dm:
    st.subheader("Instagram DM queue")
    st.caption("Instagram messages are a manual copy-and-paste queue; this dashboard does not send DMs.")
    if dm_queue.empty:
        st.info("Upload instagram_dm_queue.csv to view the manual DM queue.")
    else:
        st.dataframe(dm_queue, use_container_width=True, hide_index=True)
        st.download_button(
            "Download DM queue CSV",
            dm_queue.to_csv(index=False).encode("utf-8-sig"),
            "instagram_dm_queue.csv",
            "text/csv",
        )

st.divider()
st.caption(
    "Influencer Outreach System · Dashboard displays uploaded/local CSV exports; "
    "it does not send emails or Instagram DMs."
)
