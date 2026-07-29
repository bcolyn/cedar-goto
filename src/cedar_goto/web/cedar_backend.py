"""Wraps a plain TelescopeBackend with the cedar-facilitation actions the
web UI exposes -- syncing the mount to cedar's plate solve, syncing to the
last commanded target, and re-slewing to it (web/ui.py). SlewToCoordinates
(Async) and every other Alpaca member proxy straight through to `inner`
unchanged; this class does not drive the mount itself beyond what the user
explicitly requests via those actions -- no automatic correction loop. GoTo
accuracy is normally good enough once there's a nearby sync point, and the
human decides when (or whether) cedar should get involved.
"""
from __future__ import annotations

import logging
import time

from cedar_goto.config import PositionSourceConfig
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.ports import MountControl, SolveSource
from cedar_goto.core.solve import SolveAcceptance, SolveResult
from cedar_goto.web.alpaca_errors import ParkedError
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION, Member
from cedar_goto.web.backend import TelescopeBackend

logger = logging.getLogger(__name__)

_SLEW_MEMBERS = frozenset({"SlewToCoordinates", "SlewToCoordinatesAsync"})
_AT_PARK_MEMBER = ALL_MEMBERS_BY_ACTION["atpark"]

# How long a fetched cedar position is reused for reported RightAscension/
# Declination -- see _cached_cedar_position(). Matched to cedar's own ~1 Hz
# solve cadence: a shorter TTL cannot return fresher data, it just re-fetches
# the same solve at 75 ms a time. First tried at 0.2 s, which was too short to
# help a real client -- an ASCOM client polling every few hundred ms missed
# the window on every refresh, and only the RA/Dec pair read milliseconds
# apart ever hit. Only the *reported* position is cached; sync_to_cedar() and
# the slew paths call get_latest_solve() directly and are unaffected.
_POSITION_CACHE_TTL_S = 1.0


class SyncRefused(Exception):
    """Raised by sync_to_cedar() when refusing for a reason more specific
    than "nothing acceptable yet" -- currently just solve.is_plate_solve
    being False (e.g. MountEchoCedar's loopback). Distinct from returning
    None, which covers the routine "cedar hasn't produced a good solve
    yet" case."""


class CedarTelescopeBackend:
    def __init__(
        self,
        inner: TelescopeBackend,
        mount: MountControl,
        cedar: SolveSource,
        acceptance: SolveAcceptance,
        position_config: PositionSourceConfig,
    ) -> None:
        self._inner = inner
        self._mount = mount
        self._cedar = cedar
        self._acceptance = acceptance
        self._position_config = position_config
        self._last_target: CelestialCoord | None = None
        self._last_target_time_unix: float | None = None
        self._position_cache: tuple[float, float] | None = None
        self._position_cached: bool = False
        self._position_cache_at: float = 0.0

    async def get(self, member: Member):
        if member.name in ("RightAscension", "Declination") and self._position_config.source != "mount":
            position = await self._cached_cedar_position()
            if position is not None:
                ra_hours, dec_deg = position
                return ra_hours if member.name == "RightAscension" else dec_deg
        return await self._inner.get(member)

    async def put(self, member: Member, params: dict):
        if member.name in _SLEW_MEMBERS:
            return await self._start_slew(member, params)
        if member.name in ("AbortSlew", "Park"):
            # Tell cedar the targeting session is over so it stops offering
            # push-to guidance (SlewRequest fields in FrameResult) -- pairs
            # with notify_slew_started in _start_slew below.
            await self._cedar.notify_slew_stopped()
        return await self._inner.put(member, params)

    async def query(self, member: Member, params: dict):
        return await self._inner.query(member, params)

    async def _start_slew(self, member: Member, params: dict):
        # Fail fast before touching cedar state at all -- AtPark is a cheap
        # cached read (see IndiTelescopeBackend._slew), so this costs
        # nothing and gives the client the ParkedException it expects
        # instead of a slew attempt the mount silently ignores or hangs on.
        if await self._inner.get(_AT_PARK_MEMBER):
            raise ParkedError("Cannot slew while the mount is parked -- unpark first")
        # Tagged with the mount's own advertised epoch, not a hardcoded
        # J2000 (epoch-seam decision, 2026-07-26): an Alpaca/INDI client is
        # required to send coordinates in whatever epoch this device's own
        # EquatorialSystem advertises (JNow for the real INDI mount).
        target = CelestialCoord(
            ra_deg=params["RightAscension"] * 15.0,
            dec_deg=params["Declination"],
            epoch=await self._mount.get_equatorial_system(),
        )
        self._last_target = target
        self._last_target_time_unix = time.time()
        # cedar-goto intercepts the ASCOM slew, so without this cedar-server
        # never learns a GoTo is happening and can't offer its own push-to
        # guidance -- e.g. for a client jogging the mount by hand while
        # watching cedar's live view. Left active through the slew's
        # completion, cleared explicitly by AbortSlew/Park or once the user
        # confirms via sync_to_target().
        await self._cedar.notify_slew_started(target)
        return await self._inner.put(member, params)

    async def abort(self) -> None:
        """Same effect as the Alpaca AbortSlew action -- exposed directly
        for the web UI so it doesn't need to round-trip through its own
        HTTP API."""
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
        """Web UI "sync mount to cedar" action: sync the mount straight to
        cedar's current plate-solved position. Returns the solve used, or
        None if cedar has nothing acceptable right now (the routine case --
        no solve yet, or it didn't pass SolveAcceptance).

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

    async def realign_cedar(self) -> None:
        """Web UI "Realign" action: tell cedar-server to update/refine its
        boresight offset now, using whatever's currently centered in the
        telescope's field of view (SolveSource.capture_boresight(),
        cedar.proto ActionRequest.capture_boresight) -- the same effect as
        pressing Realign in cedar-server's own UI. No refusal/precondition
        checks here: cedar-server itself decides whether it's in a state to
        act on this."""
        await self._cedar.capture_boresight()

    async def sync_to_target(self) -> CelestialCoord | None:
        """Web UI "sync mount to target" action: the user has manually
        centered the last commanded target in the main scope and confirms
        the mount is now actually there. Syncs to the originally-commanded
        coordinate, not to cedar's solve -- deliberately independent of
        cedar, since cedar's own solve may be systematically offset from
        the main scope's optical axis (e.g. a mechanically misaligned
        finder box), which is exactly what a human centering in the main
        scope corrects for.

        Returns the target synced to, or None if nothing's been commanded
        yet."""
        if self._last_target is None:
            return None
        target = self._last_target
        await self._mount.sync_to(target)
        await self._cedar.notify_slew_stopped()
        return target

    async def reslew_to_target(self) -> CelestialCoord | None:
        """Web UI "slew mount to target" action: a single, direct
        mount.slew_to() repeat of the last commanded GoTo -- no solving, no
        iteration. GoTo accuracy is normally good enough once there's a
        nearby sync point; this is the plain mechanical retry a user
        reaches for, fully explicit and predictable.

        Returns the target slewed to, or None if nothing's been commanded
        yet."""
        if self._last_target is None:
            return None
        target = self._last_target
        await self._mount.slew_to(target)
        return target

    async def status_snapshot(self) -> dict:
        """Web UI dashboard status (web/ui.py): last commanded target and
        cedar's current solve, queried live on every call -- there's no
        background task tracking this anymore, so "last solve" reflects
        whatever cedar reports right now, not a cached evaluation."""
        result: dict = {
            "last_target": _coord_dict(self._last_target) if self._last_target else None,
            "last_target_time_unix": self._last_target_time_unix,
        }
        try:
            solve = await self._cedar.get_latest_solve()
        except Exception as exc:
            logger.warning("cedar solve source unavailable (%r) while building status snapshot", exc)
            solve = None
        result["last_solve"] = _solve_dict(solve) if solve is not None else None
        return result

    async def _cached_cedar_position(self) -> tuple[float, float] | None:
        """_cedar_position() memoised for _POSITION_CACHE_TTL_S.

        Measured on the Pi 2026-07-29: get_latest_solve() costs 75 ms median
        (57-109 ms), and it is the *only* slow thing cedar-goto does -- every
        other Alpaca member answers in 5-6 ms straight from the mount. An
        ASCOM client reads RightAscension and Declination as two separate
        requests milliseconds apart, so an uncached refresh pays it twice,
        ~150 ms, and gets the identical solve back both times: cedar solves
        at roughly 1 Hz, far slower than clients poll.

        Why this is worth a cache rather than accepted latency: SkySafari
        opens a fresh TCP connection per Alpaca call, and over WiFi a reply
        that late arrives after the phone's radio has dozed, so the AP
        buffers it to the next DTIM and retries it. That presents as
        downlink packet loss and cost days of chasing RF causes that were
        never there -- see cedar-total's CLAUDE.md. cedar-server answers the
        same calls in 2 ms and was rock-solid on the identical radio; that
        contrast is what located this.

        The TTL is deliberately far shorter than cedar's solve cadence, so
        this mostly just collapses the RA/Dec pair into one fetch rather
        than serving genuinely old positions.
        """
        now = time.monotonic()
        if self._position_cached and now - self._position_cache_at < _POSITION_CACHE_TTL_S:
            return self._position_cache
        position = await self._cedar_position()
        # A None (no solve yet, or cedar unreachable) is cached too -- it
        # costs exactly as much to discover as a real solve, and indoors
        # with nothing to solve it is the common case. Hence the separate
        # _position_cached flag: None is a cacheable value here, not a
        # "nothing cached" marker.
        self._position_cache = position
        self._position_cached = True
        self._position_cache_at = now
        return position

    async def _cedar_position(self) -> tuple[float, float] | None:
        """DESIGN.md §3 "Reported position": cedar-preferred with mount
        fallback -- returns None (falls back to inner/mount) when cedar has
        no fresh, acceptable solve. `self._cedar` is expected to already be
        an EpochNormalizingSolveSource (wired in __main__._build_backend),
        so solve.sky_coord arrives in the mount's own advertised epoch, not
        raw J2000 -- this can report it as-is instead of converting here.

        A cedar-server outage (unreachable, gRPC error -- not just "no
        solve yet") must degrade the same way: "cedar_fallback_mount"
        promises falling back to the mount's own position, not surfacing a
        driver error on every position poll."""
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
