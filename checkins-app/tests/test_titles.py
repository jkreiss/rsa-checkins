from fakes import FIX, canned_parse, parse_responder

from rsa_checkins.claude_api import TitleParse
from rsa_checkins.shopify_export import read_export
from rsa_checkins.titles import normalize_name, parses_for, read_title


def test_normalize_name_merges_jr_variants():
    assert normalize_name("Odell Beckham Jr.") == normalize_name("Odell Beckham Jr") == "odell beckham jr"


def test_normalize_name_strips_punctuation_and_spaces():
    assert normalize_name("  Shaquille  O’Neal, ") == normalize_name("Shaquille O'Neal") == "shaquille oneal"


HARD = ("Emmitt Smith and Tony Dorsett", "Atlanta Braves Greats", "Jim Kelly", "Michael Irvin and Emmitt Smith")


def _asked(call) -> list[str]:
    import json
    return [i["title"] for i in json.loads(call["messages"][0]["content"])]


def test_parses_are_cached(conn, fake_client_factory):
    _, products = read_export(FIX)
    items = [(p.title, p.product_type, p.tags) for p in products]
    c = fake_client_factory(responder=parse_responder)
    first = parses_for(conn, c, "m", items)
    second = parses_for(conn, c, "m", items)
    assert len(c.calls) == 1
    assert first == second and len(second) == len(items)
    t = next(p.title for p in products if p.title.startswith("Jim Kelly"))
    assert second[t] == TitleParse(canned_parse(t)["kind"], canned_parse(t)["subjects"])


def test_claude_reads_only_titles_code_cant(conn, fake_client_factory):
    _, products = read_export(FIX)
    items = [(p.title, p.product_type, p.tags) for p in products]
    c = fake_client_factory(responder=parse_responder)
    out = parses_for(conn, c, "m", items)
    assert sorted(_asked(c.calls[0])) == sorted(t for t, _, _ in items if t.startswith(HARD))
    tee = next(t for t, _, _ in items if t.startswith("Tee Higgins"))
    assert out[tee] == TitleParse("signed", ["Tee Higgins"])
    # code's answers aren't cached, so improving the rules later takes effect on the next run
    assert conn.execute("SELECT COUNT(*) FROM title_parses").fetchone()[0] == len(HARD)


def test_parses_for_only_asks_for_uncached_titles(conn, fake_client_factory):
    _, products = read_export(FIX)
    items = [(p.title, p.product_type, p.tags) for p in products]
    hard = [it for it in items if it[0].startswith(HARD)]
    c = fake_client_factory(responder=parse_responder)
    parses_for(conn, c, "m", hard[:2])
    parses_for(conn, c, "m", items)
    assert _asked(c.calls[1]) == [t for t, _, _ in hard[2:]]


def test_no_claude_call_when_code_reads_every_title(conn, fake_client_factory):
    c = fake_client_factory(responses=[])
    out = parses_for(conn, c, "m", [("Tee Higgins Signed Jersey (JSA)", "Autographed Football Jerseys", "FB")])
    assert out["Tee Higgins Signed Jersey (JSA)"].subjects == ["Tee Higgins"] and c.calls == []


# ---------- reading titles in code ----------

def test_read_title_single_signer():
    assert read_title("Tee Higgins Signed Cincinatti White Football Jersey (BECKETT)", "Autographed Football Jerseys") \
        == TitleParse("signed", ["Tee Higgins"])
    assert read_title("George Teague Signed Defender of the Star Inscription Dallas Cowboys Speed Mini Football Helmet ()",
                      "Autographed Football Mini Helmets") == TitleParse("signed", ["George Teague"])


def test_read_title_adds_suffix_full_stop():
    assert read_title("Odell Beckham Jr Signed Los Angeles Jersey (Beckett)", "").subjects == ["Odell Beckham Jr."]
    assert read_title("Patrick Mahomes Sr Signed Who's Your Daddy? Inscription Jersey (JSA)", "").subjects == ["Patrick Mahomes Sr."]
    assert read_title("Ken Griffey Jr. Signed Mariners Jersey (JSA)", "").subjects == ["Ken Griffey Jr."]


def test_read_title_leaves_hard_titles_to_claude():
    assert read_title("Emmitt Smith and Tony Dorsett Signed Dallas Cowboys Speed Mini Football Helmet (JSA)", "") is None
    assert read_title("Atlanta Braves Greats Sheffield, Murphy, Jones, Justice Signed Multi-Inscription Photo (JSA)", "") is None
    assert read_title("Brian Urlacher HOF 18 Inscription and Lance Briggs Dual Signed Helmet", "") is None
    assert read_title("Jack Ham & Jack Lambert Signed Photo", "") is None
    assert read_title("Steelers Team Signed Football", "") is None
    assert read_title("Signed Football (JSA)", "") is None


def test_read_title_unsigned_goes_to_claude():
    assert read_title("Jim Kelly Authentic Buffalo Bills Salute Large Unsigned Nike Football Jersey", "Unsigned Football Jerseys") is None


def test_read_title_sealed_box():
    assert read_title("1981 Donruss Vintage Golf Stars Wax Box", "") == TitleParse("no_player", ["1981 Donruss Vintage Golf Stars"])
    assert read_title("1993 Upper Deck Series 1 Hobby Box", "Baseball Card Wax Box") == TitleParse("no_player", ["1993 Upper Deck Series 1"])
    assert read_title("2020 Panini Prizm Football Blaster Box", "").subjects == ["2020 Panini Prizm Football"]
    assert read_title("1989 Topps Baseball Complete Set", "Baseball Card Set").subjects == ["1989 Topps Baseball"]


def test_read_title_other_unsigned_titles_go_to_claude():
    assert read_title("Mickey Mantle 1952 Topps Reprint Card", "Baseball Cards") is None


def test_finished_batches_are_saved_when_a_later_one_fails(conn, fake_client_factory):
    import json as _json

    import pytest
    from fakes import text_response

    from rsa_checkins.claude_api import ClaudeNoResult
    items = [(f"P{i} Signed Ball (JSA)", "Autographed Baseballs", "BS") for i in range(120)]

    def responder(kw):
        asked = _json.loads(kw["messages"][0]["content"])
        if any(a["title"].startswith("P1") and len(a["title"]) == 22 for a in asked):   # third batch (P100-P119)
            return text_response({"results": []})
        return text_response({"results": [{"title": a["title"], "kind": "signed", "subjects": ["X"], "league": "",
                                           "team": ""} for a in asked]})

    with pytest.raises(ClaudeNoResult):
        parses_for(conn, fake_client_factory(responder=responder), "m", items)
    assert conn.execute("SELECT COUNT(*) FROM title_parses").fetchone()[0] == 100


def test_four_word_names_go_to_claude_unless_the_last_is_a_suffix():
    assert read_title("Henry Winkler Coach Klein Signed Waterboy 8x10 Photo (JSA)", "") is None   # character name
    assert read_title("Martin Luther King Jr Signed Photo (PSA)", "").subjects == ["Martin Luther King Jr."]
    assert read_title("Adam Pacman Jones Signed Jersey (JSA)", "").subjects == ["Adam Pacman Jones"]


def test_titles_starting_with_the_go_to_claude():
    assert read_title("The Mighty Ducks Signed 9 Signature Inscription Hockey Jersey (Beckett)", "") is None


def test_claude_is_told_to_leave_group_signings_without_names():
    from rsa_checkins import rules
    assert "empty subjects" in rules.TITLE_PARSE_PROMPT and "cast" in rules.TITLE_PARSE_PROMPT
