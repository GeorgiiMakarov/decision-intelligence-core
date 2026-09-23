"""API smoke test — regression coverage for the reconstructed api/ package.

Bugs 1 and 2 (api/deps.py, api/main.py) were reconstruction artifacts that made
`import api.main` fail outright: module-level functions were left indented as
methods / inside a `finally:` block, so the server could not even start.
Importing the app below is the regression gate for both.

Bug 3 (application/policy_evaluator.py) made every GET /v1/scoreboard return
500 with UnboundLocalError: the REST wiring in api/deps.py passes
required_metrics=[] so the `committed` loop never assigned `base_score`. The
ingest -> scoreboard round trip below exercises exactly that path.

Stdlib + fastapi only; no docker, no live Postgres/Redis/Kafka.
"""
from __future__ import annotations

import os

os.environ.setdefault("CORE_ENV", "local")

import api.main  # noqa: F401 — the import itself is the test for bugs 1-2
from fastapi.testclient import TestClient


def test_healthz():
    with TestClient(api.main.app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_ingest_then_scoreboard_200():
    with TestClient(api.main.app) as client:
        r = client.post("/v1/metrics", json={
            "decision_id": "smoke-dec-1",
            "metric_name": "latency_p95_ms",
            "value": 42.0,
            "idempotency_key": "smoke-key-00000001",
            "evidence_refs": ["smoke:evidence:1"],
            "proposed_by": "smoke-test",
        })
        assert r.status_code == 202, r.text
        assert r.json()["status"] == "ACCEPTED"

        # Bug 3 made this a 500 (UnboundLocalError on base_score).
        r = client.get("/v1/scoreboard/smoke-dec-1")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decision_id"] == "smoke-dec-1"
        assert "latency_p95_ms" in body["metrics"]


def test_scoreboard_unknown_decision_404():
    with TestClient(api.main.app) as client:
        r = client.get("/v1/scoreboard/does-not-exist")
        assert r.status_code == 404
