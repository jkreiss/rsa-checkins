"""Turns one check-in row into a Shopify product's text: title, SEO title, alt text and tags.

The patterns come from each tab's example row in the check-in workbook
(see docs/superpowers/specs/2026-10-27-checkins-sheet-design.md §4).
"""
from dataclasses import dataclass, field

from . import teams
from .checkin_sheet import RawRow
from .config import (METAFIELD_AUTHENTICITY, METAFIELD_LEAGUE, METAFIELD_PLAYER, METAFIELD_SPORT,
                     METAFIELD_TEAM, METAFIELD_WHOLESALE)
from .descriptions import sport_value
from .rules import AUTHENTICATOR_CASE, AUTHENTICITY_VALUES, CHECKIN_FIXED_VALUES, CHECKIN_TYPES, SPORT_CODES

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


# ---- One row -> every Shopify column ----

@dataclass
class Built:
    tab: str
    row: int
    player: str
    title: str
    seo_title: str
    product_type: str
    tags: str
    auth: str
    team_for_ai: str
    league: str
    columns: dict[str, str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Problem:
    tab: str
    row: int
    name: str
    reason: str


def _number(value: str) -> float | None:
    try:
        return float(value.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def money(value: str) -> str | None:
    """Money with 2 decimals ("$349.99" -> "349.99"); "" stays ""; None when it isn't a number."""
    if not value.strip():
        return ""
    n = _number(value)
    return None if n is None else f"{n:.2f}"


def whole(value: str) -> str | None:
    """A whole number ("15"); "" stays ""; None when it isn't one."""
    if not value.strip():
        return ""
    n = _number(value)
    return None if n is None or not n.is_integer() else str(int(n))


# Shopify column <- sheet meaning, and how the value is checked.
_MONEY = {"Variant Price": "price", "Variant Compare At Price": "compare", "Cost per item": "cost",
          METAFIELD_WHOLESALE: "ws"}


def build(raw: RawRow) -> Built | Problem:
    v = dict(raw.values)
    name = _name(v)
    if not (v["first"] and v["last"]):
        return Problem(raw.tab, raw.row, name, "no first or last name")
    if not v["cert"]:
        return Problem(raw.tab, raw.row, name, "no cert")
    if raw.tab == "jerseys" and v["jersey_type"].lower() not in ("custom", "authentic"):
        return Problem(raw.tab, raw.row, name,
                       f"jersey type is \"{v['jersey_type']}\"; it must be Custom or Authentic")

    warnings = []
    if not v["mascot"]:
        v["mascot"] = teams.mascot_for(v["league"], v["city"])
        if not v["mascot"]:
            warnings.append(f"mascot not found for {v['city'] or '(no team)'} ({v['league'] or 'no league'}); "
                            "left out of the title, tags and Team")

    title, seo = title_for(raw.tab, v), seo_title_for(raw.tab, v)
    cert = cert_name(v["cert"])
    auth = cert if cert in AUTHENTICITY_VALUES else ""
    if not auth:
        warnings.append(f"cert {cert} isn't one of {', '.join(AUTHENTICITY_VALUES)}; Authenticity left blank")
    ncaa = _is_ncaa(v)
    team_for_ai = _join(v["city"], v["mascot"]) if v["mascot"] else ""
    tags = tags_for(raw.tab, v)
    product_type = CHECKIN_TYPES.get(raw.tab, "")

    columns = {
        **CHECKIN_FIXED_VALUES,
        "Title": title,
        "Type": product_type,
        "Tags": tags,
        "Variant SKU": v["sku"],
        "Variant Barcodes": v["upc"],
        "Image Alt Text": alt_text_for(raw.tab, v),
        "SEO Title": seo,
        METAFIELD_AUTHENTICITY: auth,
        METAFIELD_LEAGUE: v["league"],
        METAFIELD_PLAYER: name,
        METAFIELD_SPORT: sport_value(v["sport"], "", ""),
        METAFIELD_TEAM: "" if ncaa else team_for_ai,
    }
    for column, meaning in _MONEY.items():
        value = money(v[meaning])
        if value is None:
            warnings.append(f"{meaning} \"{v[meaning]}\" isn't a number; left blank")
        columns[column] = value or ""
    qty = whole(v["inv"])
    if qty is None:
        warnings.append(f"inv \"{v['inv']}\" isn't a whole number; left blank")
    columns["Variant Inventory Qty"] = qty or ""
    weight = _number(v["weight"]) if v["weight"] else None
    if v["weight"] and weight is None:
        warnings.append(f"weight \"{v['weight']}\" isn't a number; Variant Grams left blank")
    grams = 28 * weight if weight is not None else None
    columns["Variant Grams"] = "" if grams is None else (str(int(grams)) if grams.is_integer() else f"{grams:g}")

    return Built(raw.tab, raw.row, name, title, seo, product_type, tags, cert, team_for_ai, v["league"],
                 columns, warnings)
