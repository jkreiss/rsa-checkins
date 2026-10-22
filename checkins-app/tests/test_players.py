from datetime import timedelta

from fakes import NOW

from rsa_checkins.claude_api import Fact, Research
from rsa_checkins.players import (add_fact, delete_fact, force_refresh, get_or_create_subject, is_fresh,
                                  list_facts, previous_notes, save_research, search_subjects, subject_facts,
                                  update_fact)


def _research(*facts, status="active", name="Odell Beckham Jr."):
    return Research(name, status, "Football", ["Giants", "Rams"], "Rams", [Fact(f, f"https://x/{i}") for i, f in enumerate(facts)])


def _row(conn, sid):
    return conn.execute("SELECT * FROM subjects WHERE id=?", (sid,)).fetchone()


def test_get_or_create_subject_merges_name_variants(conn):
    a = get_or_create_subject(conn, "Odell Beckham Jr.", "person")
    assert get_or_create_subject(conn, "Odell Beckham Jr", "person") == a
    assert get_or_create_subject(conn, "Odell Beckham Jr", "product_line") != a


def test_save_research_updates_subject(conn):
    sid = get_or_create_subject(conn, "Odell Beckham Jr", "person")
    conn.execute("UPDATE subjects SET research_attempts=2, research_error='x', claimed_by='w', claimed_at='t' WHERE id=?", (sid,))
    save_research(conn, sid, _research("Fact A"))
    r = _row(conn, sid)
    assert (r["name"], r["status"], r["sport"], r["current_team"]) == ("Odell Beckham Jr.", "active", "Football", "Rams")
    assert r["researched_at"] and r["research_attempts"] == 0 and r["research_error"] is None and r["claimed_by"] is None
    sf = subject_facts(conn, sid)
    assert sf.teams == ["Giants", "Rams"] and [f.fact for f in sf.facts] == ["Fact A"]


def test_fresh_rules(conn):
    sid = get_or_create_subject(conn, "A", "person")
    assert not is_fresh(_row(conn, sid), 90, NOW)
    conn.execute("UPDATE subjects SET researched_at=?, status='retired' WHERE id=?", ((NOW - timedelta(days=400)).isoformat(), sid))
    assert is_fresh(_row(conn, sid), 90, NOW)
    conn.execute("UPDATE subjects SET status='active', researched_at=? WHERE id=?", ((NOW - timedelta(days=91)).isoformat(), sid))
    assert not is_fresh(_row(conn, sid), 90, NOW)
    conn.execute("UPDATE subjects SET status='unknown' WHERE id=?", (sid,))
    assert not is_fresh(_row(conn, sid), 90, NOW)
    conn.execute("UPDATE subjects SET researched_at=? WHERE id=?", ((NOW - timedelta(days=89)).isoformat(), sid))
    assert is_fresh(_row(conn, sid), 90, NOW)
    pl = get_or_create_subject(conn, "1981 Donruss", "product_line")
    conn.execute("UPDATE subjects SET researched_at=? WHERE id=?", ((NOW - timedelta(days=1000)).isoformat(), pl))
    assert is_fresh(_row(conn, pl), 90, NOW)


def test_edited_fact_survives_refresh_and_deleted_not_readded(conn):
    sid = get_or_create_subject(conn, "Odell Beckham Jr", "person")
    save_research(conn, sid, _research("Fact A", "Fact B", "Fact C"))
    by_text = {r["fact"]: r["id"] for r in list_facts(conn, sid)}
    update_fact(conn, by_text["Fact A"], "Fact A corrected", "https://fixed")
    delete_fact(conn, by_text["Fact B"])
    save_research(conn, sid, _research("Fact B", "Fact D"))
    live = {r["fact"]: r for r in list_facts(conn, sid)}
    assert set(live) == {"Fact A corrected", "Fact D"}
    assert live["Fact A corrected"]["edited"] == 1 and live["Fact A corrected"]["source_url"] == "https://fixed"
    assert [f.fact for f in subject_facts(conn, sid).facts] == ["Fact A corrected", "Fact D"]


def test_fact_crud_and_search(conn):
    sid = get_or_create_subject(conn, "Christina Applegate", "person")
    get_or_create_subject(conn, "Tee Higgins", "person")
    add_fact(conn, sid, "Starred in Married... with Children", "https://a")
    assert [r["fact"] for r in list_facts(conn, sid)] == ["Starred in Married... with Children"]
    assert [r["name"] for r in search_subjects(conn, "apple")] == ["Christina Applegate"]
    save_research(conn, sid, _research(name="Christina Applegate"))
    force_refresh(conn, sid)
    assert _row(conn, sid)["researched_at"] is None


def test_previous_notes_returns_second_paragraphs(conn, fake_client_factory):
    from fakes import prepared_run
    from rsa_checkins.jobs import complete_product
    prepared_run(conn, fake_client_factory)
    emmitt = conn.execute("SELECT id FROM subjects WHERE name='Emmitt Smith'").fetchone()["id"]
    pids = [r["product_id"] for r in conn.execute("SELECT product_id FROM product_subjects WHERE subject_id=? ORDER BY product_id", (emmitt,))]
    complete_product(conn, pids[0], "<p>one</p><p>Note &amp; one</p>", "s")
    complete_product(conn, pids[1], "<p>two</p><p>Note two</p>", "s")
    assert sorted(previous_notes(conn, [emmitt])) == ["Note & one", "Note two"]
    assert previous_notes(conn, [emmitt], limit=1) and len(previous_notes(conn, [emmitt], limit=1)) == 1


def test_retired_players_are_rechecked_after_their_own_period(conn):
    sid = get_or_create_subject(conn, "A", "person")
    conn.execute("UPDATE subjects SET status='retired', researched_at=? WHERE id=?", ((NOW - timedelta(days=181)).isoformat(), sid))
    assert not is_fresh(_row(conn, sid), 30, NOW, retired_days=180)
    conn.execute("UPDATE subjects SET researched_at=? WHERE id=?", ((NOW - timedelta(days=179)).isoformat(), sid))
    assert is_fresh(_row(conn, sid), 30, NOW, retired_days=180)
    pl = get_or_create_subject(conn, "1981 Donruss", "product_line")      # card sets: never re-checked
    conn.execute("UPDATE subjects SET researched_at=? WHERE id=?", ((NOW - timedelta(days=1000)).isoformat(), pl))
    assert is_fresh(_row(conn, pl), 30, NOW, retired_days=180)
