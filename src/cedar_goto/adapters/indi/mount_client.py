"""MountControl adapter over direct INDI (indi-refactor.md) instead of
through indi_alpaca_server, which has a confirmed bug (stale property
snapshot taken at its own connect time) that silently breaks Alpaca-driven
slews on this mount -- ON_COORD_SET/EQUATORIAL_EOD_COORD end up invisible to
it. Mirrors AlpacaMountClient (adapters/alpaca/mount_client.py); see
indi-refactor.md's property mapping table for the INDI side of each
MountControl method.
"""
from __future__ import annotations

import logging
import time

from cedar_goto.adapters.indi.client import IndiConnection
from cedar_goto.core.coords import EPOCH_MATCH_TOLERANCE_YR, CelestialCoord
from cedar_goto.core.ports import MountControl

logger = logging.getLogger(__name__)

_EQUATORIAL_EOD_COORD = "EQUATORIAL_EOD_COORD"
_ON_COORD_SET = "ON_COORD_SET"
_ALIGNMENT_POINTSET_SIZE = "ALIGNMENT_POINTSET_SIZE"
_ALIGNMENT_POINTSET_ACTION = "ALIGNMENT_POINTSET_ACTION"
_ALIGNMENT_POINTSET_COMMIT = "ALIGNMENT_POINTSET_COMMIT"


def _current_jyear() -> float:
    from astropy.time import Time

    return Time(time.time(), format="unix").jyear


class IndiMountClient(MountControl):
    def __init__(self, conn: IndiConnection) -> None:
        self._conn = conn

    async def get_sync_point_count(self) -> int:
        """Not part of the MountControl Protocol -- mirrors
        IndiTelescopeBackend.get_sync_point_count() (adapters/indi/
        telescope_backend.py), INDI's generic Alignment Subsystem property,
        confirmed present and populated by sync_to() on this driver."""
        values = await self._conn.get_numbers(_ALIGNMENT_POINTSET_SIZE)
        return int(values[_ALIGNMENT_POINTSET_SIZE])

    async def clear_sync_points(self) -> None:
        """Select the CLEAR action then fire COMMIT to execute it -- same
        two-step protocol as IndiTelescopeBackend.clear_sync_points()."""
        await self._conn.set_switch(_ALIGNMENT_POINTSET_ACTION, "CLEAR")
        await self._conn.wait_for_switch_confirmed(_ALIGNMENT_POINTSET_ACTION, "CLEAR")
        await self._conn.set_switch(_ALIGNMENT_POINTSET_COMMIT, _ALIGNMENT_POINTSET_COMMIT)

    async def slew_to(self, target: CelestialCoord) -> None:
        # ON_COORD_SET=TRACK, not SLEW -- goto-and-track semantics, matching
        # what SlewToCoordinatesAsync is expected to do (indi-refactor.md).
        await self._check_epoch(target)
        await self._conn.set_switch(_ON_COORD_SET, "TRACK")
        await self._conn.wait_for_switch_confirmed(_ON_COORD_SET, "TRACK")
        await self._conn.set_numbers(
            _EQUATORIAL_EOD_COORD, {"RA": target.ra_deg / 15.0, "DEC": target.dec_deg}
        )

    async def is_slewing(self) -> bool:
        return await self._conn.is_property_busy(_EQUATORIAL_EOD_COORD)

    async def sync_to(self, coord: CelestialCoord) -> None:
        await self._check_epoch(coord)
        await self._conn.set_switch(_ON_COORD_SET, "SYNC")
        await self._conn.wait_for_switch_confirmed(_ON_COORD_SET, "SYNC")
        await self._conn.set_numbers(
            _EQUATORIAL_EOD_COORD, {"RA": coord.ra_deg / 15.0, "DEC": coord.dec_deg}
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

    async def _check_epoch(self, coord: CelestialCoord) -> None:
        """Regression tripwire, not a conversion (epoch-seam decision,
        2026-07-26): this driver no longer converts epochs itself -- the
        single conversion seam is EpochNormalizingSolveSource, so every
        coordinate reaching this class is expected to already be tagged in
        this mount's own working epoch (JNow). Logs rather than raises -- a
        wrong tag is a correctness bug in the caller, not a reason to abort
        an in-progress slew command."""
        mount_epoch = await self.get_equatorial_system()
        if abs(coord.epoch - mount_epoch) > EPOCH_MATCH_TOLERANCE_YR:
            logger.warning(
                "IndiMountClient received a coordinate tagged epoch=%.4f but this mount's "
                "working epoch is %.4f -- caller failed to convert (the epoch seam belongs on "
                "SolveSource, not here)", coord.epoch, mount_epoch,
            )
