"""RSA Check-ins: Streamlit entry point."""
import streamlit as st

from rsa_checkins.ui import get_conn, worker_running

st.set_page_config(page_title="RSA Check-ins")
conn = get_conn()

if not worker_running(conn):   # nothing is shown while it's running
    st.sidebar.warning("Worker not running. Contact Joel.", icon="🔴")

st.navigation([
    st.Page("pages/checkins.py", title="Checkins", default=True),
    st.Page("pages/run.py", title="Shopify Product Export"),
    st.Page("pages/players.py", title="Player Information"),
    st.Page("pages/settings.py", title="Settings"),
]).run()
