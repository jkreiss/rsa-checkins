"""Shopify Product Export page: upload an export, see what it will do, start/pause it, download the results."""
import streamlit as st

from rsa_checkins import db, jobs, output
from rsa_checkins.shopify_export import ExportFormatError
from rsa_checkins.ui import RunPage, get_conn, run_picker, run_status, save_upload

conn = get_conn()
st.title("Shopify Product Export")


def _preview_details(conn, run_id, p) -> None:
    st.caption(f"{p.reused} product(s) reuse a description from an earlier run. "
               f"{p.skipped_new_style} product(s) already have a new-style description and are skipped.")


PAGE = RunPage(
    noun="Export", input_kind="shopify_export", state_key="run_id",
    empty_text="Upload a Shopify product export to start.",
    preview_details=_preview_details,
    download_caption="Import with \"Overwrite products with matching handles\" ticked. A product deleted or renamed in "
                     "Shopify since this export was taken would come back as a new product.",
    build_csv=lambda conn, run_id: output.build_output_csv(conn, run_id, db.get_setting(conn, "output_columns")),
    csv_name="shopify-import-{run_id}.csv",
)

# ---------- upload ----------
with st.form("upload", clear_on_submit=True):
    uploaded = st.file_uploader("Shopify product export", type=["csv"])
    include_drafts = st.checkbox("Include drafts", value=bool(db.get_setting(conn, "include_drafts")))
    submitted = st.form_submit_button("Update products", key="create-run")

if submitted and uploaded is not None:
    path, name = save_upload(uploaded, "export.csv")
    try:
        st.session_state[PAGE.state_key] = jobs.create_run(conn, path, name, include_drafts)
    except ExportFormatError as e:
        path.unlink(missing_ok=True)
        st.error(str(e))
elif submitted:
    st.error("Choose a CSV file first.")

run_status(run_picker(conn, PAGE), PAGE)
