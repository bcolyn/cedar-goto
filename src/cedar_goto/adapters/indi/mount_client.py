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


def _current_jyear() -> float:
    from astropy.time import Time

    return Time(time.time(), format="unix").jyear


class IndiMountClient(MountControl):
    def __init__(self, conn: IndiConnection) -> None:
        self._conn = conn

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
