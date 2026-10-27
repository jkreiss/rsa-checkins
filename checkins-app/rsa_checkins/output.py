"""Output files: the Shopify import CSV and the facts log CSV."""
import csv
import io
import json
import sqlite3

from .config import (METAFIELD_AUTHENTICITY, METAFIELD_COLUMNS, METAFIELD_LEAGUE, METAFIELD_PLAYER,  # noqa: F401
                     METAFIELD_SPORT, METAFIELD_TEAM, METAFIELD_WHOLESALE, OPTION_COLUMNS)
from .descriptions import authenticity_value, sport_value

REQUIRED = ("Handle", "Title", *OPTION_COLUMNS)   # always in the output, whatever the saved setting
ALWAYS = (*REQUIRED, METAFIELD_WHOLESALE)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _template_header(header: list[str]) -> list[str]:
    """The export's columns plus any always-included ones it lacks, placed as in "Updates Template.csv"."""
    header = list(header)
    for c in reversed(OPTION_COLUMNS):
        if c not in header:
            header.insert(header.index("Title") + 1 if "Title" in header else len(header), c)
    if METAFIELD_WHOLESALE not in header:   # exports made before the metafield existed: after the custom ones
        custom = [i for i, c in enumerate(header) if "(product.metafields.custom." in c]
        header.insert(custom[-1] + 1 if custom else len(header), METAFIELD_WHOLESALE)
    return header


def output_columns(selected: list[str], header: list[str]) -> list[str]:
    """The chosen columns plus the always-included ones, in the export's (and the template's) order."""
    wanted = set(selected) | set(ALWAYS)
    return [c for c in _template_header(header) if c in wanted]


def _strip_formula(value: str) -> str:
    """For text Claude wrote that goes into Shopify: a leading formula character is never meant."""
    return (value or "").lstrip("=+-@\t\r ").strip()


def _quote_formula(value: str) -> str:
    """For the facts log, which people open in a spreadsheet: keep the text, stop it running."""
    return "'" + value if value.startswith(_FORMULA_START) else value


def first_two_words(title: str) -> str:
    words = [w.strip(",;:") for w in (title or "").split()[:2]]
    return _strip_formula(" ".join(w for w in words if w))


def derived_values(product: sqlite3.Row, subject_names: list[str]) -> dict[str, str]:
    names = [n for n in (_strip_formula(n) for n in subject_names) if n]
    return {
        METAFIELD_AUTHENTICITY: authenticity_value(product["title"]),
        METAFIELD_LEAGUE: _strip_formula(product["league"]),
        METAFIELD_PLAYER: "" if product["kind"] == "no_player" else ", ".join(names),
        METAFIELD_SPORT: sport_value("", product["tags"], product["title"]),
        METAFIELD_TEAM: _strip_formula(product["team"]),
        "SEO Title": _strip_formula(product["seo_title"] or ""),
        "Body (HTML)": product["description_html"] or "",
    }


def _subject_names(conn, product_id: int) -> list[str]:
    return [r["name"] for r in conn.execute(
        "SELECT s.name FROM product_subjects ps JOIN subjects s ON s.id = ps.subject_id "
        "WHERE ps.product_id = ? ORDER BY ps.position", (product_id,))]


def build_output_csv(conn: sqlite3.Connection, run_id: int, columns: list[str]) -> bytes:
    header = json.loads(conn.execute("SELECT header FROM runs WHERE id = ?", (run_id,)).fetchone()["header"])
    cols = output_columns(columns, header)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for p in conn.execute("SELECT * FROM products WHERE run_id = ? AND state = 'done' ORDER BY id", (run_id,)):
        first_row = json.loads(p["first_row"])
        derived = derived_values(p, _subject_names(conn, p["id"]))
        no_options = not any(first_row.get(c, "").strip() for c in OPTION_COLUMNS)
        row = []
        for c in cols:
            existing = first_row.get(c, "")
            if c == "Body (HTML)":
                row.append(derived[c])
            elif c in OPTION_COLUMNS:   # copy the product's options; blank means the one-variant default
                row.append(OPTION_COLUMNS[c] if no_options else existing)
            elif c == "SEO Title":
                row.append(derived[c] or existing)
            elif c == METAFIELD_SPORT:   # always the word: codes are written out, blanks filled
                row.append(sport_value(existing, p["tags"], p["title"]))
            elif c in METAFIELD_COLUMNS:   # the app's value wins; the export's only when the app has none
                value = derived[c] if derived[c].strip() else existing
                if c == METAFIELD_PLAYER and not value.strip() and p["kind"] != "no_player":
                    value = first_two_words(p["title"])   # owner: "first two words in title is fine" as a fallback
                row.append(value)
            else:
                row.append(existing)
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def _safe_url(url: str) -> str:
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def build_facts_csv(conn: sqlite3.Connection, run_id: int) -> bytes:
    rows = conn.execute(
        "SELECT s.name, f.fact, f.source_url, f.checked_at FROM facts f JOIN subjects s ON s.id = f.subject_id "
        "WHERE f.deleted = 0 AND s.id IN (SELECT ps.subject_id FROM product_subjects ps "
        "JOIN products p ON p.id = ps.product_id WHERE p.run_id = ?) "
        "ORDER BY s.name COLLATE NOCASE, s.id, f.id", (run_id,)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Player", "Fact", "Source URL", "Checked"])
    for r in rows:
        w.writerow([_quote_formula(r["name"]), _quote_formula(r["fact"]), _safe_url(r["source_url"]), r["checked_at"]])
    return buf.getvalue().encode("utf-8")
