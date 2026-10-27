import pytest

import rsa_checkins.rules as rules
from rsa_checkins.descriptions import (auth_sentence, authenticator, authenticity_value, build_html, sport_from_tags,
                                       sport_value)


@pytest.mark.parametrize("title,expected", [
    ("Michael Irvin and Emmitt Smith Signed Texas Stadium Seatback (JSA WB877012)", "JSA"),
    ("Tee Higgins Signed Cincinatti White Football Jersey (BECKETT)", "Beckett"),
    ("George Teague Signed ... Mini Football Helmet ()", ""),
    ("1981 Donruss Vintage Golf Stars Wax Box", ""),
    ("X Signed Ball (Fanatics/MLB)", "Fanatics/MLB"),
    ("X Signed Ball (JSA )", "JSA"),
])
def test_authenticator(title, expected):
    assert authenticator(title) == expected


def test_auth_sentence_signed_and_unsigned():
    s = auth_sentence("X Signed Jersey (JSA)", "signed", 0)
    assert s == ("It was authenticated by JSA, carries a unique tamper-evident authentication sticker, "
                 "and like every item we sell, is backed by our 100% money-back guarantee.")
    assert auth_sentence("X Signed Helmet ()", "signed", 1).startswith("It carries a unique tamper-evident")
    u = auth_sentence("Jim Kelly ... Unsigned Nike Football Jersey", "unsigned_player", 1)
    assert u == "It is backed by the same 100% money-back guarantee we stand behind on every item."
    for k in ("unsigned_player", "no_player"):
        for i in range(3):
            assert "sticker" not in auth_sentence("t", k, i) and "It is is" not in auth_sentence("t", k, i)


def test_authenticity_and_sport_values():
    assert authenticity_value("X Signed Ball (Fanatics/MLB)") == "Fanatics"
    assert authenticity_value("X Signed Ball (MLB)") == ""
    assert authenticity_value("X Signed Jersey (JSA WB877012)") == "JSA"
    assert sport_from_tags("Eagles, FB, imported, jersey") == "FB"   # the code; sport_value writes it out
    assert sport_from_tags("Categorized, ET, In-Stock") == ""
    assert sport_from_tags("fb, football") == ""


def test_build_html_escapes_text():
    h = build_html('Signed "Who\'s Your Daddy?" & more <b>', "Auth.", "Buy it.", "Note.")
    assert h == '<p>Signed "Who\'s Your Daddy?" &amp; more &lt;b&gt; Auth. Buy it.</p><p>Note.</p>'


def test_no_certificate_wording_anywhere():
    text = " ".join(rules.SIGNED_GUARANTEES + rules.UNSIGNED_SENTENCES).lower()
    assert "certificate" not in text and "coa" not in text.split()


# ---------- SEO title, built in code ----------

from rsa_checkins.descriptions import SEO_MAX, item_word, seo_title  # noqa: E402

SEO_CASES = [
    # (title, kind, product type, player names, team) -> expected
    (("Tee Higgins Signed Cincinatti White Football Jersey (BECKETT)", "signed", "Autographed Football Jerseys",
      ["Tee Higgins"], "Cincinnati Bengals"), "Tee Higgins Autographed Cincinnati Jersey - Beckett Authentication"),
    (("Christina Applegate Signed Pose 10 8x10 Photo (JSA)", "signed", "Autographed Entertainment Photos",
      ["Christina Applegate"], ""), "Christina Applegate Autographed 8x10 Photo - JSA Authentication"),
    (("George Teague Signed Defender of the Star Inscription Dallas Cowboys Speed Mini Football Helmet ()", "signed",
      "Autographed Football Mini Helmets", ["George Teague"], "Dallas Cowboys"), "George Teague Autographed Dallas Mini Helmet"),
    # too long with the city -> city dropped, authenticator kept
    (("Odell Beckham Jr Signed Los Angeles Two Tone Blue Football Jersey (Beckett)", "signed", "Autographed Football Jerseys",
      ["Odell Beckham Jr."], "Los Angeles Rams"), "Odell Beckham Jr. Autographed Jersey - Beckett Authentication"),
    # two signers too long with full names -> surnames
    (("Emmitt Smith and Tony Dorsett Signed Dallas Cowboys Speed Mini Football Helmet (JSA)", "signed",
      "Autographed Football Mini Helmets", ["Emmitt Smith", "Tony Dorsett"], "Dallas Cowboys"),
     "Smith & Dorsett Autographed Dallas Mini Helmet - JSA Authentication"),
    (("Ken Griffey Jr. Signed Baseball (Fanatics/MLB)", "signed", "Autographed Baseballs", ["Ken Griffey Jr."], "Seattle Mariners"),
     "Ken Griffey Jr. Autographed Seattle Baseball - Fanatics Authentication"),
    (("Jim Kelly Authentic Buffalo Bills Salute Large Unsigned Nike Football Jersey", "unsigned_player",
      "Unsigned Football Jerseys", ["Jim Kelly"], "Buffalo Bills"), "Jim Kelly Buffalo Bills Jersey"),
    (("1981 Donruss Vintage Golf Stars Wax Box", "no_player", "", ["1981 Donruss Vintage Golf Stars"], ""),
     "1981 Donruss Vintage Golf Stars Wax Box"),
]


@pytest.mark.parametrize("args,expected", SEO_CASES)
def test_seo_title(args, expected):
    assert seo_title(*args) == expected
    assert len(expected) <= SEO_MAX


def test_seo_title_gives_up_when_it_cant_fit_or_doesnt_know_the_item():
    braves = ("Atlanta Braves Greats Sheffield, Murphy, Jones, Justice Signed Multi-Inscription Pose 2 16x20 Photo (JSA)",
              "signed", "Autographed Baseball Photos", ["Gary Sheffield", "Dale Murphy", "Chipper Jones", "David Justice"],
              "Atlanta Braves")
    assert seo_title(*braves) is None           # too long even with surnames and no city -> Claude's
    seat = ("Michael Irvin and Emmitt Smith Signed Texas Stadium Seatback (JSA WB877012)", "signed",
            "Autographed Football Collectibles", ["Michael Irvin", "Emmitt Smith"], "Dallas Cowboys")
    assert seo_title(*seat) is None             # "Collectibles" isn't an item word -> Claude's
    assert seo_title("x Signed Ball (JSA)", "signed", "Autographed Baseballs", [], "") is None


@pytest.mark.parametrize("product_type,title,expected", [
    ("Autographed Football Mini Helmets", "", "Mini Helmet"),
    ("Autographed Football Full-Size Helmets", "", "Full-Size Helmet"),
    ("Autographed Baseball Souvenir Helmets", "", "Souvenir Helmet"),
    ("Autographed Baseball Jerseys", "", "Jersey"),
    ("Framed Football Jerseys", "", "Jersey"),
    ("Autographed Baseballs", "", "Baseball"),
    ("Autographed Basketballs", "", "Basketball"),
    ("Autographed Soccer Balls", "", "Soccer Ball"),
    ("Autographed Baseball Bats", "", "Bat"),
    ("Autographed Baseball Photos", "X Signed 16x20 Photo", "16x20 Photo"),
    ("Autographed TV/Film 11x14 Photos", "X Signed Photo", "11x14 Photo"),
    ("Autographed Football Photos", "X Signed Photo", "Photo"),
    ("Autographed Boxing Gloves", "", "Boxing Glove"),
    ("Autographed Sports Magazine", "", "Magazine"),
    ("Autographed Baseball HOF Plaque Cards", "", "HOF Plaque Card"),
    ("Autographed Football Collectibles", "", None),
    ("", "", None),
])
def test_item_word(product_type, title, expected):
    assert item_word(product_type, title) == expected


@pytest.mark.parametrize("existing,tags,title,expected", [
    ("Football", "FB, GREEN BAG", "Mason Miller Signed USA Olympic Baseball Jersey (JSA)", "Baseball"),   # title word wins
    ("", "jersey, Unsigned, Warriors", "Steph Curry Authentic Unsigned Basketball Jersey", "Basketball"),
    ("", "Brewers, BS", "Jacob Misiorowski Signed Milwaukee Cream Jersey (JSA)", "Baseball"),   # no word: tag code
    ("Football", "Eagles", "Some Signed Photo", "Football"),       # no word or code: existing kept
    ("baseball", "", "x", "Baseball"),
    ("FB", "", "x", "Football"),                                   # an existing code is written out
    ("", "FB", "Bo Jackson Signed Football and Baseball Photo", "Football"),  # two sports in the title: tag code
    ("", "WR, imported", "Some Signed Belt", "Wrestling"),
    ("", "Framed Photos", "Christina Applegate Signed Photo", ""),
    ("Golf", "", "x", "Golf"),                                     # not one of the six: left as it is
])
def test_sport_value(existing, tags, title, expected):
    assert sport_value(existing, tags, title) == expected
