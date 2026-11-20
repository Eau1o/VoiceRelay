import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone


def week_start(now=None):
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=7, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    return start if start <= now else start - timedelta(days=7)


def estimate(path):
    since = week_start().isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.execute("PRAGMA busy_timeout=1000")
        return db.execute("""SELECT COALESCE(SUM(LENGTH(refined_text)), 0)
            FROM history_v2 WHERE created_at >= ? AND status = 'completed'""", (since,)).fetchone()[0]
