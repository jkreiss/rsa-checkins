"""The subject store: players (people) and sealed product lines, with their facts."""
import html
import json
import re
import sqlite3
from datetime import datetime, timedelta

from .claude_api import Fact, Research, SubjectFacts
from .db import now_iso, parse_iso, transaction
from .titles import normalize_name


def get_or_create_subject(conn: sqlite3.Connection, name: str, kind: str) -> int:
    norm = normalize_name(name)
    conn.execute("INSERT OR IGNORE INTO subjects (kind, name, norm_name) VALUES (?, ?, ?)", (kind, name.strip(), norm))
    return conn.execute("SELECT id FROM subjects WHERE kind = ? AND norm_name = ?", (kind, norm)).fetchone()["id"]


def is_fresh(row: sqlite3.Row, refresh_days: int, now: datetime) -> bool:
    if row["researched_at"] is None:
        return False
    if row["kind"] == "product_line" or row["status"] == "retired":
        return True
    return now - parse_iso(row["researched_at"]) < timedelta(days=refresh_days)


def save_research(conn: sqlite3.Connection, subject_id: int, r: Research, worker_id: str | None = None) -> bool:
    """Saves research. With worker_id, only if that worker still holds the claim (a late worker is ignored)."""
    now = now_iso()
    with transaction(conn):
        if worker_id is not None:
            owner = conn.execute("SELECT claimed_by FROM subjects WHERE id = ?", (subject_id,)).fetchone()
            if owner is None or owner["claimed_by"] != worker_id:
                return False
        conn.execute(
            "UPDATE subjects SET name = ?, status = ?, sport = ?, teams = ?, current_team = ?, researched_at = ?, "
            "research_attempts = 0, research_error = NULL, claimed_by = NULL, claimed_at = NULL WHERE id = ?",
            (r.display_name, r.status, r.sport, json.dumps(r.teams), r.current_team, now, subject_id),
        )
        conn.execute("DELETE FROM facts WHERE subject_id = ? AND edited = 0 AND deleted = 0", (subject_id,))
        deleted = {row["fact"] for row in conn.execute(
            "SELECT fact FROM facts WHERE subject_id = ? AND deleted = 1", (subject_id,))}
        for f in r.facts:
            if f.fact not in deleted:
                conn.execute("INSERT INTO facts (subject_id, fact, source_url, checked_at) VALUES (?, ?, ?, ?)",
                             (subject_id, f.fact, f.source_url, now))
    return True


def list_facts(conn: sqlite3.Connection, subject_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM facts WHERE subject_id = ? AND deleted = 0 ORDER BY id", (subject_id,)).fetchall()


def subject_facts(conn: sqlite3.Connection, subject_id: int) -> SubjectFacts:
    s = conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
    return SubjectFacts(
        name=s["name"], kind=s["kind"], status=s["status"], sport=s["sport"] or "",
        teams=json.loads(s["teams"]), current_team=s["current_team"],
        facts=[Fact(f["fact"], f["source_url"]) for f in list_facts(conn, subject_id)],
    )


_P = re.compile(r"<p>(.*?)</p>", re.S)


def previous_notes(conn: sqlite3.Connection, subject_ids: list[int], limit: int = 10) -> list[str]:
    if not subject_ids:
        return []
    marks = ",".join("?" * len(subject_ids))
    rows = conn.execute(
        f"SELECT DISTINCT p.id, p.description_html, p.updated_at FROM products p "
        f"JOIN product_subjects ps ON ps.product_id = p.id "
        f"WHERE ps.subject_id IN ({marks}) AND p.state = 'done' AND p.description_html IS NOT NULL "
        f"ORDER BY p.updated_at DESC, p.id DESC",
        subject_ids,
    ).fetchall()
    notes: list[str] = []
    for row in rows:
        paras = _P.findall(row["description_html"])
        if len(paras) >= 2:
            note = html.unescape(paras[1]).strip()
            if note and note not in notes:
                notes.append(note)
                if len(notes) >= limit:
                    break
    return notes


def search_subjects(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[sqlite3.Row]:
    like = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return conn.execute("SELECT * FROM subjects WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?",
                        (like, limit)).fetchall()


# Hand edits stamp the subject, so descriptions written before the edit aren't reused (spec §5).

def _mark_edited(conn, subject_id: int) -> None:
    conn.execute("UPDATE subjects SET facts_edited_at = ? WHERE id = ?", (now_iso(), subject_id))


def add_fact(conn: sqlite3.Connection, subject_id: int, fact: str, url: str) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO facts (subject_id, fact, source_url, checked_at, edited) VALUES (?, ?, ?, ?, 1)",
                     (subject_id, fact.strip(), url.strip(), now_iso()))
        _mark_edited(conn, subject_id)


def _edit_fact(conn, fact_id: int, sql: str, args: tuple) -> None:
    with transaction(conn):
        row = conn.execute("SELECT subject_id FROM facts WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            return
        conn.execute(sql, (*args, fact_id))
        _mark_edited(conn, row["subject_id"])


def update_fact(conn: sqlite3.Connection, fact_id: int, fact: str, url: str) -> None:
    _edit_fact(conn, fact_id, "UPDATE facts SET fact = ?, source_url = ?, edited = 1 WHERE id = ?",
               (fact.strip(), url.strip()))


def delete_fact(conn: sqlite3.Connection, fact_id: int) -> None:
    _edit_fact(conn, fact_id, "UPDATE facts SET deleted = 1 WHERE id = ?", ())


def force_refresh(conn: sqlite3.Connection, subject_id: int) -> None:
    conn.execute("UPDATE subjects SET researched_at = NULL WHERE id = ?", (subject_id,))
