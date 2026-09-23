
from __future__ import annotations

import datetime as dt

from domain.enums import MetricStatus, PolicyVerdict
from domain.models import MetricRecord, RiskSignalEntry
from application.policy_evaluator import evaluate_policy

NOW = dt.datetime.now(dt.timezone.utc)

def _committed(name: str, value: float, evidence=("e1",)) -> MetricRecord:
    return MetricRecord(
        decision_id="d1", metric_name=name, value=value, proposed_by="test",
        idempotency_key=f"idem-{name}", evidence_refs=list(evidence),
        status=MetricStatus.COMMITTED, created_at=NOW,
    )

def test_insufficient_data_when_metric_missing():
    result = evaluate_policy(
        decision_id="d1", required_metrics=["dsti", "kdn", "aml"],
        metrics={"dsti": _committed("dsti", 0.8)}, risk_signals=[],
    )
    assert result.status == PolicyVerdict.INSUFFICIENT_DATA
    assert result.trust_score is None
    assert result.missing_metrics == ["aml", "kdn"]

def test_insufficient_data_never_returns_zero_as_a_disguised_missing_flag():
    # Regression guard for I4: "missing" must produce None, never 0.0, which
    # could otherwise be silently treated as "a very bad but real score".
    result = evaluate_policy(decision_id="d1", required_metrics=["a"], metrics={}, risk_signals=[])
    assert result.trust_score is None
    assert result.trust_score != 0.0

def test_approve_when_all_committed_and_no_risk():
    result = evaluate_policy(
        decision_id="d1", required_metrics=["dsti", "kdn"],
        metrics={"dsti": _committed("dsti", 0.9), "kdn": _committed("kdn", 0.85)},
        risk_signals=[],
    )
    assert result.status == PolicyVerdict.APPROVE
    assert result.trust_score is not None and result.trust_score >= 0.7

def test_critical_risk_forces_reject_even_with_high_base_score():
    risk = RiskSignalEntry(decision_id="d1", metric_name="kdn", category="CRITICAL", severity=0.9, status="ACTIVE")
    result = evaluate_policy(
        decision_id="d1", required_metrics=["dsti"],
        metrics={"dsti": _committed("dsti", 0.95)}, risk_signals=[risk],
    )
    assert result.status == PolicyVerdict.REJECT

def test_evidence_refs_are_deduplicated_and_sorted_in_the_verdict():
    result = evaluate_policy(
        decision_id="d1", required_metrics=["dsti", "kdn"],
        metrics={
        "dsti": _committed("dsti", 0.9, evidence=("z", "a")),
        "kdn": _committed("kdn", 0.9, evidence=("a", "m")),
        },
        risk_signals=[],
    )
    assert result.evidence_refs == sorted(set(result.evidence_refs))




