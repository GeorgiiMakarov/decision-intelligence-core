
"""Enumerations shared across the Core domain. Spec v1.2, section 1."""
from __future__ import annotations
from enum import Enum

class MetricStatus(str, Enum):
    """Lifecycle stage of a metric, section 1.6."""
    PROPOSED = "PROPOSED"
    DEBATED = "DEBATED"
    CRITIQUED = "CRITIQUED"
    RECONCILED = "RECONCILED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"

class UpdateMetricStatus(str, Enum):
    """Synchronous response status for the UpdateMetric command."""
    ACCEPTED = "ACCEPTED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    REJECTED_MISSING_EVIDENCE = "REJECTED_MISSING_EVIDENCE"

class DecisionStage(str, Enum):
    PROPOSED = "PROPOSED"
    DEBATING = "DEBATING"
    RECONCILING = "RECONCILING"
    READY = "READY"
    REJECTED = "REJECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ABANDONED = "ABANDONED"

class PolicyVerdict(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class RiskSeverityCategory(str, Enum):
    DATA_FRESHNESS = "DATA_FRESHNESS"
    CONTRADICTION = "CONTRADICTION"
    CRITICAL = "CRITICAL"
    POLICY_BREACH = "POLICY_BREACH"

class ProofPosition(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"




