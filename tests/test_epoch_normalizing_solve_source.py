"""EpochNormalizingSolveSource -- the single epoch-conversion seam
(epoch-seam decision, 2026-07-26)."""
from __future__ import annotations

import pytest

from cedar_goto.core._precession import precess
from cedar_goto.core.coords import J2000, CelestialCoord
from cedar_goto.core.epoch_normalizing_solve_source import EpochNormalizingSolveSource
from cedar_goto.core.solve import SolveResult

_WORKING_EPOCH = 1950.0
"""Arbitrary fixed epoch, deliberately distinct from J2000, so tests exercise
a real precess() call deterministically -- unlike JNow ("now"), this doesn't
depend on wall-clock time."""


def _make_solve(ra_deg: float = 120.0, dec_deg: float = 30.0, epoch: float = J2000) -> SolveResult:
    return SolveResult(
        sky_coord=CelestialCoord(ra_deg=ra_deg, dec_deg=dec_deg, epoch=epoch),
        capture_time_unix=0.0,
        num_matches=42,
        prob=1e-20,
        p90_error_arcsec=8.0,
        solution_from_imu=False,
    )


class _FakeSolveSource:
    def __init__(self, solve: SolveResult | None) -> None:
        self._solve = solve
        self.slew_started_calls: list[CelestialCoord] = []
        self.slew_stopped_count = 0

    async def stream_solves(self):
        if self._solve is not None:
            yield self._solve

    async def get_latest_solve(self) -> SolveResult | None:
        return self._solve

    async def notify_slew_started(self, target: CelestialCoord) -> None:
        self.slew_started_calls.append(target)

    async def notify_slew_stopped(self) -> None:
        self.slew_stopped_count += 1


async def _fixed_working_epoch() -> float:
    return _WORKING_EPOCH


async def _j2000_working_epoch() -> float:
    return J2000


async def test_stream_solves_precesses_j2000_to_working_epoch():
    inner = _FakeSolveSource(_make_solve())
    wrapped = EpochNormalizingSolveSource(inner, _fixed_working_epoch)

    solves = [s async for s in wrapped.stream_solves()]

    assert len(solves) == 1
    expected = precess(_make_solve().sky_coord, _WORKING_EPOCH)
    assert solves[0].sky_coord.epoch == pytest.approx(_WORKING_EPOCH)
    assert solves[0].sky_coord.ra_deg == pytest.approx(expected.ra_deg)
    assert solves[0].sky_coord.dec_deg == pytest.approx(expected.dec_deg)
    # Non-coordinate fields pass through unchanged.
    assert solves[0].num_matches == 42
    assert solves[0].p90_error_arcsec == 8.0


async def test_get_latest_solve_precesses_and_passes_through_none():
    inner = _FakeSolveSource(_make_solve())
    wrapped = EpochNormalizingSolveSource(inner, _fixed_working_epoch)

    solve = await wrapped.get_latest_solve()
    assert solve is not None
    assert solve.sky_coord.epoch == pytest.approx(_WORKING_EPOCH)

    empty = EpochNormalizingSolveSource(_FakeSolveSource(None), _fixed_working_epoch)
    assert await empty.get_latest_solve() is None


async def test_notify_slew_started_converts_working_epoch_to_j2000():
    inner = _FakeSolveSource(None)
    wrapped = EpochNormalizingSolveSource(inner, _fixed_working_epoch)
    target = CelestialCoord(ra_deg=120.0, dec_deg=30.0, epoch=_WORKING_EPOCH)

    await wrapped.notify_slew_started(target)

    assert len(inner.slew_started_calls) == 1
    forwarded = inner.slew_started_calls[0]
    expected = precess(target, J2000)
    assert forwarded.epoch == pytest.approx(J2000)
    assert forwarded.ra_deg == pytest.approx(expected.ra_deg)
    assert forwarded.dec_deg == pytest.approx(expected.dec_deg)


async def test_notify_slew_stopped_passes_through():
    inner = _FakeSolveSource(None)
    wrapped = EpochNormalizingSolveSource(inner, _fixed_working_epoch)

    await wrapped.notify_slew_stopped()

    assert inner.slew_stopped_count == 1


async def test_no_conversion_needed_when_working_epoch_is_already_j2000():
    """The mocks (e.g. MockCedar/MountEchoCedar) already emit J2000, and the
    mock mount's default working epoch is also J2000 -- this wrapper must be
    a true no-op then, not just a numerically-close one (precess()'s
    identity short-circuit, exercised end-to-end through the wrapper)."""
    solve = _make_solve()
    inner = _FakeSolveSource(solve)
    wrapped = EpochNormalizingSolveSource(inner, _j2000_working_epoch)

    result = await wrapped.get_latest_solve()

    assert result is not None
    assert result.sky_coord is solve.sky_coord
