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

        while True:
            self._check_abort()
            yield LoopStatus(LoopState.SLEWING_MOUNT, iteration, true_target, commanded)
            await self._mount.slew_to(commanded)
            await self._wait_for_settle()

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
