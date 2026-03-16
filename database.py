import sqlite3
import os
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

import config

JST = timezone(timedelta(hours=9))


def _db_path():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    return config.DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                park TEXT NOT NULL,
                date TEXT NOT NULL,
                day_of_week TEXT NOT NULL,
                court TEXT NOT NULL,
                time TEXT NOT NULL,
                scraped_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scrape_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                slot_count INTEGER DEFAULT 0,
                error_message TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_slots_date ON slots(date)
        """)


def save_slots(slots: list[dict]):
    """成功時のみ全件入替え"""
    now = datetime.now(JST).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM slots")
        for s in slots:
            conn.execute(
                "INSERT INTO slots (park, date, day_of_week, court, time, scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
                (s["park"], s["date"], s["day_of_week"], s["court"], s["time"], now),
            )


def get_slots_for_date(date_str: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT park, date, day_of_week, court, time FROM slots WHERE date = ? ORDER BY park, court, time",
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_dates_with_slots(year: int, month: int) -> dict[str, int]:
    """月内の空きスロット数を日付ごとに返す"""
    prefix = f"{year:04d}-{month:02d}-"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, COUNT(*) as cnt FROM slots WHERE date LIKE ? GROUP BY date",
            (prefix + "%",),
        ).fetchall()
        return {r["date"]: r["cnt"] for r in rows}


def get_all_dates_with_slots() -> dict[str, int]:
    """全期間の空きスロット数を日付ごとに返す"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, COUNT(*) as cnt FROM slots GROUP BY date",
        ).fetchall()
        return {r["date"]: r["cnt"] for r in rows}


def get_total_slot_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM slots").fetchone()
        return row["cnt"] if row else 0


def get_slots_for_date_filtered(date_str: str, parks: list[str] | None = None) -> list[dict]:
    with get_conn() as conn:
        if parks:
            placeholders = ",".join("?" for _ in parks)
            rows = conn.execute(
                f"SELECT park, date, day_of_week, court, time FROM slots WHERE date = ? AND park IN ({placeholders}) ORDER BY park, court, time",
                (date_str, *parks),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT park, date, day_of_week, court, time FROM slots WHERE date = ? ORDER BY park, court, time",
                (date_str,),
            ).fetchall()
        return [dict(r) for r in rows]


def log_scrape_start() -> int:
    now = datetime.now(JST).isoformat()
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO scrape_log (started_at, status) VALUES (?, 'running')",
            (now,),
        )
        return cursor.lastrowid


def log_scrape_finish(log_id: int, status: str, slot_count: int = 0, error_message: str = ""):
    now = datetime.now(JST).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE scrape_log SET finished_at = ?, status = ?, slot_count = ?, error_message = ? WHERE id = ?",
            (now, status, slot_count, error_message, log_id),
        )


def get_last_scrape() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
