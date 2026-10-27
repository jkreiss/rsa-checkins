"""Run page: upload an export, see what it will do, start/pause it, download the results."""
import os
from datetime import datetime, timezone

import streamlit as st

from rsa_checkins import config, db, jobs, output
from rsa_checkins.shopify_export import ExportFormatError
from rsa_checkins.ui import STATUS_WORDS, activity_section, get_conn, progress_section

conn = get_conn()
st.title("Shopify Product Export")

# ---------- upload ----------
with st.form("upload", clear_on_submit=True):
    uploaded = st.file_uploader("Shopify product export", type=["csv"])
    include_drafts = st.checkbox("Include drafts", value=bool(db.get_setting(conn, "include_drafts")))
    submitted = st.form_submit_button("Update products", key="create-run")

if submitted and uploaded is not None:
    name = os.path.basename(uploaded.name) or "export.csv"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    config.upload_dir().mkdir(parents=True, exist_ok=True)
    path = config.upload_dir() / f"{stamp}-{name}"
    path.write_bytes(uploaded.getvalue())
    try:
        st.session_state["run_id"] = jobs.create_run(conn, path, name, include_drafts)
    except ExportFormatError as e:
        path.unlink(missing_ok=True)
        st.error(str(e))
elif submitted:
    st.error("Choose a CSV file first.")

# ---------- run picker ----------
runs = jobs.list_runs(conn, "shopify_export")
if not runs:
    st.info("Upload a Shopify product export to start.")
    st.stop()

ids = [r["id"] for r in runs]
labels = {r["id"]: f"Export {r['id']} · {r['filename']} · {STATUS_WORDS[r['status']]} · {r['created_at'][:16].replace('T', ' ')}"
          for r in runs}
chosen = st.session_state.get("run_id")
run_id = st.selectbox("Export", ids, index=ids.index(chosen) if chosen in ids else 0, format_func=labels.get)
st.session_state["run_id"] = run_id


@st.fragment(run_every=5)
def status_area(run_id: int) -> None:
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    status = run["status"]
    pr = jobs.progress(conn, run_id)

    if status == "parsing":
        st.info(STATUS_WORDS["parsing"])
    elif status == "error":
        st.error(f"This export stopped: {run['error']}")
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
        st.caption(f"{p.reused} product(s) reuse a description from an earlier run. "
                   f"{p.skipped_new_style} product(s) already have a new-style description and are skipped.")
        if st.button("Start", key=f"start-{run_id}", type="primary"):
            jobs.set_run_status(conn, run_id, "running")
            st.rerun(scope="fragment")
    else:
        progress_section(conn, run_id, status, pr)

    activity_section(conn, run_id, status)

    if pr.done > 0:
        st.subheader("Downloads")
        st.caption("Import with \"Overwrite products with matching handles\" ticked. A product deleted or renamed in "
                   "Shopify since this export was taken would come back as a new product.")
        columns = db.get_setting(conn, "output_columns")
        c = st.columns(2)
        c[0].download_button("Download import CSV", lambda: output.build_output_csv(conn, run_id, columns),
                             file_name=f"shopify-import-{run_id}.csv", mime="text/csv", on_click="ignore",
                             type="primary", width="stretch", icon=":material/download:",
                             key=f"dl-desc-{run_id}")
        c[1].download_button("Download facts log", lambda: output.build_facts_csv(conn, run_id),
                             file_name=f"facts-log-{run_id}.csv", mime="text/csv", on_click="ignore",
                             width="stretch", icon=":material/description:",
                             key=f"dl-facts-{run_id}")


status_area(run_id)
