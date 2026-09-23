
"""Completion Criteria — decides when a decision_id is ready to emit
DecisionReady to Goal Loop. Deliberately tiny and separate from
PolicyEvaluator: 'ready to publish a verdict' (this module) and 'what the
verdict is' (policy_evaluator.py) are different questions, per the 7-component
list in functional_requirements treating them as distinct components."""
from __future__ import annotations

from domain.enums import MetricStatus

def is_ready_to_publish(required_metrics: list[str], statuses: dict[str, MetricStatus]) -> bool:
    """True once every required metric has reached a TERMINAL status
(COMMITTED, REJECTED or SUPERSEDED) — i.e. nothing is still in flight.
This is intentionally weaker than 'all COMMITTED': a profile whose Policy
Evaluator can tolerate some REJECTED metrics (partial commits, I10) can
still publish. A profile that requires all-COMMITTED (Construction
Profile, section 4.3) enforces that separately in ITS OWN policy
configuration, not here — see the v1.1 review note on I10 vs
Construction Profile.

Takes `dict[str, MetricStatus]` rather than `dict[str, MetricRecord]` on
purpose: this makes the function usable from BOTH sides of the CQRS
boundary — the write side (CommandHandler, working from its own staging
state) and the read side (ScoreboardProjector, working from
ScoreboardMetricView) — without depending on either one's specific model
type.
"""
    terminal = {MetricStatus.COMMITTED, MetricStatus.REJECTED, MetricStatus.SUPERSEDED}
    for name in required_metrics:
        status = statuses.get(name)
        if status is None or status not in terminal:
            return False
    return True




