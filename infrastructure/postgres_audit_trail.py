
"""
Durable AuditTrail over Postgres. Fills the gap flagged in api/deps.py
('this repo does not ship a production AuditTrail implementation') — Core
constraints name AuditTrail as one of four persistence interfaces, so it
needs a real backend option alongside Kafka (EventBus) and Redis
(ProjectionStore).

Idempotency (I6) is enforced by a UNIQUE constraint on idempotency_key, not
just application-level checking — a duplicate insert raises
UniqueViolationError, which append() below catches and turns into a
deduplicated AppendResult by re-reading the existing row. That keeps the
guarantee correct even under concurrent duplicate requests (the DB, not
Python, is the arbiter of uniqueness).

Requires asyncpg + the schema in `schema.sql` (next to this file's usage in
docker-compose.yml, applied via the `db-migrate` service).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg

from interfaces.audit_trail import AppendResult

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
event_id         UUID PRIMARY KEY,
decision_id      TEXT NOT NULL,
event_type       TEXT NOT NULL,
payload          JSONB NOT NULL,
idempotency_key  TEXT UNIQUE,
seq              BIGSERIAL,
batch_id         TEXT,
created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_events_decision ON audit_events (decision_id, seq);
CREATE INDEX IF NOT EXISTS idx_audit_events_unbatched ON audit_events (batch_id) WHERE batch_id IS NULL;
"""

class PostgresAuditTrail:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresAuditTrail":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        return cls(pool)

    async def append(
        self, decision_id: str, event_type: str, payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> AppendResult:
        event_id = str(uuid.uuid4())
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO audit_events (event_id, decision_id, event_type, payload, idempotency_key) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    event_id, decision_id, event_type, json.dumps(payload), idempotency_key,
                )
            return AppendResult(event_id=event_id, deduplicated=False)
        except asyncpg.UniqueViolationError:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT event_id FROM audit_events WHERE idempotency_key = $1", idempotency_key
                )
            existing_id = row["event_id"] if row else None
            return AppendResult(event_id=str(existing_id), deduplicated=True, existing_event_id=str(existing_id))

    async def read_range(self, decision_id: str, since_seq: int = 0) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT event_type, payload, seq FROM audit_events "
                "WHERE decision_id = $1 AND seq > $2 ORDER BY seq ASC",
                decision_id, since_seq,
            )
        return [{"event_type": r["event_type"], **json.loads(r["payload"])} for r in rows]

    async def read_unbatched(self, limit: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT event_id, event_type, payload FROM audit_events "
                "WHERE batch_id IS NULL AND event_type = 'MetricCommitted' "
                "ORDER BY seq ASC LIMIT $1",
                limit,
            )
        return [{"event_id": str(r["event_id"]), "event_type": r["event_type"], **json.loads(r["payload"])} for r in rows]

    async def mark_batched(self, event_ids: list[str], batch_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE audit_events SET batch_id = $1 WHERE event_id = ANY($2::uuid[])",
                batch_id, event_ids,
            )




