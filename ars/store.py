from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .models import Event, EventType, SignedActionEnvelope


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            TEXT    NOT NULL,
    event_type        TEXT    NOT NULL,
    agreement_hash    TEXT    NOT NULL,
    payload           TEXT    NOT NULL,
    actor             TEXT    NOT NULL,
    signature         TEXT    NOT NULL,
    timestamp         TEXT    NOT NULL,
    server_received_at TEXT   NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id);

CREATE TABLE IF NOT EXISTS jobs (
    job_id     TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class EventStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def create_job(self, job_id: str, timestamp: str) -> None:
        self._conn.execute(
            "INSERT INTO jobs (job_id, created_at, updated_at) VALUES (?, ?, ?)",
            (job_id, timestamp, timestamp),
        )
        self._conn.commit()

    def job_exists(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row is not None

    def append_event(self, envelope: SignedActionEnvelope) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """INSERT INTO events
               (job_id, event_type, agreement_hash, payload, actor, signature, timestamp, server_received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                envelope.job_id,
                envelope.type.value,
                envelope.agreement_hash,
                json.dumps(envelope.payload),
                envelope.actor,
                envelope.signature,
                envelope.timestamp,
                now,
            ),
        )
        self._conn.execute(
            "UPDATE jobs SET updated_at = ? WHERE job_id = ?", (now, envelope.job_id),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_events(self, job_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE job_id = ? ORDER BY event_id ASC", (job_id,),
        ).fetchall()
        return [
            Event(
                event_id=r["event_id"],
                job_id=r["job_id"],
                event_type=EventType(r["event_type"]),
                agreement_hash=r["agreement_hash"],
                payload=json.loads(r["payload"]),
                actor=r["actor"],
                signature=r["signature"],
                timestamp=r["timestamp"],
                server_received_at=r["server_received_at"],
            )
            for r in rows
        ]
