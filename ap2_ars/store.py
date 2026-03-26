"""Extended EventStore with string-typed events for AP2."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from ars.models import Event, EventType
from ars.store import EventStore

from .models import AP2Event, AP2SignedActionEnvelope, is_base_event_type


class AP2EventStore(EventStore):
    """Subclasses base EventStore. Overrides get_events/append_event to use
    string-typed AP2Event instead of enum-typed Event.

    The SQLite schema is identical (event_type is TEXT in SQL).
    """

    def append_ap2_event(self, envelope: AP2SignedActionEnvelope) -> int:
        """Append an AP2 event. Accepts string event type."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """INSERT INTO events
               (job_id, event_type, agreement_hash, payload, actor, signature, timestamp, server_received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                envelope.job_id,
                envelope.type,  # string directly
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

    def get_ap2_events(self, job_id: str) -> list[AP2Event]:
        """Return all events as AP2Event (string event_type, no enum coercion)."""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE job_id = ? ORDER BY event_id ASC", (job_id,),
        ).fetchall()
        return [
            AP2Event(
                event_id=r["event_id"],
                job_id=r["job_id"],
                event_type=r["event_type"],  # raw string
                agreement_hash=r["agreement_hash"],
                payload=json.loads(r["payload"]),
                actor=r["actor"],
                signature=r["signature"],
                timestamp=r["timestamp"],
                server_received_at=r["server_received_at"],
            )
            for r in rows
        ]

    def get_base_events(self, job_id: str) -> list[Event]:
        """Return only base ARS events, converted to ars.models.Event."""
        all_events = self.get_ap2_events(job_id)
        result: list[Event] = []
        for ev in all_events:
            if is_base_event_type(ev.event_type):
                result.append(
                    Event(
                        event_id=ev.event_id,
                        job_id=ev.job_id,
                        event_type=EventType(ev.event_type),
                        agreement_hash=ev.agreement_hash,
                        payload=ev.payload,
                        actor=ev.actor,
                        signature=ev.signature,
                        timestamp=ev.timestamp,
                        server_received_at=ev.server_received_at,
                    )
                )
        return result
