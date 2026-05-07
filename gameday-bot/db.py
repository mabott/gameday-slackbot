import sqlite3
import logging
from contextlib import contextmanager
from config import DB_PATH

log = logging.getLogger(__name__)


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                sport TEXT,
                home_team TEXT,
                away_team TEXT,
                start_time TEXT,
                slack_ts TEXT,
                pregame_posted INTEGER DEFAULT 0,
                midgame_posted INTEGER DEFAULT 0,
                final_posted INTEGER DEFAULT 0,
                date TEXT,
                home_record TEXT DEFAULT '',
                away_record TEXT DEFAULT ''
            )
        """)
        for col in ("home_record", "away_record", "broadcasts"):
            try:
                conn.execute(f"ALTER TABLE games ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass  # column already exists
        conn.commit()
    log.info("DB initialized at %s", DB_PATH)


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def upsert_game(game_id, sport, home_team, away_team, start_time_iso, date,
                home_record="", away_record="", broadcasts=""):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO games (game_id, sport, home_team, away_team, start_time, date,
                               home_record, away_record, broadcasts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                home_record = excluded.home_record,
                away_record = excluded.away_record,
                broadcasts = excluded.broadcasts
        """, (game_id, sport, home_team, away_team, start_time_iso, date,
              home_record, away_record, broadcasts))
        conn.commit()


def get_games_for_date(date):
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM games WHERE date = ?", (date,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_game(game_id):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM games WHERE game_id = ?", (game_id,)
        ).fetchone()
    return dict(row) if row else None


def save_slack_ts(game_id, ts):
    with _conn() as conn:
        conn.execute(
            "UPDATE games SET slack_ts = ? WHERE game_id = ?", (ts, game_id)
        )
        conn.commit()


def mark_posted(game_id, stage):
    """stage: 'pregame', 'midgame', or 'final'"""
    col = f"{stage}_posted"
    with _conn() as conn:
        conn.execute(f"UPDATE games SET {col} = 1 WHERE game_id = ?", (game_id,))
        conn.commit()


def is_posted(game_id, stage):
    row = get_game(game_id)
    if not row:
        return False
    return bool(row.get(f"{stage}_posted"))


def cleanup_old_games(before_date):
    """Remove games from dates before before_date (YYYY-MM-DD)."""
    with _conn() as conn:
        conn.execute("DELETE FROM games WHERE date < ?", (before_date,))
        conn.commit()
    log.info("Cleaned up games before %s", before_date)
