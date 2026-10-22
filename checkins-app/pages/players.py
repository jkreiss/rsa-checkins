"""Players page: look up a player, fix or delete facts, force a re-check."""
import json

import streamlit as st

from rsa_checkins import players
from rsa_checkins.ui import get_conn

conn = get_conn()
st.title("Players")

query = st.text_input("Search by name", key="player-search")
if not query.strip():
    st.caption("Type part of a name to find a player.")
    st.stop()

found = players.search_subjects(conn, query)
if not found:
    st.info("No players match that name.")
    st.stop()

names = {r["id"]: f"{r['name']} ({'product line' if r['kind'] == 'product_line' else 'person'})" for r in found}
sid = st.selectbox("Player", list(names), format_func=names.get)
s = conn.execute("SELECT * FROM subjects WHERE id = ?", (sid,)).fetchone()

st.subheader(s["name"])
teams = ", ".join(json.loads(s["teams"])) or "—"
st.markdown(
    f"**Kind:** {'Product line' if s['kind'] == 'product_line' else 'Person'}  \n"
    f"**Status:** {s['status']}  \n"
    f"**Sport:** {s['sport'] or '—'}  \n"
    f"**Teams:** {teams}  \n"
    f"**Current team:** {s['current_team'] or '—'}  \n"
    f"**Last checked:** {s['researched_at'][:10] if s['researched_at'] else 'never'}"
)
if s["research_error"]:
    st.warning(f"Last research attempt failed: {s['research_error']}")
if st.button("Re-check on next run", key=f"refresh-{sid}"):
    players.force_refresh(conn, sid)
    st.success("This player will be looked up again on the next run.")

st.subheader("Facts")
facts = players.list_facts(conn, sid)
if not facts:
    st.caption("No facts saved.")
for f in facts:
    with st.container(border=True):
        text = st.text_input("Fact", value=f["fact"], key=f"fact-{f['id']}")
        url = st.text_input("Source URL", value=f["source_url"], key=f"url-{f['id']}")
        c = st.columns([1, 1, 4])
        if c[0].button("Save", key=f"save-{f['id']}"):
            players.update_fact(conn, f["id"], text, url)
            st.rerun()
        if c[1].button("Delete", key=f"delete-{f['id']}"):
            players.delete_fact(conn, f["id"])
            st.rerun()
        c[2].caption(("Edited by hand · " if f["edited"] else "") + f"checked {f['checked_at'][:10]}")

with st.form("add-fact", clear_on_submit=True):
    st.write("**Add fact**")
    new_fact = st.text_input("Fact")
    new_url = st.text_input("Source URL")
    if st.form_submit_button("Add fact") and new_fact.strip():
        players.add_fact(conn, sid, new_fact, new_url)
        st.rerun()
