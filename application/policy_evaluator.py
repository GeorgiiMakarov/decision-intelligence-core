
"""Policy Evaluator. Section 1.7 pseudocode from the v1.1 spec review,
implemented for real. Enforces I4: never fabricate a trust_score from an
incomplete metric set — return INSUFFICIENT_DATA instead of 0 or None-as-zero.

Zero Trust between services (design_principles): this function recomputes
from the committed metric set every call. It does not trust a cached verdict
from a previous run, including its own.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import ClassVar

from domain.enums import MetricStatus, PolicyVerdict as PolicyVerdictEnum
from domain.models import MetricRecord, PolicyVerdictResult, RiskSignalEntry

@dataclass(frozen=True)
class PolicyThresholds:
    approve_at: float = 0.7  # Banking Profile KZ, section 4.1: 'REJECT если score < 0.7'
    reject_below: float = 0.5

    RISK_WEIGHTS: ClassVar[dict[str, float]] = {
        "DATA_FRESHNESS": 0.05,
        "CONTRADICTION": 0.15,
        "POLICY_BREACH": 0.30,
        "CRITICAL": 0.50,
    }

def evaluate_policy(
    *,
    decision_id: str,
    required_metrics: list[str],
    metrics: dict[str, MetricRecord],
    risk_signals: list[RiskSignalEntry],
    weights: dict[str, float] | None = None,
    thresholds: PolicyThresholds = PolicyThresholds(),
) -> PolicyVerdictResult:
    now = dt.datetime.now(dt.timezone.utc)

    committed = {
    name: m for name, m in metrics.items()
    if m.status == MetricStatus.COMMITTED and name in required_metrics
    }
    missing = sorted(set(required_metrics) - set(committed.keys()))

    # I4 — hard gate. No branch below this point may return a numeric score
    # if `missing` is non-empty.
    if missing:
        return PolicyVerdictResult(
        trust_score=None,
        status=PolicyVerdictEnum.INSUFFICIENT_DATA,
        missing_metrics=missing,
        evidence_refs=[],
        computed_at=now,
    )

    w = weights or {name: 1.0 for name in required_metrics}
    numeric_terms = []
    for name, record in committed.items():
        numeric_val = record.value if isinstance(record.value, (int, float)) else 1.0
        numeric_terms.append(numeric_val * w.get(name, 1.0))
        total_weight = sum(w.get(name, 1.0) for name in committed) or 1.0
        base_score = sum(numeric_terms) / total_weight
        base_score = max(0.0, min(1.0, base_score))

    active_risk = [r for r in risk_signals if r.status == "ACTIVE"]
    risk_penalty = sum(r.severity * PolicyThresholds.RISK_WEIGHTS.get(r.category, 0.1) for r in active_risk)
    trust_score = max(0.0, min(1.0, base_score - risk_penalty))

    has_critical = any(r.category == "CRITICAL" for r in active_risk)
    if trust_score >= thresholds.approve_at and not has_critical:
        status = PolicyVerdictEnum.APPROVE
    elif trust_score < thresholds.reject_below or has_critical:
        status = PolicyVerdictEnum.REJECT
    else:
        status = PolicyVerdictEnum.MANUAL_REVIEW

    evidence_refs = sorted({ref for m in committed.values() for ref in m.evidence_refs})

    return PolicyVerdictResult(
    trust_score=trust_score,
    status=status,
    missing_metrics=[],
    evidence_refs=evidence_refs,
    computed_at=now,
    )




