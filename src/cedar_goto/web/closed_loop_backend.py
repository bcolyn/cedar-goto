"""Phase 2 (DESIGN.md §5, §10): wraps a plain TelescopeBackend so
SlewToCoordinates(Async) runs the closed loop instead of a bare proxy.

Everything else -- Tracking, capability flags, park, etc. -- still proxies
straight through to `inner`, unchanged from Phase 1 (DESIGN.md §3:
"transparent proxy", intercept only the slew).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from cedar_goto.adapters.buzzer import Buzzer, NullBuzzer
from cedar_goto.config import PositionSourceConfig
from cedar_goto.core.coords import J2000, CelestialCoord
from cedar_goto.core.loop import (
    ClosedLoopSlew,
    LoopConfigCore,
    LoopState,
    LoopStatus,
    SlewAborted,
    SlewTimedOut,
)
from cedar_goto.core.ports import MountControl, SolveSource
from cedar_goto.core.solve import SolveAcceptance, SolveResult
from cedar_goto.web.alpaca_errors import ParkedError
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION, Member
from cedar_goto.web.backend import TelescopeBackend

logger = logging.getLogger(__name__)

_SLEW_MEMBERS = frozenset({"SlewToCoordinates", "SlewToCoordinatesAsync"})
_AT_PARK_MEMBER = ALL_MEMBERS_BY_ACTION["atpark"]


class SyncRefused(Exception):
    """Raised by sync_to_cedar() when refusing for a reason more specific
    than "nothing acceptable yet" -- currently just solve.is_plate_solve
    being False (e.g. MountEchoCedar's loopback). Distinct from returning
    None, which covers the routine "cedar hasn't produced a good solve
    yet" case."""


class CorrectionRefused(Exception):
    """Raised by correct_now() when a closed loop is already running --
    distinct from returning None ("nothing to correct to yet"), since the
    fix is different: abort first, rather than slew somewhere first."""


class ClosedLoopTelescopeBackend:
    def __init__(
        self,
        inner: TelescopeBackend,
        mount: MountControl,
        cedar: SolveSource,
        loop_config: LoopConfigCore,
        acceptance: SolveAcceptance,
        position_config: PositionSourceConfig,
        buzzer: Buzzer | None = None,
        correction_enabled: bool = True,
        on_correction_changed: Callable[[bool], None] | None = None,
    ) -> None:
        self._inner = inner
        self._mount = mount
        self._cedar = cedar
        self._loop_config = loop_config
        self._acceptance = acceptance
        self._position_config = position_config
        self._buzzer = buzzer if buzzer is not None else NullBuzzer()
        self._task: asyncio.Task | None = None
        self._current_loop: ClosedLoopSlew | None = None
        self._last_status: LoopStatus | None = None
        self._last_target: CelestialCoord | None = None
        self._correction_enabled = correction_enabled
        self._on_correction_changed = on_correction_changed

    @property
    def last_status(self) -> LoopStatus | None:
        return self._last_status

    def set_correction_enabled(self, enabled: bool) -> None:
        """Web UI "auto-correction" toggle. Takes effect on the *next* slew
        only -- doesn't abort a closed-loop slew already in progress. With
        correction off, SlewToCoordinates(Async) is a bare proxy to `inner`
        (Phase 1 behavior): no cedar feedback, no nudging, just the GoTo as
        commanded -- for when cedar's solves aren't trustworthy enough to
        act on automatically right now, without having to restart the
        service to change config.

        on_correction_changed (state.py, wired in __main__.py) persists this
        across restarts -- deliberately a callback rather than this class
        doing file I/O itself, so the closed-loop logic stays independent of
        where/how (or whether) the host process persists it."""
        self._correction_enabled = enabled
        if self._on_correction_changed is not None:
            self._on_correction_changed(enabled)

    async def get(self, member: Member):
        if member.name == "Slewing":
            if self._loop_active():
                return True
            if not self._correction_enabled:
                # No loop task drives Slewing while correction is off (see
                # _start_slew) -- fall back to the mount's own idea of
                # whether it's still moving, same as a plain proxy.
                return await self._inner.get(member)
            return False
        if member.name in ("RightAscension", "Declination") and self._position_config.source != "mount":
            position = await self._cedar_position()
            if position is not None:
                ra_hours, dec_deg = position
                return ra_hours if member.name == "RightAscension" else dec_deg
        return await self._inner.get(member)

    async def put(self, member: Member, params: dict):
        if member.name in _SLEW_MEMBERS:
            return await self._start_slew(member, params, wait=(member.name == "SlewToCoordinates"))
        if member.name == "AbortSlew":
            # abort() alone is only a cooperative signal -- confirmed live
            # that a task blocked inside a solve-wait RPC stays in
            # AWAIT_SOLVE indefinitely even after this fires unless actually
            # cancelled. This didn't hang AbortSlew itself (it never awaited
            # the task), but it meant Abort silently failed to really stop
            # the loop.
            if self._loop_active():
                self._current_loop.abort()
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
                await self._cedar.notify_slew_stopped()
            return await self._inner.put(member, params)
        if member.name == "Park":
            # Parking mid-slew must not race the loop's next slew_to/sync_to
            # -- stop it first and wait for the background task to actually
            # exit before handing off to the mount. abort() alone is only a
            # cooperative signal the loop checks between its own awaits --
            # confirmed live that it does NOT interrupt a task already
            # blocked inside a solve-wait RPC (AWAIT_SOLVE with no solve
            # forthcoming), which hung this handler indefinitely. cancel()
            # forces it.
            if self._loop_active():
                self._current_loop.abort()
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
                await self._cedar.notify_slew_stopped()
            return await self._inner.put(member, params)
        return await self._inner.put(member, params)

    async def query(self, member: Member, params: dict):
        return await self._inner.query(member, params)

    def _loop_active(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _start_slew(self, member: Member, params: dict, wait: bool):
        # Fail fast before touching loop/cedar state at all -- AtPark is a
        # cheap cached read (see IndiTelescopeBackend._slew), so this costs
        # nothing and gives the client the ParkedException it expects instead
        # of a slew attempt that the mount silently ignores or hangs on.
        if await self._inner.get(_AT_PARK_MEMBER):
            raise ParkedError("Cannot slew while the mount is parked -- unpark first")
        target = CelestialCoord(
            ra_deg=params["RightAscension"] * 15.0, dec_deg=params["Declination"], epoch=J2000
        )
        self._last_target = target
        # cedar-goto intercepts the ASCOM slew and drives the mount itself,
        # so without this cedar-server never learns a GoTo is happening and
        # can't offer its own push-to guidance (SlewRequest fields in
        # FrameResult) -- e.g. for a client jogging the mount by hand while
        # watching cedar's live view. Left active (no notify_slew_stopped
        # here) through CONVERGED/FAILED/OUT_OF_RANGE -- the whole point of
        # this design is that the human may still need to nudge onto target
        # after the automatic correction is done. Cleared explicitly by
        # AbortSlew/Park or once the user confirms via sync_to_target().
        await self._cedar.notify_slew_started(target)
        if self._loop_active():
            # A new slew supersedes whatever's in progress -- abort it and
            # wait for the task to actually stop before starting the next.
            # Same hang risk as Park() above: abort() alone can't interrupt
            # a task blocked inside a solve-wait RPC, so force it.
            self._current_loop.abort()
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

        if not self._correction_enabled:
            # Bare proxy slew, same as before the closed loop existed --
            # remembers the target (for a later manual "sync to target")
            # but applies no cedar-driven correction at all.
            return await self._inner.put(member, params)

        self._launch_loop(target)
        if wait:
            await self._task
        return None

    def _launch_loop(self, target: CelestialCoord) -> None:
        self._current_loop = ClosedLoopSlew(self._mount, self._cedar, self._loop_config, self._acceptance)
        self._task = asyncio.create_task(self._run_loop(self._current_loop, target))

    async def _run_loop(self, loop: ClosedLoopSlew, target: CelestialCoord) -> None:
        iteration = self._last_status.iteration if self._last_status else 0
        try:
            async for status in loop.run(target):
                self._last_status = status
                iteration = status.iteration
                logger.info("closed-loop slew: %s", status)
            if self._last_status is not None:
                self._beep_for(self._last_status.state)
        except SlewAborted:
            logger.info("closed-loop slew aborted")
        except SlewTimedOut as exc:
            logger.warning("closed-loop slew timed out: %s", exc)
            self._buzzer.failure()
        except Exception:
            # A mount/cedar error here would otherwise kill this background
            # task silently -- Slewing just quietly goes false with no
            # trace of why (bit us testing against a real mount that
            # started parked). Surface it in both the log and last_status.
            logger.exception("closed-loop slew failed unexpectedly")
            self._last_status = LoopStatus(
                LoopState.FAILED, iteration, target, message="unexpected error, see server log"
            )
            self._buzzer.failure()

    def _beep_for(self, state: LoopState) -> None:
        if state is LoopState.CONVERGED:
            self._buzzer.success()
        elif state is LoopState.FAILED:
            self._buzzer.failure()

    async def abort(self) -> None:
        """Same effect as the Alpaca AbortSlew action -- exposed directly
        for the web UI (DESIGN.md §8) so it doesn't need to round-trip
        through its own HTTP API."""
        await self.put(ALL_MEMBERS_BY_ACTION["abortslew"], {})

    async def get_sync_point_count(self) -> int | None:
        """None if `inner` doesn't support this (only IndiTelescopeBackend
        does -- mount alignment/sync points aren't an ASCOM concept, so
        mock/alpyca have no equivalent)."""
        get = getattr(self._inner, "get_sync_point_count", None)
        return await get() if get is not None else None

    async def clear_sync_points(self) -> bool:
        """Returns False (no-op) if `inner` doesn't support this."""
        clear = getattr(self._inner, "clear_sync_points", None)
        if clear is None:
            return False
        await clear()
        return True

    async def sync_to_cedar(self) -> SolveResult | None:
        """Web UI "sync now" action (DESIGN.md §8): sync the mount straight
        to cedar's current plate-solved position, bypassing the closed
        loop. Returns the solve used, or None if cedar has nothing
        acceptable right now (the routine case -- no solve yet, or it
        didn't pass SolveAcceptance).

        Raises SyncRefused instead of returning None when the solve exists
        but isn't a real plate solve (e.g. MountEchoCedar's loopback) --
        syncing the mount's persistent alignment/sync-point database
        against its own already-possibly-wrong belief would corrupt it, and
        that's a distinct, more actionable problem than "nothing yet". See
        SolveResult.is_plate_solve."""
        solve = await self._cedar.get_latest_solve()
        if solve is None:
            return None
        if not solve.is_plate_solve:
            raise SyncRefused("solve source is not a real plate solve (e.g. MountEchoCedar loopback)")
        if not self._acceptance.accepts(solve):
            return None
        await self._mount.sync_to(solve.sky_coord)
        return solve

    async def sync_to_target(self) -> CelestialCoord | None:
        """Web UI "sync to target" action: the user has manually centered
        the requested target in the main scope (whether the closed loop got
        it close via cedar's plate solves, or the slew was a bare proxy with
        correction disabled) and confirms the mount is now actually there.
        Syncs to the originally-commanded coordinate, not to cedar's solve --
        deliberately independent of cedar, since cedar's own solve may be
        systematically offset from the main scope's optical axis (e.g. a
        mechanically misaligned finder box) and is exactly what a human
        centering in the main scope corrects for.

        Returns the target synced to, or None if there's no completed slew
        to sync to yet, or one is still in progress (synced while it's
        still moving the mount out from under the user)."""
        if self._loop_active() or self._last_target is None:
            return None
        target = self._last_target
        await self._mount.sync_to(target)
        await self._cedar.notify_slew_stopped()
        return target

    async def correct_now(self) -> CelestialCoord | None:
        """Web UI "correct now" action: run the closed loop against the last
        commanded target on demand, without waiting for a fresh slew from the
        client. This is the escape hatch for auto-correction being off (or
        the slew having already finished) and the user then deciding they do
        want cedar to nudge after all -- otherwise the only way to get a
        correction is to re-issue the GoTo from the planetarium app.

        Deliberately ignores _correction_enabled: that toggle governs what
        happens automatically on a slew, and pressing this button *is* the
        user asking for correction explicitly.

        Returns the target being corrected to (the loop then runs in the
        background, reported via status_snapshot like any other slew), or
        None if no slew has been commanded yet. Raises CorrectionRefused if
        a loop is already running."""
        if self._loop_active():
            raise CorrectionRefused("a closed-loop slew is already running -- abort it first")
        if self._last_target is None:
            return None
        target = self._last_target
        # sync_to_target()/AbortSlew/Park may already have told cedar the
        # slew is over, so re-arm its push-to guidance for this target --
        # notify_slew_started is idempotent from cedar's point of view.
        await self._cedar.notify_slew_started(target)
        self._launch_loop(target)
        return target

    def status_snapshot(self) -> dict:
        status = self._last_status
        result: dict = {
            "correction_enabled": self._correction_enabled,
            "last_target": _coord_dict(self._last_target) if self._last_target else None,
        }
        if status is None:
            result["state"] = "IDLE"
            return result
        result.update(
            {
                "state": status.state.name,
                "iteration": status.iteration,
                "commanded": _coord_dict(status.commanded) if status.commanded else None,
                "error_arcmin": status.error_arcmin,
                "message": status.message,
                "last_solve": _solve_dict(status.last_solve) if status.last_solve else None,
            }
        )
        return result

    async def _cedar_position(self) -> tuple[float, float] | None:
        """DESIGN.md §3 "Reported position": cedar-preferred with mount
        fallback -- returns None (falls back to inner/mount) when cedar has
        no fresh, acceptable solve. Reports cedar's coordinate directly in
        J2000 rather than converting to the mount's advertised
        EquatorialSystem -- an acceptable Phase 2 simplification since
        cedar-goto normalizes internally to J2000 (DESIGN.md §4); exact
        epoch-matching for strict clients is a follow-up if it matters in
        practice.

        A cedar-server outage (unreachable, gRPC error -- not just "no
        solve yet") must degrade the same way: "cedar_fallback_mount"
        promises falling back to the mount's own position, not surfacing a
        driver error on every position poll. Found 2026-07-22: this call
        was unguarded, unlike sync_to_cedar and the closed loop itself,
        both of which already tolerate a missing/rejected solve."""
        try:
            solve = await self._cedar.get_latest_solve()
        except Exception as exc:
            logger.warning("cedar solve source unavailable (%r), falling back to mount position", exc)
            return None
        if solve is None:
            return None
        if solve.capture_time_unix < time.time() - self._position_config.max_solve_age_s:
            return None
        if not self._acceptance.accepts(solve):
            return None
        coord = solve.sky_coord
        return coord.ra_deg / 15.0, coord.dec_deg


def _coord_dict(coord: CelestialCoord) -> dict:
    return {"ra_deg": coord.ra_deg, "dec_deg": coord.dec_deg, "epoch": coord.epoch}


def _solve_dict(solve: SolveResult) -> dict:
    return {
        "sky_coord": _coord_dict(solve.sky_coord),
        "capture_time_unix": solve.capture_time_unix,
        "num_matches": solve.num_matches,
        "prob": solve.prob,
        "p90_error_arcsec": solve.p90_error_arcsec,
        "solution_from_imu": solve.solution_from_imu,
    }
