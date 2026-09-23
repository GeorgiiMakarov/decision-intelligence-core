
"""
Domain events. Spec v1.2 sections 1.4, 1.6, 1.8.

Every event that references a Runtime carries `runtime_context: JsonValue`.
Core stores this as opaque data and MUST NOT parse or branch on its contents
(section 1.4) — that is what keeps Core decoupled from AI Orchestrator Runtime,
Workflow Runtime, Human Review Runtime, etc. JsonValue (not dict[str, str]):
different Runtime Implementations put genuinely different shapes here —
nested config, numbers, booleans — not just flat string pairs, and Core
never inspects it either way, so there is no reason to constrain it beyond
'valid JSON'.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

class _RuntimeEvent(BaseModel):
    """Base for any event that can originate from a pluggable Runtime."""
    runtime_context: JsonValue = Field(default_factory=dict)

    # --- Lifecycle events (section 1.6) ----------------------------------------

class MetricProposed(_RuntimeEvent):
    event_type: Literal["MetricProposed"] = "MetricProposed"
    decision_id: str
    metric_name: str
    value: Any
    idempotency_key: str
    proposed_by: str
    occurred_at: dt.datetime

class DebateOutcome(_RuntimeEvent):
    event_type: Literal["DebateOutcome"] = "DebateOutcome"
    decision_id: str
    metric_name: str
    consensus_value: Any
    dissent_refs: list[str] = Field(default_factory=list)
    occurred_at: dt.datetime

class RiskSignal(_RuntimeEvent):
    event_type: Literal["RiskSignal"] = "RiskSignal"
    decision_id: str
    metric_name: str
    risk_level: str
    severity: float = Field(ge=0.0, le=1.0, default=0.0)
    contradiction_flags: list[str] = Field(default_factory=list)
    occurred_at: dt.datetime

class ReconciledDecision(_RuntimeEvent):
    event_type: Literal["ReconciledDecision"] = "ReconciledDecision"
    decision_id: str
    metric_name: str
    final_value: Any
    resolution_method: str
    evidence_refs: list[str] = Field(default_factory=list)
    idempotency_key: str
    proposed_by: str
    occurred_at: dt.datetime

class MetricCommitted(BaseModel):
    event_type: Literal["MetricCommitted"] = "MetricCommitted"
    decision_id: str
    metric_name: str
    value: Any
    evidence_refs: list[str]
    idempotency_key: str
    leaf_hash: str
    committed_at: dt.datetime

class MetricRejected(BaseModel):
    event_type: Literal["MetricRejected"] = "MetricRejected"
    decision_id: str
    metric_name: str
    idempotency_key: str
    reason: str  # MISSING_EVIDENCE | DUPLICATE_IDEMPOTENCY_KEY
    occurred_at: dt.datetime

class MetricSuperseded(BaseModel):
    """The append-only 'rollback': never mutates the original committed leaf
(I7). A new leaf records that an earlier COMMITTED metric has been
superseded by new risk context arriving after the original commit."""
    event_type: Literal["MetricSuperseded"] = "MetricSuperseded"
    decision_id: str
    metric_name: str
    original_leaf_hash: str
    new_risk_context: str
    superseded_by_idempotency_key: str
    occurred_at: dt.datetime

class MerkleRootPublished(BaseModel):
    event_type: Literal["MerkleRootPublished"] = "MerkleRootPublished"
    batch_id: str
    root: str
    leaf_count: int
    anchor_signature: str
    anchor_timestamp: dt.datetime

class DecisionReady(BaseModel):
    event_type: Literal["DecisionReady"] = "DecisionReady"
    decision_id: str
    trust_score: float | None
    policy_verdict: str
    merkle_root: str | None
    committed_metrics: list[str]
    occurred_at: dt.datetime

class EvidenceAttached(_RuntimeEvent):
    """Was missing: Assumption 3 says evidence arrives asynchronously from
RAG, but no event previously modeled that arrival — evidence only ever
showed up already-embedded in evidence_refs on ReconciledDecision/
UpdateMetric. This is what application/evidence_registry.py consumes."""
    event_type: Literal["EvidenceAttached"] = "EvidenceAttached"
    decision_id: str
    evidence_id: str
    source_type: str  # RAG_DOCUMENT | POLICY | EXTERNAL_API | MANUAL_UPLOAD
    content_hash: str
    storage_ref: str
    fetched_at: dt.datetime

    # --- Goal Loop events --------------------------------------------------------

class GoalCreated(BaseModel):
    event_type: Literal["GoalCreated"] = "GoalCreated"
    decision_id: str
    goal_id: str
    required_metrics: list[str]
    occurred_at: dt.datetime

class GoalCancelled(BaseModel):
    event_type: Literal["GoalCancelled"] = "GoalCancelled"
    decision_id: str
    reason: str
    occurred_at: dt.datetime

    # --- Runtime Integration events (section 1.4) --------------------------------

class RuntimeArtifactDeployed(_RuntimeEvent):
    event_type: Literal["RuntimeArtifactDeployed"] = "RuntimeArtifactDeployed"
    artifact_type: str
    artifact_id: str
    version: str
    content_hash: str
    deployed_at: dt.datetime

class RuntimeConfigUpdated(_RuntimeEvent):
    event_type: Literal["RuntimeConfigUpdated"] = "RuntimeConfigUpdated"
    config_type: str
    config_id: str
    version: str
    content_hash: str
    occurred_at: dt.datetime


# Union of everything Core can consume from the event bus. Used by the
# event dispatcher (application/event_dispatcher.py) to route by event_type.
InboundEvent = (
    MetricProposed
    | DebateOutcome
    | RiskSignal
    | ReconciledDecision
    | EvidenceAttached
    | GoalCreated
    | GoalCancelled
    | RuntimeArtifactDeployed
    | RuntimeConfigUpdated
)




