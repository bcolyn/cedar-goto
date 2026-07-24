"""Port interfaces the closed-loop core depends on (DESIGN.md §12).

Real adapters (Alpaca mount client, cedar gRPC client) and the mock harness
(DESIGN.md §9a) both implement these protocols. The core imports nothing
else from `adapters/` — this is the seam that keeps a future rewrite
mechanical.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol

from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.solve import SolveResult


class MountControl(Protocol):
    """What the closed loop needs from a GoTo mount."""

    async def slew_to(self, target: CelestialCoord) -> None:
        """Command an async slew. Returns once the command is accepted (not once settled)."""
        ...

    async def is_slewing(self) -> bool: ...

    async def sync_to(self, coord: CelestialCoord) -> None: ...

    async def get_equatorial_system(self) -> float:
        """Return the epoch (Julian year) the mount's coordinates are expressed in."""
        ...

    async def get_position(self) -> CelestialCoord:
        """Mount's own reported RA/Dec (used for idle-position fallback, DESIGN.md §3)."""
        ...

    async def abort_slew(self) -> None: ...


class SolveSource(Protocol):
    """What the closed loop needs from cedar-server."""

    def stream_solves(self) -> AsyncIterator[SolveResult]:
        """Long-lived stream of plate-solve frame results (cedar GetFrames)."""
        ...

    async def get_latest_solve(self) -> SolveResult | None:
        """Most recent solve, or None if none yet / stale. Used for idle-position reporting."""
        ...

    async def notify_slew_started(self, target: CelestialCoord) -> None:
        """Tell cedar-server a GoTo to `target` is starting (cedar.proto
        ActionRequest.initiate_slew), so it can offer push-to guidance
        (SlewRequest fields in FrameResult) via its own display -- e.g.
        Cedar Aim. cedar-goto's closed loop drives the mount itself, so
        without this cedar-server has no idea a slew is even happening.
        Must not raise -- a solve source with no real cedar-server to
        notify (mock/echo) is a no-op, and a real one degrades to a no-op
        with a logged warning rather than breaking the actual slew."""
        ...

    async def notify_slew_stopped(self) -> None:
        """Tell cedar-server the slew is finished/discontinued (cedar.proto
        ActionRequest.stop_slew), clearing any push-to guidance it was
        showing. Same no-raise contract as notify_slew_started()."""
        ...
