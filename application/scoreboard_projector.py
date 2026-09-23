
"""
Scoreboard Projector — rebuilds the CQRS read model from AuditTrail. This is
the ONLY thing that writes to ProjectionStore (coding_rule: commands never
read projection; by the same discipline, only the projector writes it).

Delegates reconstruction to the three named registry components instead of
inlining their logic (metrics_registry.py, risk_matrix.py,
evidence_registry.py) — Scoreboard Core's own job per functional_requirements
is narrower: aggregate what those three already reconstructed, run Policy
Evaluator over it, and materialize the read model. Evidence Registry is
would_be wired here too (evidence_registry.reconstruct) once I3 is
strengthened to check evidence existence, not just non-emptiness — see
evidence_registry.py's module docstring.

Deterministic state reconstruction (design_principles): replay(decision_id)
run twice against the same event log must produce byte-identical
ScoreboardState except for `rebuilt_at`. tests/integration/test_replay.py
checks exactly this.
"""
from __future__ import annotations

import datetime as dt

from domain.models import ScoreboardMetricView, ScoreboardState
from interfaces.audit_trail import AuditTrail
from interfaces.projection_store import ProjectionStore
from application import metrics_registry, risk_matrix
from application.policy_evaluator import evaluate_policy

class ScoreboardProjector:
    def __init__(self, audit_trail: AuditTrail, projection_store: ProjectionStore) -> None:
        self._audit = audit_trail
        self._store = projection_store

    async def rebuild(self, decision_id: str, required_metrics: list[str]) -> ScoreboardState:
        events = await self._audit.read_range(decision_id)

        metrics = metrics_registry.reconstruct(decision_id, events)
        risk_signals = risk_matrix.reconstruct(decision_id, events)
        last_root_event = next(
            (e for e in reversed(events) if e.get("event_type") == "MerkleRootPublished"),
            None,
        )
        merkle_root_ref = last_root_event["root"] if last_root_event else None
        merkle_timestamp = (
            dt.datetime.fromisoformat(last_root_event["anchor_timestamp"]) if last_root_event else None
        )

        verdict = evaluate_policy(
            decision_id=decision_id,
            required_metrics=required_metrics,
            metrics=metrics,
            risk_signals=risk_signals,
        )

        views = {
            name: ScoreboardMetricView(
            value=m.value, evidence_refs=m.evidence_refs,
            committed_at=m.created_at, status=m.status,
            )
            for name, m in metrics.items()
        }

        state = ScoreboardState(
            decision_id=decision_id,
            trust_score=verdict.trust_score,
            policy_verdict=verdict.status,
            metrics=views,
            merkle_root_ref=merkle_root_ref,
            merkle_timestamp=merkle_timestamp,
            rebuilt_at=dt.datetime.now(dt.timezone.utc),
            rebuild_seq=len(events),
        )
        await self._store.set(f"scoreboard:{decision_id}", state.model_dump(mode="json"))
        return state




