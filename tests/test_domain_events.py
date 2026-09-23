"""Regression test for domain.events.

The reconstruction left the `InboundEvent` union (and its comment) indented
inside the `RuntimeConfigUpdated` class body, so `import domain.events`
raised `NameError: name 'RuntimeConfigUpdated' is not defined`. Nothing in
the codebase imported the module, which is why pytest stayed green while
the module was unusable. This test is the import gate.
"""
from __future__ import annotations

import typing

import domain.events as events


EXPECTED_MEMBERS = {
    "MetricProposed",
    "DebateOutcome",
    "RiskSignal",
    "ReconciledDecision",
    "EvidenceAttached",
    "GoalCreated",
    "GoalCancelled",
    "RuntimeArtifactDeployed",
    "RuntimeConfigUpdated",
}


def test_domain_events_imports() -> None:
    assert events.InboundEvent is not None


def test_inbound_event_union_members() -> None:
    args = typing.get_args(events.InboundEvent)
    assert {a.__name__ for a in args} == EXPECTED_MEMBERS
