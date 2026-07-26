"""The single epoch-conversion seam (epoch-seam decision, 2026-07-26).

SolveSource always emits J2000: plate solvers are inherently J2000/ICRS by
construction, not by choice -- verified for esa/tetra3 and smroid/cedar-solve
from source (zero occurrences of precess/astropy/erfa/obstime; solve_from_
image() takes no observation time and no observer location, so of-date
output is structurally impossible), and independently for astrometry.net
(Dustin Lang) and ASTAP. cedar-goto's internal working epoch is whatever its
own MountControl adapter's device actually advertises (JNow for the real
INDI mount, a fixed epoch for Alpaca's equJ2000/equJ2050/equB1950, "now" for
equTopocentric).

This wraps any SolveSource and does the one conversion cedar-goto needs:
precesses outbound solves J2000 -> working epoch, and precesses the inbound
notify_slew_started() target working epoch -> J2000 (cedar-server's own
convention). Everything downstream of this wrapper -- core/loop.py,
MountControl adapters -- works in a single consistent epoch and never sees
J2000 unless the working epoch happens to be J2000.

Applied uniformly in __main__._build_backend to every SolveSource, real and
mock alike -- see adapters/mock/echo_cedar.py's MountEchoCedar for why the
mocks still bother emitting J2000 of their own accord even though the
round-trip through this wrapper is often a no-op: uniformity (every
SolveSource honors the same contract) beats saving a currently-free
conversion.
"""
from __future__ import annotations

import dataclasses
from typing import AsyncIterator, Awaitable, Callable

from cedar_goto.core._precession import precess
from cedar_goto.core.coords import J2000, CelestialCoord
from cedar_goto.core.ports import SolveSource
from cedar_goto.core.solve import SolveResult


class EpochNormalizingSolveSource(SolveSource):
    def __init__(self, inner: SolveSource, working_epoch: Callable[[], Awaitable[float]]) -> None:
        self._inner = inner
        self._working_epoch = working_epoch

    async def _to_working_epoch(self, solve: SolveResult) -> SolveResult:
        epoch = await self._working_epoch()
        return dataclasses.replace(solve, sky_coord=precess(solve.sky_coord, epoch))

    async def stream_solves(self) -> AsyncIterator[SolveResult]:
        async for solve in self._inner.stream_solves():
            yield await self._to_working_epoch(solve)

    async def get_latest_solve(self) -> SolveResult | None:
        solve = await self._inner.get_latest_solve()
        return None if solve is None else await self._to_working_epoch(solve)

    async def notify_slew_started(self, target: CelestialCoord) -> None:
        await self._inner.notify_slew_started(precess(target, J2000))

    async def notify_slew_stopped(self) -> None:
        await self._inner.notify_slew_stopped()
