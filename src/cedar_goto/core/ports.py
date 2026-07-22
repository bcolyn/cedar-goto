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
