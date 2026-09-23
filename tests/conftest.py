
"""Shared pytest fixtures. All integration tests run against the in-memory
adapters (infrastructure/memory_adapters.py) — see that module's docstring
for why this is the correct way to test application logic, not a
workaround."""
from __future__ import annotations

import pytest

from application.command_handler import CommandHandler
from application.merkle import MerkleBatchBuilder
from application.merkle_anchor_service import MerkleAnchorService
from application.scoreboard_projector import ScoreboardProjector
from infrastructure.ed25519_signer import Ed25519Signer
from infrastructure.memory_adapters import MemoryAuditTrail, MemoryEventBus, MemoryProjectionStore, MemoryTsa

@pytest.fixture
def audit_trail() -> MemoryAuditTrail:
    return MemoryAuditTrail()

@pytest.fixture
def projection_store() -> MemoryProjectionStore:
    return MemoryProjectionStore()

@pytest.fixture
def event_bus() -> MemoryEventBus:
    return MemoryEventBus()

@pytest.fixture
def signer() -> Ed25519Signer:
    return Ed25519Signer(key_id="test")

@pytest.fixture
def tsa() -> MemoryTsa:
    return MemoryTsa()

@pytest.fixture
def merkle_builder() -> MerkleBatchBuilder:
    # small thresholds so tests can force a close deterministically
    return MerkleBatchBuilder(max_leaves=3, max_seconds=9999)

@pytest.fixture
def command_handler(audit_trail, event_bus, merkle_builder, signer, tsa) -> CommandHandler:
    return CommandHandler(audit_trail=audit_trail, event_bus=event_bus, merkle_builder=merkle_builder, signer=signer, tsa=tsa)

@pytest.fixture
def merkle_anchor(merkle_builder, audit_trail, projection_store, signer, tsa) -> MerkleAnchorService:
    return MerkleAnchorService(builder=merkle_builder, audit_trail=audit_trail, projection_store=projection_store, signer=signer, tsa=tsa)

@pytest.fixture
def projector(audit_trail, projection_store) -> ScoreboardProjector:
    return ScoreboardProjector(audit_trail=audit_trail, projection_store=projection_store)




