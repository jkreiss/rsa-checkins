"""Settings page."""
import json

import streamlit as st

from rsa_checkins import db
from rsa_checkins.config import DEFAULT_OUTPUT_COLUMNS
from rsa_checkins.output import REQUIRED
from rsa_checkins.ui import get_conn

conn = get_conn()
st.title("Settings")

latest = conn.execute("SELECT header FROM runs ORDER BY id DESC LIMIT 1").fetchone()
header = json.loads(latest["header"]) if latest else list(DEFAULT_OUTPUT_COLUMNS)
current = [c for c in db.get_setting(conn, "output_columns") if c not in REQUIRED]
options = [c for c in header if c not in REQUIRED]
options += [c for c in current if c not in options]

# model = st.text_input("Model", value=db.get_setting(conn, "model"), key="model")
refresh_days = st.number_input("Re-check active players after (days)", min_value=1, step=1,
                               value=int(db.get_setting(conn, "refresh_days")), key="refresh_days",
                               help="30 is about a month. Players whose status is unknown count as active.")
retired_refresh_days = st.number_input("Re-check retired players after (days)", min_value=1, step=1,
                                       value=int(db.get_setting(conn, "retired_refresh_days")),
                                       key="retired_refresh_days", help="180 is about 6 months.")
# concurrency = st.number_input("Players at a time", min_value=1, max_value=4, step=1,
#                               value=int(db.get_setting(conn, "concurrency")), key="concurrency",
#                               help="Takes effect when the worker restarts.")
# st.caption("Players at a time takes effect when the worker restarts.")
# st.write("**Output columns**")
# st.caption("Handle and Title are always included.")
# columns = st.multiselect("Other columns", options, default=current, key="output_columns")
# include_drafts = st.checkbox("Include drafts by default", value=bool(db.get_setting(conn, "include_drafts")),
#                              key="include_drafts")

if st.button("Save", key="save-settings", type="primary"):
    # db.set_setting(conn, "model", model.strip() or "claude-sonnet-5-5")
    db.set_setting(conn, "refresh_days", int(refresh_days))
    db.set_setting(conn, "retired_refresh_days", int(retired_refresh_days))
    # db.set_setting(conn, "concurrency", int(concurrency))
    # db.set_setting(conn, "output_columns", [*REQUIRED, *columns])
    # db.set_setting(conn, "include_drafts", bool(include_drafts))
    st.success("Saved.")
