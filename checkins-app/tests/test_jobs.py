from datetime import timedelta

from fakes import FIX, NOW, prepared_run

from rsa_checkins.claude_api import ClaudeNoResult, Fact, Research
from rsa_checkins.jobs import (MAX_ATTEMPTS, WRITE_GROUP_SIZE, ResearchWork, WriteWork, claim_next, complete_product,
                               complete_research, create_run, fail_products, fail_research, failed_products,
                               list_runs, prepare_run, preview, progress, retry_failed, set_run_status)
from rsa_checkins.players import is_fresh


def _research_all(conn):
    for s in conn.execute("SELECT id, name FROM subjects").fetchall():
        complete_research(conn, s["id"], Research(s["name"], "active", "Football", [], None, [Fact("f", "")]))


def _sid(conn, name):
    return conn.execute("SELECT id FROM subjects WHERE name=?", (name,)).fetchone()["id"]


def test_create_and_prepare_run_counts(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    p = preview(conn, run_id, 90, NOW)
    assert (p.products, p.skipped_new_style, p.reused) == (10, 1, 0)
    assert p.subjects == 14 and p.subjects_to_research == 14 and p.subjects_fresh == 0
    assert conn.execute("SELECT kind FROM subjects WHERE name LIKE '1981 Donruss%'").fetchone()["kind"] == "product_line"
    assert conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()["status"] == "ready"
    braves = conn.execute("SELECT * FROM products WHERE handle LIKE 'atlanta-braves%'").fetchone()
    assert (braves["kind"], braves["team"], braves["league"]) == ("signed", "Atlanta Braves", "MLB")
    names = [r["name"] for r in conn.execute(
        "SELECT s.name FROM product_subjects ps JOIN subjects s ON s.id=ps.subject_id WHERE ps.product_id=? ORDER BY ps.position",
        (braves["id"],))]
    assert names == ["Gary Sheffield", "Dale Murphy", "Chipper Jones", "David Justice"]


def test_prepare_run_error_sets_run_error(conn, fake_client_factory):
    run_id = create_run(conn, FIX, "x.csv", include_drafts=True)
    prepare_run(conn, fake_client_factory(responses=[ClaudeNoResult("nope")] * 2), "m", run_id)
    row = conn.execute("SELECT status, error FROM runs WHERE id=?", (run_id,)).fetchone()
    assert (row["status"], row["error"]) == ("error", "nope")


def test_drafts_excluded_when_asked(conn):
    run_id = create_run(conn, FIX, "x.csv", include_drafts=False)
    assert progress(conn, run_id).total == 7


def test_paused_run_gives_no_work(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "paused")
    assert claim_next(conn, "w1", 90, NOW) is None


def test_ready_run_gives_no_work_until_started(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    assert claim_next(conn, "w1", 90, NOW) is None
    set_run_status(conn, run_id, "running")
    assert claim_next(conn, "w1", 90, NOW) is not None


def test_research_before_write_and_group_size(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    w = claim_next(conn, "w1", 90, NOW)
    assert isinstance(w, ResearchWork)
    assert claim_next(conn, "w2", 90, NOW).subject_id != w.subject_id   # claimed work not handed out twice
    assert 1 <= len(w.example_titles) <= 5


def test_write_group_shares_subjects_and_is_capped(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    tee = _sid(conn, "Tee Higgins")
    first = conn.execute("SELECT * FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run_id,)).fetchone()
    for i in range(10):   # 10 more Tee Higgins products
        cur = conn.execute(
            "INSERT INTO products (run_id, handle, title, product_type, tags, shop_status, first_row, kind) "
            "VALUES (?, ?, ?, '', '', 'active', '{}', 'signed')", (run_id, f"tee-{i}", f"Tee Higgins Signed Item {i}"))
        conn.execute("INSERT INTO product_subjects VALUES (?, ?, 0)", (cur.lastrowid, tee))
    complete_research(conn, tee, Research("Tee Higgins", "active", "Football", [], None, []))
    w = claim_next(conn, "w1", 90, NOW)
    while isinstance(w, ResearchWork):
        w = claim_next(conn, "w1", 90, NOW)
    assert isinstance(w, WriteWork) and len(w.product_ids) == WRITE_GROUP_SIZE
    assert w.product_ids[0] == first["id"]
    rest = claim_next(conn, "w2", 90, NOW)
    while isinstance(rest, ResearchWork):
        rest = claim_next(conn, "w2", 90, NOW)
    assert isinstance(rest, WriteWork) and len(rest.product_ids) == 11 - WRITE_GROUP_SIZE
    assert not set(rest.product_ids) & set(w.product_ids)


def test_stale_claim_is_reclaimed(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    w = claim_next(conn, "w1", 90, NOW)
    again = claim_next(conn, "w2", 90, NOW + timedelta(minutes=16))
    assert isinstance(again, ResearchWork) and again.subject_id == w.subject_id


def test_stale_write_claim_is_reclaimed(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    _research_all(conn)
    w = claim_next(conn, "w1", 90, NOW)
    assert isinstance(w, WriteWork)
    again = claim_next(conn, "w2", 90, NOW + timedelta(minutes=16))
    assert again.product_ids == w.product_ids


def test_research_failure_fails_dependent_products(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    dorsett = _sid(conn, "Tony Dorsett")
    for i in range(MAX_ATTEMPTS):
        fail_research(conn, dorsett, "search broke")
        state = conn.execute("SELECT state FROM products WHERE handle LIKE 'emmitt-smith-and-tony%'").fetchone()["state"]
        assert state == ("failed" if i == MAX_ATTEMPTS - 1 else "pending")
    helmet = conn.execute("SELECT state, error FROM products WHERE handle LIKE 'emmitt-smith-and-tony%'").fetchone()
    assert helmet["state"] == "failed" and "Tony Dorsett" in helmet["error"]
    pr = progress(conn, run_id)
    assert (pr.failed, pr.pending) == (1, 9)
    assert [r["handle"] for r in failed_products(conn, run_id)] == ["emmitt-smith-and-tony-dorsett-signed-dallas-cowboys-speed-mini-football-helmet"]


def test_fresh_subject_skips_research(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    _research_all(conn)
    assert isinstance(claim_next(conn, "w1", 90, NOW), WriteWork)
    assert preview(conn, run_id, 90, NOW).subjects_fresh == 14
    sid = _sid(conn, "Jim Kelly")
    conn.execute("UPDATE subjects SET status='retired', researched_at=? WHERE id=?", ((NOW - timedelta(days=400)).isoformat(), sid))
    assert is_fresh(conn.execute("SELECT * FROM subjects WHERE id=?", (sid,)).fetchone(), 90, NOW)
    conn.execute("UPDATE subjects SET status='active', researched_at=? WHERE id=?", ((NOW - timedelta(days=91)).isoformat(), sid))
    assert not is_fresh(conn.execute("SELECT * FROM subjects WHERE id=?", (sid,)).fetchone(), 90, NOW)
    w = claim_next(conn, "w2", 90, NOW)
    assert isinstance(w, ResearchWork) and w.subject_id == sid


def test_run_done_when_last_product_completes(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    ids = [r["id"] for r in conn.execute("SELECT id FROM products WHERE run_id=? ORDER BY id", (run_id,))]
    for pid in ids[:-1]:
        complete_product(conn, pid, "<p>a</p><p>b</p>", "seo")
    assert progress(conn, run_id).status == "running"
    complete_product(conn, ids[-1], "<p>a</p><p>b</p>", "seo")
    pr = progress(conn, run_id)
    assert (pr.status, pr.done, pr.pending, pr.total) == ("done", 10, 0, 10)


def test_fail_products_retries_then_fails_and_retry_failed_resets(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    ids = [r["id"] for r in conn.execute("SELECT id FROM products WHERE run_id=? ORDER BY id", (run_id,))]
    for pid in ids[1:]:
        complete_product(conn, pid, "<p>a</p><p>b</p>", "seo")
    for i in range(MAX_ATTEMPTS):
        fail_products(conn, [ids[0]], "No description returned")
    row = conn.execute("SELECT state, error, attempts FROM products WHERE id=?", (ids[0],)).fetchone()
    assert (row["state"], row["error"], row["attempts"]) == ("failed", "No description returned", MAX_ATTEMPTS)
    assert progress(conn, run_id).status == "done"
    assert retry_failed(conn, run_id) == 1
    row = conn.execute("SELECT state, attempts FROM products WHERE id=?", (ids[0],)).fetchone()
    assert (row["state"], row["attempts"]) == ("pending", 0)
    assert progress(conn, run_id).status == "running"


def test_retry_failed_resets_research_attempts(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    dorsett = _sid(conn, "Tony Dorsett")
    for _ in range(MAX_ATTEMPTS):
        fail_research(conn, dorsett, "x")
    assert retry_failed(conn, run_id) == 1
    assert conn.execute("SELECT research_attempts FROM subjects WHERE id=?", (dorsett,)).fetchone()[0] == 0


def test_create_run_reuses_previous_description(conn, fake_client_factory):
    run1 = prepared_run(conn, fake_client_factory)
    pid = conn.execute("SELECT id FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run1,)).fetchone()["id"]
    complete_product(conn, pid, "<p>new</p><p>note</p>", "Tee Higgins Autographed Cincinnati Jersey - Beckett Authentication")
    run2 = create_run(conn, FIX, "again.csv", include_drafts=True)
    row = conn.execute("SELECT state, reused, description_html FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run2,)).fetchone()
    assert (row["state"], row["reused"], row["description_html"]) == ("done", 1, "<p>new</p><p>note</p>")
    assert preview(conn, run2, 90, NOW).reused == 1


def test_reused_product_keeps_parse_and_subjects(conn, fake_client_factory):
    run1 = prepared_run(conn, fake_client_factory)
    pid = conn.execute("SELECT id FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run1,)).fetchone()["id"]
    complete_product(conn, pid, "<p>new</p><p>note</p>", "seo")
    run2 = create_run(conn, FIX, "again.csv", include_drafts=True)
    row = conn.execute("SELECT * FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run2,)).fetchone()
    assert (row["kind"], row["team"], row["league"], row["seo_title"]) == ("signed", "Cincinnati Bengals", "NFL", "seo")
    linked = conn.execute("SELECT subject_id FROM product_subjects WHERE product_id=?", (row["id"],)).fetchall()
    assert [r[0] for r in linked] == [_sid(conn, "Tee Higgins")]


def test_run_with_only_reused_products_is_done_when_started(conn, fake_client_factory):
    run1 = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run1, "running")
    for r in conn.execute("SELECT id FROM products WHERE run_id=?", (run1,)).fetchall():
        complete_product(conn, r["id"], "<p>a</p><p>b</p>", "seo")
    run2 = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run2, "running")
    assert progress(conn, run2).status == "done"


def test_list_runs_newest_first(conn, fake_client_factory):
    a = create_run(conn, FIX, "a.csv", include_drafts=True)
    b = create_run(conn, FIX, "b.csv", include_drafts=True)
    assert [r["id"] for r in list_runs(conn)] == [b, a]


def test_prepare_api_error_marks_run_error(conn, fake_client_factory):
    import anthropic
    import httpx2
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError("invalid x-api-key", response=httpx2.Response(401, request=req), body=None)
    run_id = create_run(conn, FIX, "x.csv", include_drafts=True)
    prepare_run(conn, fake_client_factory(responses=[err]), "m", run_id)
    row = conn.execute("SELECT status, error FROM runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "error" and "invalid x-api-key" in row["error"]


def test_retry_prepare_sets_run_back_to_parsing(conn, fake_client_factory):
    from rsa_checkins.jobs import retry_prepare
    run_id = create_run(conn, FIX, "x.csv", include_drafts=True)
    prepare_run(conn, fake_client_factory(responses=[ClaudeNoResult("nope")] * 2), "m", run_id)
    retry_prepare(conn, run_id)
    row = conn.execute("SELECT status, error FROM runs WHERE id=?", (run_id,)).fetchone()
    assert (row["status"], row["error"]) == ("parsing", None)


def test_stale_writer_cannot_overwrite_newer_result(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    _research_all(conn)
    old = claim_next(conn, "w1", 90, NOW)
    new = claim_next(conn, "w2", 90, NOW + timedelta(minutes=16))
    pid = old.product_ids[0]
    assert new.product_ids[0] == pid
    complete_product(conn, pid, "<p>w1 late</p><p>x</p>", "w1", worker_id="w1")     # w1 lost the claim
    assert conn.execute("SELECT state FROM products WHERE id=?", (pid,)).fetchone()["state"] == "pending"
    complete_product(conn, pid, "<p>w2</p><p>x</p>", "w2", worker_id="w2")
    complete_product(conn, pid, "<p>w1 later</p><p>x</p>", "w1", worker_id="w1")
    fail_products(conn, [pid], "late failure", worker_id="w1")
    row = conn.execute("SELECT description_html, attempts, error FROM products WHERE id=?", (pid,)).fetchone()
    assert (row["description_html"], row["attempts"], row["error"]) == ("<p>w2</p><p>x</p>", 0, None)


def test_stale_researcher_cannot_overwrite_or_fail(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    old = claim_next(conn, "w1", 90, NOW)
    new = claim_next(conn, "w2", 90, NOW + timedelta(minutes=16))
    assert new.subject_id == old.subject_id
    complete_research(conn, new.subject_id, Research("Right Name", "active", "Football", [], None, [Fact("new", "")]),
                      worker_id="w2")
    complete_research(conn, old.subject_id, Research("Stale Name", "active", "Football", [], None, [Fact("old", "")]),
                      worker_id="w1")
    fail_research(conn, old.subject_id, "late error", worker_id="w1")
    s = conn.execute("SELECT name, research_attempts FROM subjects WHERE id=?", (old.subject_id,)).fetchone()
    assert (s["name"], s["research_attempts"]) == ("Right Name", 0)


def test_client_retries_fit_inside_the_claim_timeout():
    from rsa_checkins.claude_api import make_client
    from rsa_checkins.jobs import CLAIM_TIMEOUT_MIN
    c = make_client(api_key="test")
    assert c.max_retries == 2 and c.timeout == 300
    assert c.timeout * (c.max_retries + 1) <= CLAIM_TIMEOUT_MIN * 60


def test_fact_edit_after_writing_blocks_reuse(conn, fake_client_factory):
    from rsa_checkins.players import add_fact, delete_fact, list_facts, update_fact
    run1 = prepared_run(conn, fake_client_factory)
    tee_pid = conn.execute("SELECT id FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run1,)).fetchone()["id"]
    kelly_pid = conn.execute("SELECT id FROM products WHERE run_id=? AND handle LIKE 'jim-kelly%'", (run1,)).fetchone()["id"]
    complete_product(conn, tee_pid, "<p>old</p><p>note</p>", "seo")
    complete_product(conn, kelly_pid, "<p>old</p><p>note</p>", "seo")
    tee = _sid(conn, "Tee Higgins")
    add_fact(conn, tee, "Corrected fact", "https://a")
    run2 = create_run(conn, FIX, "again.csv", include_drafts=True)
    states = {r["handle"][:9]: (r["state"], r["reused"]) for r in conn.execute(
        "SELECT handle, state, reused FROM products WHERE run_id=? AND (handle LIKE 'tee-higgins%' OR handle LIKE 'jim-kelly%')", (run2,))}
    assert states == {"tee-higgi": ("pending", 0), "jim-kelly": ("done", 1)}
    fid = list_facts(conn, tee)[0]["id"]
    for change in (lambda: update_fact(conn, fid, "x", ""), lambda: delete_fact(conn, fid)):
        conn.execute("UPDATE subjects SET facts_edited_at = NULL WHERE id = ?", (tee,))
        change()
        assert conn.execute("SELECT facts_edited_at FROM subjects WHERE id=?", (tee,)).fetchone()[0]


def test_re_research_alone_does_not_block_reuse(conn, fake_client_factory):
    run1 = prepared_run(conn, fake_client_factory)
    pid = conn.execute("SELECT id FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run1,)).fetchone()["id"]
    complete_product(conn, pid, "<p>old</p><p>note</p>", "seo")
    complete_research(conn, _sid(conn, "Tee Higgins"), Research("Tee Higgins", "active", "Football", [], None, [Fact("f", "")]))
    run2 = create_run(conn, FIX, "again.csv", include_drafts=True)
    assert conn.execute("SELECT reused FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run2,)).fetchone()[0] == 1


def test_current_activity_names_claimed_work(conn, fake_client_factory):
    from rsa_checkins.jobs import current_activity
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    assert current_activity(conn, NOW) == []
    w = claim_next(conn, "w1", 90, NOW)
    assert current_activity(conn, NOW) == [f"Looking up {w.name}"]
    assert current_activity(conn, NOW + timedelta(minutes=16)) == []      # an expired claim isn't current
    conn.execute("UPDATE subjects SET claimed_at=NULL, claimed_by=NULL")
    _research_all(conn)
    ww = claim_next(conn, "w1", 90, NOW)
    title = conn.execute("SELECT title FROM products WHERE id=?", (ww.product_ids[0],)).fetchone()["title"]
    assert current_activity(conn, NOW) == [f"Writing: {title}"]


def test_event_log_keeps_newest(conn):
    from rsa_checkins.jobs import EVENT_LOG_SIZE, log_event, recent_events
    for i in range(EVENT_LOG_SIZE + 5):
        log_event(conn, f"event {i}")
    events = recent_events(conn, limit=3)
    assert [e["message"] for e in events] == [f"event {EVENT_LOG_SIZE + 4}", f"event {EVENT_LOG_SIZE + 3}", f"event {EVENT_LOG_SIZE + 2}"]
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == EVENT_LOG_SIZE


def test_team_and_league_come_from_tags_not_claude(conn, fake_client_factory):
    from fakes import CANNED_PARSES
    run_id = prepared_run(conn, fake_client_factory)
    rows = conn.execute("SELECT title, team, league FROM products WHERE run_id=?", (run_id,)).fetchall()
    assert len(rows) == 10
    for r in rows:
        _, _, league, team = next(v for k, v in CANNED_PARSES.items() if r["title"].startswith(k))
        assert (r["team"], r["league"]) == (team, league), r["title"]


def test_reuse_recomputes_team_and_league_with_current_rules(conn, fake_client_factory):
    run1 = prepared_run(conn, fake_client_factory)
    pid = conn.execute("SELECT id FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run1,)).fetchone()["id"]
    complete_product(conn, pid, "<p>a</p><p>b</p>", "seo")
    conn.execute("UPDATE products SET team='Old Team', league='OLD' WHERE id=?", (pid,))   # written under older rules
    run2 = create_run(conn, FIX, "again.csv", include_drafts=True)
    row = conn.execute("SELECT reused, team, league FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run2,)).fetchone()
    assert (row["reused"], row["team"], row["league"]) == (1, "Cincinnati Bengals", "NFL")


def test_stale_retired_player_is_researched_again(conn, fake_client_factory):
    run_id = prepared_run(conn, fake_client_factory)
    set_run_status(conn, run_id, "running")
    _research_all(conn)
    sid = _sid(conn, "Jim Kelly")
    conn.execute("UPDATE subjects SET status='retired', researched_at=? WHERE id=?", ((NOW - timedelta(days=200)).isoformat(), sid))
    w = claim_next(conn, "w1", 30, NOW, retired_days=180)
    assert isinstance(w, ResearchWork) and w.subject_id == sid
    assert preview(conn, run_id, 30, NOW, retired_days=180).subjects_to_research == 1


def test_preview_counts_known_players_on_reused_products(conn, fake_client_factory):
    run1 = prepared_run(conn, fake_client_factory)
    _research_all(conn)
    for r in conn.execute("SELECT id FROM products WHERE run_id=?", (run1,)).fetchall():
        complete_product(conn, r["id"], "<p>a</p><p>b</p>", "seo")
    run2 = prepared_run(conn, fake_client_factory)        # same export again: every description is reused
    linked = conn.execute("SELECT COUNT(DISTINCT ps.subject_id) FROM product_subjects ps JOIN products p "
                          "ON p.id = ps.product_id WHERE p.run_id=?", (run2,)).fetchone()[0]
    p = preview(conn, run2, 90, NOW)
    assert p.reused == p.products and linked > 0
    assert (p.subjects, p.subjects_fresh, p.subjects_to_research) == (linked, linked, 0)


def test_preview_known_player_on_reused_product_is_not_looked_up(conn, fake_client_factory):
    run1 = prepared_run(conn, fake_client_factory)
    _research_all(conn)
    pid = conn.execute("SELECT id FROM products WHERE run_id=? AND handle LIKE 'tee-higgins%'", (run1,)).fetchone()["id"]
    complete_product(conn, pid, "<p>a</p><p>b</p>", "seo")
    conn.execute("UPDATE subjects SET researched_at = '2000-01-01T00:00:00+00:00' WHERE name = 'Tee Higgins'")
    run2 = prepared_run(conn, fake_client_factory)        # Tee Higgins' product is reused, so no look-up needed
    p = preview(conn, run2, 90, NOW)
    assert p.subjects_to_research == 0
    assert p.subjects_fresh == p.subjects
