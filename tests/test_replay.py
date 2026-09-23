
"""Deterministic state reconstruction (design_principles): rebuilding the
Scoreboard from the same event log twice must produce identical state,
except for the rebuilt_at timestamp itself."""
from __future__ import annotations

import pytest

from application.command_handler import UpdateMetricCommand

@pytest.mark.asyncio
async def test_replay_is_deterministic(command_handler, projector):
    decision_id = "dd-replay-1"
    await command_handler.handle_update_metric(UpdateMetricCommand(
        decision_id=decision_id, metric_name="dsti", value=0.8,
        idempotency_key="k-1", evidence_refs=["e1"], proposed_by="planner", runtime_context={},
    ))
    await command_handler.handle_update_metric(UpdateMetricCommand(
        decision_id=decision_id, metric_name="kdn", value=0.75,
        idempotency_key="k-2", evidence_refs=["e2"], proposed_by="planner", runtime_context={},
    ))

    required = ["dsti", "kdn"]
    first = await projector.rebuild(decision_id, required)
    second = await projector.rebuild(decision_id, required)

    assert first.trust_score == second.trust_score
    assert first.policy_verdict == second.policy_verdict
    assert first.merkle_root_ref == second.merkle_root_ref
    assert {k: v.value for k, v in first.metrics.items()} == {k: v.value for k, v in second.metrics.items()}
    assert first.rebuild_seq == second.rebuild_seq  # same number of events replayed both times




