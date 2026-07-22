"""MountControl adapter over a real Alpaca mount, via alpyca (DESIGN.md §3a, §7).

alpyca's Telescope client is synchronous (blocking HTTP under the hood), so
every call is wrapped in asyncio.to_thread to fit the async MountControl port.

Not yet exercised against real hardware (Wave 150i via INDI->Alpaca bridge) —
shape verified against alpyca's public Telescope API. Bridge fidelity
(Slewing accuracy, native Sync, async slew, EquatorialSystem) must be
verified at first bring-up per DESIGN.md §3a/§11.
"""
from __future__ import annotations

import asyncio
import time

from alpaca.telescope import EquatorialCoordinateType, Telescope

from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.ports import MountControl

# equTopocentric ("JNow") has no fixed epoch — it moves with the current
# date. Fixed epochs map directly; topocentric is resolved to "now" in
# Julian years at call time.
_FIXED_EPOCHS = {
    EquatorialCoordinateType.equJ2000: 2000.0,
    EquatorialCoordinateType.equJ2050: 2050.0,
    EquatorialCoordinateType.equB1950: 1950.0,
}


def _current_jyear() -> float:
    from astropy.time import Time

    return Time(time.time(), format="unix").jyear


class AlpacaMountClient(MountControl):
    def __init__(self, address: str, device_number: int = 0) -> None:
        host, _, port = address.partition(":")
        self._telescope = Telescope(f"{host}:{port}" if port else address, device_number)

    async def slew_to(self, target: CelestialCoord) -> None:
        mount_target = await self._to_mount_epoch(target)
        await asyncio.to_thread(
            self._telescope.SlewToCoordinatesAsync, mount_target.ra_deg / 15.0, mount_target.dec_deg
        )

    async def is_slewing(self) -> bool:
        return await asyncio.to_thread(lambda: self._telescope.Slewing)

    async def sync_to(self, coord: CelestialCoord) -> None:
        mount_coord = await self._to_mount_epoch(coord)
        await asyncio.to_thread(
            self._telescope.SyncToCoordinates, mount_coord.ra_deg / 15.0, mount_coord.dec_deg
        )

    async def get_equatorial_system(self) -> float:
        eq_type = await asyncio.to_thread(lambda: self._telescope.EquatorialSystem)
        if eq_type in _FIXED_EPOCHS:
            return _FIXED_EPOCHS[eq_type]
        # equTopocentric or equOther: treat as "now".
        return _current_jyear()

    async def get_position(self) -> CelestialCoord:
        epoch = await self.get_equatorial_system()
        ra_hours, dec_deg = await asyncio.to_thread(
            lambda: (self._telescope.RightAscension, self._telescope.Declination)
        )
        return CelestialCoord(ra_deg=ra_hours * 15.0, dec_deg=dec_deg, epoch=epoch)

    async def abort_slew(self) -> None:
        await asyncio.to_thread(self._telescope.AbortSlew)

    async def _to_mount_epoch(self, coord: CelestialCoord) -> CelestialCoord:
        """cedar-goto works internally in J2000 (DESIGN.md §4); convert to
        whatever epoch the mount currently advertises before sending."""
        from cedar_goto.core._precession import precess

        mount_epoch = await self.get_equatorial_system()
        return precess(coord, mount_epoch)
