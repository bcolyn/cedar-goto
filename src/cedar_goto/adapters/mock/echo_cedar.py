"""A SolveSource that reports the mount's own position as if it were a
plate-solve.

Lets the closed loop be exercised end-to-end against real hardware without a
working cedar-server (e.g. daylight, no stars). Not a production component:
it isn't independent ground truth, just a loopback for validating the
plumbing.

Emits solves tagged J2000 via precess_to_j2000(), same as every other
SolveSource (epoch-seam decision, 2026-07-26: the port's contract is "always
J2000", enforced by EpochNormalizingSolveSource downstream) -- even though
the mount's own position is already close to a no-op round-trip through this
particular loopback. Kept for uniformity (every SolveSource honors the same
contract, so nothing downstream needs to special-case this one) rather than
skipping the conversion to save what's usually a near-free precess() call.

Every solve is marked is_plate_solve=False (core/solve.py) -- the UI sync
path (web/cedar_backend.py's sync_to_cedar()) refuses to mount.sync_to()
with one of these, since syncing against the mount's own
already-possibly-wrong belief would corrupt its persistent alignment/
sync-point database with circular, non-independent data.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from cedar_goto.core._precession import precess_to_j2000
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.ports import MountControl, SolveSource
from cedar_goto.core.solve import SolveResult

logger = logging.getLogger(__name__)


class MountEchoCedar(SolveSource):
    def __init__(self, mount: MountControl, poll_interval_s: float = 0.5) -> None:
        self._mount = mount
        self._poll_interval_s = poll_interval_s

    async def get_latest_solve(self) -> SolveResult | None:
        coord = await self._mount.get_position()
        return SolveResult(
            sky_coord=precess_to_j2000(coord),
            capture_time_unix=time.time(),
            num_matches=999,
            prob=0.0,
            p90_error_arcsec=0.0,
            solution_from_imu=False,
            is_plate_solve=False,
        )

    async def stream_solves(self) -> AsyncIterator[SolveResult]:
        while True:
            solve = await self.get_latest_solve()
            if solve is not None:
                yield solve
            await asyncio.sleep(self._poll_interval_s)

    async def notify_slew_started(self, target: CelestialCoord) -> None:
        # No real cedar-server here to notify -- log it so this doesn't
        # look like push-to guidance should be working while testing
        # against a real mount without a working cedar-server.
        logger.info(
            "MountEchoCedar: not notifying cedar-server of slew to RA %.4f Dec %.4f "
            "(no real cedar-server here -- push-to guidance won't activate)",
            target.ra_deg, target.dec_deg,
        )

    async def notify_slew_stopped(self) -> None:
        logger.info("MountEchoCedar: not notifying cedar-server that the slew stopped (no real cedar-server here)")

    async def capture_boresight(self) -> None:
        logger.info("MountEchoCedar: not capturing boresight (no real cedar-server here)")
