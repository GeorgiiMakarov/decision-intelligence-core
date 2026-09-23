# decision-intelligence-core

Decision Intelligence Framework v1.2 — Core service. A decision-logging and audit core with Clean Architecture / DDD layout: domain events are appended to an immutable audit trail, anchored in Merkle batches (Ed25519-signed, RFC 3161 timestamped), and projected into a queryable scoreboard.

**Status:** Restored from a damaged monolithic bundle on 2026-09-23. All 29 pytest tests pass; the standalone `tests/verify_core_logic_stdlib.py` (311 checks, stdlib only) passes.

## Verified invariants (only these are claimed)

- **I3** — empty `evidence_refs` is rejected (`MetricRejected`, reason `MISSING_EVIDENCE`), never committed.
- **I4** — incomplete metric sets project to `INSUFFICIENT_DATA`, never a numeric score.
- **I6** — a repeated `idempotency_key` returns `DUPLICATE_IGNORED`; the original leaf is untouched.
- **I7** — superseding appends a new `MetricSuperseded` event; the original leaf hash is byte-identical and never rewritten.

Merkle inclusion proofs verify offline (`verify_inclusion_proof`); Ed25519 signatures round-trip and fail on wrong-key/tampered input.

## Layout

```
domain/          Enums, Pydantic models, domain events (no infrastructure imports)
interfaces/      Ports: AuditTrail, EventBus, ProjectionStore, Signer, Tsa (Protocols)
application/     CommandHandler, ScoreboardProjector, PolicyEvaluator,
                 MetricsRegistry, RiskMatrix, Merkle batching + anchor service,
                 EvidenceRegistry, CompletionCriteria, EventDispatcher
infrastructure/  In-memory adapters (tests), Postgres audit trail, Redis, Kafka,
                 Ed25519 signer (cryptography), RFC 3161 TSA client (base interface)
api/             FastAPI app (REST): POST /v1/metrics, GET /v1/scoreboard, GET /v1/proofs
grpc_transport/  gRPC servicer (same application layer as REST); generated stubs via:
                   python -m grpc_tools.protoc -I grpc_transport \
                     --python_out=grpc_transport --grpc_python_out=grpc_transport \
                     grpc_transport/core.proto
tests/           pytest suite (29 tests) + verify_core_logic_stdlib.py (stdlib-only)
openapi.yaml     Hand-maintained OpenAPI 3.1 (diff against app.openapi() after route changes)
docker-compose.yml  Postgres, Redis, Kafka for local integration runs
```

`grpc_transport/` was renamed from `grpc/` during restoration — the old name shadowed the pip-installed `grpc` framework package on `sys.path`.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # tests, lint, typecheck

pytest -q                              # 29 tests
python tests/verify_core_logic_stdlib.py  # 311 stdlib-only checks
```

## Extension point: Domain Profiles

`UpdateMetricCommand.runtime_context` carries caller-specific context (e.g. planner version, session id) through the pipeline without changing the core. Domain-specific mappings (event → metric, policy thresholds) live outside this package and plug in via `runtime_context` — see `docs/domain-profiles/` for examples.

## Known gaps

- `grpc_transport/core_pb2.py` / `core_pb2_grpc.py` are not committed; generate with the protoc command above.
- `infrastructure/rfc3161_tsa.py` is the base TSA interface; national CA integration is out of scope for the core.
- Postgres/Redis/Kafka adapters are implemented against the port interfaces; integration tests against live services are not included.
