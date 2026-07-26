"""Closed-loop slew state machine (DESIGN.md §5).

Pure core logic: depends only on the MountControl / SolveSource ports, plus
stdlib asyncio and time. No FastAPI, grpc, or astropy imports here.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum, auto

from cedar_goto.core.coords import CelestialCoord, angular_separation_deg, offset_correction
from cedar_goto.core.ports import MountControl, SolveSource
from cedar_goto.core.solve import SolveAcceptance, SolveResult


class LoopState(Enum):
    IDLE = auto()
    PRESYNC = auto()
    SLEWING_MOUNT = auto()
    SETTLING = auto()
    AWAIT_SOLVE = auto()
    EVALUATE = auto()
    CONVERGED = auto()
    OUT_OF_RANGE = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class LoopConfigCore:
    """Loop tuning parameters, decoupled from the pydantic config module."""

    tolerance_arcmin: float = 1.0
    """Below this, the loop stops nudging and reports CONVERGED -- the
    "min_move" below which further correction isn't worth another slew."""
    max_correction_arcmin: float | None = None
    """Above this, the loop refuses to nudge at all and reports
    OUT_OF_RANGE instead -- a solve this far off the requested target is
    more likely a bad solve/mismatch than real pointing error, and blindly
    slewing on it is the wrong call. None disables the check (unbounded
    nudging, the historical behavior)."""
    max_iterations: int = 3
    settle_s: float = 1.5
    mount_slewing_poll_interval_s: float = 0.25
    mount_slewing_timeout_s: float = 120.0
    solve_wait_timeout_s: float = 15.0
    sync_point_confirm_timeout_s: float = 3.0
    """How long to keep polling for the mount to publish a sync-point count
    above the pre-sync baseline before concluding no point was recorded.
    Measured live 2026-07-26 against the real driver: ~0.1s."""
    sync_point_poll_interval_s: float = 0.1


@dataclass(frozen=True, slots=True)
class LoopStatus:
    """A snapshot emitted as the loop progresses — for Slewing/, web UI, logs."""

    state: LoopState
    iteration: int
    true_target: CelestialCoord
    commanded: CelestialCoord | None = None
    last_solve: SolveResult | None = None
    error_arcmin: float | None = None
    message: str = ""


class SlewAborted(Exception):
    pass


class SlewTimedOut(Exception):
    pass


class ClosedLoopSlew:
    """Runs the closed-loop slew state machine for a single target.

    Usage: `async for status in ClosedLoopSlew(mount, cedar, config, acceptance).run(target):`
    Call `.abort()` from another task to cancel mid-run.
    """

    def __init__(
        self,
        mount: MountControl,
        cedar: SolveSource,
        config: LoopConfigCore,
        acceptance: SolveAcceptance,
    ) -> None:
        self._mount = mount
        self._cedar = cedar
        self._config = config
        self._acceptance = acceptance
        self._abort_event = asyncio.Event()

    def abort(self) -> None:
        self._abort_event.set()

    async def run(self, true_target: CelestialCoord):
        self._abort_event.clear()
        commanded = true_target
        iteration = 0

        # Optional MountControl capability (found live 2026-07-25: this
        # mount's default GoTo speed overshoots the target, which the
        # closed loop then has to correct out over extra iterations).
        # getattr'd rather than added to the MountControl Protocol proper
        # since it's mount-specific and most adapters (Alpaca, mocks) have
        # no equivalent -- a no-op there is correct, not a missing feature.
        prepare_for_correction = getattr(self._mount, "prepare_for_correction", None)
        restore_after_correction = getattr(self._mount, "restore_after_correction", None)
        # Same getattr'd-optional-capability pattern, for the mount's own
        # alignment/pointing-model sync points (INDI's generic Alignment
        # Subsystem). Found live 2026-07-26: a GOTO immediately preceded by
        # syncing the mount to a fresh, boresight-accurate solve of its
        # current position is far more reliable than a bare GOTO relying on
        # whatever alignment already existed -- see the PRESYNC step below.
        # Done fresh every iteration (not just once at the start): each
        # iteration's presync point is deleted again right after its GOTO
        # (delete_sync_point, not clear_sync_points) so the set never grows
        # past whatever the user already had before this run started --
        # confirmed live that leaving points to accumulate destabilizes this
        # mount's pointing model ("go haywire"), but wiping the whole set
        # would also destroy points the user added earlier in the session by
        # their own alignment routine, which isn't ours to discard.
        get_sync_point_count = getattr(self._mount, "get_sync_point_count", None)
        delete_sync_point = getattr(self._mount, "delete_sync_point", None)
        can_presync = get_sync_point_count is not None and delete_sync_point is not None
        if prepare_for_correction is not None:
            await prepare_for_correction()
        try:
            while True:
                our_sync_point_index = None
                if can_presync:
                    self._check_abort()
                    yield LoopStatus(LoopState.PRESYNC, iteration, true_target, commanded)
                    presync_solve = await self._await_fresh_accepted_solve()
                    if presync_solve is not None and presync_solve.is_plate_solve:
                        baseline_count = await get_sync_point_count()
                        await self._mount.sync_to(presync_solve.sky_coord)
                        new_count = await self._await_sync_point_added(
                            get_sync_point_count, baseline_count
                        )
                        if new_count is not None:
                            our_sync_point_index = new_count - 1

                self._check_abort()
                yield LoopStatus(LoopState.SLEWING_MOUNT, iteration, true_target, commanded)
                await self._mount.slew_to(commanded)
                await self._wait_for_settle()

                if our_sync_point_index is not None:
                    await delete_sync_point(our_sync_point_index)

                self._check_abort()
                yield LoopStatus(LoopState.SETTLING, iteration, true_target, commanded)
                await asyncio.sleep(self._config.settle_s)

                self._check_abort()
                yield LoopStatus(LoopState.AWAIT_SOLVE, iteration, true_target, commanded)
                solve = await self._await_fresh_accepted_solve()
                if solve is None:
                    yield LoopStatus(
                        LoopState.FAILED, iteration, true_target, commanded,
                        message="no acceptable solve within timeout",
                    )
                    return

                actual = solve.sky_coord
                error_deg = angular_separation_deg(true_target, actual)
                error_arcmin = error_deg * 60.0
                yield LoopStatus(
                    LoopState.EVALUATE, iteration, true_target, commanded, solve, error_arcmin,
                )

                if error_arcmin <= self._config.tolerance_arcmin:
                    # No automatic sync here -- a plate solve this close is still
                    # not proof the mount is centered on `true_target` for the
                    # user's actual optical path (e.g. a finder-scope/main-scope
                    # offset), only that cedar thinks it is. See
                    # ClosedLoopTelescopeBackend.sync_to_target() for the
                    # manual, user-confirmed sync this replaced.
                    yield LoopStatus(
                        LoopState.CONVERGED, iteration, true_target, commanded, solve, error_arcmin,
                        message="converged",
                    )
                    return

                if (
                    self._config.max_correction_arcmin is not None
                    and error_arcmin > self._config.max_correction_arcmin
                ):
                    yield LoopStatus(
                        LoopState.OUT_OF_RANGE, iteration, true_target, commanded, solve, error_arcmin,
                        message=(
                            f"error {error_arcmin:.1f}' exceeds max_correction_arcmin "
                            f"({self._config.max_correction_arcmin:.1f}') -- not nudging automatically"
                        ),
                    )
                    return

                iteration += 1
                if iteration >= self._config.max_iterations:
                    yield LoopStatus(
                        LoopState.FAILED, iteration, true_target, commanded, solve, error_arcmin,
                        message=f"did not converge within {self._config.max_iterations} iterations",
                    )
                    return

                commanded = offset_correction(true_target, commanded, actual)
        finally:
            if restore_after_correction is not None:
                await restore_after_correction()

    async def _await_sync_point_added(self, get_sync_point_count, baseline_count: int) -> int | None:
        """Poll until the mount publishes a sync-point count above
        `baseline_count`, and return it. None means no point was recorded.

        Reading the count once, immediately after sync_to(), is not enough:
        sync_to() returns as soon as the coordinate has been sent, and the
        driver publishes the updated ALIGNMENT_POINTSET_SIZE about 0.1s
        later (measured live 2026-07-26). That single read therefore saw
        the pre-sync value *every* time, the loop concluded it had added
        nothing, and it skipped deleting its own presync point on every
        iteration -- so the points accumulated across a run, which is
        precisely what destabilizes this mount's pointing model (the
        failure b839170's delete was added to prevent). Same class of race
        as IndiConnection.wait_for_switch_confirmed().

        Returning None is a real outcome, not just a timeout: this driver
        silently declines to record a point while parked (confirmed live,
        "Sync ... in park position"), and there is then nothing to delete.
        """
        deadline = time.monotonic() + self._config.sync_point_confirm_timeout_s
        while True:
            count = await get_sync_point_count()
            if count > baseline_count:
                return count
            if time.monotonic() > deadline:
                return None
            self._check_abort()
            await asyncio.sleep(self._config.sync_point_poll_interval_s)

    async def _wait_for_settle(self) -> None:
        deadline = time.monotonic() + self._config.mount_slewing_timeout_s
        while await self._mount.is_slewing():
            self._check_abort()
            if time.monotonic() > deadline:
                raise SlewTimedOut("mount did not report settled in time")
            await asyncio.sleep(self._config.mount_slewing_poll_interval_s)

    async def _await_fresh_accepted_solve(self) -> SolveResult | None:
        settle_complete_time = time.time()
        try:
            async with asyncio.timeout(self._config.solve_wait_timeout_s):
                async for solve in self._cedar.stream_solves():
                    self._check_abort()
                    if solve.capture_time_unix >= settle_complete_time and self._acceptance.accepts(solve):
                        return solve
        except TimeoutError:
            # Checking a deadline only between yielded solves (the previous
            # approach) is dead code if stream_solves() never yields at all
            # (confirmed live: a capped/idle camera blocks forever inside a
            # single GetFrame RPC, never reaching a per-iteration check).
            # asyncio.timeout() cancels the wait even mid-RPC.
            return None
        return None

    def _check_abort(self) -> None:
        if self._abort_event.is_set():
            raise SlewAborted()
