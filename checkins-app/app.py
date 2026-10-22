"""RSA Check-ins: Streamlit entry point."""
import streamlit as st

from rsa_checkins.ui import get_conn, worker_running

st.set_page_config(page_title="RSA Check-ins")
conn = get_conn()

with st.sidebar:
    if worker_running(conn):
        st.success("Worker running")
    else:
        st.warning("Worker not running. Runs won't make progress until it starts.", icon="🔴")

st.navigation([
    st.Page("pages/run.py", title="Run"),
    st.Page("pages/players.py", title="Players"),
    st.Page("pages/settings.py", title="Settings"),
]).run()
