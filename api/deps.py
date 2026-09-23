
"""
Dependency injection wiring. Constraint: 'Dependency Injection, без
глобального состояния, Core stateless'.

Everything mutable lives inside an AppState instance attached to
`app.state` by the FastAPI lifespan context in main.py — not in module-level
globals. Which concrete adapters get constructed (Memory* vs Kafka/Redis*) is
controlled by environment variables, so `docker-compose up` and pytest use
the exact same wiring code with different CORE_ENV values.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from application.command_handler import CommandHandler
from application.merkle import MerkleBatchBuilder
from application.merkle_anchor_service import MerkleAnchorService
from application.scoreboard_projector import ScoreboardProjector
from infrastructure.ed25519_signer import Ed25519Signer
from infrastructure.memory_adapters import MemoryAuditTrail, MemoryEventBus, MemoryProjectionStore, MemoryTsa
from interfaces.audit_trail import AuditTrail
from interfaces.event_bus import EventBus
from interfaces.projection_store import ProjectionStore
from interfaces.signer import Signer
from interfaces.tsa import TimestampAuthority

@dataclass
class AppState:
    audit_trail: AuditTrail
    projection_store: ProjectionStore
    event_bus: EventBus
    signer: Signer
    tsa: TimestampAuthority
    merkle_builder: MerkleBatchBuilder
    merkle_anchor: MerkleAnchorService
    command_handler: CommandHandler
    projector: ScoreboardProjector
    required_metrics_by_decision: dict[str, list[str]]

def _load_required_metrics() -> dict[str, list[str]]:
    """Per-decision required metrics for the REST scoreboard, from the
    CORE_REQUIRED_METRICS env var as JSON: {"decision-id": ["metric.a", ...]}.

    Missing, empty, or malformed value -> {} (the historical default: the
    scoreboard then treats any committed set as vacuously complete).
    Malformed entries inside a well-formed object are dropped, not fatal.
    """
    raw = os.environ.get("CORE_REQUIRED_METRICS", "")
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, list[str]] = {}
    for decision_id, metrics in parsed.items():
        if (
            isinstance(decision_id, str)
            and isinstance(metrics, list)
            and all(isinstance(m, str) for m in metrics)
        ):
            result[decision_id] = list(metrics)
    return result


async def build_app_state() -> AppState:
    """Async on purpose (not just sync-with-a-wrapper): PostgresAuditTrail.connect()
below awaits real pool creation + schema migration, and api/main.py's
lifespan is already an async context manager, so `await build_app_state()`
there is the natural call, not a workaround."""
    env = os.environ.get("CORE_ENV", "local")

    if env == "docker":
        # Imported here, not at module load time, so `import api.deps` does
        # not require aiokafka/redis/asyncpg to be installed just to run
        # unit tests locally against the Memory* adapters.
        from infrastructure.kafka_adapter import KafkaEventBus
        from infrastructure.postgres_audit_trail import PostgresAuditTrail
        from infrastructure.redis_adapter import RedisProjectionStore

        audit_trail: AuditTrail = await PostgresAuditTrail.connect(
        os.environ.get("DATABASE_URL", "postgresql://core:core@postgres:5432/core")
        )
        projection_store: ProjectionStore = RedisProjectionStore(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
        )
        event_bus: EventBus = KafkaEventBus(
        bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"),
        consumer_group="decision-intelligence-core",
        )
        tsa: TimestampAuthority = MemoryTsa()  # TODO: Rfc3161HttpTsa once a
        # concrete profile endpoint (e.g. NUTS RK) is configured — see
        # infrastructure/rfc3161_tsa.py; left pluggable-but-unset here
        # deliberately rather than guessing an endpoint.
    else:
        audit_trail = MemoryAuditTrail()
        projection_store = MemoryProjectionStore()
        event_bus = MemoryEventBus()
        tsa = MemoryTsa()

    signer: Signer = Ed25519Signer(key_id=os.environ.get("SIGNER_KEY_ID", "core-dev-v1"))

    max_leaves = int(os.environ.get("MERKLE_MAX_LEAVES", "1000"))
    max_seconds = float(os.environ.get("MERKLE_MAX_SECONDS", "5"))
    merkle_builder = MerkleBatchBuilder(max_leaves=max_leaves, max_seconds=max_seconds)

    command_handler = CommandHandler(
    audit_trail=audit_trail, event_bus=event_bus,
    merkle_builder=merkle_builder, signer=signer, tsa=tsa,
    )
    projector = ScoreboardProjector(audit_trail=audit_trail, projection_store=projection_store)
    merkle_anchor = MerkleAnchorService(
    builder=merkle_builder, audit_trail=audit_trail,
    projection_store=projection_store, signer=signer, tsa=tsa,
    )

    return AppState(
    audit_trail=audit_trail, projection_store=projection_store, event_bus=event_bus,
    signer=signer, tsa=tsa, merkle_builder=merkle_builder, merkle_anchor=merkle_anchor,
    command_handler=command_handler, projector=projector,
    required_metrics_by_decision=_load_required_metrics(),
    )




