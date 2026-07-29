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

import logging
from typing import AsyncIterator

import grpc

from cedar_goto.adapters.cedar_grpc.generated import cedar_common_pb2, cedar_pb2, cedar_pb2_grpc
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.ports import SolveSource
from cedar_goto.core.solve import SolveResult

logger = logging.getLogger(__name__)


def _solve_epoch(ps: cedar_common_pb2.PlateSolution, coord: cedar_common_pb2.CelestialCoord) -> float:
    """SolveSource must emit J2000 (epoch-seam decision, 2026-07-26), but
    cedar-server doesn't always say so honestly: ps.epoch_equinox is a bare
    int32 (cedar.proto), not `optional`, so an unset one reads as 0 rather
    than being absent -- and it can legitimately be 1950 for an old B1950
    BSC5 catalog, not always 2000. Prefer it when non-zero (it's the
    solver's own claim about its catalog); fall back to CelestialCoord.epoch
    (also not `optional` in this build -- observed unset in practice); fall
    back to 2000.0 (the plate-solver default, and correct for every
    catalog/solver combination confirmed so far). Logs rather than raises
    when the two disagree -- this is best-effort epoch archaeology on data
    cedar-server itself doesn't always populate, not a hard contract."""
    coord_epoch = coord.epoch if coord.HasField("epoch") else None
    if ps.epoch_equinox:
        if coord_epoch is not None and abs(ps.epoch_equinox - coord_epoch) > 1e-6:
            logger.warning(
                "cedar plate solution epoch mismatch: epoch_equinox=%s vs CelestialCoord.epoch=%s "
                "-- using epoch_equinox", ps.epoch_equinox, coord_epoch,
            )
        return float(ps.epoch_equinox)
    return coord_epoch if coord_epoch is not None else 2000.0


def _to_solve_result(frame: cedar_pb2.FrameResult) -> SolveResult | None:
    """frame.has_result is deliberately not checked here: per cedar.proto,
    it's only populated for non_blocking requests (GetFrame's early-return
    "no new result yet" signal) -- for blocking requests (non_blocking=False,
    what stream_solves() always uses) the server leaves it unset/false even
    when plate_solution is genuinely present. Checking it unconditionally
    (confirmed live: this cedar-server build never sets has_result=true for
    any blocking GetFrame response) made stream_solves() silently discard
    every solve it ever received, which is why every closed-loop AWAIT_SOLVE
    ran out its full solve_wait_timeout_s and failed even while cedar was
    solving successfully multiple times a second the whole time.
    HasField("plate_solution") alone is the correct, sufficient signal in
    both the blocking and non-blocking cases -- a non-blocking "nothing new"
    response has no plate_solution either."""
    if not frame.HasField("plate_solution"):
        return None
    ps = frame.plate_solution
    # image_sky_coord is the RA/Dec of the *image center*, not necessarily
    # where the telescope's actual optical path points -- confirmed live
    # 2026-07-25 (visually, at the eyepiece) that this cedar-box's boresight
    # is meaningfully off from image center (finder/main-scope-style
    # misalignment between the cedar camera and the actual scope). Prefer
    # ps.target_sky_coord[0] when present: per cedar.proto it's "Result of
    # SolveExtension.target_pixel", and cedar-server's solve_engine worker
    # unconditionally sets that request field from its own calibrated
    # boresight_pixel whenever one is set -- so this is the boresight's real
    # sky position from cedar's own plate-solve WCS (pure pixel-to-sky
    # reprojection), not a fallback or an echo of the slew target.
    #
    # Deliberately NOT using cedar-server's location_based_info/alt-az path
    # (tried first, reverted): confirmed live that cedar-server's own
    # alt_az_from_equatorial() (elements/src/astro_util.rs) computes hour
    # angle as `GMST + longitude - ra` using the plate solve's J2000 RA
    # directly, without precessing to the apparent/of-date epoch first --
    # a real cedar-server bug that made round-tripping through alt/az
    # introduce its own (inconsistent, position-dependent) error on top of
    # whatever we were trying to fix. Reading target_sky_coord directly
    # avoids cedar-server's alt/az math entirely and stays in the same
    # plain-RA/Dec domain already proven reliable all night.
    if ps.target_sky_coord:
        coord = ps.target_sky_coord[0]
    else:
        coord = ps.image_sky_coord
    return SolveResult(
        sky_coord=CelestialCoord(
            ra_deg=coord.ra,
            dec_deg=coord.dec,
            epoch=_solve_epoch(ps, coord),
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
        """Long-polls via prev_frame_id, not prev_solution_id -- confirmed live
        against this cedar-server build (version 0.17.0) that FrameResult.solution_id
        stays frozen at 0 on every response even as frame_id and the plate
        solution both advance normally frame to frame. cedar.proto documents
        prev_solution_id as behaving identically to prev_frame_id when there's
        no IMU (true here: use_imu=false) in OPERATE mode, but that's not what
        this server build actually does.

        Uses its own dedicated channel/stub, opened fresh per call and closed
        when the generator exits, rather than the client's shared long-lived
        channel/stub -- confirmed live that AWAIT_SOLVE could hang for the
        full solve_wait_timeout_s on the very first GetFrame of a brand new
        call (0 solves yielded), while an independent process opening a fresh
        channel to the same cedar-server got instant, accepted solves the
        entire time. The shared channel accumulates one long-poll GetFrame
        per closed-loop attempt across the service's lifetime; when
        asyncio.timeout() cancels the awaiting task, cleanup of the
        underlying gRPC call on that shared channel isn't reliable enough in
        practice, and it wedges the channel for subsequent calls. A
        per-attempt channel means a wedged one is simply discarded instead of
        accumulating."""
        channel = grpc.aio.insecure_channel(self._address)
        try:
            stub = cedar_pb2_grpc.CedarStub(channel)
            prev_frame_id: int | None = None
            while True:
                kwargs = {"prev_frame_id": prev_frame_id} if prev_frame_id is not None else {}
                frame = await stub.GetFrame(cedar_pb2.FrameRequest(non_blocking=False, **kwargs))
                prev_frame_id = frame.frame_id
                solve = _to_solve_result(frame)
                if solve is not None:
                    yield solve
        finally:
            await channel.close()

    async def get_latest_solve(self) -> SolveResult | None:
        request = cedar_pb2.FrameRequest(non_blocking=True)
        frame = await self._stub.GetFrame(request)
        return _to_solve_result(frame)

    async def notify_slew_started(self, target: CelestialCoord) -> None:
        """Lets cedar-server offer push-to guidance (SlewRequest fields in
        FrameResult) for a slew cedar-goto's own closed loop is driving --
        without this, cedar-server has no idea a slew is happening at all,
        since cedar-goto intercepts the ASCOM slew instead of forwarding it.
        Best-effort: a failure here must not break the actual mount
        nudging, which doesn't depend on cedar-server knowing about it."""
        # target.epoch is set explicitly rather than left to the proto's
        # documented "defaults to 2000.0 if omitted" -- this client is meant
        # to receive J2000 targets already (EpochNormalizingSolveSource
        # converts working-epoch -> J2000 before calling here), and an
        # explicit field survives a future change to that default or to what
        # calls this method without silently reintroducing the mis-tag bug
        # the epoch-seam decision (2026-07-26) closed.
        try:
            await self._stub.InitiateAction(
                cedar_pb2.ActionRequest(
                    initiate_slew=cedar_common_pb2.CelestialCoord(
                        ra=target.ra_deg, dec=target.dec_deg, epoch=target.epoch
                    )
                )
            )
        except grpc.RpcError as exc:
            logger.warning("cedar-server InitiateAction(initiate_slew) failed: %r", exc)

    async def notify_slew_stopped(self) -> None:
        try:
            await self._stub.InitiateAction(cedar_pb2.ActionRequest(stop_slew=True))
        except grpc.RpcError as exc:
            logger.warning("cedar-server InitiateAction(stop_slew) failed: %r", exc)

    async def capture_boresight(self) -> None:
        try:
            await self._stub.InitiateAction(cedar_pb2.ActionRequest(capture_boresight=True))
        except grpc.RpcError as exc:
            logger.warning("cedar-server InitiateAction(capture_boresight) failed: %r", exc)
