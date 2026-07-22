"""Convergence tests for ClosedLoopSlew against the mock harness (DESIGN.md §9a).

Runs entirely against mocks: no hardware, no daylight-blocked plate solving.
"""
from __future__ import annotations

import dataclasses

import pytest

from cedar_goto.adapters.mock.cedar import MockCedar
from cedar_goto.adapters.mock.mount import MockMount
from cedar_goto.adapters.mock.world import HarmonicErrorModel, World
from cedar_goto.core.coords import CelestialCoord, angular_separation_deg
from cedar_goto.core.loop import ClosedLoopSlew, LoopConfigCore, LoopState, SlewStrategy
from cedar_goto.core.solve import SolveAcceptance

TARGET = CelestialCoord(ra_deg=120.0, dec_deg=30.0)


class _NonPlateSolveCedar:
    """Wraps MockCedar but marks every solve is_plate_solve=False, standing
    in for adapters.mock.echo_cedar.MountEchoCedar's loopback without
    needing the real mount plumbing."""

    def __init__(self, inner: MockCedar) -> None:
        self._inner = inner

    async def get_latest_solve(self):
        solve = await self._inner.get_latest_solve()
        return solve if solve is None else dataclasses.replace(solve, is_plate_solve=False)

    async def stream_solves(self):
        async for solve in self._inner.stream_solves():
            yield dataclasses.replace(solve, is_plate_solve=False)


class _SyncCountingMount:
    """Spies on sync_to() calls without changing MockMount's behavior."""

    def __init__(self, inner: MockMount) -> None:
        self._inner = inner
        self.sync_calls = 0

    async def slew_to(self, target):
        await self._inner.slew_to(target)

    async def is_slewing(self):
        return await self._inner.is_slewing()

    async def sync_to(self, coord):
        self.sync_calls += 1
        await self._inner.sync_to(coord)

    async def get_equatorial_system(self):
        return await self._inner.get_equatorial_system()

    async def get_position(self):
        return await self._inner.get_position()

    async def abort_slew(self):
        await self._inner.abort_slew()


def make_world(seed: int = 1) -> World:
    import random

    return World(error_model=HarmonicErrorModel(rng=random.Random(seed)))


async def run_to_completion(world: World, config: LoopConfigCore):
    mount = MockMount(world)
    cedar = MockCedar(world)
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())
    statuses = []
    async for status in loop.run(TARGET):
        statuses.append(status)
    return statuses


@pytest.mark.parametrize("strategy", [SlewStrategy.OFFSET, SlewStrategy.SYNC_RESLEW])
async def test_converges_within_max_iterations(strategy: SlewStrategy):
    world = make_world()
    config = LoopConfigCore(strategy=strategy, tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)

    statuses = await run_to_completion(world, config)

    assert statuses[-1].state is LoopState.CONVERGED, [s.state for s in statuses]
    assert statuses[-1].error_arcmin <= config.tolerance_arcmin
    assert statuses[-1].iteration < config.max_iterations


async def test_offset_strategy_reduces_error_each_iteration():
    world = make_world(seed=2)
    config = LoopConfigCore(strategy=SlewStrategy.OFFSET, tolerance_arcmin=0.01, max_iterations=5, settle_s=0.01)

    statuses = await run_to_completion(world, config)

    evaluations = [s for s in statuses if s.state is LoopState.EVALUATE]
    errors = [s.error_arcmin for s in evaluations]
    assert len(errors) >= 2
    # Each pass should not be worse than the first (allowing small noise wiggle).
    assert errors[-1] <= errors[0]


async def test_final_sync_syncs_mount_to_true_target():
    world = make_world()
    config = LoopConfigCore(strategy=SlewStrategy.OFFSET, tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01, final_sync=True)

    statuses = await run_to_completion(world, config)

    assert statuses[-1].state is LoopState.CONVERGED
    assert angular_separation_deg(world.true_pointing, TARGET) < 1e-6


async def test_final_sync_skipped_when_solve_is_not_a_real_plate_solve():
    """MountEchoCedar-like loopback solves must never sync the mount's
    persistent alignment/sync-point database against its own
    already-possibly-wrong belief (found 2026-07-22, SolveResult.is_plate_solve)."""
    world = make_world()
    cedar = _NonPlateSolveCedar(MockCedar(world))
    mount = _SyncCountingMount(MockMount(world))
    config = LoopConfigCore(
        strategy=SlewStrategy.OFFSET, tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01, final_sync=True
    )
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())

    statuses = [s async for s in loop.run(TARGET)]

    assert statuses[-1].state is LoopState.CONVERGED
    assert "sync skipped" in statuses[-1].message
    assert mount.sync_calls == 0


async def test_sync_reslew_never_syncs_when_solve_is_not_a_real_plate_solve():
    world = make_world()
    cedar = _NonPlateSolveCedar(MockCedar(world))
    mount = _SyncCountingMount(MockMount(world))
    config = LoopConfigCore(
        strategy=SlewStrategy.SYNC_RESLEW, tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01,
        final_sync=False,
    )
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())

    statuses = [s async for s in loop.run(TARGET)]

    assert statuses[-1].state in (LoopState.CONVERGED, LoopState.FAILED)
    assert mount.sync_calls == 0


async def test_fails_gracefully_when_solves_never_accepted():
    world = make_world()
    world.inject_solve_failures(count=10_000)  # never a good solve
    config = LoopConfigCore(
        strategy=SlewStrategy.OFFSET, tolerance_arcmin=1.0, max_iterations=3,
        settle_s=0.01, solve_wait_timeout_s=0.2,
    )

    statuses = await run_to_completion(world, config)

    assert statuses[-1].state is LoopState.FAILED
    assert "no acceptable solve" in statuses[-1].message


async def test_abort_stops_the_loop():
    world = make_world()
    config = LoopConfigCore(strategy=SlewStrategy.OFFSET, settle_s=0.5)
    mount = MockMount(world)
    cedar = MockCedar(world)
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())

    statuses = []
    from cedar_goto.core.loop import SlewAborted

    with pytest.raises(SlewAborted):
        async for status in loop.run(TARGET):
            statuses.append(status)
            if status.state is LoopState.SLEWING_MOUNT:
                loop.abort()
