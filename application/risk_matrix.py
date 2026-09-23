
"""
Risk Matrix — one of the 8 named components. Section 1.2 Bounded Context /
Design Decision (carried from the v1.1/v1.2 review): Risk Matrix is a STORE
populated by Critic's RiskSignal events; it never generates risk signals
itself, only accumulates and exposes them for Policy Evaluator.
"""
from __future__ import annotations

from typing import Any

from domain.models import RiskSignalEntry

def reconstruct(decision_id: str, events: list[dict[str, Any]]) -> list[RiskSignalEntry]:
    signals: list[RiskSignalEntry] = []
    for evt in events:
        if evt.get("event_type") != "RiskSignal":
            continue
        signals.append(
            RiskSignalEntry(
                decision_id=decision_id,
                metric_name=evt["metric_name"],
                category=evt.get("risk_level", "UNKNOWN"),
                severity=evt.get("severity", 0.0),
                status="ACTIVE",
                contradiction_flags=evt.get("contradiction_flags", []),
            )
        )
    return signals

def active_only(signals: list[RiskSignalEntry]) -> list[RiskSignalEntry]:
    return [s for s in signals if s.status == "ACTIVE"]

def has_critical(signals: list[RiskSignalEntry]) -> bool:
    return any(s.category == "CRITICAL" and s.status == "ACTIVE" for s in signals)




