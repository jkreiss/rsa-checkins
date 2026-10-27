"""Checkins page: upload a check-in workbook, see what it will make, start it, download new draft products."""
import streamlit as st

from rsa_checkins import jobs, output
from rsa_checkins.checkin_sheet import CheckinFormatError
from rsa_checkins.ui import RunPage, get_conn, run_picker, run_status, saved_upload

conn = get_conn()
st.title("Checkins")


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


def _preview_details(conn, run_id, p) -> None:
    notes = jobs.run_notes(conn, run_id)
    st.caption("From the tabs: " + ", ".join(f"{tab} {n}" for tab, n in notes["tabs"].items())
               if notes["tabs"] else "No products found on the tabs.")
    _notes_tables(notes)


def _started_details(conn, run_id) -> None:
    notes = jobs.run_notes(conn, run_id)
    if notes["problems"] or notes["warnings"] or notes["ignored_tabs"]:
        with st.expander("Rows left out and warnings"):
            _notes_tables(notes)


PAGE = RunPage(
    noun="Check-in", input_kind="checkin_sheet", state_key="checkin_run_id",
    empty_text="Upload a check-in sheet (.xlsx) to start.",
    preview_details=_preview_details,
    started_details=_started_details,
    download_caption='Import as new products and leave "Overwrite products with matching handles" unticked, so '
                     "existing products are never changed. Every product comes in as a draft.",
    build_csv=output.build_checkin_csv,
    download_suffix="new-product-import",
)

# ---------- upload ----------
with st.form("upload-checkin", clear_on_submit=True):
    uploaded = st.file_uploader("Check-in sheet", type=["xlsx"])
    submitted = st.form_submit_button("Create products", key="create-checkin-run")

if submitted and uploaded is not None:
    with saved_upload(uploaded, "checkin.xlsx") as (path, name):
        try:
            st.session_state[PAGE.state_key] = jobs.create_checkin_run(conn, path, name)
        except CheckinFormatError as e:
            st.error(str(e))
elif submitted:
    st.error("Choose an .xlsx file first.")

run_status(run_picker(conn, PAGE), PAGE)
