
"""
Core domain models. Spec v1.2 section 1.4 (data model), section 1.7 (contracts).

These are the Pydantic v2 models used INSIDE the Core (persisted / returned by
GetScoreboard, GetMerkleProof). They are distinct from api/schemas.py, which are
the wire-level request/response shapes for the REST layer (hexagonal boundary:
API schemas may evolve independently of domain models).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, JsonValue, field_validator

from domain.enums import MetricStatus, PolicyVerdict as PolicyVerdictEnum, ProofPosition

class EvidenceRecord(BaseModel):
    """Evidence Registry entry. Never stores raw personal data (Assumption 6) —
only a content hash and a storage reference (WORM, localized storage)."""
    evidence_id: str
    decision_id: str
    source_type: str  # RAG_DOCUMENT | POLICY | EXTERNAL_API | MANUAL_UPLOAD
    content_hash: str
    storage_ref: str
    fetched_at: dt.datetime
    ttl_expires_at: dt.datetime | None = None

class MetricRecord(BaseModel):
    """Metrics Registry entry — one row per (decision_id, metric_name, idempotency_key).
Append-only: a new value for the same metric_name is a NEW record, never an
UPDATE of an existing one (invariant I7)."""

    decision_id: str
    metric_name: str
    value: Any
    proposed_by: str
    idempotency_key: str
    evidence_refs: list[str] = Field(default_factory=list)
    status: MetricStatus = MetricStatus.PROPOSED
    created_at: dt.datetime
    leaf_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")  # hex SHA-256, set only when status == COMMITTED
    runtime_context: JsonValue = Field(default_factory=dict)  # opaque, spec 1.4
    superseded_by: str | None = None  # idempotency_key of the superseding record, if any

    @field_validator("evidence_refs")
    @classmethod
    def _sorted_unique(cls, v: list[str]) -> list[str]:
        # Leaf hash formula requires evidence_refs_sorted — normalize at the model
        # boundary so every downstream consumer sees the canonical order.
        return sorted(set(v))

class RiskSignalEntry(BaseModel):
    decision_id: str
    metric_name: str
    category: str
    severity: float = Field(ge=0.0, le=1.0)
    status: str = "ACTIVE"  # ACTIVE | RESOLVED
    resolved_by: str | None = None
    resolved_at: dt.datetime | None = None
    contradiction_flags: list[str] = Field(default_factory=list)

class ScoreboardMetricView(BaseModel):
    value: Any
    evidence_refs: list[str]
    committed_at: dt.datetime
    status: MetricStatus

class ScoreboardState(BaseModel):
    """Scoreboard Core — CQRS read projection. NOT the source of truth; it is
rebuilt deterministically from the append-only event log (I2, I7)."""

    decision_id: str
    trust_score: float | None = None  # None == INSUFFICIENT_DATA (I4)
    policy_verdict: PolicyVerdictEnum = PolicyVerdictEnum.INSUFFICIENT_DATA
    metrics: dict[str, ScoreboardMetricView] = Field(default_factory=dict)
    merkle_root_ref: str | None = None
    merkle_timestamp: dt.datetime | None = None  # when merkle_root_ref was anchored (TSA time)
    rebuilt_at: dt.datetime
    rebuild_seq: int

class ProofNode(BaseModel):
    hash: str
    position: ProofPosition

class MerkleProofResponse(BaseModel):
    leaf_hash: str
    proof_path: list[ProofNode]
    root: str
    anchor_signature: str
    anchor_timestamp: dt.datetime

class PolicyVerdictResult(BaseModel):
    trust_score: float | None
    status: PolicyVerdictEnum
    missing_metrics: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    computed_at: dt.datetime




