
"""I6 end-to-end through CommandHandler.handle_update_metric, not just at
the AuditTrail layer (see tests/verify_core_logic_stdlib.py section 5 for
the lower-level version of this check)."""
from __future__ import annotations

import pytest

from application.command_handler import UpdateMetricCommand
from domain.enums import UpdateMetricStatus

@pytest.mark.asyncio
async def test_redelivered_update_metric_is_deduplicated(command_handler, audit_trail):
    cmd = UpdateMetricCommand(
        decision_id="dd-idem-1", metric_name="aml_check", value="CLEAR",
        idempotency_key="k-fixed", evidence_refs=["ev-1"], proposed_by="planner", runtime_context={},
    )
    first = await command_handler.handle_update_metric(cmd)
    second = await command_handler.handle_update_metric(cmd)  # exact redelivery

    assert first.status == UpdateMetricStatus.ACCEPTED
    assert second.status == UpdateMetricStatus.DUPLICATE_IGNORED

    events = await audit_trail.read_range("dd-idem-1")
    committed = [e for e in events if e["event_type"] == "MetricCommitted"]
    assert len(committed) == 1, "I6: redelivery must never create a second leaf"

@pytest.mark.asyncio
async def test_missing_evidence_is_rejected_not_committed(command_handler, audit_trail):
    cmd = UpdateMetricCommand(
        decision_id="dd-idem-2", metric_name="aml_check", value="CLEAR",
        idempotency_key="k-no-evidence", evidence_refs=[], proposed_by="planner", runtime_context={},
    )
    result = await command_handler.handle_update_metric(cmd)
    assert result.status == UpdateMetricStatus.REJECTED_MISSING_EVIDENCE

    events = await audit_trail.read_range("dd-idem-2")
    assert not any(e["event_type"] == "MetricCommitted" for e in events)
    assert any(e["event_type"] == "MetricRejected" and e["reason"] == "MISSING_EVIDENCE" for e in events)




