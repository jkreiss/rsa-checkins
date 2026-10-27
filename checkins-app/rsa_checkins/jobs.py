"""Runs and products: the crash-safe work queue the worker takes from."""
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import checkin_build, players
from .checkin_sheet import read_workbook
from .config import TEMPLATE_COLUMNS
from .claude_api import WORK_ERRORS, Research
from .db import iso, now_iso, transaction
from .shopify_export import NEW_STYLE_MARKER, needs_description, read_export
from .teams import match_team
from .titles import parses_for

MAX_ATTEMPTS = 3
CLAIM_TIMEOUT_MIN = 15
WRITE_GROUP_SIZE = 8
EXAMPLE_TITLES = 5


# ---------- creating and preparing runs ----------

def create_run(conn: sqlite3.Connection, upload_path: Path, filename: str, include_drafts: bool) -> int:
    header, products = read_export(upload_path)
    skipped = sum(1 for p in products
                  if p.status in ("active", "draft") and (include_drafts or p.status == "active")
                  and NEW_STYLE_MARKER in p.body_html)
    now = now_iso()
    with transaction(conn):
        run_id = conn.execute(
            "INSERT INTO runs (created_at, filename, upload_path, header, include_drafts, skipped_new_style, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'parsing')",
            (now, filename, str(upload_path), json.dumps(header), int(include_drafts), skipped),
        ).lastrowid
        for p in products:
            if not needs_description(p, include_drafts):
                continue
            pid = conn.execute(
                "INSERT INTO products (run_id, handle, title, product_type, tags, shop_status, first_row, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, p.handle, p.title, p.product_type, p.tags, p.status, json.dumps(p.first_row), now),
            ).lastrowid
            _reuse_previous(conn, pid, run_id, p)
    return run_id


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def create_checkin_run(conn: sqlite3.Connection, upload_path: Path, filename: str) -> int:
    """A run for a check-in workbook. Rows are built here, so it starts 'ready' (no title parsing).

    Raises CheckinFormatError when the file isn't a check-in workbook."""
    sheet = read_workbook(upload_path)
    built, problems, warnings = [], [], []
    for raw in sheet.rows:
        b = checkin_build.build(raw)
        if isinstance(b, checkin_build.Problem):
            problems.append(asdict(b))
            continue
        built.append(b)
        warnings += [{"tab": b.tab, "row": b.row, "name": b.player, "warning": w} for w in b.warnings]
    tabs: dict[str, int] = {}
    for b in built:
        tabs[b.tab] = tabs.get(b.tab, 0) + 1
    notes = {"tabs": tabs, "problems": problems, "warnings": warnings, "ignored_tabs": sheet.ignored_tabs}
    now = now_iso()
    with transaction(conn):
        run_id = conn.execute(
            "INSERT INTO runs (created_at, filename, upload_path, input_kind, header, include_drafts, status, notes) "
            "VALUES (?, ?, ?, 'checkin_sheet', ?, 1, 'ready', ?)",
            (now, filename, str(upload_path), json.dumps(TEMPLATE_COLUMNS), json.dumps(notes)),
        ).lastrowid
        used: dict[str, int] = {}
        for b in built:
            base = _slug(b.title)
            used[base] = used.get(base, 0) + 1
            handle = base if used[base] == 1 else f"{base}-{used[base]}"
            pid = conn.execute(
                "INSERT INTO products (run_id, handle, title, product_type, tags, shop_status, first_row, kind, "
                "team, league, seo_title, auth, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, 'signed', ?, ?, ?, ?, ?)",
                (run_id, handle, b.title, b.product_type, b.tags, json.dumps(b.columns), b.team_for_ai, b.league,
                 b.seo_title, b.auth, now),
            ).lastrowid
            _link_subject(conn, pid, b.player, "person", 0)
    return run_id


def run_notes(conn: sqlite3.Connection, run_id: int) -> dict:
    return json.loads(conn.execute("SELECT notes FROM runs WHERE id = ?", (run_id,)).fetchone()["notes"])


def _link_subject(conn, product_id: int, name: str, kind: str, position: int) -> None:
    sid = players.get_or_create_subject(conn, name, kind)
    conn.execute("INSERT OR IGNORE INTO product_subjects (product_id, subject_id, position) VALUES (?, ?, ?)",
                 (product_id, sid, position))
    # A subject that ran out of attempts in an earlier run gets a full set again.
    conn.execute("UPDATE subjects SET research_attempts = 0 WHERE id = ? AND research_attempts >= ?",
                 (sid, MAX_ATTEMPTS))


def _reuse_previous(conn, product_id: int, run_id: int, product) -> None:
    handle, title = product.handle, product.title
    prev = conn.execute(
        "SELECT * FROM products WHERE handle = ? AND title = ? AND state = 'done' AND run_id < ? "
        "ORDER BY run_id DESC, id DESC LIMIT 1",
        (handle, title, run_id),
    ).fetchone()
    if prev is None:
        return
    edited_since = conn.execute(
        "SELECT 1 FROM product_subjects ps JOIN subjects s ON s.id = ps.subject_id "
        "WHERE ps.product_id = ? AND s.facts_edited_at >= ? LIMIT 1", (prev["id"], prev["updated_at"])).fetchone()
    if edited_since:
        return   # a fact was corrected by hand after this was written: write it again
    conn.execute(
        "UPDATE products SET state = 'done', reused = 1, description_html = ?, seo_title = ?, "
        "kind = ?, team = ?, league = ? WHERE id = ?",
        # team/league are worked out again by the current rules: cheap, and rule changes then reach reused products
        (prev["description_html"], prev["seo_title"], prev["kind"], *match_team(product.tags, title, product.product_type),
         product_id),
    )
    conn.execute(
        "INSERT INTO product_subjects (product_id, subject_id, position) "
        "SELECT ?, subject_id, position FROM product_subjects WHERE product_id = ?",
        (product_id, prev["id"]),
    )


def prepare_run(conn: sqlite3.Connection, client, model: str, run_id: int) -> None:
    rows = conn.execute("SELECT id, title, product_type, tags FROM products WHERE run_id = ? AND state = 'pending' "
                        "ORDER BY id", (run_id,)).fetchall()
    try:
        parses = parses_for(conn, client, model, [(r["title"], r["product_type"], r["tags"]) for r in rows])
    except WORK_ERRORS as e:
        conn.execute("UPDATE runs SET status = 'error', error = ? WHERE id = ?", (str(e), run_id))
        return
    with transaction(conn):
        for r in rows:
            parse = parses[r["title"]]
            team, league = match_team(r["tags"], r["title"], r["product_type"])
            conn.execute("UPDATE products SET kind = ?, team = ?, league = ? WHERE id = ?",
                         (parse.kind, team, league, r["id"]))
            conn.execute("DELETE FROM product_subjects WHERE product_id = ?", (r["id"],))
            subject_kind = "product_line" if parse.kind == "no_player" else "person"
            for pos, name in enumerate(parse.subjects):
                _link_subject(conn, r["id"], name, subject_kind, pos)
        conn.execute("UPDATE runs SET status = 'ready', error = NULL WHERE id = ?", (run_id,))


def retry_prepare(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("UPDATE runs SET status = 'parsing', error = NULL WHERE id = ? AND status = 'error'", (run_id,))


# ---------- preview and status ----------

@dataclass
class Preview:
    products: int
    reused: int
    skipped_new_style: int
    subjects: int
    subjects_fresh: int
    subjects_to_research: int


def preview(conn: sqlite3.Connection, run_id: int, refresh_days: int, now: datetime,
            retired_days: int | None = None) -> Preview:
    run = conn.execute("SELECT skipped_new_style FROM runs WHERE id = ?", (run_id,)).fetchone()
    counts = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(reused), 0) AS reused FROM products WHERE run_id = ?",
                          (run_id,)).fetchone()
    subjects = conn.execute(
        "SELECT DISTINCT s.* FROM subjects s JOIN product_subjects ps ON ps.subject_id = s.id "
        "JOIN products p ON p.id = ps.product_id WHERE p.run_id = ? AND p.state = 'pending'",
        (run_id,),
    ).fetchall()
    fresh = sum(1 for s in subjects if players.is_fresh(s, refresh_days, now, retired_days))
    return Preview(counts["n"], counts["reused"], run["skipped_new_style"], len(subjects), fresh, len(subjects) - fresh)


def set_run_status(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
        if status == "running":
            _finish_run_if_done(conn, run_id)


def _finish_run_if_done(conn, run_id: int) -> None:
    pending = conn.execute("SELECT 1 FROM products WHERE run_id = ? AND state = 'pending' LIMIT 1", (run_id,)).fetchone()
    if pending is None:
        conn.execute("UPDATE runs SET status = 'done' WHERE id = ? AND status = 'running'", (run_id,))


# ---------- claiming work ----------

@dataclass
class ResearchWork:
    subject_id: int
    name: str
    kind: str
    example_titles: list[str]


@dataclass
class WriteWork:
    product_ids: list[int]


_OPEN_PRODUCTS = ("FROM products p JOIN runs r ON r.id = p.run_id "
                  "WHERE r.status = 'running' AND p.state = 'pending'")


def claim_next(conn: sqlite3.Connection, worker_id: str, refresh_days: int,
               now: datetime, retired_days: int | None = None) -> ResearchWork | WriteWork | None:
    cutoff = iso(now - timedelta(minutes=CLAIM_TIMEOUT_MIN))
    stamp = iso(now)
    with transaction(conn):
        # 1. research a subject that some open product is waiting on
        subjects = conn.execute(
            "SELECT DISTINCT s.* FROM subjects s JOIN product_subjects ps ON ps.subject_id = s.id "
            f"WHERE ps.product_id IN (SELECT p.id {_OPEN_PRODUCTS}) "
            "AND (s.claimed_at IS NULL OR s.claimed_at < ?) ORDER BY s.id",
            (cutoff,),
        ).fetchall()
        for s in subjects:
            if players.is_fresh(s, refresh_days, now, retired_days):
                continue
            conn.execute("UPDATE subjects SET claimed_by = ?, claimed_at = ? WHERE id = ?", (worker_id, stamp, s["id"]))
            titles = [r["title"] for r in conn.execute(
                f"SELECT p.title {_OPEN_PRODUCTS} AND p.id IN (SELECT product_id FROM product_subjects WHERE subject_id = ?) "
                "ORDER BY p.id LIMIT ?", (s["id"], EXAMPLE_TITLES))]
            return ResearchWork(s["id"], s["name"], s["kind"], titles)

        # 2. write a group of products whose subjects are all fresh
        products = conn.execute(
            f"SELECT p.id, p.run_id {_OPEN_PRODUCTS} AND (p.claimed_at IS NULL OR p.claimed_at < ?) ORDER BY p.id",
            (cutoff,),
        ).fetchall()
        if not products:
            return None
        links: dict[int, list[int]] = {p["id"]: [] for p in products}
        fresh: dict[int, bool] = {}
        marks = ",".join("?" * len(links))
        for row in conn.execute(
                f"SELECT ps.product_id, s.* FROM product_subjects ps JOIN subjects s ON s.id = ps.subject_id "
                f"WHERE ps.product_id IN ({marks})", list(links)):
            links[row["product_id"]].append(row["id"])
            if row["id"] not in fresh:
                fresh[row["id"]] = players.is_fresh(row, refresh_days, now, retired_days)
        group_key = None
        group: list[int] = []
        for p in products:
            sids = links[p["id"]]
            if not all(fresh[s] for s in sids):
                continue
            key = (p["run_id"], tuple(sorted(sids)))
            if group_key is None:
                group_key = key
            if key == group_key:
                group.append(p["id"])
                if len(group) == WRITE_GROUP_SIZE:
                    break
        if not group:
            return None
        conn.executemany("UPDATE products SET claimed_by = ?, claimed_at = ? WHERE id = ?",
                         [(worker_id, stamp, pid) for pid in group])
        return WriteWork(group)


# ---------- finishing work ----------

# Finishing calls take the worker_id that claimed the work. A worker whose claim expired and was
# taken over (or already finished by someone else) is ignored, so a late reply never overwrites.

def _owner_guard(worker_id: str | None) -> tuple[str, list]:
    return ("", []) if worker_id is None else (" AND claimed_by = ?", [worker_id])


def complete_research(conn: sqlite3.Connection, subject_id: int, r: Research, worker_id: str | None = None) -> bool:
    return players.save_research(conn, subject_id, r, worker_id)


def fail_research(conn: sqlite3.Connection, subject_id: int, error: str, worker_id: str | None = None) -> None:
    now = now_iso()
    guard, args = _owner_guard(worker_id)
    with transaction(conn):
        cur = conn.execute("UPDATE subjects SET research_attempts = research_attempts + 1, research_error = ?, "
                           f"claimed_by = NULL, claimed_at = NULL WHERE id = ?{guard}", [error, subject_id, *args])
        if cur.rowcount == 0:
            return
        s = conn.execute("SELECT name, research_attempts FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        if s["research_attempts"] < MAX_ATTEMPTS:
            return
        victims = conn.execute(
            "SELECT p.id, p.run_id FROM products p JOIN product_subjects ps ON ps.product_id = p.id "
            "WHERE ps.subject_id = ? AND p.state = 'pending'", (subject_id,)).fetchall()
        conn.executemany(
            "UPDATE products SET state = 'failed', error = ?, claimed_by = NULL, claimed_at = NULL, updated_at = ? "
            "WHERE id = ?",
            [(f"Research failed for {s['name']}: {error}", now, v["id"]) for v in victims])
        for run_id in {v["run_id"] for v in victims}:
            _finish_run_if_done(conn, run_id)


def complete_product(conn: sqlite3.Connection, product_id: int, html: str, seo_title: str,
                     worker_id: str | None = None) -> bool:
    guard, args = _owner_guard(worker_id)
    with transaction(conn):
        cur = conn.execute(
            "UPDATE products SET state = 'done', description_html = ?, seo_title = ?, error = NULL, "
            f"claimed_by = NULL, claimed_at = NULL, updated_at = ? WHERE id = ? AND state = 'pending'{guard}",
            [html, seo_title, now_iso(), product_id, *args])
        if cur.rowcount == 0:
            return False
        run_id = conn.execute("SELECT run_id FROM products WHERE id = ?", (product_id,)).fetchone()["run_id"]
        _finish_run_if_done(conn, run_id)
    return True


def fail_products(conn: sqlite3.Connection, product_ids: list[int], error: str, worker_id: str | None = None) -> None:
    if not product_ids:
        return
    marks = ",".join("?" * len(product_ids))
    guard, args = _owner_guard(worker_id)
    with transaction(conn):
        conn.execute(
            f"UPDATE products SET attempts = attempts + 1, error = ?, claimed_by = NULL, claimed_at = NULL, "
            f"updated_at = ?, state = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE state END "
            f"WHERE id IN ({marks}) AND state = 'pending'{guard}",
            [error, now_iso(), MAX_ATTEMPTS, *product_ids, *args])
        for row in conn.execute(f"SELECT DISTINCT run_id FROM products WHERE id IN ({marks})", product_ids).fetchall():
            _finish_run_if_done(conn, row["run_id"])


def retry_failed(conn: sqlite3.Connection, run_id: int) -> int:
    with transaction(conn):
        ids = [r["id"] for r in conn.execute("SELECT id FROM products WHERE run_id = ? AND state = 'failed'", (run_id,))]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        conn.execute(f"UPDATE products SET state = 'pending', attempts = 0, error = NULL, claimed_by = NULL, "
                     f"claimed_at = NULL WHERE id IN ({marks})", ids)
        conn.execute(f"UPDATE subjects SET research_attempts = 0, research_error = NULL WHERE id IN "
                     f"(SELECT subject_id FROM product_subjects WHERE product_id IN ({marks}))", ids)
        conn.execute("UPDATE runs SET status = 'running' WHERE id = ? AND status = 'done'", (run_id,))
        return len(ids)


# ---------- reporting ----------

EVENT_LOG_SIZE = 200


def log_event(conn: sqlite3.Connection, message: str) -> None:
    """A short line for the progress page's recent activity. Only the newest EVENT_LOG_SIZE are kept."""
    with transaction(conn):
        cur = conn.execute("INSERT INTO events (at, message) VALUES (?, ?)", (now_iso(), message))
        conn.execute("DELETE FROM events WHERE id <= ?", (cur.lastrowid - EVENT_LOG_SIZE,))


def recent_events(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def current_activity(conn: sqlite3.Connection, now: datetime) -> list[str]:
    """What the worker holds a live claim on right now."""
    cutoff = iso(now - timedelta(minutes=CLAIM_TIMEOUT_MIN))
    out = [f"Looking up {r['name']}" for r in conn.execute(
        "SELECT name FROM subjects WHERE claimed_at >= ? ORDER BY claimed_at, id", (cutoff,))]
    for r in conn.execute(
            "SELECT MIN(title) AS title, COUNT(*) AS n FROM products WHERE state = 'pending' AND claimed_at >= ? "
            "GROUP BY claimed_by, claimed_at ORDER BY claimed_at", (cutoff,)):
        out.append(f"Writing: {r['title']}" + (f" (+{r['n'] - 1} more)" if r["n"] > 1 else ""))
    return out

@dataclass
class Progress:
    status: str
    total: int
    done: int
    reused: int
    pending: int
    failed: int


def progress(conn: sqlite3.Connection, run_id: int) -> Progress:
    status = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()["status"]
    c = conn.execute(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(state = 'done'), 0) AS done, COALESCE(SUM(reused), 0) AS reused, "
        "COALESCE(SUM(state = 'pending'), 0) AS pending, COALESCE(SUM(state = 'failed'), 0) AS failed "
        "FROM products WHERE run_id = ?", (run_id,)).fetchone()
    return Progress(status, c["total"], c["done"], c["reused"], c["pending"], c["failed"])


def failed_products(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM products WHERE run_id = ? AND state = 'failed' ORDER BY id", (run_id,)).fetchall()


def list_runs(conn: sqlite3.Connection, input_kind: str | None = None) -> list[sqlite3.Row]:
    if input_kind is None:
        return conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    return conn.execute("SELECT * FROM runs WHERE input_kind = ? ORDER BY id DESC", (input_kind,)).fetchall()
