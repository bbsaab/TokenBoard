"""SQLite database operations for usage tracking."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from . import config


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    db_path = Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the database schema."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                UNIQUE(timestamp, session_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON usage_records(timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_id ON usage_records(session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_model ON usage_records(model)
        """)
        conn.commit()
    finally:
        conn.close()


def insert_usage(
    timestamp: str,
    session_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0
) -> bool:
    """
    Insert a usage record into the database.

    Returns True if inserted, False if record already exists.
    """
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO usage_records
            (timestamp, session_id, model, input_tokens, output_tokens,
             cache_creation_tokens, cache_read_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, session_id, model, input_tokens, output_tokens,
              cache_creation_tokens, cache_read_tokens))
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def get_usage_in_window(hours: float) -> dict:
    """
    Get aggregated usage for the past N hours.

    Returns dict with total tokens by category and by model.
    """
    conn = get_connection()
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        # Get totals
        row = conn.execute("""
            SELECT
                COALESCE(SUM(input_tokens), 0) as input_tokens,
                COALESCE(SUM(output_tokens), 0) as output_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) as cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                COUNT(*) as message_count
            FROM usage_records
            WHERE timestamp >= ?
        """, (cutoff,)).fetchone()

        result = {
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cache_creation_tokens": row["cache_creation_tokens"],
            "cache_read_tokens": row["cache_read_tokens"],
            "total_tokens": (
                row["input_tokens"] + row["output_tokens"] +
                row["cache_creation_tokens"] + row["cache_read_tokens"]
            ),
            "message_count": row["message_count"],
            "by_model": {}
        }

        # Get breakdown by model
        rows = conn.execute("""
            SELECT
                model,
                COALESCE(SUM(input_tokens), 0) as input_tokens,
                COALESCE(SUM(output_tokens), 0) as output_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) as cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                COUNT(*) as message_count
            FROM usage_records
            WHERE timestamp >= ?
            GROUP BY model
        """, (cutoff,)).fetchall()

        for row in rows:
            result["by_model"][row["model"]] = {
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_creation_tokens": row["cache_creation_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "total_tokens": (
                    row["input_tokens"] + row["output_tokens"] +
                    row["cache_creation_tokens"] + row["cache_read_tokens"]
                ),
                "message_count": row["message_count"]
            }

        return result
    finally:
        conn.close()


def get_usage_in_days(days: int) -> dict:
    """
    Get aggregated usage for the past N days.

    Returns dict with total tokens by category and by model.
    """
    return get_usage_in_window(hours=days * 24)


def get_hourly_aggregates(hours: int = 24) -> list[dict]:
    """
    Get hourly aggregated usage for the past N hours.

    Returns list of dicts with hour and token counts.
    """
    conn = get_connection()
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        rows = conn.execute("""
            SELECT
                strftime('%Y-%m-%dT%H:00:00', timestamp) as hour,
                COALESCE(SUM(input_tokens), 0) as input_tokens,
                COALESCE(SUM(output_tokens), 0) as output_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) as cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                COUNT(*) as message_count
            FROM usage_records
            WHERE timestamp >= ?
            GROUP BY hour
            ORDER BY hour
        """, (cutoff,)).fetchall()

        return [
            {
                "hour": row["hour"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_creation_tokens": row["cache_creation_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "total_tokens": (
                    row["input_tokens"] + row["output_tokens"] +
                    row["cache_creation_tokens"] + row["cache_read_tokens"]
                ),
                "message_count": row["message_count"]
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_daily_aggregates(days: int = 7) -> list[dict]:
    """
    Get daily aggregated usage for the past N days.

    Returns list of dicts with date and token counts.
    """
    conn = get_connection()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        rows = conn.execute("""
            SELECT
                date(timestamp) as day,
                COALESCE(SUM(input_tokens), 0) as input_tokens,
                COALESCE(SUM(output_tokens), 0) as output_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) as cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens,
                COUNT(*) as message_count
            FROM usage_records
            WHERE timestamp >= ?
            GROUP BY day
            ORDER BY day
        """, (cutoff,)).fetchall()

        return [
            {
                "day": row["day"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_creation_tokens": row["cache_creation_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "total_tokens": (
                    row["input_tokens"] + row["output_tokens"] +
                    row["cache_creation_tokens"] + row["cache_read_tokens"]
                ),
                "message_count": row["message_count"]
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_record_count() -> int:
    """Get the total number of records in the database."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as count FROM usage_records").fetchone()
        return row["count"]
    finally:
        conn.close()
