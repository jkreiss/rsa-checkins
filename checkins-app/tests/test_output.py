import csv
import io
import json

from fakes import prepared_run

from rsa_checkins.claude_api import Fact, Research
from rsa_checkins.config import DEFAULT_OUTPUT_COLUMNS
from rsa_checkins.jobs import complete_product, complete_research
from rsa_checkins.output import (METAFIELD_PLAYER, build_facts_csv, build_output_csv, derived_values,
                                 output_columns)
from rsa_checkins.players import delete_fact, list_facts

HTML = '<p>Signed, "framed" &amp; ready.</p><p>Note, with commas</p>'


def _rows(data: bytes) -> list[dict]:
    assert not data.startswith(b"\xef\xbb\xbf")
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


def _done_run(conn, fake_client_factory, skip=()):
    run_id = prepared_run(conn, fake_client_factory)
    for r in conn.execute("SELECT id, handle FROM products WHERE run_id=?", (run_id,)).fetchall():
        if not any(r["handle"].startswith(s) for s in skip):
            complete_product(conn, r["id"], HTML, f"SEO {r['handle'][:20]}")
    return run_id


def _by_handle(rows, prefix):
    return next(r for r in rows if r["Handle"].startswith(prefix))


def test_default_output_has_nine_columns_and_only_done_products(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory, skip=("tee-higgins",))
    data = build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)
    header = next(csv.reader(io.StringIO(data.decode("utf-8"))))
    assert header == DEFAULT_OUTPUT_COLUMNS
    rows = _rows(data)
    assert len(rows) == 9 and not any(r["Handle"].startswith("tee-higgins") for r in rows)


def test_app_values_replace_existing_ones(conn, fake_client_factory):
    rows = _rows(build_output_csv(conn, _done_run(conn, fake_client_factory), DEFAULT_OUTPUT_COLUMNS))
    odell = _by_handle(rows, "odell")
    assert odell[METAFIELD_PLAYER] == "Odell Beckham Jr."             # export had the cut-off "Odell Beckham"
    assert odell["Team (product.metafields.custom.team)"] == "Los Angeles Rams"
    kelly = _by_handle(rows, "jim-kelly")
    assert kelly[METAFIELD_PLAYER] == "Jim Kelly"
    assert kelly["Sport (product.metafields.custom.sport)"] == "Football"  # no sport code in his tags: "Football" in the title
    assert kelly["Team (product.metafields.custom.team)"] == "Buffalo Bills"
    assert kelly["League (product.metafields.custom.league)"] == "NFL"
    jacob = _by_handle(rows, "jacob-misiorowski")
    assert jacob["Sport (product.metafields.custom.sport)"] == "Baseball"   # BS tag
    assert odell["Sport (product.metafields.custom.sport)"] == "Football"   # export said "Football": kept as the word
    assert jacob["Authenticity (product.metafields.custom.authenticity)"] == "JSA"
    braves = _by_handle(rows, "atlanta-braves")
    assert braves[METAFIELD_PLAYER] == "Gary Sheffield, Dale Murphy, Chipper Jones, David Justice"
    assert _by_handle(rows, "1981-donruss")[METAFIELD_PLAYER] == ""


def test_player_uses_researched_display_name(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    sid = conn.execute("SELECT id FROM subjects WHERE name='Jim Kelly'").fetchone()["id"]
    complete_research(conn, sid, Research("James Kelly", "retired", "Football", [], None, []))
    assert _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "jim-kelly")[METAFIELD_PLAYER] == "James Kelly"


def test_seo_title_and_body_always_replaced(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    conn.execute("UPDATE products SET first_row = json_set(first_row, '$.\"SEO Title\"', 'Willis McGahee jersey') "
                 "WHERE handle LIKE 'odell%'")
    odell = _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "odell")
    assert odell["SEO Title"].startswith("SEO odell") and odell["Body (HTML)"] == HTML


def test_empty_written_seo_title_keeps_existing(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    conn.execute("UPDATE products SET seo_title = '', first_row = json_set(first_row, '$.\"SEO Title\"', 'Old SEO') "
                 "WHERE handle LIKE 'odell%'")
    assert _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "odell")["SEO Title"] == "Old SEO"


def test_extra_column_in_header_order_and_missing_dropped(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    data = build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS + ["Tags", "Not A Column"])
    header = next(csv.reader(io.StringIO(data.decode("utf-8"))))
    assert header == [*DEFAULT_OUTPUT_COLUMNS[:3], "Tags", *DEFAULT_OUTPUT_COLUMNS[3:]]
    assert _by_handle(_rows(data), "jim-kelly")["Tags"].startswith("Bills, jersey")


def test_output_columns_always_has_handle_title_and_options_in_export_order():
    header = ["Handle", "Title", "Body (HTML)", "Option1 Name", "Option1 Value", "Tags", "SEO Title"]
    always = ["Handle", "Title", "Option1 Name", "Option1 Value"]
    assert output_columns(["SEO Title", "Tags"], header) == [*always, "Tags", "SEO Title", WHOLESALE]
    assert output_columns([], header) == [*always, WHOLESALE]


WHOLESALE = "Wholesale Price (product.metafields.custom.wholesale_price)"


def test_wholesale_price_column_is_empty_and_placed_like_the_template(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    for cols in (DEFAULT_OUTPUT_COLUMNS, ["Handle", "Title", "Body (HTML)"]):   # also with an older saved setting
        data = build_output_csv(conn, run_id, cols)
        header = next(csv.reader(io.StringIO(data.decode("utf-8"))))
        assert header[-1] == WHOLESALE
        assert all(r[WHOLESALE] == "" for r in _rows(data))


def test_output_columns_put_wholesale_after_the_custom_metafields():
    header = ["Handle", "Title", "Team (product.metafields.custom.team)", "Text (product.metafields.custom.text)",
              "Google: Custom Product (product.metafields.mm-google-shopping.custom_product)", "Status"]
    assert output_columns(["Status", "Text (product.metafields.custom.text)"], header) == \
        ["Handle", "Title", "Option1 Name", "Option1 Value", "Text (product.metafields.custom.text)", WHOLESALE, "Status"]


def test_wholesale_price_copied_when_the_export_has_it(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    header = json.loads(conn.execute("SELECT header FROM runs WHERE id=?", (run_id,)).fetchone()["header"])
    conn.execute("UPDATE runs SET header=? WHERE id=?", (json.dumps([*header, WHOLESALE]), run_id))
    p = conn.execute("SELECT id, first_row FROM products WHERE run_id=? AND handle LIKE 'odell%'", (run_id,)).fetchone()
    row = {**json.loads(p["first_row"]), WHOLESALE: "45.00"}
    conn.execute("UPDATE products SET first_row=? WHERE id=?", (json.dumps(row), p["id"]))
    rows = _rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS))
    assert _by_handle(rows, "odell")[WHOLESALE] == "45.00"          # never blanked once the store has values
    assert _by_handle(rows, "jim-kelly")[WHOLESALE] == ""


def test_option_columns_copied_from_export(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    rows = _rows(build_output_csv(conn, run_id, ["Handle", "Title"]))   # e.g. an older saved setting
    assert all((r["Option1 Name"], r["Option1 Value"]) == ("Title", "Default Title") for r in rows)


def test_option_columns_keep_real_options_and_fill_blanks(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    for handle, name, value in (("odell", "Size", "Large"), ("jim-kelly", "", "")):
        p = conn.execute("SELECT id, first_row FROM products WHERE run_id=? AND handle LIKE ?",
                         (run_id, handle + "%")).fetchone()
        row = json.loads(p["first_row"])
        row["Option1 Name"], row["Option1 Value"] = name, value
        conn.execute("UPDATE products SET first_row=? WHERE id=?", (json.dumps(row), p["id"]))
    rows = _rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS))
    assert (_by_handle(rows, "odell")["Option1 Name"], _by_handle(rows, "odell")["Option1 Value"]) == ("Size", "Large")
    assert (_by_handle(rows, "jim-kelly")["Option1 Name"], _by_handle(rows, "jim-kelly")["Option1 Value"]) == \
        ("Title", "Default Title")


def test_output_round_trips_html_with_commas_and_quotes(conn, fake_client_factory):
    rows = _rows(build_output_csv(conn, _done_run(conn, fake_client_factory), DEFAULT_OUTPUT_COLUMNS))
    assert all(r["Body (HTML)"] == HTML for r in rows)


def test_derived_values_neutralise_formulas(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    conn.execute("UPDATE products SET seo_title = '=HYPERLINK(\"x\")', team = '+Team' WHERE handle LIKE 'jim-kelly%'")
    p = conn.execute("SELECT * FROM products WHERE handle LIKE 'jim-kelly%'").fetchone()
    d = derived_values(p, ["@Jim Kelly"])
    assert d["SEO Title"] == 'HYPERLINK("x")' and d["Team (product.metafields.custom.team)"] == "Team"
    assert d[METAFIELD_PLAYER] == "Jim Kelly"


def test_facts_csv_live_facts_only_sorted_and_safe(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    tee = conn.execute("SELECT id FROM subjects WHERE name='Tee Higgins'").fetchone()["id"]
    kelly = conn.execute("SELECT id FROM subjects WHERE name='Jim Kelly'").fetchone()["id"]
    complete_research(conn, tee, Research("Tee Higgins", "active", "Football", [], None, [
        Fact("Drafted 2020", "https://a.example/tee"), Fact("=cmd|' /C calc'!A0", "javascript:alert(1)"),
        Fact("Wrong fact", "https://b.example")]))
    complete_research(conn, kelly, Research("Jim Kelly", "retired", "Football", [], None, [Fact("Bills QB", "http://c.example")]))
    delete_fact(conn, next(f["id"] for f in list_facts(conn, tee) if f["fact"] == "Wrong fact"))
    rows = list(csv.reader(io.StringIO(build_facts_csv(conn, run_id).decode("utf-8"))))
    assert rows[0] == ["Player", "Fact", "Source URL", "Checked"]
    body = rows[1:]
    assert [r[0] for r in body] == ["Jim Kelly", "Tee Higgins", "Tee Higgins"]
    assert body[0][1:3] == ["Bills QB", "http://c.example"] and body[0][3]
    assert body[1][1:3] == ["Drafted 2020", "https://a.example/tee"]
    assert body[2][1:3] == ["'=cmd|' /C calc'!A0", ""]


def test_existing_value_kept_when_the_app_finds_nothing(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    conn.execute("""UPDATE products SET first_row = json_set(first_row,
                    '$."Team (product.metafields.custom.team)"', 'Hollywood',
                    '$."League (product.metafields.custom.league)"', 'SAG')
                    WHERE handle LIKE 'christina-applegate%'""")
    apple = _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "christina-applegate")
    assert apple["Team (product.metafields.custom.team)"] == "Hollywood"   # app has no team: don't blank it
    assert apple["League (product.metafields.custom.league)"] == "SAG"


def test_app_league_replaces_a_wrong_existing_one(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    conn.execute("""UPDATE products SET first_row = json_set(first_row, '$."League (product.metafields.custom.league)"', 'NFL')
                    WHERE handle LIKE 'jacob-misiorowski%'""")
    jacob = _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "jacob-misiorowski")
    assert jacob["League (product.metafields.custom.league)"] == "MLB"


def test_player_falls_back_to_first_two_title_words_when_no_person(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    pid = conn.execute("SELECT id FROM products WHERE handle LIKE 'george-teague%'").fetchone()["id"]
    conn.execute("DELETE FROM product_subjects WHERE product_id=?", (pid,))           # e.g. a cast-signed item
    conn.execute("""UPDATE products SET first_row = json_set(first_row, '$."Player (product.metafields.custom.player)"', '')
                    WHERE id=?""", (pid,))
    teague = _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "george-teague")
    assert teague[METAFIELD_PLAYER] == "George Teague"
    assert _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "1981-donruss")[METAFIELD_PLAYER] == ""


def test_existing_player_beats_the_two_word_fallback(conn, fake_client_factory):
    run_id = _done_run(conn, fake_client_factory)
    pid = conn.execute("SELECT id FROM products WHERE handle LIKE 'george-teague%'").fetchone()["id"]
    conn.execute("DELETE FROM product_subjects WHERE product_id=?", (pid,))
    teague = _by_handle(_rows(build_output_csv(conn, run_id, DEFAULT_OUTPUT_COLUMNS)), "george-teague")
    assert teague[METAFIELD_PLAYER] == "George Teague"   # the export's own value ("George Teague")


def test_first_two_words():
    from rsa_checkins.output import first_two_words
    assert first_two_words("The Mighty Ducks Signed 9 Signature Hockey Jersey") == "The Mighty"
    assert first_two_words("Jack Ham, Andy Russell and Jack Lambert Signed Photo") == "Jack Ham"
