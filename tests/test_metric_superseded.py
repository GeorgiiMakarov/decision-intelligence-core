"""Scenario 3 from the v1.1 spec review: a CRITICAL RiskSignal arrives AFTER
a metric is already COMMITTED and anchored. I7 forbids rewriting the
original leaf; MetricSuperseded is the compensating, append-only 'rollback'."""
from __future__ import annotations

import pytest

from application.command_handler import UpdateMetricCommand
from domain.enums import MetricStatus

@pytest.mark.asyncio
async def test_supersede_does_not_rewrite_original_leaf(command_handler, merkle_anchor, audit_trail, projector):
    decision_id = "dd-supersede-1"

    cmd_result = await command_handler.handle_update_metric(
        UpdateMetricCommand(
        decision_id=decision_id, metric_name="risk_check", value="OK",
        idempotency_key="k-orig", evidence_refs=["ev-1"], proposed_by="critic",
        runtime_context={},
        )
    )
    await merkle_anchor.force_close()
    original_leaf = cmd_result.leaf_hash
    assert original_leaf is not None

    root_before = (await projector.rebuild(decision_id, ["risk_check"])).merkle_root_ref

    # A delayed CRITICAL signal shows up after the commit + anchor above.
    await command_handler.supersede_metric(
        decision_id=decision_id, metric_name="risk_check", original_leaf_hash=original_leaf,
        new_risk_context="CRITICAL: contradicts earlier RAG evidence", superseding_idempotency_key="k-supersede",
    )

    events = await audit_trail.read_range(decision_id)
    committed_events = [e for e in events if e["event_type"] == "MetricCommitted"]
    assert len(committed_events) == 1
    assert committed_events[0]["leaf_hash"] == original_leaf, "I7: original leaf must be byte-identical, untouched"

    sb = await projector.rebuild(decision_id, ["risk_check"])
    assert sb.metrics["risk_check"].status == MetricStatus.SUPERSEDED
    assert sb.merkle_root_ref == root_before, "supersession must not retroactively change the already-published root"




