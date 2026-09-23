
"""Full lifecycle, no conflicts: propose -> debate -> critique -> reconcile
-> commit -> anchor -> DecisionReady-ready state."""
from __future__ import annotations

import pytest

from application.command_handler import UpdateMetricCommand
from domain.enums import UpdateMetricStatus, PolicyVerdict

@pytest.mark.asyncio
async def test_full_lifecycle_reaches_approve(command_handler, merkle_anchor, projector):
    decision_id = "dd-happy-1"

    await command_handler.on_metric_proposed({
        "decision_id": decision_id, "metric_name": "dsti", "value": 0.3,
        "idempotency_key": "k-dsti", "proposed_by": "planner", "occurred_at": "2026-07-09T00:00:00Z",
        "runtime_context": {"planner": "2.3"},
    })
    await command_handler.on_debate_outcome({
        "decision_id": decision_id, "metric_name": "dsti", "consensus_value": 0.3,
        "dissent_refs": [], "occurred_at": "2026-07-09T00:00:01Z",
    })
    await command_handler.on_risk_signal({
        "decision_id": decision_id, "metric_name": "dsti", "risk_level": "LOW", "severity": 0.0,
        "occurred_at": "2026-07-09T00:00:02Z",
    })
    await command_handler.on_reconciled_decision({
        "decision_id": decision_id, "metric_name": "dsti", "final_value": 0.9,
        "resolution_method": "no_conflict", "evidence_refs": ["ev-1"],
        "idempotency_key": "k-dsti", "proposed_by": "planner", "occurred_at": "2026-07-09T00:00:03Z",
    })

    await merkle_anchor.force_close()
    sb = await projector.rebuild(decision_id, required_metrics=["dsti"])

    assert sb.policy_verdict == PolicyVerdict.APPROVE
    assert sb.trust_score is not None and sb.trust_score >= 0.7
    assert sb.merkle_root_ref is not None
    assert "dsti" in sb.metrics

@pytest.mark.asyncio
async def test_update_metric_command_direct_path(command_handler):
    """A Runtime that has already reconciled internally can call
UpdateMetric directly instead of publishing the full event sequence —
both paths converge on the same _commit()."""
    cmd = UpdateMetricCommand(
        decision_id="dd-happy-2", metric_name="kdn_limit_check", value="WITHIN_LIMIT",
        idempotency_key="k-kdn-1", evidence_refs=["ev-a"], proposed_by="ai-orchestrator",
        runtime_context={"router": "1.7"},
    )
    result = await command_handler.handle_update_metric(cmd)
    assert result.status == UpdateMetricStatus.ACCEPTED
    assert result.leaf_hash is not None




