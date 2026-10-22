"""Small helpers shared by the Streamlit pages."""
import sqlite3
from datetime import datetime, timedelta, timezone

import streamlit as st

from . import config, db

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
