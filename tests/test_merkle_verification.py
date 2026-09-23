
"""GetMerkleProof's payload must be verifiable completely offline (I9) -
this test constructs the proof through the real anchoring path
(CommandHandler -> MerkleAnchorService -> ProjectionStore) and then verifies
it using ONLY application.merkle.verify_inclusion_proof, with no further
calls into audit_trail / projection_store / command_handler."""
from __future__ import annotations

import pytest

from application.command_handler import UpdateMetricCommand
from application.merkle import ProofStep, verify_inclusion_proof

@pytest.mark.asyncio
async def test_proof_verifies_fully_offline(command_handler, merkle_anchor, projection_store):
    result = await command_handler.handle_update_metric(UpdateMetricCommand(
        decision_id="dd-offline-1", metric_name="dsti", value=0.42,
        idempotency_key="k-offline", evidence_refs=["ev-1"], proposed_by="planner", runtime_context={},
    ))
    await merkle_anchor.force_close()

    proof_row = await projection_store.get(f"merkle_proof:{result.leaf_hash}")
    assert proof_row is not None

    # From here on, only stdlib bytes.fromhex + verify_inclusion_proof are used -
    # simulating exactly what an external verifier (a regulator) would do with
    # nothing but the JSON GetMerkleProof already returned.
    leaf_hash = bytes.fromhex(proof_row["leaf_hash"])
    root = bytes.fromhex(proof_row["root"])
    steps = [ProofStep(sibling_hash=bytes.fromhex(n["hash"]), position=n["position"]) for n in proof_row["proof_path"]]

    assert verify_inclusion_proof(leaf_hash, steps, root)

@pytest.mark.asyncio
async def test_single_leaf_batch_has_empty_proof_path_and_still_verifies(command_handler, merkle_anchor, projection_store):
    result = await command_handler.handle_update_metric(UpdateMetricCommand(
        decision_id="dd-offline-2", metric_name="solo_metric", value=1,
        idempotency_key="k-solo", evidence_refs=["ev-1"], proposed_by="planner", runtime_context={},
    ))
    await merkle_anchor.force_close()
    proof_row = await projection_store.get(f"merkle_proof:{result.leaf_hash}")

    assert proof_row["proof_path"] == []
    assert proof_row["root"] == proof_row["leaf_hash"], "single-leaf batch: root IS the leaf"




