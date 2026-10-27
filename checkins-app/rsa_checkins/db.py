"""SQLite connection, schema and settings."""
import copy
from contextlib import contextmanager
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('person','product_line')),
  name TEXT NOT NULL,
  norm_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('active','retired','unknown')),
  sport TEXT, teams TEXT NOT NULL DEFAULT '[]', current_team TEXT,
  researched_at TEXT, facts_edited_at TEXT,
  research_attempts INTEGER NOT NULL DEFAULT 0, research_error TEXT,
  claimed_by TEXT, claimed_at TEXT,
  UNIQUE (kind, norm_name)
);

CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  fact TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '',
  checked_at TEXT NOT NULL,
  edited INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS title_parses (title TEXT PRIMARY KEY, parse TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL, filename TEXT NOT NULL, upload_path TEXT NOT NULL,
  input_kind TEXT NOT NULL DEFAULT 'shopify_export',
  header TEXT NOT NULL,
  include_drafts INTEGER NOT NULL,
  skipped_new_style INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('parsing','ready','running','paused','done','error')),
  error TEXT,
  notes TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  handle TEXT NOT NULL, title TEXT NOT NULL, product_type TEXT NOT NULL, tags TEXT NOT NULL,
  shop_status TEXT NOT NULL, first_row TEXT NOT NULL,
  kind TEXT CHECK (kind IN ('signed','unsigned_player','no_player')),
  team TEXT NOT NULL DEFAULT '', league TEXT NOT NULL DEFAULT '',
  seo_title TEXT,
  auth TEXT,
  state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','done','failed')),
  reused INTEGER NOT NULL DEFAULT 0,
  description_html TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  claimed_by TEXT, claimed_at TEXT, updated_at TEXT,
  UNIQUE (run_id, handle)
);

CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT NOT NULL, message TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS product_subjects (
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  subject_id INTEGER NOT NULL REFERENCES subjects(id),
  position INTEGER NOT NULL,
  PRIMARY KEY (product_id, subject_id)
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# Columns added after the first release: (table, column, definition). Added to older files on start.
MIGRATIONS = [
    ("subjects", "facts_edited_at", "TEXT"),
    ("runs", "notes", "TEXT NOT NULL DEFAULT '{}'"),    # check-in runs: rows left out, warnings, rows per tab
    ("products", "auth", "TEXT"),                       # check-in products: the cert, from the sheet
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def get_setting(conn: sqlite3.Connection, key: str) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return copy.deepcopy(DEFAULT_SETTINGS.get(key))
    return json.loads(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = True):
    """One write transaction. Joins the caller's transaction if one is already open."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
