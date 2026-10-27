"""Small helpers shared by the Streamlit pages."""
import sqlite3
from datetime import datetime, timedelta, timezone

import streamlit as st

from . import config, db, jobs

HEARTBEAT_MAX_AGE = timedelta(seconds=60)

STATUS_WORDS = {
    "parsing": "Reading product titles…",
    "ready": "Ready to start",
    "running": "Running",
    "paused": "Paused",
    "done": "Finished",
    "error": "Stopped with an error",
}


def get_conn() -> sqlite3.Connection:
    """One connection per browser session, so two open tabs never share a transaction."""
    key = f"_conn:{config.db_path()}"
    if key not in st.session_state:
        conn = db.connect(config.db_path())
        db.init_db(conn)
        st.session_state[key] = conn
    return st.session_state[key]


def worker_running(conn: sqlite3.Connection, now: datetime | None = None) -> bool:
    beat = db.get_setting(conn, "worker_heartbeat")
    if not beat:
        return False
    now = now or datetime.now(timezone.utc)
    return now - db.parse_iso(beat) < HEARTBEAT_MAX_AGE


# ---------- shared by the run pages (inside their auto-refreshing fragment) ----------

def progress_section(conn: sqlite3.Connection, run_id: int, status: str, pr: "jobs.Progress") -> None:
    """A started run: status line, progress bar, counts and Pause/Resume."""
    if status == "done":
        st.success(STATUS_WORDS["done"])
    else:
        st.write(f"**{STATUS_WORDS[status]}**")
    st.progress((pr.done + pr.failed) / pr.total if pr.total else 1.0)
    c = st.columns(4)
    c[0].metric("Done", pr.done)
    c[1].metric("Remaining", pr.pending)
    c[2].metric("Failed", pr.failed)
    c[3].metric("Reused", pr.reused)
    if status == "running" and st.button("Pause", key=f"pause-{run_id}"):
        jobs.set_run_status(conn, run_id, "paused")
        st.rerun(scope="fragment")
    if status == "paused" and st.button("Resume", key=f"resume-{run_id}", type="primary"):
        jobs.set_run_status(conn, run_id, "running")
        st.rerun(scope="fragment")


def activity_section(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    """What the worker is doing, recent activity, and failed products with Retry."""
    if status in ("running", "paused"):
        activity = jobs.current_activity(conn, datetime.now(timezone.utc))
        st.caption("Working on: " + ("; ".join(activity) if activity else "nothing right now"))
    events = jobs.recent_events(conn, limit=10)
    if events and status != "parsing":
        with st.expander("Recent activity", expanded=status in ("running", "paused")):
            for e in events:
                st.text(f"{db.parse_iso(e['at']).astimezone():%H:%M}  {e['message']}")

    failed = jobs.failed_products(conn, run_id)
    if failed:
        st.subheader(f"Failed products ({len(failed)})")
        st.dataframe([{"Title": f["title"], "Reason": f["error"]} for f in failed], hide_index=True)
        if st.button("Retry failed", key=f"retry-{run_id}"):
            jobs.retry_failed(conn, run_id)
            st.rerun(scope="fragment")
