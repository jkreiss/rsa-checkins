"""Turns one check-in row into a Shopify product's text: title, SEO title, alt text and tags.

The patterns come from each tab's example row in the check-in workbook
(see docs/superpowers/specs/2026-10-27-checkins-sheet-design.md §4).
"""
from .rules import AUTHENTICATOR_CASE, SPORT_CODES

SEO_MAX = 70
_JERSEY_SPORTS = {"Football", "Baseball", "Basketball", "Hockey", "Soccer"}
_SPORT_WORD_TO_CODE = {word.lower(): code for code, word in SPORT_CODES.items()}


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def _inscription(v: dict, word: str) -> str:
    return f"{v['inscription']} {word}" if v["inscription"] else ""


def cert_name(cert: str) -> str:
    return AUTHENTICATOR_CASE.get(cert.strip().lower(), cert.strip())


def sport_code(sport: str) -> str:
    return _SPORT_WORD_TO_CODE.get(sport.strip().lower(), "")


def _name(v: dict) -> str:
    return _join(v["first"], v["last"])


def _is_ncaa(v: dict) -> bool:
    return v["league"].strip().upper() == "NCAA"


def title_for(tab: str, v: dict) -> str:
    name, cert = _name(v), cert_name(v["cert"])
    if tab == "jerseys":
        place = "College" if _is_ncaa(v) else v["city"]
        if v["jersey_type"].lower() == "authentic":
            body = _join(place, v["mascot"], "Authentic", v["league"], v["color"], v["model"], "Jersey")
        else:
            sport = v["sport"].strip().title()
            body = _join(place, v["color"], v["model"], sport if sport in _JERSEY_SPORTS else "", "Jersey")
        body = _join(body, _inscription(v, "Inscription"))
    elif tab == "fs-helm":
        nfl = "NFL" if v["league"].strip().upper() == "NFL" else ""
        body = _join(v["city"], v["mascot"], nfl, v["model"], v["style"], v["rep_auth"], "Football Helmet",
                     _inscription(v, "Inscription"))
    elif tab == "minis":
        body = _join(v["city"], v["mascot"], v["style"], "Mini Helmet", _inscription(v, "Inscription"))
    else:  # fb-balls
        league = "" if _is_ncaa(v) else v["league"]
        body = _join(v["city"], v["mascot"], league, v["style"], "Football", _inscription(v, "Inscribed"))
    return f"{name} Autographed {body} - {cert}"


_SEO_PARTS = {  # (city, mascot, style, item) - which parts each tab's SEO title uses
    "jerseys": (True, False, False, "Jersey"),
    "fs-helm": (True, True, False, "Helmet"),
    "minis": (True, True, True, "Mini Helmet"),
    "fb-balls": (True, True, False, "Football"),
}


def seo_title_for(tab: str, v: dict) -> str:
    """At most 70 characters: drop the style, then the mascot, then the city; never the ending."""
    use_city, use_mascot, use_style, item = _SEO_PARTS[tab]
    parts = {"city": v["city"] if use_city else "", "mascot": v["mascot"] if use_mascot else "",
             "style": v["style"] if use_style else ""}
    ending = f" - {cert_name(v['cert'])} Authentication"
    for drop in (None, "style", "mascot", "city"):
        if drop:
            parts[drop] = ""
        text = _join(_name(v), "Autographed", parts["city"], parts["mascot"], parts["style"], item) + ending
        if len(text) <= SEO_MAX:
            break
    return text


def alt_text_for(tab: str, v: dict) -> str:
    item = {"jerseys": "Jersey", "fs-helm": "Helmet", "minis": "Mini Helmet", "fb-balls": "Football"}[tab]
    mascot = "" if tab == "jerseys" else v["mascot"]
    return _join(_name(v), "Autographed", mascot, item)


def tags_for(tab: str, v: dict) -> str:
    code = sport_code(v["sport"])
    if tab == "jerseys":
        tags = ["Jerseys", v["player_type"], v["mascot"], v["jersey_type"], v["league"], v["bag"], code, "Imported"]
    elif tab == "fs-helm":
        tags = [v["mascot"], v["rep_auth"], v["league"], code, v["player_type"], v["bag"], "Imported"]
    elif tab == "minis":
        tags = [v["mascot"], v["league"], v["player_type"], v["bag"], code]
    else:  # fb-balls
        tags = [v["league"], v["mascot"], "Imported", v["player_type"], v["bag"], code]
    return ", ".join(t for t in tags if t)
