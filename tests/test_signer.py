
from __future__ import annotations

from infrastructure.ed25519_signer import Ed25519Signer

def test_sign_verify_roundtrip():
    signer = Ed25519Signer(key_id="k1")
    payload = b"merkle-root-bytes"
    sig = signer.sign(payload)
    assert signer.verify(payload, sig, signer.public_key_bytes())

def test_verify_fails_for_wrong_payload():
    signer = Ed25519Signer(key_id="k1")
    sig = signer.sign(b"root-A")
    assert not signer.verify(b"root-B", sig, signer.public_key_bytes())

def test_verify_fails_for_wrong_key():
    a, b = Ed25519Signer(key_id="a"), Ed25519Signer(key_id="b")
    sig = a.sign(b"payload")
    assert not b.verify(b"payload", sig, b.public_key_bytes())

def test_key_id_survives_for_rotation_lookup():
    signer = Ed25519Signer(key_id="kz-banking-v7")
    assert signer.key_id() == "kz-banking-v7"




