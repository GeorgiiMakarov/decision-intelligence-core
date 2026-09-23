
"""
FastAPI entrypoint. Wires: the 3 contract methods (UpdateMetric,
GetScoreboard, GetMerkleProof), event-bus subscriptions for the lifecycle
events Core listens to (section 1.8), and a background task that ticks the
Merkle batch closer.

OpenTelemetry + structured logging (constraints) are configured here, once,
at process start — not scattered across modules.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from api.deps import AppState, build_app_state
from api.schemas import (
    ErrorResponse,
    GetMerkleProofResponse,
    GetScoreboardResponse,
    ProofNodeOut,
    ScoreboardMetricOut,
    UpdateMetricRequest,
    UpdateMetricResponseBody,
)
from application.command_handler import UpdateMetricCommand
from domain.enums import UpdateMetricStatus

# --- structured logging (stdlib only, per constraints 'structured logging') -----

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(payload)

def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # --- OpenTelemetry (constraints: 'OpenTelemetry tracing') ------------------

    # Kept optional: importing opentelemetry is not required to run the service

    # with tracing disabled, since it is not installed in every environment this

    # code might be reviewed in (it was not available in the sandbox that wrote

    # this file — see README 'Known gaps').

def _configure_tracing(app: FastAPI) -> None:
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        logging.getLogger("core.api").warning(
            "opentelemetry not installed; tracing disabled. "
            "pip install opentelemetry-sdk opentelemetry-instrumentation-fastapi to enable."
        )


async def _merkle_closer_loop(state: AppState, interval_s: float = 1.0) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            await state.merkle_anchor.maybe_close_and_anchor()
        except Exception:  # noqa: BLE001 - background loop must not die on one bad batch
            logging.getLogger("core.api").exception("merkle batch close failed")

def _register_event_routes(state: AppState) -> None:
    ch = state.command_handler
    routes = {
        "metrics.proposed": ch.on_metric_proposed,
        "metrics.debate-outcome": ch.on_debate_outcome,
        "metrics.risk-signal": ch.on_risk_signal,
        "metrics.reconciled": ch.on_reconciled_decision,
        "evidence.attached": ch.on_evidence_attached,
        "goal.created": ch.on_goal_created,
        "goal.cancelled": ch.on_goal_cancelled,
        "runtime.artifact-deployed": ch.on_runtime_artifact_deployed,
        "runtime.config-updated": ch.on_runtime_config_updated,
    }
    for topic, handler in routes.items():
        asyncio.ensure_future(state.event_bus.subscribe(topic, handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    state = await build_app_state()
    app.state.core = state
    await state.event_bus.start()
    _register_event_routes(state)
    closer_task = asyncio.create_task(_merkle_closer_loop(state))
    try:
        yield
    finally:
        closer_task.cancel()
        await state.merkle_anchor.force_close()  # flush on shutdown, don't lose a partial batch
        await state.event_bus.stop()

app = FastAPI(title="Decision Intelligence Layer — Core", version="1.2.0", lifespan=lifespan)
_configure_tracing(app)

def _state(request: Request) -> AppState:
    return request.app.state.core

@app.post("/v1/metrics", response_model=UpdateMetricResponseBody, responses={422: {"model": ErrorResponse}})
async def update_metric(body: UpdateMetricRequest, request: Request):
    state = _state(request)
    cmd = UpdateMetricCommand(
        decision_id=body.decision_id,
        metric_name=body.metric_name,
        value=body.value,
        idempotency_key=body.idempotency_key,
        evidence_refs=body.evidence_refs,
        proposed_by=body.proposed_by,
        runtime_context=body.runtime_context,
    )
    result = await state.command_handler.handle_update_metric(cmd)
    if result.status == UpdateMetricStatus.REJECTED_MISSING_EVIDENCE:
        raise HTTPException(status_code=422, detail="evidence_refs must be non-empty (invariant I3)")
    return JSONResponse(status_code=202, content=UpdateMetricResponseBody(status=result.status.value).model_dump())

@app.get("/v1/scoreboard/{decision_id}", response_model=GetScoreboardResponse)
async def get_scoreboard(decision_id: str, request: Request):
    state = _state(request)
    required = state.required_metrics_by_decision.get(decision_id, [])
    result = await state.projector.rebuild(decision_id, required)
    if not result.metrics:
        raise HTTPException(status_code=404, detail="decision_id not found")
    return GetScoreboardResponse(
        decision_id=result.decision_id,
        trust_score=result.trust_score if result.trust_score is not None else "INSUFFICIENT_DATA",
        metrics={
        name: ScoreboardMetricOut(value=m.value, evidence_refs=m.evidence_refs, committed_at=m.committed_at)
        for name, m in result.metrics.items()
        },
        merkle_root_ref=result.merkle_root_ref,
        merkle_timestamp=result.merkle_timestamp,
        rebuilt_at=result.rebuilt_at,
    )

@app.get("/v1/merkle-proof", response_model=GetMerkleProofResponse)
async def get_merkle_proof(decision_id: str, metric_name: str, request: Request):
    state = _state(request)
    required = state.required_metrics_by_decision.get(decision_id, [metric_name])
    scoreboard = await state.projector.rebuild(decision_id, required)
    metric = scoreboard.metrics.get(metric_name)
    if metric is None:
        raise HTTPException(status_code=404, detail="metric not found or not yet committed")

    events = await state.audit_trail.read_range(decision_id)
    committed = next(
        (e for e in events if e.get("event_type") == "MetricCommitted" and e.get("metric_name") == metric_name),
        None,
    )
    if committed is None or "leaf_hash" not in committed:
        raise HTTPException(status_code=404, detail="leaf not yet anchored — batch has not closed")

    proof_row = await state.projection_store.get(f"merkle_proof:{committed['leaf_hash']}")
    if proof_row is None:
        raise HTTPException(status_code=404, detail="leaf committed but not yet anchored — try again shortly")

    return GetMerkleProofResponse(
        leaf_hash=proof_row["leaf_hash"],
        proof_path=[ProofNodeOut(hash=n["hash"], position=n["position"]) for n in proof_row["proof_path"]],
        root=proof_row["root"],
        anchor_signature=proof_row["anchor_signature"],
        anchor_timestamp=proof_row["anchor_timestamp"],
    )

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}




