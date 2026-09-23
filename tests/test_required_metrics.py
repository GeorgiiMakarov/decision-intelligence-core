"""Configurable required metrics via CORE_REQUIRED_METRICS.

Regression: api/deps.py hardcoded required_metrics_by_decision={}, so the
REST scoreboard always evaluated a vacuously complete (empty) required set
-> trust_score 0.0 and REJECT for every decision, regardless of the metrics
actually committed. With CORE_REQUIRED_METRICS set, the scoreboard
evaluates the real required set instead.

Stdlib + fastapi only; no docker, no live Postgres/Redis/Kafka.
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("CORE_ENV", "local")

import api.main
from api.deps import _load_required_metrics
from fastapi.testclient import TestClient


def _ingest(client, decision_id, metric_name, value, key):
    r = client.post("/v1/metrics", json={
        "decision_id": decision_id,
        "metric_name": metric_name,
        "value": value,
        "idempotency_key": key,
        "evidence_refs": ["req:evidence:1"],
        "proposed_by": "req-test",
    })
    assert r.status_code == 202, r.text


def test_load_required_metrics_parsing(monkeypatch):
    monkeypatch.setenv("CORE_REQUIRED_METRICS", '{"dec-a": ["m.x", "m.y"], "dec-b": []}')
    assert _load_required_metrics() == {"dec-a": ["m.x", "m.y"], "dec-b": []}

    monkeypatch.setenv("CORE_REQUIRED_METRICS", "{not valid json")
    assert _load_required_metrics() == {}

    monkeypatch.setenv("CORE_REQUIRED_METRICS", '["not", "an", "object"]')
    assert _load_required_metrics() == {}

    monkeypatch.setenv("CORE_REQUIRED_METRICS", '{"dec-a": ["ok", 42]}')
    assert _load_required_metrics() == {}

    monkeypatch.delenv("CORE_REQUIRED_METRICS", raising=False)
    assert _load_required_metrics() == {}


def test_configured_required_metrics_give_meaningful_verdict(monkeypatch):
    monkeypatch.setenv(
        "CORE_REQUIRED_METRICS", json.dumps({"req-dec-1": ["latency_p95_ms"]})
    )
    with TestClient(api.main.app) as client:
        _ingest(client, "req-dec-1", "latency_p95_ms", 0.9, "req-key-00000001")
        r = client.get("/v1/scoreboard/req-dec-1")
        assert r.status_code == 200, r.text
        body = r.json()
        # 0.9 >= approve_at (0.7): a real verdict, not the vacuously-complete
        # 0.0/REJECT the hardcoded {} produced for every decision.
        assert body["trust_score"] == pytest.approx(0.9)


def test_missing_configured_metric_is_insufficient_data(monkeypatch):
    monkeypatch.setenv(
        "CORE_REQUIRED_METRICS", json.dumps({"req-dec-2": ["latency_p95_ms"]})
    )
    with TestClient(api.main.app) as client:
        _ingest(client, "req-dec-2", "other_metric", 0.9, "req-key-00000002")
        r = client.get("/v1/scoreboard/req-dec-2")
        assert r.status_code == 200, r.text
        # I4: the required metric was never committed -> INSUFFICIENT_DATA,
        # not a fabricated 0.0.
        assert r.json()["trust_score"] == "INSUFFICIENT_DATA"


def test_unset_env_keeps_historical_default(monkeypatch):
    monkeypatch.delenv("CORE_REQUIRED_METRICS", raising=False)
    with TestClient(api.main.app) as client:
        _ingest(client, "req-dec-3", "latency_p95_ms", 0.9, "req-key-00000003")
        r = client.get("/v1/scoreboard/req-dec-3")
        assert r.status_code == 200, r.text
        assert r.json()["trust_score"] == 0.0
