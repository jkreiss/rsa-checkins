"""Checkins page: upload a check-in workbook, see what it will make, start it, download new draft products."""
import os
from datetime import datetime, timezone

import streamlit as st

from rsa_checkins import config, db, jobs, output
from rsa_checkins.checkin_sheet import CheckinFormatError
from rsa_checkins.ui import STATUS_WORDS, activity_section, get_conn, progress_section

conn = get_conn()
st.title("Checkins")

# ---------- upload ----------
with st.form("upload-checkin", clear_on_submit=True):
    uploaded = st.file_uploader("Check-in sheet", type=["xlsx"])
    submitted = st.form_submit_button("Read check-in sheet", key="create-checkin-run")

if submitted and uploaded is not None:
    name = os.path.basename(uploaded.name) or "checkin.xlsx"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    config.upload_dir().mkdir(parents=True, exist_ok=True)
    path = config.upload_dir() / f"{stamp}-{name}"
    path.write_bytes(uploaded.getvalue())
    try:
        st.session_state["checkin_run_id"] = jobs.create_checkin_run(conn, path, name)
    except CheckinFormatError as e:
        path.unlink(missing_ok=True)
        st.error(str(e))
elif submitted:
    st.error("Choose an .xlsx file first.")

# ---------- run picker ----------
runs = jobs.list_runs(conn, "checkin_sheet")
if not runs:
    st.info("Upload a check-in sheet (.xlsx) to start.")
    st.stop()

ids = [r["id"] for r in runs]
labels = {r["id"]: f"Check-in {r['id']} · {r['filename']} · {STATUS_WORDS[r['status']]} · "
                   f"{r['created_at'][:16].replace('T', ' ')}" for r in runs}
chosen = st.session_state.get("checkin_run_id")
run_id = st.selectbox("Check-in", ids, index=ids.index(chosen) if chosen in ids else 0, format_func=labels.get)
st.session_state["checkin_run_id"] = run_id


def _notes_tables(notes: dict) -> None:
    if notes["problems"]:
        st.subheader(f"Rows left out ({len(notes['problems'])})")
        st.dataframe([{"Tab": p["tab"], "Row": p["row"], "Name": p["name"], "Reason": p["reason"]}
                      for p in notes["problems"]], hide_index=True)
    if notes["warnings"]:
        st.subheader(f"Warnings ({len(notes['warnings'])})")
        st.dataframe([{"Tab": w["tab"], "Row": w["row"], "Name": w["name"], "Warning": w["warning"]}
                      for w in notes["warnings"]], hide_index=True)
    if notes["ignored_tabs"]:
        st.caption("Tabs not read: " + ", ".join(notes["ignored_tabs"]))


@st.fragment(run_every=5)
def status_area(run_id: int) -> None:
    status = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()["status"]
    pr = jobs.progress(conn, run_id)
    notes = jobs.run_notes(conn, run_id)

    if status == "ready":
        p = jobs.preview(conn, run_id, int(db.get_setting(conn, "refresh_days")), datetime.now(timezone.utc),
                         int(db.get_setting(conn, "retired_refresh_days")))
        st.subheader("What this will do")
        c = st.columns(3)
        c[0].metric("New products", p.products)
        c[1].metric("Players already known", p.subjects_fresh)
        c[2].metric("Players to look up", p.subjects_to_research)
        st.dataframe([{"Tab": tab, "Products": n} for tab, n in notes["tabs"].items()], hide_index=True)
        _notes_tables(notes)
        if p.products and st.button("Start", key=f"start-checkin-{run_id}", type="primary"):
            jobs.set_run_status(conn, run_id, "running")
            st.rerun(scope="fragment")
    else:
        progress_section(conn, run_id, status, pr)
        with st.expander("Rows left out and warnings"):
            _notes_tables(notes)

    activity_section(conn, run_id, status)

    if pr.done > 0:
        st.subheader("Downloads")
        st.caption('Import as new products and leave "Overwrite products with matching handles" unticked, so '
                   "existing products are never changed. Every product comes in as a draft.")
        c = st.columns(2)
        c[0].download_button("Download import CSV", lambda: output.build_checkin_csv(conn, run_id),
                             file_name=f"shopify-new-products-{run_id}.csv", mime="text/csv", on_click="ignore",
                             type="primary", width="stretch", icon=":material/download:",
                             key=f"dl-checkin-{run_id}")
        c[1].download_button("Download facts log", lambda: output.build_facts_csv(conn, run_id),
                             file_name=f"facts-log-{run_id}.csv", mime="text/csv", on_click="ignore",
                             width="stretch", icon=":material/description:",
                             key=f"dl-checkin-facts-{run_id}")


status_area(run_id)
