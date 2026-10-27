from pathlib import Path

import pytest
from fakes import FIX
from streamlit.testing.v1 import AppTest

from rsa_checkins import config, db
from rsa_checkins.claude_api import Fact, Research
from rsa_checkins.jobs import complete_product, create_run, set_run_status
from rsa_checkins.players import get_or_create_subject, save_research

APP_DIR = Path(__file__).resolve().parent.parent
PAGES = ["views/checkins.py", "views/run.py", "views/players.py", "views/settings.py"]


@pytest.fixture
def data_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKINS_DATA_DIR", str(tmp_path))
    c = db.connect(config.db_path())
    db.init_db(c)
    yield c
    c.close()


def _app(path: str) -> AppTest:
    return AppTest.from_file(str(APP_DIR / path), default_timeout=30).run()


def _labels(at, kind):
    return [e.label for e in at.get(kind)]


def test_app_renders(data_conn):
    at = _app("app.py")
    assert not at.exception
    assert [w.value for w in at.sidebar.warning] == ["Worker not running. Contact Joel."]


def test_app_shows_worker_running_with_fresh_heartbeat(data_conn):
    db.set_setting(data_conn, "worker_heartbeat", db.now_iso())
    at = _app("app.py")
    assert not at.sidebar.success and not at.sidebar.warning


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_on_empty_db(data_conn, page):
    assert not _app(page).exception


def test_ready_run_shows_start(data_conn):
    run_id = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    data_conn.execute("UPDATE runs SET status='ready' WHERE id=?", (run_id,))
    at = _app("views/run.py")
    assert not at.exception
    assert "Start" in _labels(at, "button")
    at.button(key=f"start-{run_id}").click().run()
    assert data_conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()["status"] == "running"


def test_parsing_run_says_reading_titles(data_conn):
    create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    at = _app("views/run.py")
    assert any("Reading product titles" in i.value for i in at.info)


def test_done_run_shows_two_downloads(data_conn):
    run_id = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    pid = data_conn.execute("SELECT id FROM products WHERE run_id=? LIMIT 1", (run_id,)).fetchone()["id"]
    complete_product(data_conn, pid, "<p>a</p><p>b</p>", "seo")
    data_conn.execute("UPDATE runs SET status='done' WHERE id=?", (run_id,))
    at = _app("views/run.py")
    assert not at.exception
    buttons = at.get("download_button")
    assert [b.proto.label for b in buttons] == ["Download import CSV", "Download facts log"]
    assert buttons[0].proto.type == "primary"


def _uploads_kept() -> list:
    d = config.upload_dir()
    return sorted(p.name for p in d.rglob("*") if p.is_file()) if d.exists() else []


def test_upload_creates_one_run(data_conn):
    at = _app("views/run.py")
    at.file_uploader[0].set_value(("export.csv", FIX.read_bytes(), "text/csv"))
    at.button(key="create-run").click().run()
    assert not at.exception
    at.run()
    runs = data_conn.execute("SELECT * FROM runs").fetchall()
    assert len(runs) == 1 and runs[0]["filename"] == "export.csv" and runs[0]["status"] == "parsing"
    assert _uploads_kept() == []      # read into the database, then deleted


def test_upload_wrong_file_shows_error(data_conn):
    at = _app("views/run.py")
    at.file_uploader[0].set_value(("../../evil.csv", b"a,b\n1,2\n", "text/csv"))
    at.button(key="create-run").click().run()
    assert any("Missing columns" in e.value for e in at.error)
    assert data_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert _uploads_kept() == []


def test_failed_products_listed_with_retry(data_conn):
    run_id = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    data_conn.execute("UPDATE products SET state='failed', error='Research failed for X: boom' WHERE run_id=?", (run_id,))
    data_conn.execute("UPDATE runs SET status='done' WHERE id=?", (run_id,))
    at = _app("views/run.py")
    assert "Retry failed" in _labels(at, "button")
    at.button(key=f"retry-{run_id}").click().run()
    assert data_conn.execute("SELECT COUNT(*) FROM products WHERE state='pending'").fetchone()[0] == 10


def test_players_page_edits_facts(data_conn):
    sid = get_or_create_subject(data_conn, "Tee Higgins", "person")
    save_research(data_conn, sid, Research("Tee Higgins", "active", "Football", ["Bengals"], "Bengals",
                                           [Fact("Drafted 2020", "https://a")]))
    at = _app("views/players.py")
    at.text_input(key="player-search").input("higgins").run()
    assert not at.exception
    fid = data_conn.execute("SELECT id FROM facts").fetchone()["id"]
    # facts are read-only until Edit is pressed
    assert not [t for t in at.text_area if t.key == f"fact-{fid}"]
    assert any("Drafted 2020" in m.value for m in at.markdown)
    at.button(key=f"edit-{fid}").click().run()
    at.text_area(key=f"fact-{fid}").input("Drafted in 2020 by Cincinnati").run()
    at.button(key=f"save-{fid}").click().run()
    row = data_conn.execute("SELECT fact, edited FROM facts WHERE id=?", (fid,)).fetchone()
    assert (row["fact"], row["edited"]) == ("Drafted in 2020 by Cincinnati", 1)
    assert not [t for t in at.text_area if t.key == f"fact-{fid}"]          # back to read-only after Save
    at.button(key=f"refresh-{sid}").click().run()
    assert data_conn.execute("SELECT researched_at FROM subjects WHERE id=?", (sid,)).fetchone()[0] is None


def test_settings_saved(data_conn):
    at = _app("views/settings.py")
    at.number_input(key="refresh_days").set_value(30).run()
    at.number_input(key="retired_refresh_days").set_value(365).run()
    at.button(key="save-settings").click().run()
    assert not at.exception
    assert db.get_setting(data_conn, "refresh_days") == 30
    assert db.get_setting(data_conn, "retired_refresh_days") == 365
    cols = db.get_setting(data_conn, "output_columns")
    assert cols[:2] == ["Handle", "Title"] and set(cols) == set(config.DEFAULT_OUTPUT_COLUMNS)


def test_error_run_offers_try_again(data_conn):
    run_id = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    data_conn.execute("UPDATE runs SET status='error', error='bad key' WHERE id=?", (run_id,))
    at = _app("views/run.py")
    assert any("bad key" in e.value for e in at.error)
    at.button(key=f"try-again-{run_id}").click().run()
    assert data_conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()["status"] == "parsing"


def test_running_run_shows_activity(data_conn):
    from rsa_checkins.jobs import log_event
    run_id = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    data_conn.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
    log_event(data_conn, "Looked up Tee Higgins (3 facts)")
    at = _app("views/run.py")
    assert not at.exception
    assert any("Looked up Tee Higgins (3 facts)" in t.value for t in at.text)


def test_download_warns_about_missing_handles(data_conn):
    run_id = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    pid = data_conn.execute("SELECT id FROM products WHERE run_id=? LIMIT 1", (run_id,)).fetchone()["id"]
    complete_product(data_conn, pid, "<p>a</p><p>b</p>", "seo")
    at = _app("views/run.py")
    assert any("new product" in c.value and "test import" in c.value for c in at.caption)


def test_cancel_edit_keeps_the_fact(data_conn):
    sid = get_or_create_subject(data_conn, "Tee Higgins", "person")
    save_research(data_conn, sid, Research("Tee Higgins", "active", "Football", [], None, [Fact("Drafted 2020", "https://a")]))
    at = _app("views/players.py")
    at.text_input(key="player-search").input("higgins").run()
    fid = data_conn.execute("SELECT id FROM facts").fetchone()["id"]
    at.button(key=f"edit-{fid}").click().run()
    at.text_area(key=f"fact-{fid}").input("Something else").run()
    at.button(key=f"cancel-{fid}").click().run()
    assert data_conn.execute("SELECT fact FROM facts WHERE id=?", (fid,)).fetchone()[0] == "Drafted 2020"
    assert not [t for t in at.text_area if t.key == f"fact-{fid}"]


def test_delete_from_edit_mode(data_conn):
    sid = get_or_create_subject(data_conn, "Tee Higgins", "person")
    save_research(data_conn, sid, Research("Tee Higgins", "active", "Football", [], None,
                                           [Fact("Wrong fact", "https://a"), Fact("Right fact", "https://b")]))
    at = _app("views/players.py")
    at.text_input(key="player-search").input("higgins").run()
    wrong = data_conn.execute("SELECT id FROM facts WHERE fact='Wrong fact'").fetchone()["id"]
    at.button(key=f"edit-{wrong}").click().run()
    at.button(key=f"delete-{wrong}").click().run()
    assert not at.exception
    assert [r[0] for r in data_conn.execute("SELECT fact FROM facts WHERE deleted=0")] == ["Right fact"]
    assert not any("Wrong fact" in m.value for m in at.markdown)


def test_page_is_named_large_inventory_export(data_conn):
    at = _app("views/run.py")
    assert at.title[0].value == "Large inventory export"
    assert at.button(key="create-run").label == "Update products"
    nav = (APP_DIR / "app.py").read_text()
    assert 'title="Large inventory export"' in nav


# ---------- Checkins page ----------

from checkin_fixture import make_workbook  # noqa: E402
from rsa_checkins.jobs import create_checkin_run  # noqa: E402

NO_CERT = {"sport": "Football", "league": "NFL", "type": "Custom", "inv": 1, "first-name": "Joe",
           "last-name": "Namath", "team": "New York", "mascot": "Jets"}


def _checkin_run(conn, tmp_path, extra=None):
    return create_checkin_run(conn, make_workbook(tmp_path / "c.xlsx", extra), "c.xlsx")


def test_checkins_is_first_and_default(data_conn):
    nav = (APP_DIR / "app.py").read_text()
    assert nav.index("views/checkins.py") < nav.index("views/run.py")
    assert 'title="Checkins"' in nav and "default=True" in nav
    at = _app("app.py")
    assert not at.exception
    assert at.title[0].value == "Checkins"


def test_checkins_ready_run_shows_preview_and_start(data_conn, tmp_path):
    run_id = _checkin_run(data_conn, tmp_path, {"jerseys": [NO_CERT]})
    at = _app("views/checkins.py")
    assert not at.exception
    assert any("jerseys 5" in c.value for c in at.caption)
    tables = [df.value.to_string() for df in at.dataframe]
    assert any("Joe Namath" in t and "cert" in t for t in tables)
    assert "Start" in _labels(at, "button")
    at.button(key=f"start-{run_id}").click().run()
    assert data_conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()["status"] == "running"


def test_checkins_download_caption(data_conn, tmp_path):
    run_id = _checkin_run(data_conn, tmp_path)
    p = data_conn.execute("SELECT id, seo_title FROM products WHERE run_id=? LIMIT 1", (run_id,)).fetchone()
    set_run_status(data_conn, run_id, "running")
    complete_product(data_conn, p["id"], "<p>a</p>", p["seo_title"])
    data_conn.execute("UPDATE runs SET status='done' WHERE id=?", (run_id,))
    at = _app("views/checkins.py")
    assert not at.exception
    assert any('leave "Overwrite products with matching handles" unticked' in c.value for c in at.caption)
    assert "Download import CSV" in _labels(at, "download_button")


def test_checkins_has_upload_form(data_conn):
    at = _app("views/checkins.py")
    assert at.button(key="create-checkin-run").label == "Create products"


def test_export_page_hides_checkin_runs(data_conn, tmp_path):
    _checkin_run(data_conn, tmp_path)
    at = _app("views/run.py")
    assert not at.exception
    assert any("Upload a Shopify product export to start." in i.value for i in at.info)


def test_checkins_page_hides_export_runs(data_conn):
    create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    at = _app("views/checkins.py")
    assert any("Upload a check-in sheet" in i.value for i in at.info)


def test_both_run_pages_preview_the_same_way(data_conn, tmp_path):
    export = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    data_conn.execute("UPDATE runs SET status='ready' WHERE id=?", (export,))
    _checkin_run(data_conn, tmp_path)
    shown = []
    for page in ("views/run.py", "views/checkins.py"):
        at = _app(page)
        assert not at.exception
        shown.append(([m.label for m in at.metric], [s.value for s in at.subheader][:1], "Start" in _labels(at, "button")))
    assert shown[0] == shown[1]
    assert shown[0][0] == ["Products to write", "Players already known", "Players to look up"]


def test_checkins_upload_creates_run_and_keeps_no_file(data_conn, tmp_path):
    at = _app("views/checkins.py")
    data = make_workbook(tmp_path / "c.xlsx").read_bytes()
    at.file_uploader[0].set_value(("checkin.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    at.button(key="create-checkin-run").click().run()
    assert not at.exception
    runs = data_conn.execute("SELECT * FROM runs").fetchall()
    assert len(runs) == 1 and runs[0]["input_kind"] == "checkin_sheet" and runs[0]["filename"] == "checkin.xlsx"
    assert _uploads_kept() == []


def test_checkins_wrong_file_shows_error_and_keeps_no_file(data_conn):
    at = _app("views/checkins.py")
    at.file_uploader[0].set_value(("notes.xlsx", b"not a workbook", "application/octet-stream"))
    at.button(key="create-checkin-run").click().run()
    assert at.error and data_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert _uploads_kept() == []


def test_no_pages_folder():
    # A folder named "pages" next to app.py makes Streamlit's first load after a restart list the files
    # ("app, checkins, run...") instead of the app's own menu. The pages live in "views" instead.
    assert not (APP_DIR / "pages").exists()
    nav = (APP_DIR / "app.py").read_text()
    assert all((APP_DIR / p).exists() for p in ("views/checkins.py", "views/run.py", "views/players.py",
                                                  "views/settings.py"))
    assert '"views/checkins.py"' in nav and '"pages/' not in nav


@pytest.mark.parametrize("status", ["running", "paused"])
def test_no_downloads_until_the_run_is_finished(data_conn, tmp_path, status):
    export = create_run(data_conn, FIX, "export_small.csv", include_drafts=True)
    checkin = _checkin_run(data_conn, tmp_path)
    for run_id in (export, checkin):
        pid = data_conn.execute("SELECT id FROM products WHERE run_id=? LIMIT 1", (run_id,)).fetchone()["id"]
        complete_product(data_conn, pid, "<p>a</p><p>b</p>", "seo")       # some done, others still to write
        data_conn.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
    for page in ("views/run.py", "views/checkins.py"):
        at = _app(page)
        assert not at.exception
        assert at.get("download_button") == [] and "Downloads" not in [h.value for h in at.subheader]


@pytest.mark.parametrize("upload,kind,expected", [
    ("products export 10.20.csv", "product-update-import", "products export 10.20-product-update-import.csv"),
    ("Football checkin sheet.xlsx", "new-product-import", "Football checkin sheet-new-product-import.csv"),
    ("Football checkin sheet.xlsx", "facts-log", "Football checkin sheet-facts-log.csv"),
    ("noext", "facts-log", "noext-facts-log.csv"),
    ("", "new-product-import", "upload-new-product-import.csv"),
])
def test_download_names_follow_the_upload(upload, kind, expected):
    from rsa_checkins.ui import download_name
    assert download_name(upload, kind) == expected


def test_pages_name_their_downloads():
    assert 'download_suffix="product-update-import"' in (APP_DIR / "views/run.py").read_text()
    assert 'download_suffix="new-product-import"' in (APP_DIR / "views/checkins.py").read_text()
