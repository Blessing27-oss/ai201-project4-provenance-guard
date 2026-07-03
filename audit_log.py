"""
audit_log.py — SQLite-backed audit log for Provenance Guard.

Each submission writes one row. Appeals update the status and
appeal_reasoning fields on the matching content_id row.
"""

import sqlite3
from datetime import datetime, timezone

DB_PATH = 'audit_log.db'

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    content_id        TEXT    NOT NULL,
    creator_id        TEXT    NOT NULL,
    timestamp         TEXT    NOT NULL,
    llm_score         REAL    NOT NULL,
    stylometric_score REAL    NOT NULL,
    confidence        REAL    NOT NULL,
    attribution       REAL    NOT NULL,
    status            TEXT    NOT NULL,
    appeal_reasoning  TEXT
);
"""

# Columns added after the initial schema — migrated on first connect.
_MIGRATIONS = [
    "ALTER TABLE audit_log ADD COLUMN stylometric_score REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE audit_log ADD COLUMN appeal_reasoning TEXT",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError:
            pass  # Column already exists.
    conn.commit()
    return conn


def log_entry(
    content_id: str,
    creator_id: str,
    llm_score: float,
    stylometric_score: float,
    confidence: float,
    attribution: float,
    status: str,
) -> None:
    """Write one row to the audit log, timestamped at call time (UTC ISO 8601)."""
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log
                (content_id, creator_id, timestamp, llm_score, stylometric_score,
                 confidence, attribution, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (content_id, creator_id, timestamp, llm_score, stylometric_score,
             confidence, attribution, status),
        )


def get_entry(content_id: str) -> dict | None:
    """Return the audit log row for a given content_id, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE content_id = ?",
            (content_id,),
        ).fetchone()
    return dict(row) if row else None


def update_appeal(content_id: str, reasoning: str) -> None:
    """Set status to 'under_review' and store the creator's appeal reasoning."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE audit_log
               SET status = 'under_review', appeal_reasoning = ?
             WHERE content_id = ?
            """,
            (reasoning, content_id),
        )


def get_recent_entries(limit: int = 10) -> list[dict]:
    """Return the most recent log entries, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
