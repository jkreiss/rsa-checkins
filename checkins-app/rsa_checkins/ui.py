"""Small helpers shared by the Streamlit pages."""
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import streamlit as st

from . import config, db, jobs, output

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


# ---------- one layout for both run pages (Checkins and Shopify Product Export) ----------

@dataclass(frozen=True)
class RunPage:
    noun: str                                     # "Export", "Check-in": the picker and its labels
    input_kind: str                               # runs.input_kind this page lists
    state_key: str                                # session key remembering the chosen run
    empty_text: str                               # shown before anything is uploaded
    preview_details: Callable[[sqlite3.Connection, int, "jobs.Preview"], None]   # under the three numbers
    download_caption: str
    build_csv: Callable[[sqlite3.Connection, int], bytes]
    csv_name: str                                 # file name, with {run_id}
    started_details: Callable[[sqlite3.Connection, int], None] | None = None     # under the progress


@contextmanager
def saved_upload(uploaded, fallback_name: str) -> Iterator[tuple[Path, str]]:
    """The uploaded file on disk while the run is created from it, then deleted.
    Everything a run needs is copied into the database, so uploads aren't kept."""
    name = os.path.basename(uploaded.name) or fallback_name
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    config.upload_dir().mkdir(parents=True, exist_ok=True)
    path = config.upload_dir() / f"{stamp}-{name}"
    path.write_bytes(uploaded.getvalue())
    try:
        yield path, name
    finally:
        path.unlink(missing_ok=True)


def run_picker(conn: sqlite3.Connection, page: RunPage) -> int:
    """The run select box. Stops the page when there are no runs yet."""
    runs = jobs.list_runs(conn, page.input_kind)
    if not runs:
        st.info(page.empty_text)
        st.stop()
    ids = [r["id"] for r in runs]
    labels = {r["id"]: f"{page.noun} {r['id']} · {r['filename']} · {STATUS_WORDS[r['status']]} · "
                       f"{r['created_at'][:16].replace('T', ' ')}" for r in runs}
    chosen = st.session_state.get(page.state_key)
    run_id = st.selectbox(page.noun, ids, index=ids.index(chosen) if chosen in ids else 0, format_func=labels.get)
    st.session_state[page.state_key] = run_id
    return run_id


@st.fragment(run_every=5)
def run_status(run_id: int, page: RunPage) -> None:
    """Everything under the picker: preview and Start, progress, activity, downloads."""
    conn = get_conn()
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    status = run["status"]
    pr = jobs.progress(conn, run_id)

    if status == "parsing":
        st.info(STATUS_WORDS["parsing"])
    elif status == "error":
        st.error(f"This {page.noun.lower()} stopped: {run['error']}")
        if st.button("Try again", key=f"try-again-{run_id}"):
            jobs.retry_prepare(conn, run_id)
            st.rerun(scope="fragment")
    elif status == "ready":
        p = jobs.preview(conn, run_id, int(db.get_setting(conn, "refresh_days")), datetime.now(timezone.utc),
                         int(db.get_setting(conn, "retired_refresh_days")))
        st.subheader("What this will do")
        c = st.columns(3)
        c[0].metric("Products to write", p.products - p.reused)
        c[1].metric("Players already known", p.subjects_fresh)
        c[2].metric("Players to look up", p.subjects_to_research)
        page.preview_details(conn, run_id, p)
        if st.button("Start", key=f"start-{run_id}", type="primary"):
            jobs.set_run_status(conn, run_id, "running")
            st.rerun(scope="fragment")
    else:
        progress_section(conn, run_id, status, pr)
        if page.started_details:
            page.started_details(conn, run_id)

    activity_section(conn, run_id, status)

    if status == "done" and pr.done > 0:   # only once the whole run is finished
        st.subheader("Downloads")
        st.caption(page.download_caption)
        c = st.columns(2)
        c[0].download_button("Download import CSV", lambda: page.build_csv(conn, run_id),
                             file_name=page.csv_name.format(run_id=run_id), mime="text/csv", on_click="ignore",
                             type="primary", width="stretch", icon=":material/download:", key=f"dl-import-{run_id}")
        c[1].download_button("Download facts log", lambda: output.build_facts_csv(conn, run_id),
                             file_name=f"facts-log-{run_id}.csv", mime="text/csv", on_click="ignore",
                             width="stretch", icon=":material/description:", key=f"dl-facts-{run_id}")
