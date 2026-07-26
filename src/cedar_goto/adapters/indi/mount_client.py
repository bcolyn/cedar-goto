"""MountControl adapter over direct INDI (indi-refactor.md) instead of
through indi_alpaca_server, which has a confirmed bug (stale property
snapshot taken at its own connect time) that silently breaks Alpaca-driven
slews on this mount -- ON_COORD_SET/EQUATORIAL_EOD_COORD end up invisible to
it. Mirrors AlpacaMountClient (adapters/alpaca/mount_client.py); see
indi-refactor.md's property mapping table for the INDI side of each
MountControl method.
"""
from __future__ import annotations

import asyncio
import time

from cedar_goto.adapters.indi.client import IndiConnection
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.ports import MountControl

_EQUATORIAL_EOD_COORD = "EQUATORIAL_EOD_COORD"
_ON_COORD_SET = "ON_COORD_SET"
_TELESCOPE_SLEW_RATE = "TELESCOPE_SLEW_RATE"
_TELESCOPE_MOTION_NS = "TELESCOPE_MOTION_NS"
_TELESCOPE_MOTION_WE = "TELESCOPE_MOTION_WE"
_ALIGNMENT_POINTSET_SIZE = "ALIGNMENT_POINTSET_SIZE"
_ALIGNMENT_POINTSET_ACTION = "ALIGNMENT_POINTSET_ACTION"
_ALIGNMENT_POINTSET_COMMIT = "ALIGNMENT_POINTSET_COMMIT"
_ALIGNMENT_POINTSET_CURRENT_ENTRY = "ALIGNMENT_POINTSET_CURRENT_ENTRY"
_ALIGNMENT_POINT_MANDATORY_NUMBERS = "ALIGNMENT_POINT_MANDATORY_NUMBERS"
_ALIGNMENT_POINT_ENTRY_RA = "ALIGNMENT_POINT_ENTRY_RA"
_ALIGNMENT_POINT_ENTRY_DEC = "ALIGNMENT_POINT_ENTRY_DEC"
_CORRECTION_SLEW_RATE = "1x"
"""TELESCOPE_SLEW_RATE elements are 1x..9x plus SLEW_MAX, labeled
0.5x/1x/2x/4x/8x/16x/32x/64x/128x sidereal respectively (confirmed live
2026-07-25). '1x' (0.5x sidereal, the slowest preset) is confirmed live
by eye -- pushing the gamepad's jog stick to the edge at this rate is slow
enough to center a star by hand. This is used only for the duration of a
closed-loop correction (see
IndiMountClient.prepare_for_correction/restore_after_correction), not a
permanent change."""

# nudge_to() tuning: short jog bursts via TELESCOPE_MOTION_NS/WE with
# encoder-position feedback after each one, instead of a fresh GOTO for
# small corrections -- found live 2026-07-26 that re-issuing GOTOs
# (ON_COORD_SET=TRACK + EQUATORIAL_EOD_COORD) for small corrections invokes
# this mount's own pointing-model/backlash-approach logic, which is
# unreliable once already roughly on-target (a correction iteration moved
# the boresight the wrong way entirely). Mirrors manual jog-button final
# centering. TELESCOPE_TIMED_GUIDE_NS/WE (ASCOM PulseGuide) was tried first
# and rejected -- confirmed live it produces near-zero real motion on this
# mount/driver regardless of GUIDE_RATES or TELESCOPE_TRACK_STATE, so
# there's no reliable rate to convert a desired correction into a pulse
# duration. Live jog-speed measurements at various TELESCOPE_SLEW_RATE
# presets were inconsistent (330-450"/s measured, vs. the mount visibly
# being eyeball-slow to a human at the same presets) -- rather than trust
# an assumed rate for open-loop timing, each burst is short and capped, and
# actual progress is measured via EQUATORIAL_EOD_COORD after each one.
_NUDGE_TOLERANCE_ARCSEC = 5.0
_NUDGE_MAX_BURST_S = 0.3
_NUDGE_MIN_BURST_S = 0.05
_NUDGE_SETTLE_S = 0.3
_NUDGE_MAX_ITERATIONS = 60
# Conservative (fast) assumed rate for scaling burst duration down as the
# remaining error shrinks -- picked from the higher end of the inconsistent
# live measurements (330-450"/s) so bursts undershoot rather than overshoot
# as they approach tolerance; the feedback loop corrects under/overshoot
# either way, but undershooting converges faster.
_NUDGE_ASSUMED_MAX_RATE_ARCSEC_S = 450.0


def _current_jyear() -> float:
    from astropy.time import Time

    return Time(time.time(), format="unix").jyear


def _wrap_signed_deg(delta_deg: float) -> float:
    """Wraps an RA delta to (-180, 180] so a target just past 0/360 doesn't
    look like it's almost all the way around instead of a small step."""
    return (delta_deg + 180.0) % 360.0 - 180.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class IndiMountClient(MountControl):
    def __init__(self, conn: IndiConnection) -> None:
        self._conn = conn
        self._saved_slew_rate: str | None = None

    async def prepare_for_correction(self) -> None:
        """Not part of the MountControl Protocol -- ClosedLoopSlew.run()
        getattr's this optional capability and calls it once before driving
        any mount motion, to reduce mechanical overshoot from the closed
        loop's GoTo/re-slew commands. Paired with restore_after_correction()
        in a try/finally, so the original rate always comes back regardless
        of how the loop ends (converged/failed/aborted)."""
        self._saved_slew_rate = await self._conn.get_switch_selection(_TELESCOPE_SLEW_RATE)
        if self._saved_slew_rate is not None:
            await self._conn.set_switch(_TELESCOPE_SLEW_RATE, _CORRECTION_SLEW_RATE)

    async def restore_after_correction(self) -> None:
        if self._saved_slew_rate is not None:
            await self._conn.set_switch(_TELESCOPE_SLEW_RATE, self._saved_slew_rate)
            self._saved_slew_rate = None

    async def get_sync_point_count(self) -> int:
        """Not part of the MountControl Protocol -- mirrors
        IndiTelescopeBackend.get_sync_point_count() (adapters/indi/
        telescope_backend.py), INDI's generic Alignment Subsystem property,
        confirmed present and populated by sync_to() on this driver."""
        values = await self._conn.get_numbers(_ALIGNMENT_POINTSET_SIZE)
        return int(values[_ALIGNMENT_POINTSET_SIZE])

    async def clear_sync_points(self) -> None:
        """Select the CLEAR action then fire COMMIT to execute it -- same
        two-step protocol as IndiTelescopeBackend.clear_sync_points(). Not
        used by the closed loop itself (see delete_sync_point) -- CLEAR wipes
        every point in the set, including ones the user added earlier in the
        session by their own alignment routine, not just the closed loop's
        own transient presync point."""
        await self._conn.set_switch(_ALIGNMENT_POINTSET_ACTION, "CLEAR")
        await self._conn.wait_for_switch_confirmed(_ALIGNMENT_POINTSET_ACTION, "CLEAR")
        await self._conn.set_switch(_ALIGNMENT_POINTSET_COMMIT, _ALIGNMENT_POINTSET_COMMIT)

    async def delete_sync_point(self, index: int) -> None:
        """Deletes a single alignment/sync point at `index` (0-based),
        leaving every other point untouched -- unlike clear_sync_points().
        Select the point via ALIGNMENT_POINTSET_CURRENT_ENTRY, then the same
        select-action-then-commit protocol as clear_sync_points(), with
        DELETE instead of CLEAR. NOT yet confirmed live against real
        hardware (only CLEAR was; the Pi went offline before this could be
        tested) -- verify against a real ALIGNMENT_POINTSET_SIZE change
        before trusting it in the field."""
        await self._conn.set_numbers(_ALIGNMENT_POINTSET_CURRENT_ENTRY, {_ALIGNMENT_POINTSET_CURRENT_ENTRY: index})
        await asyncio.sleep(0.3)  # let the entry pointer settle, matching read_alignment.py's confirmed-live timing
        await self._conn.set_switch(_ALIGNMENT_POINTSET_ACTION, "DELETE")
        await self._conn.wait_for_switch_confirmed(_ALIGNMENT_POINTSET_ACTION, "DELETE")
        await self._conn.set_switch(_ALIGNMENT_POINTSET_COMMIT, _ALIGNMENT_POINTSET_COMMIT)

    async def read_sync_point(self, index: int) -> CelestialCoord:
        """Read the alignment/sync point at `index` (0-based) back out of the
        driver's database, in the mount's own epoch (JNow), like
        get_position(). Select the entry via ALIGNMENT_POINTSET_CURRENT_ENTRY,
        then the same select-action-then-commit protocol as
        delete_sync_point() with READ instead of DELETE, after which
        ALIGNMENT_POINT_MANDATORY_NUMBERS holds that entry (RA in hours, Dec
        in degrees, alongside the direction vector this ignores).

        Confirmed live 2026-07-26: a point synced at RA 16.41768h Dec
        38.99705 read back identical to five decimals. Not used by the
        closed loop -- it exists so a caller can verify *which* points are
        in the database, not merely how many (tests/test_live_indi_
        correction.py), which is the gap a bare ALIGNMENT_POINTSET_SIZE
        check leaves open.
        """
        await self._conn.set_numbers(_ALIGNMENT_POINTSET_CURRENT_ENTRY, {_ALIGNMENT_POINTSET_CURRENT_ENTRY: index})
        await asyncio.sleep(0.3)  # let the entry pointer settle, as in delete_sync_point()
        await self._conn.set_switch(_ALIGNMENT_POINTSET_ACTION, "READ")
        await self._conn.wait_for_switch_confirmed(_ALIGNMENT_POINTSET_ACTION, "READ")
        await self._conn.set_switch(_ALIGNMENT_POINTSET_COMMIT, _ALIGNMENT_POINTSET_COMMIT)
        # The driver publishes the entry a beat after the commit, and unlike
        # ALIGNMENT_POINTSET_SIZE there's no counter to poll for a change --
        # the previous read's values simply sit there until replaced. 0.5s
        # is what was confirmed live; callers reading several points should
        # compare the set they get back rather than trusting each in turn.
        await asyncio.sleep(0.5)
        values = await self._conn.get_numbers(_ALIGNMENT_POINT_MANDATORY_NUMBERS)
        return CelestialCoord(
            ra_deg=values[_ALIGNMENT_POINT_ENTRY_RA] * 15.0,
            dec_deg=values[_ALIGNMENT_POINT_ENTRY_DEC],
            epoch=await self.get_equatorial_system(),
        )

    async def nudge_to(self, target: CelestialCoord) -> None:
        """Not part of the MountControl Protocol -- ClosedLoopSlew.run()
        getattr's this optional capability and, when present, uses it instead
        of slew_to() for correction iterations (everything after the first
        slew of a closed-loop run). Best-effort: gives up after
        _NUDGE_MAX_ITERATIONS regardless of whether tolerance was reached --
        the closed loop's own solve-based EVALUATE is the real accuracy
        check; this only gets the mount close via its own encoders first,
        the same way a human nudges a jog stick while watching the display."""
        mount_target = await self._to_mount_epoch(target)
        for _ in range(_NUDGE_MAX_ITERATIONS):
            pos = await self.get_position()
            dra_arcsec = _wrap_signed_deg(mount_target.ra_deg - pos.ra_deg) * 3600.0
            ddec_arcsec = (mount_target.dec_deg - pos.dec_deg) * 3600.0
            need_ns = abs(ddec_arcsec) > _NUDGE_TOLERANCE_ARCSEC
            need_we = abs(dra_arcsec) > _NUDGE_TOLERANCE_ARCSEC
            if not need_ns and not need_we:
                return

            burst_s = 0.0
            if need_ns:
                ns_burst = _clamp(
                    abs(ddec_arcsec) / _NUDGE_ASSUMED_MAX_RATE_ARCSEC_S, _NUDGE_MIN_BURST_S, _NUDGE_MAX_BURST_S
                )
                burst_s = max(burst_s, ns_burst)
                await self._conn.set_switch(
                    _TELESCOPE_MOTION_NS, "MOTION_NORTH" if ddec_arcsec > 0 else "MOTION_SOUTH"
                )
            if need_we:
                we_burst = _clamp(
                    abs(dra_arcsec) / _NUDGE_ASSUMED_MAX_RATE_ARCSEC_S, _NUDGE_MIN_BURST_S, _NUDGE_MAX_BURST_S
                )
                burst_s = max(burst_s, we_burst)
                await self._conn.set_switch(
                    _TELESCOPE_MOTION_WE, "MOTION_WEST" if dra_arcsec > 0 else "MOTION_EAST"
                )

            await asyncio.sleep(burst_s)
            if need_ns:
                await self._conn.clear_switch(_TELESCOPE_MOTION_NS)
            if need_we:
                await self._conn.clear_switch(_TELESCOPE_MOTION_WE)
            await asyncio.sleep(_NUDGE_SETTLE_S)

    async def slew_to(self, target: CelestialCoord) -> None:
        # ON_COORD_SET=TRACK, not SLEW -- goto-and-track semantics, matching
        # what SlewToCoordinatesAsync is expected to do (indi-refactor.md).
        mount_target = await self._to_mount_epoch(target)
        await self._conn.set_switch(_ON_COORD_SET, "TRACK")
        await self._conn.wait_for_switch_confirmed(_ON_COORD_SET, "TRACK")
        await self._conn.set_numbers(
            _EQUATORIAL_EOD_COORD, {"RA": mount_target.ra_deg / 15.0, "DEC": mount_target.dec_deg}
        )

    async def is_slewing(self) -> bool:
        return await self._conn.is_property_busy(_EQUATORIAL_EOD_COORD)

    async def sync_to(self, coord: CelestialCoord) -> None:
        mount_coord = await self._to_mount_epoch(coord)
        await self._conn.set_switch(_ON_COORD_SET, "SYNC")
        await self._conn.wait_for_switch_confirmed(_ON_COORD_SET, "SYNC")
        await self._conn.set_numbers(
            _EQUATORIAL_EOD_COORD, {"RA": mount_coord.ra_deg / 15.0, "DEC": mount_coord.dec_deg}
        )

    async def get_equatorial_system(self) -> float:
        # This driver family only ever reports JNow (indi-refactor.md) -- no
        # queryable property for it, unlike Alpaca's EquatorialSystem.
        return _current_jyear()

    async def get_position(self) -> CelestialCoord:
        values = await self._conn.get_numbers(_EQUATORIAL_EOD_COORD)
        return CelestialCoord(
            ra_deg=values["RA"] * 15.0,
            dec_deg=values["DEC"],
            epoch=await self.get_equatorial_system(),
        )

    async def abort_slew(self) -> None:
        await self._conn.set_switch("TELESCOPE_ABORT_MOTION", "ABORT")

    async def _to_mount_epoch(self, coord: CelestialCoord) -> CelestialCoord:
        """cedar-goto works internally in J2000 (DESIGN.md §4); convert to
        JNow (this driver's only epoch, indi-refactor.md) before sending."""
        from cedar_goto.core._precession import precess

        mount_epoch = await self.get_equatorial_system()
        return precess(coord, mount_epoch)
