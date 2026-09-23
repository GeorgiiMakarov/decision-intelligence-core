
"""
In-memory adapters implementing the same Protocols as the real Kafka/Redis
infrastructure (kafka_adapter.py, redis_adapter.py). This is what
tests/integration/ runs against.

This is not a workaround specific to this sandbox: testing application logic
against fakes that satisfy the same Protocol as production infrastructure is
the entire point of the interfaces/ boundary (dependency inversion). The
separate Kafka/Redis adapters exist so the SAME command_handler /
scoreboard_projector code runs unchanged against real infrastructure in
docker-compose.
"""
from __future__ import annotations

import uuid
from typing import Any

from interfaces.audit_trail import AppendResult
from interfaces.tsa import TsaToken

class MemoryAuditTrail:
    """Append-only. No method here can mutate an existing entry — same
guarantee the Protocol promises, just backed by a Python list instead of
a real log."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []  # global, ordered
        self._by_decision: dict[str, list[dict[str, Any]]] = {}
        self._idempotency_index: dict[str, str] = {}  # idempotency_key -> event_id
        self._batched: set[str] = set()

    async def append(
        self, decision_id: str, event_type: str, payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> AppendResult:
        if idempotency_key is not None and idempotency_key in self._idempotency_index:
            return AppendResult(
                event_id=self._idempotency_index[idempotency_key],
                deduplicated=True,
                existing_event_id=self._idempotency_index[idempotency_key],
            )
        event_id = str(uuid.uuid4())
        record = {"event_id": event_id, "event_type": event_type, "decision_id": decision_id, **payload}
        self._events.append(record)
        self._by_decision.setdefault(decision_id, []).append(record)
        if idempotency_key is not None:
            self._idempotency_index[idempotency_key] = event_id
        return AppendResult(event_id=event_id, deduplicated=False)

    async def read_range(self, decision_id: str, since_seq: int = 0) -> list[dict[str, Any]]:
        return list(self._by_decision.get(decision_id, []))[since_seq:]

    async def read_unbatched(self, limit: int) -> list[dict[str, Any]]:
        out = [e for e in self._events if e["event_id"] not in self._batched and e["event_type"] == "MetricCommitted"]
        return out[:limit]

    async def mark_batched(self, event_ids: list[str], batch_id: str) -> None:
        self._batched.update(event_ids)

class MemoryProjectionStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self._data[key] = value

    async def get_many(self, prefix: str) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self._data.items() if k.startswith(prefix)}

class MemoryEventBus:
    """Synchronous, in-process fan-out — good enough to prove dispatcher /
command-handler wiring without a broker."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list] = {}
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None:
        self.published.append((topic, key, payload))
        for handler in self._subscribers.get(topic, []):
            await handler(payload)

    async def subscribe(self, topic: str, handler) -> None:
        self._subscribers.setdefault(topic, []).append(handler)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

class MemoryTsa:
    """Deterministic fake TSA: still produces a real, checkable token
structure (matches the pluggable TSA Protocol), just without an outbound
RFC 3161 network call."""

    def __init__(self, authority_id: str = "memory-tsa") -> None:
        self._authority_id = authority_id

    async def timestamp(self, digest: bytes) -> TsaToken:
        import datetime as dt
        ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        token_bytes = digest + ts.encode("utf-8") + self._authority_id.encode("utf-8")
        return TsaToken(token_bytes=token_bytes, timestamp_iso=ts, authority_id=self._authority_id)

    def verify(self, digest: bytes, token: TsaToken) -> bool:
        expected = digest + token.timestamp_iso.encode("utf-8") + token.authority_id.encode("utf-8")
        return expected == token.token_bytes




