import pytest

from rsa_checkins import teams
from rsa_checkins.checkin_build import (alt_text_for, cert_name, seo_title_for, sport_code, tags_for,
                                        title_for)
from rsa_checkins.checkin_sheet import MEANINGS


def _v(**kw):
    return {**{m: "" for m in MEANINGS}, "sport": "Football", "league": "NFL", **kw}


KEENAN_AUTH = _v(jersey_type="Authentic", model="Mitchell & Ness", first="Keenan", last="Allen",
                 city="Indianapolis", mascot="Colts", color="White", player_type="Current", cert="JSA",
                 bag="Green Bag")
KEENAN_CUSTOM = _v(jersey_type="Custom", model="Throwback", first="Keenan", last="Allen", city="Indianapolis",
                   mascot="Colts", color="Blue", player_type="Current", cert="JSA")
MUNOZ = _v(jersey_type="Custom", first="Anthony", last="Munoz", city="Cincinnati", mascot="Bengals",
           color="Black", inscription="HOF 98", player_type="HOF", cert="JSA")
KAMARA = _v(jersey_type="Custom", league="NCAA", first="Alvin", last="Kamara", city="Tennessee",
            mascot="Volunteers", color="Black", cert="Beckett")
GRIESE = _v(rep_auth="Authentic", model="Speedflex", style="Eclipse", first="Bob", last="Griese", city="Miami",
            mascot="Dolphins", color="Black", player_type="HOF", cert="JSA")
BRADSHAW = _v(style="Throwback Gold", first="Terry", last="Bradshaw", city="Pittsburgh", mascot="Steelers",
              color="Yellow", cert="Beckett")
CROSBY = _v(style="Logo", first="Maxx", last="Crosby", city="Oakland", mascot="Raiders", cert="JSA",
            bag="Gold Bag")
DEVONTA = _v(league="NCAA", style="Logo", first="Devonta", last="Smith", city="Alabama", mascot="Crimson Tide",
             cert="Beckett")
KELCE = _v(style="The Duke", first="Jason", last="Kelce", city="Philadelphia", mascot="Eagles", cert="JSA",
           inscription="Hungry Dogs")


def test_jersey_titles():
    assert title_for("jerseys", KEENAN_AUTH) == \
        "Keenan Allen Autographed Indianapolis Colts Authentic NFL White Mitchell & Ness Jersey - JSA"
    assert title_for("jerseys", KEENAN_CUSTOM) == \
        "Keenan Allen Autographed Indianapolis Blue Throwback Football Jersey - JSA"
    assert title_for("jerseys", MUNOZ) == \
        "Anthony Munoz Autographed Cincinnati Black Football Jersey HOF 98 Inscription - JSA"
    assert title_for("jerseys", KAMARA) == "Alvin Kamara Autographed College Black Football Jersey - Beckett"
    hockey = _v(sport="Hockey", league="NHL", jersey_type="Custom", first="Philipp", last="Grubauer",
                city="Washington", color="White", cert="Beckett")
    assert title_for("jerseys", hockey) == "Philipp Grubauer Autographed Washington White Hockey Jersey - Beckett"
    showbiz = _v(sport="Entertainment", jersey_type="Custom", first="Andre", last="Reed", city="Buffalo",
                 color="Red", cert="JSA")
    assert title_for("jerseys", showbiz) == "Andre Reed Autographed Buffalo Red Jersey - JSA"


def test_other_tab_titles():
    assert title_for("fs-helm", GRIESE) == \
        "Bob Griese Autographed Miami Dolphins NFL Speedflex Eclipse Authentic Football Helmet - JSA"
    assert title_for("minis", BRADSHAW) == \
        "Terry Bradshaw Autographed Pittsburgh Steelers Throwback Gold Mini Helmet - Beckett"
    assert title_for("fb-balls", CROSBY) == "Maxx Crosby Autographed Oakland Raiders NFL Logo Football - JSA"
    assert title_for("fb-balls", DEVONTA) == "Devonta Smith Autographed Alabama Crimson Tide Logo Football - Beckett"
    assert title_for("fb-balls", KELCE) == \
        "Jason Kelce Autographed Philadelphia Eagles NFL The Duke Football Hungry Dogs Inscribed - JSA"


def test_helmet_title_with_inscription_matches_the_sheet():
    kamara = _v(league="NCAA", rep_auth="Replica", model="Speed", first="Alvin", last="Kamara", city="Tennessee",
                mascot="Volunteers", inscription="6 TDs", cert="Beckett")
    assert title_for("fs-helm", kamara) == \
        "Alvin Kamara Autographed Tennessee Volunteers Speed Replica Football Helmet 6 TDs Inscription - Beckett"


def test_seo_titles():
    assert seo_title_for("jerseys", KEENAN_AUTH) == "Keenan Allen Autographed Indianapolis Jersey - JSA Authentication"
    assert seo_title_for("fs-helm", GRIESE) == "Bob Griese Autographed Miami Dolphins Helmet - JSA Authentication"
    assert seo_title_for("fb-balls", CROSBY) == "Maxx Crosby Autographed Oakland Raiders Football - JSA Authentication"
    assert seo_title_for("minis", BRADSHAW) == "Terry Bradshaw Autographed Mini Helmet - Beckett Authentication"
    long = _v(first="Bartholomew-Maximilian", last="Featherstonehaugh-Wolfeschlegelsteinhausen",
              city="Jacksonville", mascot="Jaguars", cert="JSA")
    assert seo_title_for("fb-balls", long).endswith(" Football - JSA Authentication")


def test_seo_titles_fit_70_characters():
    for tab, v in [("jerseys", KEENAN_AUTH), ("fs-helm", GRIESE), ("minis", BRADSHAW), ("fb-balls", DEVONTA)]:
        assert len(seo_title_for(tab, v)) <= 70


def test_alt_text():
    assert alt_text_for("jerseys", KEENAN_AUTH) == "Keenan Allen Autographed Jersey"
    assert alt_text_for("fs-helm", GRIESE) == "Bob Griese Autographed Dolphins Helmet"
    assert alt_text_for("minis", BRADSHAW) == "Terry Bradshaw Autographed Steelers Mini Helmet"
    assert alt_text_for("fb-balls", CROSBY) == "Maxx Crosby Autographed Raiders Football"


def test_tags():
    assert tags_for("jerseys", KEENAN_AUTH) == "Jerseys, Current, Colts, Authentic, NFL, GREEN BAG, FB, Imported"
    assert tags_for("jerseys", {**KEENAN_CUSTOM, "model": ""}) == "Jerseys, Current, Colts, Custom, NFL, FB, Imported"
    assert tags_for("fs-helm", GRIESE) == "Dolphins, Authentic, NFL, FB, HOF, Imported"
    assert tags_for("minis", BRADSHAW) == "Steelers, NFL, FB"
    assert tags_for("fb-balls", CROSBY) == "NFL, Raiders, Imported, GOLD BAG, FB"
    baseball = tags_for("fs-helm", {**GRIESE, "sport": "Baseball"}).split(", ")
    assert "BS" in baseball and "FB" not in baseball


def test_bag_from_the_tag_column_when_green_gold_is_blank():
    bo = _v(jersey_type="Custom", first="Bo", last="Jackson", city="Los Angeles", mascot="Raiders", cert="Beckett",
            tags="GOLD BAG, Raiders")
    assert tags_for("jerseys", bo) == "Jerseys, Raiders, Custom, NFL, GOLD BAG, FB, Imported"
    bradshaw = {**BRADSHAW, "tags": "Steelers, gold bag"}
    assert tags_for("minis", bradshaw) == "Steelers, NFL, GOLD BAG, FB"


def test_green_gold_column_wins_over_the_tag_column():
    keenan = {**KEENAN_AUTH, "tags": "Colts, GOLD BAG"}           # Green/Gold says Green Bag
    tags = tags_for("jerseys", keenan).split(", ")
    assert "GREEN BAG" in tags and "GOLD BAG" not in tags


def test_other_sheet_tags_are_added_once():
    keenan = {**KEENAN_AUTH, "tags": "Colts, GREEN BAG, Rookie, nfl,  , Pro Bowl"}
    assert tags_for("jerseys", keenan) == \
        "Jerseys, Current, Colts, Authentic, NFL, GREEN BAG, FB, Imported, Rookie, Pro Bowl"


@pytest.mark.parametrize("sport,code", [("Football", "FB"), ("baseball", "BS"), ("Hockey", "HK"),
                                        ("Entertainment", ""), ("", "")])
def test_sport_code(sport, code):
    assert sport_code(sport) == code


def test_mascot_for():
    assert teams.mascot_for("NFL", "Pittsburgh") == "Steelers"
    assert teams.mascot_for("nfl", "tampa bay") == "Buccaneers"
    assert teams.mascot_for("NFL", "New York") == ""
    assert teams.mascot_for("NCAA", "Tennessee") == ""


def test_cert_name():
    assert cert_name("jsa") == "JSA"
    assert cert_name("Beckett") == "Beckett"
    assert cert_name("SGC") == "SGC"


# ---- Task 3: one row -> every Shopify column ----

from rsa_checkins.checkin_build import Built, Problem, build, money, whole  # noqa: E402
from rsa_checkins.checkin_sheet import RawRow, read_workbook  # noqa: E402
from rsa_checkins.config import (METAFIELD_AUTHENTICITY, METAFIELD_LEAGUE, METAFIELD_PLAYER,  # noqa: E402
                                 METAFIELD_SPORT, METAFIELD_TEAM, METAFIELD_WHOLESALE, TEMPLATE_COLUMNS)
from checkin_fixture import make_workbook  # noqa: E402


@pytest.fixture
def sheet(tmp_path):
    return read_workbook(make_workbook(tmp_path / "c.xlsx")).rows


def _row(sheet, last, **match):
    return next(r for r in sheet if r.values["last"] == last and all(r.values[k] == v for k, v in match.items()))


def test_template_columns():
    assert len(TEMPLATE_COLUMNS) == 88
    assert TEMPLATE_COLUMNS[0] == "Handle"
    assert TEMPLATE_COLUMNS.index(METAFIELD_WHOLESALE) == TEMPLATE_COLUMNS.index("Text (product.metafields.custom.text)") + 1
    assert "Option1 Name" in TEMPLATE_COLUMNS and "Variant Barcodes" in TEMPLATE_COLUMNS


def test_build_keenan_authentic(sheet):
    b = build(_row(sheet, "Allen", jersey_type="Authentic"))
    assert isinstance(b, Built)
    c = b.columns
    assert c["Title"] == "Keenan Allen Autographed Indianapolis Colts Authentic NFL White Mitchell & Ness Jersey - JSA"
    assert (c["Vendor"], c["Published"], c["Status"]) == ("RSA", "FALSE", "draft")
    assert c["Type"] == "Autographed Football Jerseys"
    assert c["Variant Price"] == "349.99"
    assert c["Variant Compare At Price"] == "400.00"
    assert c["Cost per item"] == "150.00"
    assert c[METAFIELD_WHOLESALE] == "200.00"
    assert c["Variant Inventory Qty"] == "15"
    assert c["Variant Grams"] == "896"
    assert c["Variant Weight Unit"] == "oz"
    assert c["Tags"] == "Jerseys, Current, Colts, Authentic, NFL, GREEN BAG, FB, Imported"
    assert c["SEO Title"] == "Keenan Allen Autographed Indianapolis Jersey - JSA Authentication"
    assert c["Image Alt Text"] == "Keenan Allen Autographed Jersey"
    assert (c[METAFIELD_AUTHENTICITY], c[METAFIELD_LEAGUE], c[METAFIELD_PLAYER], c[METAFIELD_SPORT],
            c[METAFIELD_TEAM]) == ("JSA", "NFL", "Keenan Allen", "Football", "Indianapolis Colts")
    assert (c["Option1 Name"], c["Option1 Value"]) == ("Title", "Default Title")
    assert c["Product Category"] == "Arts & Entertainment > Hobbies & Creative Arts > Collectibles > Autographs"
    assert "Handle" not in c and "Body (HTML)" not in c
    assert set(c) <= set(TEMPLATE_COLUMNS)
    assert b.warnings == []
    assert (b.auth, b.player, b.seo_title) == ("JSA", "Keenan Allen", c["SEO Title"])


def test_build_other_tabs_have_no_type(sheet):
    c = build(_row(sheet, "Griese")).columns
    assert c["Type"] == ""
    assert c[METAFIELD_SPORT] == "Football"
    assert c[METAFIELD_TEAM] == "Miami Dolphins"
    assert c["Variant Grams"] == "3584"


def test_ncaa_team_blank(sheet):
    b = build(_row(sheet, "Kamara"))
    assert b.columns[METAFIELD_TEAM] == ""
    assert b.columns[METAFIELD_LEAGUE] == "NCAA"
    assert b.team_for_ai == "Tennessee Volunteers"


def test_mascot_looked_up(sheet):
    jaws = build(_row(sheet, "Jaworski"))
    assert jaws.columns[METAFIELD_TEAM] == "Philadelphia Eagles"
    assert jaws.warnings == []
    assert "Eagles" in jaws.columns["Tags"]
    blount = build(_row(sheet, "Blount"))
    assert blount.columns[METAFIELD_TEAM] == "Tampa Bay Buccaneers"
    assert blount.columns["Variant Price"] == "69.99"


def _raw(tab="jerseys", **kw):
    base = dict(jersey_type="Custom", first="Kevin", last="Mawae", city="Philadelphia", cert="JSA")
    return RawRow(tab, 9, _v(**{**base, **kw}))


def test_mascot_not_found_warns():
    b = build(_raw(city="New York"))
    assert isinstance(b, Built)
    assert b.columns[METAFIELD_TEAM] == ""
    assert any("mascot" in w for w in b.warnings)


def test_bad_numbers_warn():
    b = build(_raw(mascot="Eagles", price="call", inv="1.5"))
    assert b.columns["Variant Price"] == ""
    assert b.columns["Variant Inventory Qty"] == ""
    assert any("price" in w for w in b.warnings)
    assert any("inv" in w for w in b.warnings)


def test_authenticity_limited():
    b = build(_raw(mascot="Eagles", cert="SGC"))
    assert b.columns[METAFIELD_AUTHENTICITY] == ""
    assert b.columns["Title"].endswith("- SGC")
    assert any("SGC" in w for w in b.warnings)


def test_problems():
    for raw, word in [(_raw(first=""), "name"), (_raw(cert=""), "cert"),
                      (_raw(jersey_type="Replica"), "Custom or Authentic")]:
        p = build(raw)
        assert isinstance(p, Problem), raw
        assert word in p.reason
        assert (p.tab, p.row) == ("jerseys", 9)


@pytest.mark.parametrize("value,out", [("$349.99", "349.99"), ("69.98999999999999", "69.99"),
                                       ("1,200", "1200.00"), ("", ""), ("x", None)])
def test_money(value, out):
    assert money(value) == out


@pytest.mark.parametrize("value,out", [("15", "15"), ("", ""), ("1.5", None), ("ten", None)])
def test_whole(value, out):
    assert whole(value) == out
