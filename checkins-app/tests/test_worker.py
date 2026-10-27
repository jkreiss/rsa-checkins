import json
import threading

import anthropic
import httpx2 as httpx

from fakes import FIX, NOW, parse_responder, search_block, text_response, tool_response

from rsa_checkins import rules, worker
from rsa_checkins.db import get_setting
from rsa_checkins.jobs import create_run, progress, set_run_status
from rsa_checkins.worker import process_one


def _research_reply(kw):
    name = kw["messages"][0]["content"].split("\n")[0].removeprefix("Subject: ")
    return tool_response("save_research", {
        "display_name": name, "status": "retired", "sport": "Football", "teams": ["Team"], "current_team": None,
        "facts": [{"fact": f"{name} fact", "source_url": "https://example.com"}]}, before=[search_block("https://example.com")])


def _write_reply(kw):
    payload = json.loads(kw["messages"][0]["content"])
    return text_response({"products": [
        {"handle": p["handle"], "sentence1": f"Signed item for {p['handle']} & co.", "call_to_action": "Order today.",
         "note": f"Note for {p['handle']}", "seo_title": f"SEO {p['handle']}"} for p in payload["products"]]})


def responder(write=_write_reply, research=_research_reply):
    def r(kw):
        if kw["system"] == rules.TITLE_PARSE_PROMPT:
            return parse_responder(kw)
        if kw["system"] == rules.RESEARCH_PROMPT:
            return research(kw)
        if kw["system"] == rules.WRITE_PROMPT:
            return write(kw)
        raise AssertionError("unexpected call")
    return r


def _started_run(conn, client):
    run_id = create_run(conn, FIX, "export_small.csv", include_drafts=True)
    assert process_one(conn, client, "w1", NOW) is True          # prepares the run
    assert conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()["status"] == "ready"
    set_run_status(conn, run_id, "running")
    return run_id


def test_worker_drains_run(conn, fake_client_factory):
    client = fake_client_factory(responder=responder())
    run_id = _started_run(conn, client)
    while process_one(conn, client, "w1", NOW):
        pass
    pr = progress(conn, run_id)
    assert (pr.done, pr.failed, pr.status) == (10, 0, "done")
    html = conn.execute("SELECT description_html FROM products WHERE handle LIKE 'jim-kelly%'").fetchone()[0]
    assert "money-back guarantee" in html and "sticker" not in html
    teague = conn.execute("SELECT description_html FROM products WHERE handle LIKE 'george-teague%'").fetchone()[0]
    assert "It carries a unique tamper-evident authentication sticker" in teague
    odell = conn.execute("SELECT description_html, seo_title FROM products WHERE handle LIKE 'odell%'").fetchone()
    assert "authenticated by Beckett" in odell["description_html"] and "&amp; co." in odell["description_html"]
    assert odell["seo_title"] == "Odell Beckham Jr. Autographed Jersey - Beckett Authentication"   # built in code
    research_calls = [c for c in client.calls if c["system"] == rules.RESEARCH_PROMPT]
    assert len(research_calls) == 14
    assert all(c["model"] == get_setting(conn, "model") for c in client.calls)


def test_write_call_gets_facts_items_and_previous_notes(conn, fake_client_factory):
    client = fake_client_factory(responder=responder())
    _started_run(conn, client)
    while process_one(conn, client, "w1", NOW):
        pass
    writes = [json.loads(c["messages"][0]["content"]) for c in client.calls if c["system"] == rules.WRITE_PROMPT]
    by_handle = {w["products"][0]["handle"]: w for w in writes}
    irvin = next(w for h, w in by_handle.items() if h.startswith("michael-irvin"))
    helmet = next(w for h, w in by_handle.items() if h.startswith("emmitt-smith-and-tony"))
    assert [s["name"] for s in irvin["subjects"]] == ["Michael Irvin", "Emmitt Smith"]
    assert irvin["subjects"][0]["facts"][0]["fact"] == "Michael Irvin fact"
    item = irvin["products"][0]
    assert (item["kind"], item["authenticator"], item["team"]) == ("signed", "JSA", "Dallas Cowboys")
    # helmet was written first (lower product id), so the Irvin & Emmitt call sees its note
    assert helmet["previous_notes"] == [] and irvin["previous_notes"] == [f"Note for {helmet['products'][0]['handle']}"]


def test_write_error_fails_group_and_retries(conn, fake_client_factory):
    writes = []

    def truncated(kw):
        writes.append(kw)
        return text_response("{", stop="max_tokens")

    client = fake_client_factory(responder=responder(write=truncated))
    run_id = _started_run(conn, client)
    while not writes:
        assert process_one(conn, client, "w1", NOW)
    handle = json.loads(writes[0]["messages"][0]["content"])["products"][0]["handle"]
    row = conn.execute("SELECT state, attempts FROM products WHERE handle=?", (handle,)).fetchone()
    assert (row["state"], row["attempts"]) == ("pending", 1)
    while process_one(conn, client, "w1", NOW):
        pass
    row = conn.execute("SELECT state, attempts, error FROM products WHERE handle=?", (handle,)).fetchone()
    assert (row["state"], row["attempts"]) == ("failed", 3) and "cut off" in row["error"]
    pr = progress(conn, run_id)
    assert (pr.failed, pr.status) == (10, "done")


def test_missing_handle_fails_with_reason(conn, fake_client_factory):
    def drop_teague(kw):
        reply = _write_reply(kw)
        data = json.loads(reply.content[0].text)
        data["products"] = [p for p in data["products"] if not p["handle"].startswith("george-teague")]
        return text_response(data)

    client = fake_client_factory(responder=responder(write=drop_teague))
    run_id = _started_run(conn, client)
    while process_one(conn, client, "w1", NOW):
        pass
    row = conn.execute("SELECT state, error FROM products WHERE handle LIKE 'george-teague%'").fetchone()
    assert (row["state"], row["error"]) == ("failed", "No description returned")
    assert progress(conn, run_id).done == 9


def test_research_error_counts_attempt(conn, fake_client_factory):
    def no_save(kw):
        return text_response("I could not find anything.")

    client = fake_client_factory(responder=responder(research=no_save))
    run_id = _started_run(conn, client)
    while process_one(conn, client, "w1", NOW):
        pass
    pr = progress(conn, run_id)
    assert (pr.failed, pr.status) == (10, "done")
    err = conn.execute("SELECT error FROM products WHERE handle LIKE 'tee-higgins%'").fetchone()["error"]
    assert err.startswith("Research failed for Tee Higgins: Claude didn't save any research")


def test_api_error_counts_as_failed_attempt(conn, fake_client_factory):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def overloaded(kw):
        return anthropic.InternalServerError("overloaded", response=httpx.Response(529, request=req), body=None)

    client = fake_client_factory(responder=responder(research=overloaded))
    run_id = _started_run(conn, client)
    assert process_one(conn, client, "w1", NOW)
    row = conn.execute("SELECT research_attempts, research_error, claimed_by FROM subjects ORDER BY id LIMIT 1").fetchone()
    assert row["research_attempts"] == 1 and "overloaded" in row["research_error"] and row["claimed_by"] is None


def test_prepare_error_marks_run(conn, fake_client_factory):
    client = fake_client_factory(responder=lambda kw: text_response({"results": []}))
    run_id = create_run(conn, FIX, "x.csv", include_drafts=True)
    assert process_one(conn, client, "w1", NOW) is True
    assert conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()["status"] == "error"
    assert process_one(conn, client, "w1", NOW) is False


def test_worker_loop_survives_errors_and_stops(conn, monkeypatch):
    stop = threading.Event()
    calls = []

    def fake_process_one(c, client, worker_id, now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("boom")
        stop.set()
        return False

    monkeypatch.setattr(worker, "process_one", fake_process_one)
    worker.worker_loop(conn, object(), "w1", stop, idle_sleep=0, error_sleep=0)
    assert len(calls) == 2


def test_heartbeat_runs_on_its_own_thread_while_work_is_slow(conn):
    """The heartbeat must keep beating while a worker thread waits minutes on one request."""
    stop = threading.Event()
    t = threading.Thread(target=worker.heartbeat_loop, args=(conn, stop), kwargs={"interval": 0.01})
    t.start()
    for _ in range(200):
        if get_setting(conn, "worker_heartbeat"):
            break
        threading.Event().wait(0.01)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive() and get_setting(conn, "worker_heartbeat")
    assert worker.HEARTBEAT_INTERVAL * 2 < 60   # the UI treats a heartbeat older than 60 s as stopped


def test_worker_logs_activity(conn, fake_client_factory):
    from rsa_checkins.jobs import recent_events
    client = fake_client_factory(responder=responder())
    _started_run(conn, client)
    while process_one(conn, client, "w1", NOW):
        pass
    messages = [e["message"] for e in recent_events(conn, limit=100)]
    assert "Looked up Tee Higgins (1 fact)" in messages
    assert any(m.startswith("Wrote 1 description: Tee Higgins Signed") for m in messages)
    assert any(m.startswith("Read") and "titles" in m for m in messages)


def test_seo_title_from_code_with_claude_as_fallback(conn, fake_client_factory):
    client = fake_client_factory(responder=responder())
    _started_run(conn, client)
    while process_one(conn, client, "w1", NOW):
        pass
    seo = dict(conn.execute("SELECT handle, seo_title FROM products").fetchall())
    tee = next(v for k, v in seo.items() if k.startswith("tee-higgins"))
    braves = next((k, v) for k, v in seo.items() if k.startswith("atlanta-braves"))
    seat = next((k, v) for k, v in seo.items() if k.startswith("michael-irvin"))
    assert tee == "Tee Higgins Autographed Cincinnati Jersey - Beckett Authentication"
    assert braves[1] == f"SEO {braves[0]}"     # four signers don't fit in 70 characters: Claude's
    assert seat[1] == f"SEO {seat[0]}"         # "Collectibles" has no item word: Claude's


def test_signed_products_get_rotating_openings(conn, fake_client_factory):
    client = fake_client_factory(responder=responder())
    _started_run(conn, client)
    while process_one(conn, client, "w1", NOW):
        pass
    kinds = {r["handle"]: (r["id"], r["kind"]) for r in conn.execute("SELECT id, handle, kind FROM products")}
    sent = [p for c in client.calls if c["system"] == rules.WRITE_PROMPT
            for p in json.loads(c["messages"][0]["content"])["products"]]
    assert sent
    for p in sent:
        pid, kind = kinds[p["handle"]]
        if kind == "signed":
            assert p["opening"] == rules.SIGNED_OPENINGS[pid % len(rules.SIGNED_OPENINGS)]
        else:
            assert p["opening"] == ""
    assert len({p["opening"] for p in sent if p["opening"]}) > 1


def test_openings_keep_the_owner_rules():
    assert len(rules.SIGNED_OPENINGS) == 4
    for o in rules.SIGNED_OPENINGS:
        assert "[person]" in o and "[item description]" in o and "[collectible term]" in o
    assert "opening" in rules.WRITE_PROMPT
