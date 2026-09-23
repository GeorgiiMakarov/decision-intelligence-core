
"""Pytest-style mirror of the checks already proven in
tests/verify_core_logic_stdlib.py, expressed as real pytest cases for CI.
See that script for the executed proof; this file is what `make test` runs
once pytest is installed (docker-compose / CI)."""
from __future__ import annotations

import pytest

from application.merkle import MerkleBatchBuilder, compute_leaf_hash, verify_inclusion_proof
from application.merkle_anchor_service import MerkleAnchorService
from infrastructure.ed25519_signer import Ed25519Signer
from infrastructure.memory_adapters import MemoryAuditTrail, MemoryProjectionStore, MemoryTsa

def test_leaf_hash_ignores_evidence_refs_order():
    a = compute_leaf_hash(decision_id="d1", metric_name="m", value=1, timestamp_iso="t",
    evidence_refs=["b", "a"], idempotency_key="k")
    b = compute_leaf_hash(decision_id="d1", metric_name="m", value=1, timestamp_iso="t",
    evidence_refs=["a", "b"], idempotency_key="k")
    assert a == b

def test_leaf_hash_changes_with_value():
    a = compute_leaf_hash(decision_id="d1", metric_name="m", value=1, timestamp_iso="t",
    evidence_refs=["a"], idempotency_key="k")
    b = compute_leaf_hash(decision_id="d1", metric_name="m", value=2, timestamp_iso="t",
    evidence_refs=["a"], idempotency_key="k")
    assert a != b

def test_odd_leaf_count_all_proofs_verify():
    builder = MerkleBatchBuilder(max_leaves=100, max_seconds=999)
    for i in range(7):
        builder.add_leaf(compute_leaf_hash(decision_id=f"d{i}", metric_name="m", value=i,
            timestamp_iso="t", evidence_refs=["e"], idempotency_key=f"k{i}"),
        event_id=f"e{i}", decision_id=f"d{i}", now_ts=0.0)
        batch, root, _ = builder.close_and_reset()
        for idx, leaf in enumerate(batch.leaves):
            assert verify_inclusion_proof(leaf, batch.proof_for(idx), root)

def test_tampered_leaf_breaks_root():
    def build(values):
        b = MerkleBatchBuilder(max_leaves=100, max_seconds=999)
        for i, v in enumerate(values):
            b.add_leaf(compute_leaf_hash(decision_id=f"d{i}", metric_name="m", value=v,
            timestamp_iso="t", evidence_refs=["e"], idempotency_key=f"k{i}"),
            event_id=f"e{i}", decision_id=f"d{i}", now_ts=0.0)
        _, root, _ = b.close_and_reset()
        return root

    original_root = build([1, 2, 3, 4])
    tampered_root = build([1, 2, 999, 4])
    assert original_root != tampered_root

def test_should_close_on_leaf_count():
    b = MerkleBatchBuilder(max_leaves=2, max_seconds=9999)
    b.add_leaf(b"x" * 32, "e1", "d1", now_ts=0.0)
    assert not b.should_close(0.1)
    b.add_leaf(b"y" * 32, "e2", "d2", now_ts=0.1)
    assert b.should_close(0.2)

def test_should_close_on_elapsed_time():
    b = MerkleBatchBuilder(max_leaves=1000, max_seconds=5)
    b.add_leaf(b"x" * 32, "e1", "d1", now_ts=100.0)
    assert not b.should_close(103.0)
    assert b.should_close(105.0)

def test_empty_batch_never_closes():
    b = MerkleBatchBuilder(max_leaves=1, max_seconds=0.001)
    assert not b.should_close(1_000_000.0)
    assert not b.has_pending()

def test_pending_leaves_carry_their_own_decision_id():
    b = MerkleBatchBuilder(max_leaves=100, max_seconds=999)
    b.add_leaf(compute_leaf_hash(decision_id="d1", metric_name="m", value=1, timestamp_iso="t",
        evidence_refs=["e"], idempotency_key="k1"),
    event_id="e1", decision_id="d1", now_ts=0.0)
    b.add_leaf(compute_leaf_hash(decision_id="d2", metric_name="m", value=2, timestamp_iso="t",
        evidence_refs=["e"], idempotency_key="k2"),
    event_id="e2", decision_id="d2", now_ts=0.0)
    _, _, pending = b.close_and_reset()
    assert [p.decision_id for p in pending] == ["d1", "d2"]

@pytest.mark.asyncio
async def test_merkle_root_published_visible_from_each_decisions_own_event_range():
    """Regression test for the scoping bug: a batch covering leaves from
several decision_ids must publish MerkleRootPublished under EACH of
them, not only under 'system' — otherwise ScoreboardProjector.rebuild()
(scoped to one decision_id) can never see it and merkle_root_ref stays
None forever."""
    audit = MemoryAuditTrail()
    store = MemoryProjectionStore()
    builder = MerkleBatchBuilder(max_leaves=100, max_seconds=999)
    anchor = MerkleAnchorService(
        builder=builder, audit_trail=audit, projection_store=store,
        signer=Ed25519Signer(key_id="t"), tsa=MemoryTsa(),
    )

    for did in ("dd-alpha", "dd-beta"):
        leaf = compute_leaf_hash(decision_id=did, metric_name="m", value=1,
        timestamp_iso="t", evidence_refs=["e"], idempotency_key=f"k-{did}")
        builder.add_leaf(leaf, event_id=f"evt-{did}", decision_id=did, now_ts=0.0)

    await anchor.force_close()

    for did in ("dd-alpha", "dd-beta"):
        events = await audit.read_range(did)
        assert any(e.get("event_type") == "MerkleRootPublished" for e in events), (
            f"{did} cannot see its own MerkleRootPublished event"
        )




