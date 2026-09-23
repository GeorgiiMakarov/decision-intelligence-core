
"""
Metrics Registry — one of the 8 named components in functional_requirements.
Previously this reconstruction logic lived inline inside
scoreboard_projector.py; factored out here so Metrics Registry is an actual
addressable component, not folded into the projector (avoids the
'не упрощай архитектуру' trap of merging named components together).

Pure function of the AuditTrail event stream -> dict[metric_name,
MetricRecord]. No I/O of its own: scoreboard_projector.py fetches events via
AuditTrail.read_range() and passes them in here.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from domain.enums import MetricStatus
from domain.models import MetricRecord

def reconstruct(decision_id: str, events: list[dict[str, Any]]) -> dict[str, MetricRecord]:
    metrics: dict[str, MetricRecord] = {}
    for evt in events:
        etype = evt.get("event_type")
        if etype == "MetricCommitted":
            metrics[evt["metric_name"]] = MetricRecord(
                decision_id=decision_id,
                metric_name=evt["metric_name"],
                value=evt["value"],
                proposed_by=evt.get("proposed_by", "unknown"),
                idempotency_key=evt["idempotency_key"],
                evidence_refs=evt["evidence_refs"],
                status=MetricStatus.COMMITTED,
                created_at=_parse(evt["committed_at"]),
                leaf_hash=evt["leaf_hash"],
            )
        elif etype == "MetricRejected":
            if evt["metric_name"] not in metrics:
                metrics[evt["metric_name"]] = MetricRecord(
                    decision_id=decision_id,
                    metric_name=evt["metric_name"],
                    value=None,
                    proposed_by="unknown",
                    idempotency_key=evt["idempotency_key"],
                    evidence_refs=[],
                    status=MetricStatus.REJECTED,
                    created_at=_parse(evt["occurred_at"]),
                )
        elif etype == "MetricSuperseded":
            target = evt["metric_name"]
            if target in metrics:
                # I7: the original record's leaf_hash/created_at/value are
                # untouched — only status + superseded_by change, and this
                # produces a NEW MetricRecord instance, it does not edit the
                # one from the MetricCommitted branch above in place.
                metrics[target] = metrics[target].model_copy(
                    update={
                    "status": MetricStatus.SUPERSEDED,
                    "superseded_by": evt["superseded_by_idempotency_key"],
                    }
                )
                return metrics
    return metrics


def _parse(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(value)




