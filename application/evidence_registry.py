
"""
Evidence Registry — one of the 8 named components. Reconstructs known
evidence for a decision from EvidenceAttached events (Assumption 3: RAG is
async — evidence can arrive before or after the metric that will cite it).

`all_present()` is provided but NOT YET wired into command_handler's I3
check (see README 'Known gaps') — today I3 only verifies evidence_refs is
non-empty, not that every referenced evidence_id resolves to a real,
registered EvidenceRecord. Wiring that in is a real strengthening of I3,
left as a deliberate, flagged next step rather than bolted on without being
able to re-run the executed verification against it in this sandbox.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from domain.models import EvidenceRecord

def reconstruct(decision_id: str, events: list[dict[str, Any]]) -> dict[str, EvidenceRecord]:
    registry: dict[str, EvidenceRecord] = {}
    for evt in events:
        if evt.get("event_type") != "EvidenceAttached":
            continue
    registry[evt["evidence_id"]] = EvidenceRecord(
        evidence_id=evt["evidence_id"],
        decision_id=decision_id,
        source_type=evt["source_type"],
        content_hash=evt["content_hash"],
        storage_ref=evt["storage_ref"],
        fetched_at=_parse(evt["fetched_at"]),
    )
    return registry

def all_present(evidence_refs: list[str], known: dict[str, EvidenceRecord]) -> bool:
    """Stricter reading of I3: not just non-empty, but every ref resolvable.
See module docstring — not yet called from command_handler.py."""
    return all(ref in known for ref in evidence_refs)

def _parse(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(value)




