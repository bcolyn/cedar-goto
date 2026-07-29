"""Mock SolveSource implementation driving a shared World (DESIGN.md §9a)."""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from cedar_goto.adapters.mock.world import World
from cedar_goto.core.coords import J2000, CelestialCoord
from cedar_goto.core.ports import SolveSource
from cedar_goto.core.solve import SolveResult


class MockCedar(SolveSource):
    def __init__(self, world: World, solve_interval_s: float = 0.05) -> None:
        self._world = world
        self._solve_interval_s = solve_interval_s
        self.slew_started_calls: list[CelestialCoord] = []
        self.slew_stopped_count = 0

    def _make_solve(self) -> SolveResult:
        if self._world.solve_failure_countdown > 0:
            self._world.solve_failure_countdown -= 1
            return SolveResult(
                sky_coord=self._world.true_pointing,
                capture_time_unix=time.time(),
                num_matches=2,
                prob=0.5,
                p90_error_arcsec=200.0,
                solution_from_imu=False,
            )
        return SolveResult(
            sky_coord=CelestialCoord(
                ra_deg=self._world.true_pointing.ra_deg,
                dec_deg=self._world.true_pointing.dec_deg,
                epoch=J2000,
            ),
            capture_time_unix=time.time(),
            num_matches=42,
            prob=1e-20,
            p90_error_arcsec=8.0,
            solution_from_imu=False,
        )

    async def stream_solves(self) -> AsyncIterator[SolveResult]:
        while True:
            if self._world.is_slewing():
                await asyncio.sleep(self._solve_interval_s)
                continue
            yield self._make_solve()
            await asyncio.sleep(self._solve_interval_s)

    async def get_latest_solve(self) -> SolveResult | None:
        if self._world.is_slewing():
            return None
        return self._make_solve()

    async def notify_slew_started(self, target: CelestialCoord) -> None:
        self.slew_started_calls.append(target)

    async def notify_slew_stopped(self) -> None:
        self.slew_stopped_count += 1
