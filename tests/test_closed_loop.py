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


class _LaggingSyncPointMount(_SyncCountingMount):
    """A mount whose sync-point count lags behind sync_to(), like the real
    INDI driver: sync_to() returns as soon as the coordinate is sent, and
    ALIGNMENT_POINTSET_SIZE only reflects the new point a beat later.

    Found live 2026-07-26: reading the count once straight after sync_to()
    always saw the pre-sync value, so the loop never recognized its own
    presync point and never deleted it.
    """

    def __init__(self, inner: MockMount, reads_before_visible: int = 2) -> None:
        super().__init__(inner)
        self._reads_before_visible = reads_before_visible
        self._pending_reads = 0
        self._count = 0
        self.deleted_indices: list[int] = []

    async def sync_to(self, coord):
        await super().sync_to(coord)
        self._pending_reads = self._reads_before_visible

    async def get_sync_point_count(self) -> int:
        if self._pending_reads > 0:
            self._pending_reads -= 1
            if self._pending_reads == 0:
                self._count += 1
        return self._count

    async def delete_sync_point(self, index: int) -> None:
        self.deleted_indices.append(index)
        self._count -= 1


async def test_presync_point_is_deleted_even_when_the_count_lags():
    """Regression for the live 2026-07-26 failure: the loop must wait for
    the mount to publish the new sync-point count instead of reading it
    once, or it leaves a presync point behind on every iteration."""
    world = make_world()
    mount = _LaggingSyncPointMount(MockMount(world))
    cedar = MockCedar(world)
    config = LoopConfigCore(
        tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01, sync_point_poll_interval_s=0.001,
    )
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())

    statuses = [s async for s in loop.run(TARGET)]

    presyncs = [s for s in statuses if s.state is LoopState.PRESYNC]
    assert len(presyncs) >= 1
    # One delete per presync, each removing the point that presync added.
    assert len(mount.deleted_indices) == mount.sync_calls
    assert mount.deleted_indices == [0] * mount.sync_calls
    assert await mount.get_sync_point_count() == 0, "presync points must not accumulate"


async def test_presync_tolerates_a_sync_that_records_no_point():
    """The real driver silently declines to record a point while parked
    ("Sync ... in park position") -- there is then nothing to delete, and
    the loop must carry on rather than deleting some other point."""
    world = make_world()
    mount = _LaggingSyncPointMount(MockMount(world), reads_before_visible=10_000)
    cedar = MockCedar(world)
    config = LoopConfigCore(
        tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01,
        sync_point_confirm_timeout_s=0.05, sync_point_poll_interval_s=0.001,
    )
    loop = ClosedLoopSlew(mount, cedar, config, SolveAcceptance())

    statuses = [s async for s in loop.run(TARGET)]

    assert statuses[-1].state is LoopState.CONVERGED, [s.state for s in statuses]
    assert mount.deleted_indices == []


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
