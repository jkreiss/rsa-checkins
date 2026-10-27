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
    assert tags_for("jerseys", KEENAN_AUTH) == "Jerseys, Current, Colts, Authentic, NFL, Green Bag, FB, Imported"
    assert tags_for("jerseys", {**KEENAN_CUSTOM, "model": ""}) == "Jerseys, Current, Colts, Custom, NFL, FB, Imported"
    assert tags_for("fs-helm", GRIESE) == "Dolphins, Authentic, NFL, FB, HOF, Imported"
    assert tags_for("minis", BRADSHAW) == "Steelers, NFL, FB"
    assert tags_for("fb-balls", CROSBY) == "NFL, Raiders, Imported, Gold Bag, FB"
    baseball = tags_for("fs-helm", {**GRIESE, "sport": "Baseball"}).split(", ")
    assert "BS" in baseball and "FB" not in baseball


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
