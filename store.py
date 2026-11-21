import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone


def week_start(now=None):
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=7, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    return start if start <= now else start - timedelta(days=7)


def save_quota(path, week, observed, result):
    # This is VoiceRelay's own file. Only one official sample is retained.
    with closing(sqlite3.connect(path, timeout=1)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS quota (
            id INTEGER PRIMARY KEY, week TEXT, observed TEXT, used INTEGER, total INTEGER)""")
        db.execute("""CREATE TABLE IF NOT EXISTS last_numeric AS
            SELECT * FROM quota WHERE used IS NOT NULL""")
        if result[0] is not None:
            db.execute("DELETE FROM last_numeric WHERE observed <= ?", (observed,))
            db.execute("""INSERT INTO last_numeric SELECT 1, ?, ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM last_numeric)""",
                (week.isoformat(), observed, *result))
        db.execute("""INSERT INTO quota VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET week=excluded.week, observed=excluded.observed,
            used=excluded.used, total=excluded.total WHERE excluded.observed > quota.observed""",
            (week.isoformat(), observed, *result))


def load_quota(path):
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        return db.execute("SELECT used, total, observed FROM quota WHERE id=1").fetchone()

def first_exhaustion_notice(path, week):
    with closing(sqlite3.connect(path, timeout=1)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS exhaustion_notice (week TEXT PRIMARY KEY)")
        return bool(db.execute("INSERT OR IGNORE INTO exhaustion_notice VALUES (?)",
                               (week.isoformat(),)).rowcount)
