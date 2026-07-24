"""Convergence tests for ClosedLoopSlew against the mock harness (DESIGN.md §9a).

Runs entirely against mocks: no hardware, no daylight-blocked plate solving.
"""
from __future__ import annotations

import pytest

from cedar_goto.adapters.mock.cedar import MockCedar
from cedar_goto.adapters.mock.mount import MockMount
from cedar_goto.adapters.mock.world import HarmonicErrorModel, World
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.loop import ClosedLoopSlew, LoopConfigCore, LoopState
from cedar_goto.core.solve import SolveAcceptance

TARGET = CelestialCoord(ra_deg=120.0, dec_deg=30.0)


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


async def test_converges_within_max_iterations():
    world = make_world()
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)

    statuses = await run_to_completion(world, config)

    assert statuses[-1].state is LoopState.CONVERGED, [s.state for s in statuses]
    assert statuses[-1].error_arcmin <= config.tolerance_arcmin
    assert statuses[-1].iteration < config.max_iterations


async def test_reduces_error_each_iteration():
    world = make_world(seed=2)
    config = LoopConfigCore(tolerance_arcmin=0.01, max_iterations=5, settle_s=0.01)

    statuses = await run_to_completion(world, config)

    evaluations = [s for s in statuses if s.state is LoopState.EVALUATE]
    errors = [s.error_arcmin for s in evaluations]
    assert len(errors) >= 2
    # Each pass should not be worse than the first (allowing small noise wiggle).
    assert errors[-1] <= errors[0]


async def test_convergence_never_syncs_the_mount():
    """The loop must never call mount.sync_to() on its own anymore (found
    2026-07-24: auto-syncing to cedar's solve on every converged slew
    corrupted a real mount's own accurate alignment model, since cedar's
    solve can be systematically offset from the main scope's optical axis
    -- e.g. a mechanically misaligned finder box). Syncing is now a manual,
    user-confirmed action (ClosedLoopTelescopeBackend.sync_to_target())."""
    world = make_world()
    mount = _SyncCountingMount(MockMount(world))
    cedar = MockCedar(world)
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())

    statuses = [s async for s in loop.run(TARGET)]

    assert statuses[-1].state is LoopState.CONVERGED
    assert mount.sync_calls == 0


async def test_out_of_range_when_error_exceeds_max_correction():
    """A solve far outside max_correction_arcmin must not be auto-nudged --
    more likely a bad solve/mismatch than real pointing error."""
    world = make_world()
    mount = _SyncCountingMount(MockMount(world))
    cedar = MockCedar(world)
    config = LoopConfigCore(
        tolerance_arcmin=0.01, max_correction_arcmin=1.0, max_iterations=3, settle_s=0.01,
    )
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())

    statuses = [s async for s in loop.run(TARGET)]

    assert statuses[-1].state is LoopState.OUT_OF_RANGE, [s.state for s in statuses]
    assert statuses[-1].error_arcmin > config.max_correction_arcmin
    assert statuses[-1].iteration == 0  # no nudge attempted
    assert mount.sync_calls == 0


async def test_fails_gracefully_when_solves_never_accepted():
    world = make_world()
    world.inject_solve_failures(count=10_000)  # never a good solve
    config = LoopConfigCore(
        tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01, solve_wait_timeout_s=0.2,
    )

    statuses = await run_to_completion(world, config)

    assert statuses[-1].state is LoopState.FAILED
    assert "no acceptable solve" in statuses[-1].message


async def test_abort_stops_the_loop():
    world = make_world()
    config = LoopConfigCore(settle_s=0.5)
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
