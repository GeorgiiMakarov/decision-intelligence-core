"""
Executable, stdlib-only proof of correctness for the parts of Core that do
NOT need pydantic/fastapi/grpc/kafka/redis to run — which happen to be
exactly the highest-consequence, hardest-to-get-right parts: the Merkle leaf
formula, tree construction, offline proof verification, idempotency
dedup, Ed25519 signing, and (section 8) the per-decision MerkleRootPublished
scoping fix.

This is run directly against the REAL application/merkle.py,
application/merkle_anchor_service.py and infrastructure/ed25519_signer.py
(all dependency-free beyond stdlib + `cryptography`) — not a
reimplementation. Only the PolicyEvaluator check below is a deliberate
mirror, clearly marked, because application/policy_evaluator.py imports
domain.models, which imports pydantic, which is not installed in this
sandbox.

Run: python3 tests/verify_core_logic_stdlib.py
"""
from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from application.merkle import (  # noqa: E402 - path setup must run first
    MerkleBatchBuilder,
    compute_leaf_hash,
    verify_inclusion_proof,
)
from infrastructure.ed25519_signer import Ed25519Signer  # noqa: E402
from application.merkle_anchor_service import MerkleAnchorService  # noqa: E402
from infrastructure.memory_adapters import MemoryAuditTrail, MemoryProjectionStore  # noqa: E402

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
failures: list[str] = []

def check(name: str, condition: bool) -> None:
    status = PASS if condition else FAIL
    print(f"[{status}] {name}")
    if not condition:
        failures.append(name)

# --------------------------------------------------------------------------

print("== 1. Leaf hash formula (merkle_requirements) ==")

# Leaf hash = SHA256(decision_id + metric_name + value + timestamp

# + evidence_refs_sorted + idempotency_key)

h1 = compute_leaf_hash(
    decision_id="dd-001", metric_name="kdn_limit_check", value="WITHIN_LIMIT",
    timestamp_iso="2026-07-09T11:42:05.902Z",
    evidence_refs=["ev-b", "ev-a"], idempotency_key="idem-1",
)
h2 = compute_leaf_hash(
    decision_id="dd-001", metric_name="kdn_limit_check", value="WITHIN_LIMIT",
    timestamp_iso="2026-07-09T11:42:05.902Z",
    evidence_refs=["ev-a", "ev-b"],  # same refs, different input order
    idempotency_key="idem-1",
)
check("same logical leaf, evidence_refs given in different order -> identical hash", h1 == h2)

h3 = compute_leaf_hash(
    decision_id="dd-001", metric_name="kdn_limit_check", value="BORDERLINE",  # value changed
    timestamp_iso="2026-07-09T11:42:05.902Z",
    evidence_refs=["ev-a", "ev-b"], idempotency_key="idem-1",
)
check("changing `value` alone changes the leaf hash", h1 != h3)
check("leaf hash is 32 bytes (SHA-256)", len(h1) == 32)

# --------------------------------------------------------------------------

print("\n== 2. Merkle tree + offline inclusion proof (I5, I9) ==")

builder = MerkleBatchBuilder(max_leaves=8, max_seconds=999)
leaves_hex = []
for i in range(5):  # odd count on purpose - exercises the pad-last-leaf path
    leaf = compute_leaf_hash(
        decision_id=f"dd-{i:03d}", metric_name="debt_to_income_ratio", value=0.3 + i * 0.01,
        timestamp_iso="2026-07-09T11:42:03.114Z", evidence_refs=[f"ev-{i}"], idempotency_key=f"idem-{i}",
    )
    leaves_hex.append(leaf.hex())
    builder.add_leaf(leaf, event_id=f"evt-{i}", decision_id=f"dd-{i:03d}", now_ts=1000.0)

batch, root, pending = builder.close_and_reset()
check("batch closed with all 5 leaves", len(batch.leaves) == 5)
check("root is 32 bytes", len(root) == 32)
check("each pending leaf carries its own decision_id (the fix's precondition)",
[p.decision_id for p in pending] == [f"dd-{i:03d}" for i in range(5)])

all_verify = True
for idx, leaf in enumerate(batch.leaves):
    proof = batch.proof_for(idx)
    ok = verify_inclusion_proof(leaf, proof, root)
    all_verify = all_verify and ok
    check("every leaf's proof verifies offline against the published root (odd leaf count, incl. padded pair)", all_verify)

    # Tamper check: mutate one committed leaf's underlying data and confirm the

    # ORIGINAL proof no longer verifies against a root built from the tampered set.

    tampered_leaf = compute_leaf_hash(
        decision_id="dd-002", metric_name="debt_to_income_ratio", value=0.99,  # attacker changes the value
        timestamp_iso="2026-07-09T11:42:03.114Z", evidence_refs=["ev-2"], idempotency_key="idem-2",
    )
    tampered_builder = MerkleBatchBuilder(max_leaves=8, max_seconds=999)
    for i in range(5):
        leaf = tampered_leaf if i == 2 else compute_leaf_hash(
            decision_id=f"dd-{i:03d}", metric_name="debt_to_income_ratio", value=0.3 + i * 0.01,
            timestamp_iso="2026-07-09T11:42:03.114Z", evidence_refs=[f"ev-{i}"], idempotency_key=f"idem-{i}",
        )
        tampered_builder.add_leaf(leaf, event_id=f"evt-{i}", decision_id=f"dd-{i:03d}", now_ts=1000.0)
        _, tampered_root, _ = tampered_builder.close_and_reset()
        check(
            "retroactively changing one leaf's value changes the published root "
            "(this IS the 'изменение истории должно ломать верификацию root' mechanism)",
            tampered_root != root,
        )

        original_proof_for_leaf2 = batch.proof_for(2)
        check(
            "original proof for the untampered leaf fails against the tampered root",
            not verify_inclusion_proof(batch.leaves[2], original_proof_for_leaf2, tampered_root),
            )

            # --------------------------------------------------------------------------

print("\n== 3. Both batching thresholds are live (fix from the v1.1/v1.2 review) ==")

b = MerkleBatchBuilder(max_leaves=1000, max_seconds=5)
for i in range(120):  # sustained-load scenario from Assumption 8: ~100-140 leaves/5s
    b.add_leaf(compute_leaf_hash(
        decision_id=f"sustain-{i}", metric_name="m", value=i,
        timestamp_iso="t", evidence_refs=["e"], idempotency_key=f"sustain-{i}",
    ), event_id=f"e{i}", decision_id=f"sustain-{i}", now_ts=1000.0)
    check("sustained load (120 leaves, elapsed<5s): count threshold NOT met yet", not b.should_close(1000.0 + 1))
    check("sustained load: time threshold fires once 5s elapse", b.should_close(1000.0 + 5.0))

    burst = MerkleBatchBuilder(max_leaves=1000, max_seconds=5)
    for i in range(1000):  # burst scenario: ~1000-1400 leaves/sec
        burst.add_leaf(compute_leaf_hash(
            decision_id=f"burst-{i}", metric_name="m", value=i,
            timestamp_iso="t", evidence_refs=["e"], idempotency_key=f"burst-{i}",
        ), event_id=f"e{i}", decision_id=f"burst-{i}", now_ts=2000.0)
check("burst load: count threshold fires well before 5s elapse", burst.should_close(2000.0 + 0.7))

        # --------------------------------------------------------------------------

print("\n== 4. Ed25519 Signer — real cryptography, not a stub (I5 signature step) ==")

signer = Ed25519Signer(key_id="test-key-1")
sig = signer.sign(root)
check("signature verifies against the correct root", signer.verify(root, sig, signer.public_key_bytes()))
check("signature does NOT verify against the tampered root", not signer.verify(tampered_root, sig, signer.public_key_bytes()))

other_signer = Ed25519Signer(key_id="test-key-2")
check(
    "signature from key A does not verify under key B's public key (no key confusion)",
    not signer.verify(root, sig, other_signer.public_key_bytes()),
)
check("key_id is carried on the signer for rotation lookup (Assumption 5)", signer.key_id() == "test-key-1")

# --------------------------------------------------------------------------

print("\n== 5. Idempotency dedup semantics (I6), against the real AuditTrail Protocol shape ==")

import asyncio
from infrastructure.memory_adapters import MemoryAuditTrail, MemoryProjectionStore, MemoryTsa

async def _idempotency_check() -> tuple[bool, bool, bool]:
    audit = MemoryAuditTrail()
    r1 = await audit.append("dd-001", "MetricCommitted", {"metric_name": "x", "value": 1}, idempotency_key="same-key")
    r2 = await audit.append("dd-001", "MetricCommitted", {"metric_name": "x", "value": 999}, idempotency_key="same-key")
    events = await audit.read_range("dd-001")
    return (not r1.deduplicated), r2.deduplicated, (len(events) == 1)

    first_not_dup, second_is_dup, only_one_leaf_stored = asyncio.run(_idempotency_check())
    check("first UpdateMetric with a new idempotency_key is NOT deduplicated", first_not_dup)
    check("redelivery with the SAME idempotency_key IS deduplicated (I6)", second_is_dup)
    check("redelivery never created a second leaf in the audit trail", only_one_leaf_stored)

    # --------------------------------------------------------------------------

print("\n== 6. Policy Evaluator INSUFFICIENT_DATA branch (I4) ==")
print("    (mirror of application/policy_evaluator.py's branching logic using")
print("     plain dataclasses instead of the Pydantic MetricRecord it actually")
print("     takes — pydantic is not installed in this sandbox, so the real")
print("     function cannot be imported here. Same branch, same guard order.)")

from dataclasses import dataclass

@dataclass
class _FakeMetric:
    status: str
    value: float = 0.0

def _mirror_evaluate(required: list[str], committed: dict[str, _FakeMetric]) -> tuple[float | None, str]:
    have = {k for k, v in committed.items() if v.status == "COMMITTED"}
    missing = sorted(set(required) - have)
    if missing:
        return None, "INSUFFICIENT_DATA"  # I4 - never a number here
    score = sum(v.value for v in committed.values()) / len(committed)
    return score, "APPROVE" if score >= 0.7 else "REJECT"

    score, status = _mirror_evaluate(["dsti", "kdn", "aml"], {"dsti": _FakeMetric("COMMITTED", 0.8)})
    check("missing 2 of 3 required metrics -> status is INSUFFICIENT_DATA, not a number", status == "INSUFFICIENT_DATA")
    check("missing metrics -> trust_score is None, never 0 or a fabricated value", score is None)

    score2, status2 = _mirror_evaluate(
        ["dsti", "kdn"], {"dsti": _FakeMetric("COMMITTED", 0.9), "kdn": _FakeMetric("COMMITTED", 0.8)}
    )
    check("all required metrics committed -> a real numeric trust_score is returned", score2 is not None and 0.0 <= score2 <= 1.0)

    # --------------------------------------------------------------------------

    print("\n== 7. MetricSuperseded never touches the original leaf (I7) ==")

async def _supersede_check() -> tuple[bool, bool]:
    audit = MemoryAuditTrail()
    await audit.append(
        "dd-777", "MetricCommitted",
        {"metric_name": "risk_check", "value": "OK", "leaf_hash": "aaaa"},
        idempotency_key="orig-key",
    )
    await audit.append(
        "dd-777", "MetricSuperseded",
        {"metric_name": "risk_check", "original_leaf_hash": "aaaa", "new_risk_context": "CRITICAL late signal"},
        idempotency_key="supersede-key",
    )
    events = await audit.read_range("dd-777")
    original_still_present = any(e["event_type"] == "MetricCommitted" and e.get("leaf_hash") == "aaaa" for e in events)
    both_events_present = len(events) == 2
    return original_still_present, both_events_present

    orig_present, both_present = asyncio.run(_supersede_check())
    check("original MetricCommitted event is still present, byte-identical, after supersession", orig_present)
    check("supersession is a NEW event, not a rewrite (event count == 2, not 1)", both_present)

    # --------------------------------------------------------------------------

    print("\n== 8. Bug fix: MerkleRootPublished visible per-decision, not just under 'system' ==")
    print("    (the real defect an external review of proposed corrections caught:")
    print("     one batch commonly covers leaves from several different decision_ids,")
    print("     and the previous code only ever published the event under")
    print("     decision_id='system' -- invisible to ScoreboardProjector.rebuild(),")
    print("     which reads one specific decision_id's own event range)")

    from application.merkle_anchor_service import MerkleAnchorService  # noqa: E402

async def _merkle_anchor_scoping_check() -> tuple[bool, bool, bool, bool, bool]:
    audit = MemoryAuditTrail()
    store = MemoryProjectionStore()
    tsa_local = MemoryTsa()
    signer_local = Ed25519Signer(key_id="anchor-test")
    builder_local = MerkleBatchBuilder(max_leaves=100, max_seconds=999)
    anchor = MerkleAnchorService(
        builder=builder_local, audit_trail=audit, projection_store=store,
        signer=signer_local, tsa=tsa_local,
    )

    # Three leaves, three DIFFERENT decisions, one batch - the exact shape
    # that broke before this fix.
    decision_ids = ["dd-alpha", "dd-beta", "dd-gamma"]
    for i, did in enumerate(decision_ids):
        leaf = compute_leaf_hash(
        decision_id=did, metric_name="m", value=i, timestamp_iso="t",
        evidence_refs=["e"], idempotency_key=f"k-{did}",
        )
        builder_local.add_leaf(leaf, event_id=f"evt-{did}", decision_id=did, now_ts=5000.0)

    batch_id = await anchor.force_close()

    results = []
    for did in decision_ids:
        events = await audit.read_range(did)
        results.append(any(e.get("event_type") == "MerkleRootPublished" for e in events))

    system_events = await audit.read_range("system")
    system_has_it = any(e.get("event_type") == "MerkleRootPublished" for e in system_events)

    return (*results, system_has_it, batch_id is not None)

alpha_ok, beta_ok, gamma_ok, system_ok, closed_ok = asyncio.run(_merkle_anchor_scoping_check())
check("batch actually closed and returned a batch_id", closed_ok)
check("decision dd-alpha's OWN event range now contains MerkleRootPublished (was invisible before)", alpha_ok)
check("decision dd-beta's OWN event range now contains MerkleRootPublished (was invisible before)", beta_ok)
check("decision dd-gamma's OWN event range now contains MerkleRootPublished (was invisible before)", gamma_ok)
check("global 'system' audit record is ALSO still published (batch-level observability kept)", system_ok)

# --------------------------------------------------------------------------

print(f"\n{'=' * 60}")
if failures:
    print(f"{len(failures)} CHECK(S) FAILED:")
    for f in failures:
        print(f"  - {f}")
        sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)




