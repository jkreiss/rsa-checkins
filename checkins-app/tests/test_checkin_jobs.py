import json
from datetime import datetime, timezone

import pytest

from checkin_fixture import make_workbook
from fakes import FIX, text_response

from rsa_checkins import players, rules
from rsa_checkins.checkin_sheet import CheckinFormatError
from rsa_checkins.claude_api import Fact, Research
from rsa_checkins.descriptions import auth_sentence
from rsa_checkins.jobs import create_checkin_run, create_run, list_runs, run_notes, set_run_status
from rsa_checkins.worker import process_one

KEENAN = "keenan-allen-autographed-indianapolis-colts-authentic-nfl-white-mitchell-ness-jersey-jsa"


def _run(conn, tmp_path, extra=None):
    path = make_workbook(tmp_path / "c.xlsx", extra)
    return create_checkin_run(conn, path, "c.xlsx")


def _products(conn, run_id):
    return conn.execute("SELECT * FROM products WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()


def test_create_checkin_run(conn, tmp_path):
    run_id = _run(conn, tmp_path)
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert (run["status"], run["input_kind"]) == ("ready", "checkin_sheet")
    rows = _products(conn, run_id)
    assert len(rows) == 10
    assert {(p["shop_status"], p["kind"]) for p in rows} == {("draft", "signed")}
    assert run_notes(conn, run_id)["tabs"] == {"jerseys": 5, "fs-helm": 1, "minis": 2, "fb-balls": 2}
    keenan = next(p for p in rows if p["handle"] == KEENAN)
    assert keenan["auth"] == "JSA"
    assert keenan["seo_title"] == "Keenan Allen Autographed Indianapolis Jersey - JSA Authentication"
    assert keenan["team"] == "Indianapolis Colts" and keenan["league"] == "NFL"
    assert json.loads(keenan["first_row"])["Variant Price"] == "349.99"
    kamara = next(p for p in rows if "kamara" in p["handle"])
    assert kamara["team"] == "Tennessee Volunteers"     # the AI still knows the college


def test_each_product_links_its_player(conn, tmp_path):
    run_id = _run(conn, tmp_path)
    names = [r["name"] for r in conn.execute(
        "SELECT s.name FROM products p JOIN product_subjects ps ON ps.product_id = p.id "
        "JOIN subjects s ON s.id = ps.subject_id WHERE p.run_id = ? ORDER BY p.id", (run_id,))]
    assert names[:2] == ["Keenan Allen", "Keenan Allen"]
    assert "LeGarrette Blount" in names and len(names) == 10


def test_duplicate_titles_get_numbered_handles(conn, tmp_path):
    keenan = {"sport": "Football", "league": "NFL", "product": "Jersey", "type": "Authentic",
              "model": "Mitchell & Ness", "inv": 1, "first-name": "Keenan", "last-name": "Allen",
              "team": "Indianapolis", "mascot": "Colts", "color": "White", "cert": "JSA"}
    run_id = _run(conn, tmp_path, {"jerseys": [keenan, keenan]})
    handles = [p["handle"] for p in _products(conn, run_id)]
    assert handles.count(KEENAN) == 1
    assert f"{KEENAN}-2" in handles and f"{KEENAN}-3" in handles


def test_problems_and_warnings_recorded(conn, tmp_path):
    no_cert = {"sport": "Football", "league": "NFL", "type": "Custom", "inv": 1, "first-name": "Joe",
               "last-name": "Namath", "team": "New York", "mascot": "Jets"}
    no_mascot = {**no_cert, "first-name": "Kevin", "last-name": "Mawae", "mascot": None, "cert": "JSA"}
    run_id = _run(conn, tmp_path, {"jerseys": [no_cert, no_mascot]})
    notes = run_notes(conn, run_id)
    assert [(p["tab"], p["row"], p["name"]) for p in notes["problems"]] == [("jerseys", 8, "Joe Namath")]
    assert "cert" in notes["problems"][0]["reason"]
    assert [(w["tab"], w["row"], w["name"]) for w in notes["warnings"]] == [("jerseys", 9, "Kevin Mawae")]
    assert "mascot" in notes["warnings"][0]["warning"]
    assert not any("namath" in p["handle"] for p in _products(conn, run_id))
    assert notes["ignored_tabs"] == []


def test_not_a_checkin_sheet_raises(conn, tmp_path):
    import openpyxl
    path = tmp_path / "x.xlsx"
    openpyxl.Workbook().save(path)
    with pytest.raises(CheckinFormatError):
        create_checkin_run(conn, path, "x.xlsx")
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_known_player_reused(conn, tmp_path):
    sid = players.get_or_create_subject(conn, "LeGarrette Blount", "person")
    run_id = _run(conn, tmp_path)
    linked = conn.execute(
        "SELECT ps.subject_id FROM products p JOIN product_subjects ps ON ps.product_id = p.id "
        "WHERE p.run_id = ? AND p.handle LIKE 'legarrette-blount%'", (run_id,)).fetchone()["subject_id"]
    assert linked == sid


def test_out_of_attempts_player_gets_new_attempts(conn, tmp_path):
    sid = players.get_or_create_subject(conn, "Bob Griese", "person")
    conn.execute("UPDATE subjects SET research_attempts = 3 WHERE id = ?", (sid,))
    _run(conn, tmp_path)
    assert conn.execute("SELECT research_attempts FROM subjects WHERE id = ?", (sid,)).fetchone()[0] == 0


def test_list_runs_by_kind(conn, tmp_path):
    export = create_run(conn, FIX, "export_small.csv", include_drafts=True)
    checkin = _run(conn, tmp_path)
    assert [r["id"] for r in list_runs(conn, "shopify_export")] == [export]
    assert [r["id"] for r in list_runs(conn, "checkin_sheet")] == [checkin]
    assert [r["id"] for r in list_runs(conn)] == [checkin, export]


def test_auth_sentence_uses_given_auth():
    assert "authenticated by JSA" in auth_sentence("Some Item", "signed", 0, auth="JSA")
    assert "authenticated by" not in auth_sentence("Some Item", "signed", 0)


def _write_reply(kw):
    payload = json.loads(kw["messages"][0]["content"])
    return text_response({"products": [
        {"handle": p["handle"], "sentence1": "Signed.", "call_to_action": "Buy.", "note": "Note.",
         "seo_title": "AI SEO"} for p in payload["products"]]})


def test_worker_writes_checkin_product(conn, tmp_path, fake_client_factory):
    run_id = _run(conn, tmp_path)
    for s in conn.execute("SELECT id, name FROM subjects").fetchall():     # every player already looked up
        players.save_research(conn, s["id"], Research(s["name"], "active", "Football", [], None,
                                                      [Fact(f"{s['name']} fact", "https://example.com")]))
    set_run_status(conn, run_id, "running")
    client = fake_client_factory(responder=lambda kw: (_write_reply(kw) if kw["system"] == rules.WRITE_PROMPT
                                                       else (_ for _ in ()).throw(AssertionError("only writes"))))
    assert process_one(conn, client, "w1", datetime.now(timezone.utc)) is True
    keenan = conn.execute("SELECT * FROM products WHERE handle = ?", (KEENAN,)).fetchone()
    assert keenan["state"] == "done"
    assert "authenticated by JSA" in keenan["description_html"]
    assert keenan["seo_title"] == "Keenan Allen Autographed Indianapolis Jersey - JSA Authentication"
    sent = json.loads(client.calls[0]["messages"][0]["content"])
    item = next(p for p in sent["products"] if p["handle"] == KEENAN)
    assert item["authenticator"] == "JSA"
    assert item["team"] == "Indianapolis Colts"


# ---- Task 5: the import file ----

import csv  # noqa: E402
import io  # noqa: E402

from rsa_checkins.config import TEMPLATE_COLUMNS  # noqa: E402
from rsa_checkins.jobs import complete_product  # noqa: E402
from rsa_checkins.output import build_checkin_csv  # noqa: E402


def _csv(data: bytes):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8")))), next(csv.reader(io.StringIO(data.decode("utf-8"))))


def test_checkin_csv(conn, tmp_path):
    run_id = _run(conn, tmp_path)
    rows = _products(conn, run_id)
    for p in rows[:2]:
        complete_product(conn, p["id"], "<p>a</p>", p["seo_title"])
    data = build_checkin_csv(conn, run_id)
    assert not data.startswith(b"\xef\xbb\xbf")
    out, header = _csv(data)
    assert header == TEMPLATE_COLUMNS
    assert len(out) == 2
    keenan = out[0]
    assert keenan["Handle"] == KEENAN
    assert keenan["Title"] == "Keenan Allen Autographed Indianapolis Colts Authentic NFL White Mitchell & Ness Jersey - JSA"
    assert (keenan["Variant Price"], keenan["Status"], keenan["Published"]) == ("349.99", "draft", "FALSE")
    assert keenan["Body (HTML)"] == "<p>a</p>"
    assert keenan["SEO Title"] == "Keenan Allen Autographed Indianapolis Jersey - JSA Authentication"
    assert keenan["Image Src"] == ""
    assert out[1]["Handle"] == f"{KEENAN.replace('colts-authentic-nfl-white-mitchell-ness', 'blue-throwback-football')}"


def test_checkin_csv_only_done(conn, tmp_path):
    run_id = _run(conn, tmp_path)
    out, _ = _csv(build_checkin_csv(conn, run_id))
    assert out == []
