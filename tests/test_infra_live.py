"""Live tests of the real infrastructure adapters against the real services
from docker-compose.yml (postgres:5432, redis:6379, kafka:9092).

These are NOT unit tests — they exercise:
  - infrastructure.postgres_audit_trail.PostgresAuditTrail
  - infrastructure.redis_adapter.RedisProjectionStore
  - infrastructure.kafka_adapter.KafkaEventBus

...against actual Postgres / Redis / Kafka backends.

Dependency skipping:
  - If asyncpg / redis / aiokafka are not installed (they are optional in
    requirements.txt), each test skips via pytest.importorskip.
  - If a service is unreachable (short ~2-3s connection probe fails), each
    test pytest.skips with "service unavailable". Plain CI without docker
    therefore stays green.

Run after:  docker-compose up -d postgres redis kafka
            pytest tests/test_infra_live.py -v

No new dependencies are introduced by this file: pytest + pytest-asyncio
only.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "core"
PG_DB = "core"
REDIS_URL = "redis://127.0.0.1:6379/0"
KAFKA_BOOTSTRAP = "127.0.0.1:9092"

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def _pg_password() -> str:
    """Read POSTGRES_PASSWORD from the repo's docker-compose.yml.

    Never hardcode the secret into this file; the compose file is the
    single source of truth for local credentials.
    """
    if not COMPOSE_FILE.exists():
        pytest.skip("docker-compose.yml not found; cannot resolve POSTGRES_PASSWORD")
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    m = re.search(r"POSTGRES_PASSWORD:\s*([^\s#'\"<>]+)", text)
    if not m:
        pytest.skip("POSTGRES_PASSWORD not found in docker-compose.yml")
    return m.group(1)


def _pg_dsn() -> str:
    # quote() in case the password contains DSN-significant characters
    return f"postgresql://{PG_USER}:{quote(_pg_password(), safe='')}@{PG_HOST}:{PG_PORT}/{PG_DB}"


def _new_suffix() -> str:
    """Unique suffix so parallel/CI runs never collide on keys or topics."""
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------
# Postgres: PostgresAuditTrail
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pg_append_then_read_range():
    pytest.importorskip("asyncpg", reason="asyncpg not installed")
    from infrastructure.postgres_audit_trail import PostgresAuditTrail

    try:
        trail = await asyncio.wait_for(PostgresAuditTrail.connect(_pg_dsn()), timeout=3.0)
    except Exception:
        pytest.skip("postgres unavailable")
    try:
        suffix = _new_suffix()
        decision_id = f"live-pg-{suffix}"
        key = f"live-pg-key-{suffix}"

        res = await trail.append(
            decision_id, "MetricCommitted",
            {"metric_name": "aml_check", "value": "CLEAR"},
            idempotency_key=key,
        )
        assert not res.deduplicated
        assert res.event_id

        events = await trail.read_range(decision_id)
        committed = [e for e in events if e["event_type"] == "MetricCommitted"]
        assert len(committed) == 1
        assert committed[0]["metric_name"] == "aml_check"
        assert committed[0]["value"] == "CLEAR"
    finally:
        # PostgresAuditTrail exposes no close(); release the pool directly.
        await trail._pool.close()


@pytest.mark.asyncio
async def test_pg_reappend_same_idempotency_key_is_deduplicated():
    """I6: a redelivered append with the same idempotency_key must not create
    a second row — the UNIQUE constraint on idempotency_key is the arbiter."""
    pytest.importorskip("asyncpg", reason="asyncpg not installed")
    from infrastructure.postgres_audit_trail import PostgresAuditTrail

    try:
        trail = await asyncio.wait_for(PostgresAuditTrail.connect(_pg_dsn()), timeout=3.0)
    except Exception:
        pytest.skip("postgres unavailable")
    try:
        suffix = _new_suffix()
        decision_id = f"live-pg-idem-{suffix}"
        key = f"live-pg-idem-key-{suffix}"

        first = await trail.append(
            decision_id, "MetricCommitted",
            {"metric_name": "sanctions_check", "value": "CLEAR"},
            idempotency_key=key,
        )
        assert not first.deduplicated

        second = await trail.append(
            decision_id, "MetricCommitted",
            {"metric_name": "sanctions_check", "value": "CLEAR"},
            idempotency_key=key,
        )
        assert second.deduplicated is True, "I6: duplicate must be deduplicated"
        assert second.existing_event_id == first.event_id

        events = await trail.read_range(decision_id)
        assert len(events) == 1, "I6: redelivery must never create a second row"
    finally:
        await trail._pool.close()


# --------------------------------------------------------------------------
# Redis: RedisProjectionStore
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_set_get_roundtrip():
    pytest.importorskip("redis.asyncio", reason="redis package not installed")
    from infrastructure.redis_adapter import RedisProjectionStore

    store = RedisProjectionStore(REDIS_URL)
    try:
        await asyncio.wait_for(store._client.ping(), timeout=3.0)
    except Exception:
        pytest.skip("redis unavailable")

    suffix = _new_suffix()
    key = f"live:projection:{suffix}"
    value = {"decision_id": f"dd-live-{suffix}", "score": 42, "verdict": "ACCEPT"}
    try:
        await store.set(key, value)
        got = await store.get(key)
        assert got == value
        assert await store.get(f"live:projection:missing-{suffix}") is None
    finally:
        await store._client.delete(key)
        await store._client.aclose()


@pytest.mark.asyncio
async def test_redis_get_many_by_prefix():
    pytest.importorskip("redis.asyncio", reason="redis package not installed")
    from infrastructure.redis_adapter import RedisProjectionStore

    store = RedisProjectionStore(REDIS_URL)
    try:
        await asyncio.wait_for(store._client.ping(), timeout=3.0)
    except Exception:
        pytest.skip("redis unavailable")

    suffix = _new_suffix()
    prefix = f"live:many:{suffix}:"
    keys = [f"{prefix}a", f"{prefix}b"]
    try:
        await store.set(keys[0], {"n": 1})
        await store.set(keys[1], {"n": 2})
        got = await store.get_many(prefix)
        assert got[keys[0]] == {"n": 1}
        assert got[keys[1]] == {"n": 2}
        # must not leak keys from other prefixes / tests
        assert all(k.startswith(prefix) for k in got)
    finally:
        await store._client.delete(*keys)
        await store._client.aclose()


# --------------------------------------------------------------------------
# Kafka: KafkaEventBus
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kafka_publish_consume_roundtrip():
    """publish(topic, key=decision_id, payload) -> consumer receives the same
    payload back. partition key = decision_id (adapter guarantee)."""
    pytest.importorskip("aiokafka", reason="aiokafka not installed")
    from infrastructure.kafka_adapter import KafkaEventBus

    suffix = _new_suffix()
    topic = f"live-decisions-{suffix}"
    decision_id = f"dd-live-{suffix}"
    payload = {"event_type": "MetricCommitted", "decision_id": decision_id, "seq": 1}

    bus = KafkaEventBus(bootstrap_servers=KAFKA_BOOTSTRAP, consumer_group=f"live-test-{suffix}")
    try:
        await asyncio.wait_for(bus.start(), timeout=10.0)
    except Exception:
        pytest.skip("kafka unavailable")

    received = asyncio.Event()
    inbox: list[dict] = []

    async def _handler(msg: dict) -> None:
        inbox.append(msg)
        received.set()

    try:
        await bus.subscribe(topic, _handler)
        # give the fresh consumer time to join the group before publishing,
        # otherwise the message can be produced before the initial offset
        # position (latest) is established and would be missed
        await asyncio.sleep(5.0)

        got_it = False
        for _ in range(3):  # re-publish a few times to absorb rebalances
            await bus.publish(topic, key=decision_id, payload=payload)
            try:
                await asyncio.wait_for(received.wait(), timeout=8.0)
                got_it = True
                break
            except asyncio.TimeoutError:
                continue
        assert got_it, "consumer never received the published message"
        assert inbox[0] == payload
    finally:
        await bus.stop()
