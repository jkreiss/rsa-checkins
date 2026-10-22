from rsa_checkins import db


def test_init_db_is_idempotent(conn):
    db.init_db(conn); db.init_db(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "subjects", "facts", "title_parses", "runs", "products", "product_subjects"} <= names


def test_setting_defaults_and_roundtrip(conn):
    assert db.get_setting(conn, "refresh_days") == 30            # active players: about a month
    assert db.get_setting(conn, "retired_refresh_days") == 180   # retired players: about 6 months
    assert db.get_setting(conn, "model") == "claude-sonnet-5-5"
    db.set_setting(conn, "output_columns", ["Handle", "Title", "Body (HTML)", "Tags"])
    assert db.get_setting(conn, "output_columns")[-1] == "Tags"


def test_wal_mode(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_init_db_adds_new_columns_to_an_older_file(tmp_path):
    from rsa_checkins import db
    c = db.connect(tmp_path / "old.sqlite3")
    c.execute("CREATE TABLE subjects (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, "
              "norm_name TEXT NOT NULL, researched_at TEXT)")
    db.init_db(c)
    assert "facts_edited_at" in {r["name"] for r in c.execute("PRAGMA table_info(subjects)")}
