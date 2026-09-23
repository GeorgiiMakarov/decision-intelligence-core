"""Tests for infrastructure/rfc3161_client.py (pure stdlib + pytest).

Offline tests build synthetic RFC 3161 DER structures with the client's own
codec and serve them from a local HTTP server, so no network is needed.
One live test hits https://freetsa.org/tsr and skips (never fails) on any
network problem.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.server
import threading

import pytest

from infrastructure.rfc3161_client import (
    OID_SIGNED_DATA,
    OID_TST_INFO,
    Rfc3161TsaClient,
    TsaError,
    _HASH_OIDS,
    der_decode,
    der_decode_integer,
    der_decode_octet_string,
    der_decode_oid,
    der_explicit,
    der_generalized_time,
    der_integer,
    der_null,
    der_octet_string,
    der_oid,
    der_sequence,
    der_set,
)
from interfaces.tsa import TimestampAuthority, TsaToken

DIGEST = hashlib.sha256(b"decision-intelligence-core probe").digest()
NONCE = 123456789


# ---------------------------------------------------------------------------
# Synthetic RFC 3161 structures (built with the client's own DER codec)
# ---------------------------------------------------------------------------

def _synthetic_tst_info(digest: bytes, nonce: int,
                        gen_time: str = "20260923000000Z") -> bytes:
    return der_sequence(
        der_integer(1),                       # version
        der_oid("1.2.3.4"),                   # policy
        der_sequence(                         # messageImprint
            der_sequence(der_oid(_HASH_OIDS["sha256"]), der_null()),
            der_octet_string(digest),
        ),
        der_integer(42),                      # serialNumber
        der_generalized_time(gen_time),       # genTime
        der_integer(nonce),                   # nonce
    )


def _synthetic_resp(status: int, tst_info_der: bytes | None = None) -> bytes:
    status_info = der_sequence(der_integer(status))
    if tst_info_der is None:
        return der_sequence(status_info)      # no token (failure responses)
    signed_data = der_sequence(
        der_integer(1),                       # version
        der_set(der_sequence(der_oid(_HASH_OIDS["sha256"]), der_null())),
        der_sequence(                         # encapContentInfo
            der_oid(OID_TST_INFO),
            der_explicit(0, der_octet_string(tst_info_der)),
        ),
        der_set(),                            # signerInfos (empty: CMS sig not verified)
    )
    content_info = der_sequence(
        der_oid(OID_SIGNED_DATA),
        der_explicit(0, signed_data),
    )
    return der_sequence(status_info, content_info)


def _token_for(resp_der: bytes) -> TsaToken:
    return TsaToken(token_bytes=resp_der, timestamp_iso="2026-09-23T00:00:00+00:00",
                    authority_id="synthetic")


# ---------------------------------------------------------------------------
# Local HTTP stub TSA (echoes request digest+nonce into a synthetic response)
# ---------------------------------------------------------------------------

class _StubHandler(http.server.BaseHTTPRequestHandler):
    mode = "ok"  # ok | wrong_nonce | wrong_digest | rejection

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler naming
        assert self.headers.get("Content-Type") == "application/timestamp-query"
        length = int(self.headers.get("Content-Length", 0))
        req_der = self.rfile.read(length)
        req = der_decode(req_der)
        mi = req.children[1]
        req_digest = der_decode_octet_string(mi.children[1])
        req_nonce = der_decode_integer(req.children[2])
        if self.mode == "rejection":
            payload = _synthetic_resp(2)
        else:
            nonce = req_nonce if self.mode == "ok" else req_nonce + 1
            digest = req_digest if self.mode != "wrong_digest" else b"\x00" * 32
            payload = _synthetic_resp(0, _synthetic_tst_info(digest, nonce))
        self.send_response(200)
        self.send_header("Content-Type", "application/timestamp-reply")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence test output
        pass


def _serve(mode: str) -> http.server.HTTPServer:
    handler = type(f"_Stub_{mode}", (_StubHandler,), {"mode": mode})
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------------------
# Offline: request building
# ---------------------------------------------------------------------------

def test_build_request_roundtrip():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    der, nonce = client.build_request(DIGEST)
    assert nonce > 0
    root = der_decode(der)
    assert root.tag_number == 0x10 and len(root.children) == 4
    assert der_decode_integer(root.children[0]) == 1            # version
    mi = root.children[1]
    assert len(mi.children) == 2
    assert der_decode_oid(mi.children[0].children[0]) == _HASH_OIDS["sha256"]
    assert der_decode_octet_string(mi.children[1]) == DIGEST
    assert der_decode_integer(root.children[2]) == nonce       # echoed nonce
    assert root.children[3].content == b"\x00"                 # certReq FALSE


def test_build_request_rejects_bad_digest_length():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    with pytest.raises(ValueError):
        client.build_request(b"too short")


def test_init_rejects_unknown_hash():
    with pytest.raises(ValueError):
        Rfc3161TsaClient("http://127.0.0.1:9/tsr", hash_name="md5")
    with pytest.raises(ValueError):
        Rfc3161TsaClient("http://127.0.0.1:9/tsr", hash_name="nope")


def test_structural_protocol_conformance():
    assert isinstance(Rfc3161TsaClient("http://127.0.0.1:9/tsr"), TimestampAuthority)


# ---------------------------------------------------------------------------
# Offline: verify() on synthetic responses (no network)
# ---------------------------------------------------------------------------

def test_verify_synthetic_granted():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    resp = _synthetic_resp(0, _synthetic_tst_info(DIGEST, NONCE))
    assert client.verify(DIGEST, _token_for(resp)) is True


def test_verify_granted_with_mods_also_true():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    resp = _synthetic_resp(1, _synthetic_tst_info(DIGEST, NONCE))
    assert client.verify(DIGEST, _token_for(resp)) is True


@pytest.mark.parametrize("status", [2, 3, 4, 5])
def test_verify_non_granted_status_false(status):
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    resp = _synthetic_resp(status)
    assert client.verify(DIGEST, _token_for(resp)) is False


def test_verify_granted_without_token_false():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    assert client.verify(DIGEST, _token_for(_synthetic_resp(0))) is False


def test_verify_wrong_digest_false():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    resp = _synthetic_resp(0, _synthetic_tst_info(DIGEST, NONCE))
    assert client.verify(b"\xff" * 32, _token_for(resp)) is False


def test_verify_garbage_false():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr")
    for junk in (b"", b"not der at all", b"\x30\x03\x02\x01\x01extra",
                 der_sequence(der_integer(1))):  # structurally valid, semantically wrong
        assert client.verify(DIGEST, _token_for(junk)) is False


# ---------------------------------------------------------------------------
# Offline: timestamp() against the local stub (full request/response path)
# ---------------------------------------------------------------------------

async def test_timestamp_local_stub_ok():
    srv = _serve("ok")
    try:
        client = Rfc3161TsaClient(f"http://127.0.0.1:{srv.server_port}/tsr",
                                  authority_id="stub")
        token = await client.timestamp(DIGEST)
        assert token.authority_id == "stub"
        assert token.token_bytes[:1] == b"\x30"          # raw DER response kept
        dt.datetime.fromisoformat(token.timestamp_iso)  # valid ISO from genTime
        assert client.verify(DIGEST, token) is True
        assert client.verify(b"\x00" * 32, token) is False
    finally:
        srv.shutdown()


async def test_timestamp_rejection_raises():
    srv = _serve("rejection")
    try:
        client = Rfc3161TsaClient(f"http://127.0.0.1:{srv.server_port}/tsr")
        with pytest.raises(TsaError, match="rejection"):
            await client.timestamp(DIGEST)
    finally:
        srv.shutdown()


async def test_timestamp_nonce_mismatch_raises():
    srv = _serve("wrong_nonce")
    try:
        client = Rfc3161TsaClient(f"http://127.0.0.1:{srv.server_port}/tsr")
        with pytest.raises(TsaError, match="nonce"):
            await client.timestamp(DIGEST)
    finally:
        srv.shutdown()


async def test_timestamp_digest_mismatch_raises():
    srv = _serve("wrong_digest")
    try:
        client = Rfc3161TsaClient(f"http://127.0.0.1:{srv.server_port}/tsr")
        with pytest.raises(TsaError, match="messageImprint"):
            await client.timestamp(DIGEST)
    finally:
        srv.shutdown()


async def test_timestamp_connection_refused_raises_not_hangs():
    client = Rfc3161TsaClient("http://127.0.0.1:9/tsr", timeout_s=3.0)
    with pytest.raises(TsaError):
        await client.timestamp(DIGEST)


# ---------------------------------------------------------------------------
# Live: freetsa.org (read-only timestamp request; skip on any network issue)
# ---------------------------------------------------------------------------

async def test_live_freetsa_timestamp_and_verify():
    client = Rfc3161TsaClient("https://freetsa.org/tsr", authority_id="freetsa.org",
                              timeout_s=20.0)
    try:
        token = await client.timestamp(DIGEST)
    except Exception as e:  # noqa: BLE001 - any network failure -> skip, never fail
        pytest.skip(f"freetsa.org unreachable: {e}")
    assert client.verify(DIGEST, token) is True
    assert client.verify(b"\x00" * 32, token) is False
    assert token.timestamp_iso  # ISO-8601 converted from TSTInfo genTime
