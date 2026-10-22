"""Players page: look up a player, fix or delete facts, force a re-check."""
import json
import re
from urllib.parse import urlsplit

import streamlit as st

from rsa_checkins import players
from rsa_checkins.ui import get_conn


def _md(text: str) -> str:
    """Show text as written: escape characters Streamlit would read as formatting ($ * _ [ ] ...)."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!$~|<>])", r"\\\1", text or "")


def _safe_url(url: str) -> str:
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""

conn = get_conn()
st.title("Player Information")

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
# One fact at a time can be open for editing. The buttons act in callbacks, before the page redraws.
def _open(fid: int) -> None:
    st.session_state["editing_fact"] = fid


def _close() -> None:
    st.session_state["editing_fact"] = None


def _save(fid: int) -> None:
    players.update_fact(conn, fid, st.session_state[f"fact-{fid}"], st.session_state[f"url-{fid}"])
    _close()


def _delete(fid: int) -> None:
    players.delete_fact(conn, fid)
    _close()


editing = st.session_state.get("editing_fact")
for f in facts:
    fid = f["id"]
    details = ("Edited by hand · " if f["edited"] else "") + f"checked {f['checked_at'][:10]}"
    with st.container(border=True):
        if editing == fid:
            # multi-line so long facts wrap; longer than the box, it scrolls
            st.text_area("Fact", value=f["fact"], key=f"fact-{fid}", height=110)
            st.text_input("Source URL", value=f["source_url"], key=f"url-{fid}")
            c = st.columns([1, 1, 1, 3])
            c[0].button("Save", key=f"save-{fid}", type="primary", on_click=_save, args=(fid,))
            c[1].button("Cancel", key=f"cancel-{fid}", on_click=_close)
            c[2].button("Delete", key=f"delete-{fid}", on_click=_delete, args=(fid,))
        else:
            c = st.columns([8, 1])
            c[0].markdown(_md(f["fact"]))
            link = _safe_url(f["source_url"])
            c[0].caption((f"[{_md(urlsplit(link).netloc or link)}]({link}) · " if link else "No source · ") + details)
            c[1].button("Edit", key=f"edit-{fid}", on_click=_open, args=(fid,))

with st.form("add-fact", clear_on_submit=True):
    st.write("**Add fact**")
    new_fact = st.text_input("Fact")
    new_url = st.text_input("Source URL")
    if st.form_submit_button("Add fact") and new_fact.strip():
        players.add_fact(conn, sid, new_fact, new_url)
        st.rerun()
