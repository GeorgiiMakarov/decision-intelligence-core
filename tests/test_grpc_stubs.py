"""Guards the generated gRPC stubs and the servicer wiring.

Regenerating the stubs (see grpc_transport/core.proto) must keep:
- the 3 RPC methods of DecisionIntelligenceCore,
- the package-relative import in core_pb2_grpc (plain `import core_pb2`
  breaks when imported as grpc_transport.core_pb2_grpc),
- serve/_main as module-level functions in grpc_transport/server.py
  (a past reconstruction left them indented as class methods, so
  `python -m grpc_transport.server` silently did nothing).
"""
from __future__ import annotations

import inspect

import pytest

grpc = pytest.importorskip("grpc")


def test_stubs_importable():
    from grpc_transport import core_pb2, core_pb2_grpc  # noqa: F401

    svc = core_pb2.DESCRIPTOR.services_by_name["DecisionIntelligenceCore"]
    assert sorted(m.name for m in svc.methods) == [
        "GetMerkleProof",
        "GetScoreboard",
        "UpdateMetric",
    ]


def test_servicer_wiring():
    from grpc_transport import core_pb2_grpc
    from grpc_transport.server import DecisionIntelligenceCoreServicer, _main, serve

    assert issubclass(
        DecisionIntelligenceCoreServicer, core_pb2_grpc.DecisionIntelligenceCoreServicer
    )
    assert inspect.isfunction(serve) and inspect.iscoroutinefunction(serve)
    assert inspect.isfunction(_main) and inspect.iscoroutinefunction(_main)
