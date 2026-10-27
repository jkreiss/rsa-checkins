"""Authenticator parsing, the fixed authentication sentence, and HTML assembly."""
import html
import re

from .rules import (AUTHENTICATOR_CASE, AUTHENTICITY_VALUES, SIGNED_GUARANTEES, SPORT_CODES,
                    UNSIGNED_SENTENCES)

_TRAILING_BRACKETS = re.compile(r"\(([^()]*)\)\s*$")


def authenticator(title: str) -> str:
    m = _TRAILING_BRACKETS.search(title or "")
    if not m:
        return ""
    tokens = m.group(1).split()
    while tokens and any(ch.isdigit() for ch in tokens[-1]):
        tokens.pop()  # drop cert numbers like "WB877012"
    if not tokens:
        return ""
    parts = " ".join(tokens).split("/")
    return "/".join(AUTHENTICATOR_CASE.get(p.strip().lower(), p.strip()) for p in parts)


def authenticity_value(title: str) -> str:
    for part in authenticator(title).split("/"):
        if part in AUTHENTICITY_VALUES:
            return part
    return ""


def sport_from_tags(tags: str) -> str:
    """The first sport code in the tags (FB, BS, BK, HK, WR, SC), or ""."""
    for tag in (tags or "").split(","):
        if tag.strip() in SPORT_CODES:
            return tag.strip()
    return ""


_SPORT_WORD_TO_CODE = {word.lower(): code for code, word in SPORT_CODES.items()}


def sport_from_title(title: str) -> str:
    """The code for the one sport word in the title ("... Baseball Jersey" -> "BS"), or "" if none or several."""
    found = set(re.findall(r"\b(" + "|".join(_SPORT_WORD_TO_CODE) + r")\b", (title or "").lower()))
    return _SPORT_WORD_TO_CODE[found.pop()] if len(found) == 1 else ""


def sport_value(existing: str, tags: str, title: str = "") -> str:
    """The Sport column, always as the full word: BS -> "Baseball" (owner, 2026-10-27).

    A sport word in the title wins, then the code in the tags, then the existing value (a code is written
    out, "FB" -> "Football"). A value that isn't one of the six sports is left as it is.
    """
    e = (existing or "").strip()
    code = (sport_from_title(title) or sport_from_tags(tags)
            or (e.upper() if e.upper() in SPORT_CODES else _SPORT_WORD_TO_CODE.get(e.lower(), "")))
    return SPORT_CODES[code] if code else e


def auth_sentence(title: str, kind: str, rotation: int) -> str:
    if kind != "signed":
        return UNSIGNED_SENTENCES[rotation % 3]
    guarantee = SIGNED_GUARANTEES[rotation % 3]
    a = authenticator(title)
    if a:
        return f"It was authenticated by {a}, carries a unique tamper-evident authentication sticker, {guarantee}."
    return f"It carries a unique tamper-evident authentication sticker, {guarantee}."


def _e(s: str) -> str:
    return html.escape((s or "").strip(), quote=False)


def build_html(sentence1: str, auth: str, call_to_action: str, note: str) -> str:
    return f"<p>{_e(sentence1)} {_e(auth)} {_e(call_to_action)}</p><p>{_e(note)}</p>"


# ---------- SEO title (spec §8b), built by rule; None means "use Claude's" ----------

SEO_MAX = 70
_TYPE_PREFIX = re.compile(r"^(?:autographed|unsigned|framed)\s+", re.I)
_SIZE = re.compile(r"\b(\d{1,2}x\d{1,2})\b", re.I)
_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
# Product type (without "Autographed") -> item word. First match wins.
_ITEMS = [
    (r"\bmini helmets?\b", "Mini Helmet"),
    (r"\bmidi helmets?\b", "Midi Helmet"),
    (r"\bfull-size helmets?\b", "Full-Size Helmet"),
    (r"\bsouvenir helmets?\b", "Souvenir Helmet"),
    (r"\bbatting helmets?\b", "Batting Helmet"),
    (r"\bjerseys?\b", "Jersey"),
    (r"\bposters?\b", "Poster"),
    (r"\bphotos?\b", "Photo"),
    (r"\bplaque cards?\b", "HOF Plaque Card"),
    (r"\bboxing gloves?\b", "Boxing Glove"),
    (r"\bboxing trunks\b", "Boxing Trunks"),
    (r"\bmagazines?\b", "Magazine"),
    (r"\bbats?\b", "Bat"),
    (r"\bsoccer balls?\b", "Soccer Ball"),
    (r"^(foot|base|basket)balls?$", None),   # "Baseballs" -> "Baseball"
]


def item_word(product_type: str, title: str) -> str | None:
    kind = _TYPE_PREFIX.sub("", (product_type or "").strip()).lower()
    for pattern, word in _ITEMS:
        m = re.search(pattern, kind)
        if not m:
            continue
        if word is None:
            return m.group(1).capitalize() + "ball"
        if word in ("Photo", "Poster"):
            size = _SIZE.search(product_type) or _SIZE.search(title or "")
            return f"{size.group(1).lower()} {word}" if size else word
        return word
    return None


def _surname(name: str) -> str:
    words = [w for w in name.split() if w.lower() not in _SUFFIXES]
    return words[-1] if words else name


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


def seo_title(title: str, kind: str, product_type: str, names: list[str], team: str) -> str | None:
    """'[Player] Autographed [place] [item] - [Authenticator] Authentication', at most 70 characters.

    Shortens the middle when needed (surnames for several signers, then no place); never the authenticator.
    Returns None when it can't build one, and the caller uses the SEO title Claude wrote.
    """
    from .teams import team_city
    if kind == "no_player":
        t = " ".join((title or "").split())
        return t if 0 < len(t) <= SEO_MAX else None
    item = item_word(product_type, title)
    if item is None or not names:
        return None
    city = team_city(team)
    whos = [_join(names)] + ([_join([_surname(n) for n in names])] if len(names) > 1 else [])
    if kind == "signed":
        a = authenticity_value(title) or authenticator(title)
        tail = f" - {a} Authentication" if a else ""
        options = [f"{who} Autographed {place}{item}{tail}" for place in ([f"{city} "] if city else []) + [""] for who in whos]
    else:   # unsigned item tied to a person: no "Autographed", no authentication part
        options = [f"{who} {place}{item}" for place in [f"{team} " if team else "", f"{city} " if city else "", ""] for who in whos]
    for o in options:
        o = " ".join(o.split())
        if len(o) <= SEO_MAX:
            return o
    return None
