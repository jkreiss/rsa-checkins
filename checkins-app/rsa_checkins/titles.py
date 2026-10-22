"""Who signed it. Code reads the titles it can (one signer, sealed boxes); Claude reads the rest, cached per title."""
import json
import re
import sqlite3
from dataclasses import asdict

from .claude_api import PARSE_BATCH, TitleParse, parse_titles
from .db import transaction
from .teams import TEAMS


def normalize_name(name: str) -> str:
    s = re.sub(r"[.'’,]", "", name.lower())
    return " ".join(s.split())


# A name part with any of these is left to Claude: several signers, inscriptions, award years, team signings.
_HARD_NAME = re.compile(r"\band\b|&|,|/|\d|\b(?:inscription|inscribed|hof|greats|team|dual|triple|multi|signed|autographed)\b", re.I)
_SIGNED = re.compile(r"\bsigned\b", re.I)
_UNSIGNED = re.compile(r"\bunsigned\b", re.I)
# Sealed product: the title ends in box/pack/case (optionally "Wax Box", "Hobby Box" ...) or "Set".
_SEALED_END = re.compile(r"\s+(?:(?:(?:wax|hobby|blaster|retail|jumbo|mega|hanger)\s+)?(?:box|pack|case)|(?:complete\s+)?set)$", re.I)
_TEAM_WORDS = {w for t in TEAMS for w in (t.full.lower(), t.nickname.lower(), t.city.lower()) if w}
MAX_NAME_WORDS = 3   # 4 only with a suffix ("Martin Luther King Jr"); else it may hold a character name
_SUFFIX = re.compile(r"^(?:jr|sr|ii|iii|iv)\.?$", re.I)


def read_title(title: str, product_type: str) -> TitleParse | None:
    """Reads a title by rule, or returns None when it needs Claude."""
    t = " ".join((title or "").split())
    if _UNSIGNED.search(t) or (product_type or "").lower().startswith("unsigned"):
        return None   # the person's name sits somewhere in the title: Claude finds it
    m = _SIGNED.search(t)
    if m:
        name = t[:m.start()].strip()
        words = name.split()
        limit = MAX_NAME_WORDS + (1 if words and _SUFFIX.match(words[-1]) else 0)
        if (not name or _HARD_NAME.search(name) or len(words) > limit or name.lower() in _TEAM_WORDS
                or words[0].lower() == "the"):   # "The Mighty Ducks": a group, not a person
            return None
        return TitleParse("signed", [re.sub(r"\b(Jr|Sr)$", r"\1.", name)])
    sealed = _SEALED_END.search(t)
    if sealed and t[:sealed.start()].strip():
        return TitleParse("no_player", [t[:sealed.start()].strip()])
    return None


def parses_for(conn: sqlite3.Connection, client, model: str,
               items: list[tuple[str, str, str]]) -> dict[str, TitleParse]:
    out: dict[str, TitleParse] = {}
    for title, product_type, _ in items:
        by_rule = read_title(title, product_type)
        if by_rule is not None:
            out[title] = by_rule   # not cached: a rule change takes effect on the next run
            continue
        row = conn.execute("SELECT parse FROM title_parses WHERE title = ?", (title,)).fetchone()
        if row is not None:
            saved = json.loads(row["parse"])   # older rows also carry league/team, no longer used
            out[title] = TitleParse(saved["kind"], saved["subjects"])
    seen = set(out)
    todo = []
    for item in items:
        if item[0] not in seen:
            seen.add(item[0])
            todo.append(item)
    # One batch at a time, saved as soon as it arrives, so a failure or restart keeps paid-for work.
    for i in range(0, len(todo), PARSE_BATCH):
        got = parse_titles(client, model, todo[i:i + PARSE_BATCH])
        with transaction(conn):
            for title, parse in got.items():
                conn.execute("INSERT OR REPLACE INTO title_parses (title, parse) VALUES (?, ?)",
                             (title, json.dumps(asdict(parse))))
        out.update(got)
    return out
