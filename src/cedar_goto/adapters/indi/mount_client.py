"""MountControl adapter over direct INDI (indi-refactor.md) instead of
through indi_alpaca_server, which has a confirmed bug (stale property
snapshot taken at its own connect time) that silently breaks Alpaca-driven
slews on this mount -- ON_COORD_SET/EQUATORIAL_EOD_COORD end up invisible to
it. Mirrors AlpacaMountClient (adapters/alpaca/mount_client.py); see
indi-refactor.md's property mapping table for the INDI side of each
MountControl method.
"""
from __future__ import annotations

import time

from cedar_goto.adapters.indi.client import IndiConnection
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.ports import MountControl

_EQUATORIAL_EOD_COORD = "EQUATORIAL_EOD_COORD"
_ON_COORD_SET = "ON_COORD_SET"
_TELESCOPE_SLEW_RATE = "TELESCOPE_SLEW_RATE"
_CORRECTION_SLEW_RATE = "2x"
"""TELESCOPE_SLEW_RATE elements are 1x..9x plus SLEW_MAX, labeled
0.5x/1x/2x/4x/8x/16x/32x/64x/128x sidereal respectively (confirmed live
2026-07-25) -- element '2x' is labeled '1.000000x', i.e. 1x sidereal.
The mount's original default/last-used rate (element '3x', 2x sidereal)
overshoots the target on the closed loop's GoTo/re-slew commands; '1x'
element (0.5x sidereal) was tried first but was too slow in practice (the
closed loop's mount_slewing_timeout_s got nowhere near covering even a
modest slew at that rate). This is used only for the duration of a
closed-loop correction (see
IndiMountClient.prepare_for_correction/restore_after_correction), not a
permanent change."""


def _current_jyear() -> float:
    from astropy.time import Time

    return Time(time.time(), format="unix").jyear


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
