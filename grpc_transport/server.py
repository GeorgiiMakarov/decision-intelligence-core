
"""
gRPC servicer. Calls into the SAME application-layer objects (CommandHandler,
ScoreboardProjector) as api/main.py's REST routes — no business logic is
duplicated between the two transports, only request/response marshalling
differs.

Renamed from `grpc/` to `grpc_transport/` during the 2026-09-23
repository restoration: the old name shadowed the real pip-installed
`grpc` package whenever the repo root was on sys.path, breaking
`import grpc` (the framework) in every environment. The rename is
confined to this transport folder; no Core Specification component
was renamed.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging

import grpc  # the pip package — see the module docstring if this import ever
# resolves to the wrong thing.
from google.protobuf import json_format

from grpc_transport import core_pb2, core_pb2_grpc  # generated via:

# python -m grpc_tools.protoc -I grpc_transport --python_out=grpc_transport --grpc_python_out=grpc_transport grpc_transport/core.proto

# (not run in the environment that generated this repo — see README 'Known gaps')

from api.deps import AppState
from application.command_handler import UpdateMetricCommand
from domain.enums import UpdateMetricStatus

logger = logging.getLogger("core.grpc")

class DecisionIntelligenceCoreServicer(core_pb2_grpc.DecisionIntelligenceCoreServicer):
    def __init__(self, state: AppState) -> None:
        self._state = state

    async def UpdateMetric(self, request, context):
        cmd = UpdateMetricCommand(
            decision_id=request.decision_id,
            metric_name=request.metric_name,
            value=json.loads(request.value.decode("utf-8")) if request.value else None,
            idempotency_key=request.idempotency_key,
            evidence_refs=list(request.evidence_refs),
            proposed_by=request.proposed_by,
            # request.runtime_context is a google.protobuf.Struct now, not a
            # map<string,string> — dict(...) on a Struct doesn't recurse
            # correctly for nested values, MessageToDict does.
            runtime_context=json_format.MessageToDict(request.runtime_context),
        )
        result = await self._state.command_handler.handle_update_metric(cmd)

        status_map = {
            UpdateMetricStatus.ACCEPTED: core_pb2.UpdateMetricResponse.ACCEPTED,
            UpdateMetricStatus.DUPLICATE_IGNORED: core_pb2.UpdateMetricResponse.DUPLICATE_IGNORED,
            UpdateMetricStatus.REJECTED_MISSING_EVIDENCE: core_pb2.UpdateMetricResponse.REJECTED_MISSING_EVIDENCE,
        }
        return core_pb2.UpdateMetricResponse(
            status=status_map[result.status],
            leaf_hash=result.leaf_hash or "",
        )

    async def GetScoreboard(self, request, context):
        required = self._state.required_metrics_by_decision.get(request.decision_id, [])
        sb = await self._state.projector.rebuild(request.decision_id, required)

        resp = core_pb2.ScoreboardState(
            decision_id=sb.decision_id,
            policy_verdict=sb.policy_verdict.value,
            merkle_root_ref=sb.merkle_root_ref or "",
            rebuilt_at_unix_ms=int(sb.rebuilt_at.timestamp() * 1000),
            merkle_timestamp_unix_ms=int(sb.merkle_timestamp.timestamp() * 1000) if sb.merkle_timestamp else 0,
        )
        if sb.trust_score is None:
            resp.insufficient_reason = core_pb2.INSUFFICIENT_DATA
        else:
            resp.trust_score = sb.trust_score
        for name, m in sb.metrics.items():
            resp.metrics.add(
                metric_name=name,
                value=json.dumps(m.value).encode("utf-8"),
                evidence_refs=m.evidence_refs,
                committed_at_unix_ms=int(m.committed_at.timestamp() * 1000),
                status=m.status.value,
            )
        return resp

    async def GetMerkleProof(self, request, context):
        events = await self._state.audit_trail.read_range(request.decision_id)
        committed = next(
            (e for e in events if e.get("event_type") == "MetricCommitted"
            and e.get("metric_name") == request.metric_name),
            None,
        )
        if committed is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "metric not committed")
            return

        proof_row = await self._state.projection_store.get(f"merkle_proof:{committed['leaf_hash']}")
        if proof_row is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "leaf committed but not yet anchored")
            return

        anchor_ts = dt.datetime.fromisoformat(proof_row["anchor_timestamp"])
        resp = core_pb2.MerkleProof(
            leaf_hash=bytes.fromhex(proof_row["leaf_hash"]),
            root=bytes.fromhex(proof_row["root"]),
            anchor_signature=bytes.fromhex(proof_row["anchor_signature"]),
            anchor_timestamp_unix_ms=int(anchor_ts.timestamp() * 1000),
        )
        for node in proof_row["proof_path"]:
            position = core_pb2.ProofNode.LEFT if node["position"] == "LEFT" else core_pb2.ProofNode.RIGHT
            resp.proof_path.add(hash=bytes.fromhex(node["hash"]), position=position)
        return resp

async def serve(state: AppState, port: int = 50051) -> None:
    server = grpc.aio.server()
    core_pb2_grpc.add_DecisionIntelligenceCoreServicer_to_server(
        DecisionIntelligenceCoreServicer(state), server
    )
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    logger.info("gRPC server listening on :%d", port)
    await server.wait_for_termination()

async def _main() -> None:
    from api.deps import build_app_state

    state = await build_app_state()
    await serve(state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())




