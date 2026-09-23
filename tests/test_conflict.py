
"""Debate Engine disagreement -> metric must NOT commit until Reconciliation
resolves it. Scenario 2 from the v1.1 spec review."""
from __future__ import annotations

import pytest

from domain.enums import MetricStatus

@pytest.mark.asyncio
async def test_dissent_blocks_commit_until_reconciled(command_handler, audit_trail):
    decision_id = "dd-conflict-1"

    await command_handler.on_metric_proposed({
        "decision_id": decision_id, "metric_name": "kdn_limit_check", "value": "WITHIN_LIMIT",
        "idempotency_key": "k-1", "proposed_by": "planner", "occurred_at": "t0",
    })
    await command_handler.on_debate_outcome({
        "decision_id": decision_id, "metric_name": "kdn_limit_check", "consensus_value": "WITHIN_LIMIT",
        "dissent_refs": ["agent-2-disagrees"], "occurred_at": "t1",
    })

    events = await audit_trail.read_range(decision_id)
    assert not any(e["event_type"] == "MetricCommitted" for e in events), \
        "dissent present -> must not auto-commit before reconciliation"

    await command_handler.on_reconciled_decision({
        "decision_id": decision_id, "metric_name": "kdn_limit_check", "final_value": "BORDERLINE",
        "resolution_method": "additional_evidence", "evidence_refs": ["ev-followup"],
        "idempotency_key": "k-1-reconciled", "proposed_by": "reconciliation", "occurred_at": "t2",
    })

    events = await audit_trail.read_range(decision_id)
    committed = [e for e in events if e["event_type"] == "MetricCommitted"]
    assert len(committed) == 1
    assert committed[0]["value"] == "BORDERLINE"



