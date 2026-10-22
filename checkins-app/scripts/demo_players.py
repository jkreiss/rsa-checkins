"""Demo players with look-alike names, for trying the Players page search.

Run inside the app container (it uses the app's own database):
    sudo docker compose exec -T checkins python - seed   < scripts/demo_players.py
    sudo docker compose exec -T checkins python - remove < scripts/demo_players.py

Safe for the real database:
- names that already exist are skipped, so real players are never touched;
- demo players are never marked as looked up, so if a real product ever names one, the app does a
  proper lookup and the real facts replace the demo ones;
- every demo fact starts with "[demo]", and "remove" deletes only demo players no product uses.
"""
import json
import sys

from rsa_checkins import config, db
from rsa_checkins.players import get_or_create_subject
from rsa_checkins.titles import normalize_name

MARK = "[demo]"
URL = "https://example.com/demo"

# name, status, sport, teams, current team, facts
PLAYERS = [
    ("Jim Carrey", "active", "Entertainment", [], None, ["Comedic actor known for Ace Ventura", "Starred in The Truman Show"]),
    ("Jim Carey", "unknown", "Entertainment", [], None, ["Look-alike spelling of Jim Carrey, for search testing"]),
    ("Jim Smith", "retired", "Football", ["Pittsburgh Steelers"], None, ["Played wide receiver in the 1970s"]),
    ("Jimmy Smith", "retired", "Football", ["Jacksonville Jaguars"], None, ["Five-time Pro Bowl receiver"]),
    ("James Smith", "unknown", "Baseball", [], None, ["Same surname as Jim Smith, different first name"]),
    ("Jim Smyth", "active", "Hockey", ["Vancouver Canucks"], "Vancouver Canucks", ["Look-alike spelling of Jim Smith"]),
    ("Jimbo Hayden", "active", "Basketball", ["Golden State Warriors"], "Golden State Warriors", ["Made-up player for search testing"]),
    ("Jim Brown", "retired", "Football", ["Cleveland Browns"], None, ["Eight-time rushing leader"]),
    ("Jim Thorpe", "retired", "Football", ["Canton Bulldogs"], None, ["Olympic gold medallist in 1912"]),
    ("Jimmie Johnson", "retired", "Racing", [], None, ["Seven-time NASCAR Cup champion"]),
]


def seed(conn) -> None:
    added = skipped = 0
    for name, status, sport, teams, current, facts in PLAYERS:
        exists = conn.execute("SELECT 1 FROM subjects WHERE kind = 'person' AND norm_name = ?",
                              (normalize_name(name),)).fetchone()
        if exists:
            print(f"skip   {name} (already in the database)")
            skipped += 1
            continue
        sid = get_or_create_subject(conn, name, "person")
        conn.execute("UPDATE subjects SET status = ?, sport = ?, teams = ?, current_team = ? WHERE id = ?",
                     (status, sport, json.dumps(teams), current, sid))   # researched_at stays NULL: never "looked up"
        for f in facts:
            conn.execute("INSERT INTO facts (subject_id, fact, source_url, checked_at) VALUES (?, ?, ?, ?)",
                         (sid, f"{MARK} {f}", URL, db.now_iso()))
        print(f"added  {name}")
        added += 1
    print(f"done: {added} added, {skipped} skipped")


def remove(conn) -> None:
    rows = conn.execute(
        "SELECT DISTINCT s.id, s.name FROM subjects s JOIN facts f ON f.subject_id = s.id "
        "WHERE f.fact LIKE ? AND s.id NOT IN (SELECT subject_id FROM product_subjects)", (MARK + "%",)).fetchall()
    for r in rows:
        conn.execute("DELETE FROM facts WHERE subject_id = ?", (r["id"],))
        conn.execute("DELETE FROM subjects WHERE id = ?", (r["id"],))
        print(f"removed {r['name']}")
    print(f"done: {len(rows)} removed")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("seed", "remove"):
        sys.exit("usage: python - seed|remove < scripts/demo_players.py")
    conn = db.connect(config.db_path())
    db.init_db(conn)
    with db.transaction(conn):
        (seed if action == "seed" else remove)(conn)
