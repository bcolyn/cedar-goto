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
import logging
import time

from alpaca.telescope import EquatorialCoordinateType, Telescope

from cedar_goto.core.coords import EPOCH_MATCH_TOLERANCE_YR, CelestialCoord
from cedar_goto.core.ports import MountControl

logger = logging.getLogger(__name__)

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
        await self._check_epoch(target)
        await asyncio.to_thread(
            self._telescope.SlewToCoordinatesAsync, target.ra_deg / 15.0, target.dec_deg
        )

    async def is_slewing(self) -> bool:
        return await asyncio.to_thread(lambda: self._telescope.Slewing)

    async def sync_to(self, coord: CelestialCoord) -> None:
        await self._check_epoch(coord)
        await asyncio.to_thread(
            self._telescope.SyncToCoordinates, coord.ra_deg / 15.0, coord.dec_deg
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

    async def _check_epoch(self, coord: CelestialCoord) -> None:
        """Regression tripwire, not a conversion (epoch-seam decision,
        2026-07-26): this driver no longer converts epochs itself -- the
        single conversion seam is EpochNormalizingSolveSource, so every
        coordinate reaching this class is expected to already be tagged in
        this mount's own advertised EquatorialSystem. Logs rather than
        raises -- a wrong tag is a correctness bug in the caller, not a
        reason to abort an in-progress slew command."""
        mount_epoch = await self.get_equatorial_system()
        if abs(coord.epoch - mount_epoch) > EPOCH_MATCH_TOLERANCE_YR:
            logger.warning(
                "AlpacaMountClient received a coordinate tagged epoch=%.4f but this mount's "
                "advertised EquatorialSystem is epoch=%.4f -- caller failed to convert (the "
                "epoch seam belongs on SolveSource, not here)", coord.epoch, mount_epoch,
            )
