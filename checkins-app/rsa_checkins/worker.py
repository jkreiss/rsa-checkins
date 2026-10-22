"""Background worker: python -m rsa_checkins.worker

Prepares new runs, then repeatedly claims one unit of work (research one subject, or write one
small group of products) and saves the result before taking the next.
"""
import logging
import signal
import sqlite3
import threading
from datetime import datetime, timezone

from . import config, db, jobs, players
from .claude_api import WORK_ERRORS, WriteItem, make_client, research_subject, write_descriptions
from .descriptions import auth_sentence, authenticator, build_html, seo_title

log = logging.getLogger("rsa_checkins.worker")

_prepare_lock = threading.Lock()
HEARTBEAT_INTERVAL = 20   # seconds; the UI says "not running" after 60


def _prepare_pending_runs(conn: sqlite3.Connection, client, model: str) -> bool:
    if not _prepare_lock.acquire(blocking=False):
        return False   # another thread is already preparing
    try:
        run = conn.execute("SELECT id FROM runs WHERE status = 'parsing' ORDER BY id LIMIT 1").fetchone()
        if run is None:
            return False
        log.info("preparing run %s", run["id"])
        jobs.prepare_run(conn, client, model, run["id"])
        n = conn.execute("SELECT COUNT(*) FROM products WHERE run_id = ? AND kind IS NOT NULL", (run["id"],)).fetchone()[0]
        status = conn.execute("SELECT status FROM runs WHERE id = ?", (run["id"],)).fetchone()["status"]
        jobs.log_event(conn, f"Read {n} product titles for run {run['id']}" if status == "ready"
                       else f"Couldn't read the titles for run {run['id']}")
        return True
    finally:
        _prepare_lock.release()


def _research(conn, client, model: str, work: jobs.ResearchWork, worker_id: str) -> None:
    log.info("researching %s", work.name)
    try:
        r = research_subject(client, model, work.name, work.kind, work.example_titles)
    except WORK_ERRORS as e:
        log.warning("research failed for %s: %s", work.name, e)
        jobs.fail_research(conn, work.subject_id, str(e), worker_id)
        jobs.log_event(conn, f"Couldn't look up {work.name}: {e}")
        return
    if jobs.complete_research(conn, work.subject_id, r, worker_id):
        n = len(r.facts)
        jobs.log_event(conn, f"Looked up {r.display_name} ({n} fact{'' if n == 1 else 's'})")


def _write(conn, client, model: str, work: jobs.WriteWork, worker_id: str) -> None:
    marks = ",".join("?" * len(work.product_ids))
    products = conn.execute(f"SELECT * FROM products WHERE id IN ({marks}) ORDER BY id", work.product_ids).fetchall()
    subject_ids: list[int] = []
    for p in products:
        for row in conn.execute("SELECT subject_id FROM product_subjects WHERE product_id = ? ORDER BY position",
                                (p["id"],)):
            if row["subject_id"] not in subject_ids:
                subject_ids.append(row["subject_id"])
    items = [WriteItem(handle=p["handle"], title=p["title"], product_type=p["product_type"], tags=p["tags"],
                       kind=p["kind"], authenticator=authenticator(p["title"]), team=p["team"]) for p in products]
    log.info("writing %d product(s): %s", len(items), items[0].title)
    try:
        written = write_descriptions(client, model, items, [players.subject_facts(conn, s) for s in subject_ids],
                                     players.previous_notes(conn, subject_ids))
    except WORK_ERRORS as e:
        log.warning("write failed for %d product(s): %s", len(products), e)
        jobs.fail_products(conn, work.product_ids, str(e), worker_id)
        jobs.log_event(conn, f"Couldn't write {len(products)} description(s): {e}")
        return
    missing, written_titles = [], []
    for p in products:
        parts = written.get(p["handle"])
        if parts is None:
            missing.append(p["id"])
            continue
        auth = auth_sentence(p["title"], p["kind"], rotation=p["id"])
        names = [r["name"] for r in conn.execute(
            "SELECT s.name FROM product_subjects ps JOIN subjects s ON s.id = ps.subject_id "
            "WHERE ps.product_id = ? ORDER BY ps.position", (p["id"],))]
        # SEO title by rule; Claude's only when the rule can't build one (unknown item, too long)
        seo = seo_title(p["title"], p["kind"], p["product_type"], names, p["team"]) or parts.seo_title
        if jobs.complete_product(conn, p["id"], build_html(parts.sentence1, auth, parts.call_to_action, parts.note),
                                 seo, worker_id):
            written_titles.append(p["title"])
    jobs.fail_products(conn, missing, "No description returned", worker_id)
    if written_titles:
        n = len(written_titles)
        more = f" (+{n - 1} more)" if n > 1 else ""
        jobs.log_event(conn, f"Wrote {n} description{'' if n == 1 else 's'}: {written_titles[0]}{more}")
    if missing:
        jobs.log_event(conn, f"No description came back for {len(missing)} product(s)")


def process_one(conn: sqlite3.Connection, client, worker_id: str, now: datetime) -> bool:
    model = db.get_setting(conn, "model")
    if _prepare_pending_runs(conn, client, model):
        return True
    work = jobs.claim_next(conn, worker_id, int(db.get_setting(conn, "refresh_days")), now,
                           int(db.get_setting(conn, "retired_refresh_days")))
    if work is None:
        return False
    if isinstance(work, jobs.ResearchWork):
        _research(conn, client, model, work, worker_id)
    else:
        _write(conn, client, model, work, worker_id)
    return True


def worker_loop(conn: sqlite3.Connection, client, worker_id: str, stop: threading.Event,
                idle_sleep: float = 5, error_sleep: float = 10) -> None:
    while not stop.is_set():
        try:
            did_work = process_one(conn, client, worker_id, datetime.now(timezone.utc))
        except Exception:
            log.exception("unexpected error in %s", worker_id)
            stop.wait(error_sleep)
            continue
        if not did_work:
            stop.wait(idle_sleep)


def heartbeat_loop(conn: sqlite3.Connection, stop: threading.Event, interval: float = HEARTBEAT_INTERVAL) -> None:
    """Runs on its own thread, so the UI sees the worker alive even while every work thread waits on Claude."""
    while not stop.is_set():
        try:
            db.set_setting(conn, "worker_heartbeat", db.now_iso())
        except Exception:
            log.exception("couldn't write heartbeat")
        stop.wait(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(threadName)s %(levelname)s %(message)s")
    setup = db.connect(config.db_path())
    db.init_db(setup)
    concurrency = max(1, int(db.get_setting(setup, "concurrency")))
    setup.close()
    client = make_client()
    stop = threading.Event()

    def on_term(signum, frame):
        log.info("stopping after the current unit")
        stop.set()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    def thread_main(n: int) -> None:
        conn = db.connect(config.db_path())
        try:
            worker_loop(conn, client, f"worker-{n}", stop)
        finally:
            conn.close()

    def heartbeat_main() -> None:
        conn = db.connect(config.db_path())
        try:
            heartbeat_loop(conn, stop)
        finally:
            conn.close()

    threads = [threading.Thread(target=thread_main, args=(n,), name=f"worker-{n}") for n in range(concurrency)]
    threads.append(threading.Thread(target=heartbeat_main, name="heartbeat"))
    for t in threads:
        t.start()
    log.info("worker started with %d thread(s)", concurrency)
    while any(t.is_alive() for t in threads):
        for t in threads:
            t.join(timeout=1)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
