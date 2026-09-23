
"""
Command Handler — the write side. Owns the lifecycle state machine
(PROPOSED -> DEBATED -> CRITIQUED -> RECONCILED -> COMMITTED/REJECTED) and
the single synchronous UpdateMetric entry point.

Design decision (carried from the v1.1/v1.2 review): UpdateMetric (the API
command) and the async ReconciledDecision event converge on the same
`_commit()` method. A Runtime can either call UpdateMetric directly once it
has already reconciled a value itself, or publish the full
Propose/Debate/Critique/Reconcile event sequence and let Core drive the
state machine — both paths end up validating I3/I6 and committing through
the same code path, so there is exactly one place a commit can happen.

Coding rule compliance: this module never imports ProjectionStore. It only
talks to AuditTrail (write side) and MerkleBatchBuilder (in-memory
accumulator, not a persistence interface). GetScoreboard/GetMerkleProof
(api/) are the only readers of ProjectionStore.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from domain.enums import MetricStatus, UpdateMetricStatus
from application.merkle import MerkleBatchBuilder, compute_leaf_hash
from interfaces.audit_trail import AuditTrail
from interfaces.event_bus import EventBus
from interfaces.signer import Signer
from interfaces.tsa import TimestampAuthority
from pydantic import JsonValue

logger = logging.getLogger("core.command_handler")

@dataclass
class UpdateMetricCommand:
    decision_id: str
    metric_name: str
    value: Any
    idempotency_key: str
    evidence_refs: list[str]
    proposed_by: str
    runtime_context: JsonValue

@dataclass
class UpdateMetricResult:
    status: UpdateMetricStatus
    leaf_hash: str | None = None

class CommandHandler:
    def __init__(
        self,
        audit_trail: AuditTrail,
        event_bus: EventBus,
        merkle_builder: MerkleBatchBuilder,
        signer: Signer,
        tsa: TimestampAuthority,
    ) -> None:
        self._audit = audit_trail
        self._bus = event_bus
        self._merkle = merkle_builder
        self._signer = signer
        self._tsa = tsa
        # In-memory lifecycle staging area, keyed by (decision_id, metric_name).
        # This is intra-process working state for events still in flight
        # (PROPOSED..RECONCILED) — NOT the read projection. It is rebuilt from
        # AuditTrail on startup via replay (see scoreboard_projector.replay_all).
        self._staging: dict[tuple[str, str], dict[str, Any]] = {}

        # ---- synchronous command -------------------------------------------------

    async def handle_update_metric(self, cmd: UpdateMetricCommand) -> UpdateMetricResult:
        # I3
        if not cmd.evidence_refs:
            await self._audit.append(
                cmd.decision_id,
                "MetricRejected",
                {
                "decision_id": cmd.decision_id,
                "metric_name": cmd.metric_name,
                "idempotency_key": cmd.idempotency_key,
                "reason": "MISSING_EVIDENCE",
                "occurred_at": _now_iso(),
                },
            )
            return UpdateMetricResult(status=UpdateMetricStatus.REJECTED_MISSING_EVIDENCE)

        return await self._commit(
            decision_id=cmd.decision_id,
            metric_name=cmd.metric_name,
            value=cmd.value,
            evidence_refs=cmd.evidence_refs,
            idempotency_key=cmd.idempotency_key,
            proposed_by=cmd.proposed_by,
        )

        # ---- lifecycle events (async, from the bus) -------------------------------

    async def on_metric_proposed(self, payload: dict[str, Any]) -> None:
        key = (payload["decision_id"], payload["metric_name"])
        self._staging[key] = {**payload, "status": MetricStatus.PROPOSED}
        await self._audit.append(payload["decision_id"], "MetricProposed", payload)

    async def on_debate_outcome(self, payload: dict[str, Any]) -> None:
        key = (payload["decision_id"], payload["metric_name"])
        stage = self._staging.setdefault(key, {})
        stage.update(payload)
        stage["status"] = MetricStatus.DEBATED
        await self._audit.append(payload["decision_id"], "DebateOutcome", payload)

    async def on_risk_signal(self, payload: dict[str, Any]) -> None:
        key = (payload["decision_id"], payload["metric_name"])
        stage = self._staging.setdefault(key, {})
        stage["status"] = MetricStatus.CRITIQUED
        stage["risk_level"] = payload.get("risk_level")
        await self._audit.append(payload["decision_id"], "RiskSignal", payload)

    async def on_reconciled_decision(self, payload: dict[str, Any]) -> None:
        key = (payload["decision_id"], payload["metric_name"])
        stage = self._staging.setdefault(key, {})
        stage.update(payload)
        stage["status"] = MetricStatus.RECONCILED
        await self._audit.append(payload["decision_id"], "ReconciledDecision", payload)

        # Auto-commit once reconciled, using the same _commit() path UpdateMetric
        # uses — this is the "async path converges on the same code" decision
        # documented in the module docstring.
        evidence_refs = payload.get("evidence_refs", [])
        if not evidence_refs:
            await self._audit.append(
                payload["decision_id"],
                "MetricRejected",
                {
                "decision_id": payload["decision_id"],
                "metric_name": payload["metric_name"],
                "idempotency_key": payload["idempotency_key"],
                "reason": "MISSING_EVIDENCE",
                "occurred_at": _now_iso(),
                },
            )
            return
        await self._commit(
            decision_id=payload["decision_id"],
            metric_name=payload["metric_name"],
            value=payload["final_value"],
            evidence_refs=evidence_refs,
            idempotency_key=payload["idempotency_key"],
            proposed_by=payload.get("proposed_by", "reconciliation"),
        )

    async def on_evidence_attached(self, payload: dict[str, Any]) -> None:
        # Reconstruction is handled by application.evidence_registry from the
        # AuditTrail stream; this handler's only job is to make sure the
        # event actually lands there (Assumption 3: RAG is async).
        await self._audit.append(payload["decision_id"], "EvidenceAttached", payload)

    async def on_runtime_artifact_deployed(self, payload: dict[str, Any]) -> None:
        # Opaque per section 1.4 — Core stores this, never interprets artifact_type.
        await self._audit.append(payload.get("decision_id", "runtime"), "RuntimeArtifactDeployed", payload)

    async def on_runtime_config_updated(self, payload: dict[str, Any]) -> None:
        await self._audit.append(payload.get("decision_id", "runtime"), "RuntimeConfigUpdated", payload)

    async def on_goal_created(self, payload: dict[str, Any]) -> None:
        await self._audit.append(payload["decision_id"], "GoalCreated", payload)

    async def on_goal_cancelled(self, payload: dict[str, Any]) -> None:
        # ABANDONED is a new event, not a deletion of the GoalCreated record — I7.
        await self._audit.append(payload["decision_id"], "GoalCancelled", payload)

        # ---- MetricSuperseded (append-only 'rollback', scenario 3) ----------------

    async def supersede_metric(
        self, decision_id: str, metric_name: str, original_leaf_hash: str,
        new_risk_context: str, superseding_idempotency_key: str,
    ) -> None:
        """A CRITICAL RiskSignal can arrive after a metric is already
    COMMITTED (e.g. delayed via RAG). I7 forbids rewriting the original
    leaf, so this appends a NEW event referencing the old leaf by hash;
    the projector (scoreboard_projector.py) is what makes the *current*
    read state reflect the supersession while root N stays untouched."""
        await self._audit.append(
            decision_id,
            "MetricSuperseded",
            {
            "decision_id": decision_id,
            "metric_name": metric_name,
            "original_leaf_hash": original_leaf_hash,
            "new_risk_context": new_risk_context,
            "superseded_by_idempotency_key": superseding_idempotency_key,
            "occurred_at": _now_iso(),
            },
            idempotency_key=superseding_idempotency_key,
        )

        # ---- shared commit path -----------------------------------------------

    async def _commit(
        self, *, decision_id: str, metric_name: str, value: Any,
        evidence_refs: list[str], idempotency_key: str, proposed_by: str,
    ) -> UpdateMetricResult:
        now = dt.datetime.now(dt.timezone.utc)
        timestamp_iso = now.isoformat(timespec="milliseconds")
        leaf_hash = compute_leaf_hash(
            decision_id=decision_id,
            metric_name=metric_name,
            value=value,
            timestamp_iso=timestamp_iso,
            evidence_refs=evidence_refs,
            idempotency_key=idempotency_key,
        ).hex()

        result = await self._audit.append(
            decision_id,
            "MetricCommitted",
            {
            "decision_id": decision_id,
            "metric_name": metric_name,
            "value": value,
            "evidence_refs": sorted(evidence_refs),
            "idempotency_key": idempotency_key,
            "leaf_hash": leaf_hash,
            "committed_at": timestamp_iso,
            "proposed_by": proposed_by,
            },
            idempotency_key=idempotency_key,
        )

        if result.deduplicated:
            # I6 — redelivery of the same idempotency_key never creates a
            # second leaf, and therefore never changes any Merkle root.
            return UpdateMetricResult(status=UpdateMetricStatus.DUPLICATE_IGNORED, leaf_hash=None)

        self._merkle.add_leaf(bytes.fromhex(leaf_hash), result.event_id, decision_id, now.timestamp())
        key = (decision_id, metric_name)
        self._staging[key] = {**self._staging.get(key, {}), "status": MetricStatus.COMMITTED, "leaf_hash": leaf_hash}

        return UpdateMetricResult(status=UpdateMetricStatus.ACCEPTED, leaf_hash=leaf_hash)

def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")




