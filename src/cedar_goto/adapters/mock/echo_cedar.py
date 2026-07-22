"""A SolveSource that reports the mount's own position as if it were a
plate-solve.

Lets the closed loop -- and critically, the *real* Alpaca mount adapter's
epoch handling (JNow -> J2000) -- be exercised end-to-end against real
hardware without a working cedar-server (e.g. daylight, no stars). Not a
production component: it isn't independent ground truth, just a loopback
for validating the plumbing.

Every solve is marked is_plate_solve=False (core/solve.py) -- the loop and
UI sync paths (core/loop.py, web/closed_loop_backend.py) refuse to
mount.sync_to() with one of these, since syncing against the mount's own
already-possibly-wrong belief would corrupt its persistent alignment/
sync-point database with circular, non-independent data.
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from cedar_goto.core._precession import precess_to_j2000
from cedar_goto.core.ports import MountControl, SolveSource
from cedar_goto.core.solve import SolveResult


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
            prob=1.0,
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
