"""SolveSource adapter over cedar-server's real gRPC Cedar service (DESIGN.md §3, §7).

Verified against a live Cedar-Box (cedar_server_version 0.17.0): GetFrame
connects and round-trips real FrameResult messages. Note cedar-server binds
gRPC on the *same port as its web UI* (tonic's GrpcWebLayer combines them,
default port 80) -- there is no separate dedicated gRPC port.

`stream_solves()` long-polls the unary `GetFrame`, not the server-streaming
`GetFrames` the .proto also declares -- confirmed live (first real GOTO
through a real mount + real cedar-server) that this cedar-server build
returns UNIMPLEMENTED for `GetFrames`, crashing the closed loop mid-slew.
`GetFrame` supports the same "block until something new" semantics via
`prev_solution_id` (see cedar.proto's FrameRequest), so this preserves
push-like behavior -- one blocking RPC per new solution, not a busy loop --
without needing the missing streaming method.
"""
from __future__ import annotations

from typing import AsyncIterator

import grpc

from cedar_goto.adapters.cedar_grpc.generated import cedar_pb2, cedar_pb2_grpc
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.ports import SolveSource
from cedar_goto.core.solve import SolveResult


def _to_solve_result(frame: cedar_pb2.FrameResult) -> SolveResult | None:
    if not frame.has_result or not frame.HasField("plate_solution"):
        return None
    ps = frame.plate_solution
    return SolveResult(
        sky_coord=CelestialCoord(
            ra_deg=ps.image_sky_coord.ra,
            dec_deg=ps.image_sky_coord.dec,
            epoch=ps.image_sky_coord.epoch if ps.image_sky_coord.HasField("epoch") else 2000.0,
        ),
        capture_time_unix=frame.capture_time.ToNanoseconds() / 1e9,
        num_matches=ps.num_matches,
        prob=ps.prob,
        p90_error_arcsec=ps.p90_error,
        solution_from_imu=ps.solution_from_imu,
    )


class CedarGrpcClient(SolveSource):
    """Connects to a real cedar-server over gRPC."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._channel = grpc.aio.insecure_channel(address)
        self._stub = cedar_pb2_grpc.CedarStub(self._channel)

    async def close(self) -> None:
        await self._channel.close()

    async def stream_solves(self) -> AsyncIterator[SolveResult]:
        prev_solution_id: int | None = None
        while True:
            kwargs = {"prev_solution_id": prev_solution_id} if prev_solution_id is not None else {}
            frame = await self._stub.GetFrame(cedar_pb2.FrameRequest(non_blocking=False, **kwargs))
            prev_solution_id = frame.solution_id
            solve = _to_solve_result(frame)
            if solve is not None:
                yield solve

    async def get_latest_solve(self) -> SolveResult | None:
        request = cedar_pb2.FrameRequest(non_blocking=True)
        frame = await self._stub.GetFrame(request)
        return _to_solve_result(frame)
