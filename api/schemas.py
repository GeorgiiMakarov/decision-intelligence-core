
"""Wire-level request/response models for the REST API. Mirrors openapi.yaml
exactly. Kept separate from domain/models.py on purpose (hexagonal boundary):
the wire format can change without touching domain logic."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

class UpdateMetricRequest(BaseModel):
    decision_id: str
    metric_name: str
    value: Any
    idempotency_key: str = Field(min_length=16)
    evidence_refs: list[str] = Field(min_length=1)
    proposed_by: str
    # Was silently dropped before (api/main.py hardcoded {}) — REST callers
    # had no way to actually supply Runtime context. Same JsonValue type as
    # the domain layer (domain/events.py, domain/models.py) and the gRPC
    # transport (grpc/core.proto's google.protobuf.Struct).
    runtime_context: JsonValue = Field(default_factory=dict)

class UpdateMetricResponseBody(BaseModel):
    status: Literal["ACCEPTED", "DUPLICATE_IGNORED"]

class ScoreboardMetricOut(BaseModel):
    value: Any
    evidence_refs: list[str]
    committed_at: dt.datetime

class GetScoreboardResponse(BaseModel):
    decision_id: str
    trust_score: float | str  # number, or "INSUFFICIENT_DATA"
    metrics: dict[str, ScoreboardMetricOut]
    merkle_root_ref: str | None
    merkle_timestamp: dt.datetime | None
    rebuilt_at: dt.datetime

class ProofNodeOut(BaseModel):
    hash: str
    position: Literal["LEFT", "RIGHT"]

class GetMerkleProofResponse(BaseModel):
    leaf_hash: str
    proof_path: list[ProofNodeOut]
    root: str
    anchor_signature: str
    anchor_timestamp: dt.datetime

class ErrorResponse(BaseModel):
    detail: str




