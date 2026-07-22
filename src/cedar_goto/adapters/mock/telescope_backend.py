"""TelescopeBackend over the mock World (DESIGN.md §9a) -- lets Phase 1's
Alpaca proxy server be exercised end-to-end (discovery, management API,
connect, read position, plain-proxy slew) without real hardware.

Unlike AlpycaTelescopeBackend, World only models sky-pointing physics, so
this class owns the rest of the ASCOM device state (Connected, Tracking,
capability flags, site info) itself.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cedar_goto.adapters.mock.world import World
from cedar_goto.core.coords import CelestialCoord, J2000
from cedar_goto.web.alpaca_errors import AlpacaError, NOT_IMPLEMENTED, VALUE_NOT_SET
from cedar_goto.web.alpaca_spec import Member

# equJ2000 (Alpaca EquatorialCoordinateType enum).
_EQUATORIAL_SYSTEM_J2000 = 2

_CAPABILITY_FLAGS = {
    "CanFindHome": False,
    "CanPark": False,
    "CanPulseGuide": False,
    "CanSetDeclinationRate": False,
    "CanSetGuideRates": False,
    "CanSetPark": False,
    "CanSetPierSide": False,
    "CanSetRightAscensionRate": False,
    "CanSetTracking": True,
    "CanSlew": True,
    "CanSlewAltAz": False,
    "CanSlewAltAzAsync": False,
    "CanSlewAsync": True,
    "CanSync": True,
    "CanSyncAltAz": False,
    "CanUnpark": False,
}


class MockTelescopeBackend:
    def __init__(
        self,
        world: World,
        site_latitude_deg: float = 0.0,
        site_longitude_deg: float = 0.0,
        site_elevation_m: float = 0.0,
    ) -> None:
        self._world = world
        self._connected = False
        self._tracking = True
        self._target_ra_deg: float | None = None
        self._target_dec_deg: float | None = None
        self._site_latitude = site_latitude_deg
        self._site_longitude = site_longitude_deg
        self._site_elevation = site_elevation_m

    async def get(self, member: Member):
        return await asyncio.to_thread(self._get_sync, member)

    async def put(self, member: Member, params: dict):
        if member.name == "SlewToCoordinates":
            # Synchronous slew: block the caller until settled, like a real
            # SlewToCoordinates (non-async) would.
            self._command_slew(params["RightAscension"], params["Declination"])
            await asyncio.sleep(self._world.settle_s)
            return None
        return await asyncio.to_thread(self._put_sync, member, params)

    async def query(self, member: Member, params: dict):
        name = member.name
        if name == "CanMoveAxis":
            return False  # not modeled by the mock
        if name == "AxisRates":
            return []
        if name == "DestinationSideOfPier":
            return -1  # pierUnknown; meridian flip not modeled
        raise AlpacaError(NOT_IMPLEMENTED, f"{name} not implemented by mock backend")

    def _get_sync(self, member: Member):
        w = self._world
        name = member.name
        if name == "Connected":
            return self._connected
        if name == "Description":
            return "cedar-goto mock mount (development/test)"
        if name == "DriverInfo":
            return "cedar-goto mock telescope backend"
        if name == "DriverVersion":
            return "0.1"
        if name == "InterfaceVersion":
            return 3
        if name == "Name":
            return "cedar-goto Mock Telescope"
        if name == "SupportedActions":
            return []
        if name in _CAPABILITY_FLAGS:
            return _CAPABILITY_FLAGS[name]
        if name == "AlignmentMode":
            # algGermanPolar, not algAltAz -- must stay consistent with the
            # capability flags: we advertise equatorial slew/sync
            # (CanSlew/CanSlewAsync/CanSync) but no Alt-Az slew capability.
            # A client that picks its slew UI from AlignmentMode first would
            # see "Alt-Az" with no matching Alt-Az slew capability and could
            # reasonably refuse to enable slewing at all.
            return 2
        if name in ("ApertureArea", "ApertureDiameter", "FocalLength"):
            return 0.0
        if name == "AtHome":
            return False
        if name == "AtPark":
            return False
        if name == "Altitude":
            return 45.0  # not modeled; static stub
        if name == "Azimuth":
            return 180.0  # not modeled; static stub
        if name == "Declination":
            return w.true_pointing.dec_deg
        if name in ("DeclinationRate", "RightAscensionRate", "GuideRateDeclination", "GuideRateRightAscension"):
            return 0.0
        if name == "DoesRefraction":
            return False
        if name == "EquatorialSystem":
            return _EQUATORIAL_SYSTEM_J2000
        if name == "IsPulseGuiding":
            return False
        if name == "RightAscension":
            return w.true_pointing.ra_deg / 15.0
        if name == "SideOfPier":
            return -1  # pierUnknown
        if name == "SiderealTime":
            return 0.0  # not modeled
        if name == "SiteElevation":
            return self._site_elevation
        if name == "SiteLatitude":
            return self._site_latitude
        if name == "SiteLongitude":
            return self._site_longitude
        if name == "Slewing":
            return w.is_slewing()
        if name == "SlewSettleTime":
            return int(w.settle_s)
        if name == "TargetDeclination":
            if self._target_dec_deg is None:
                raise AlpacaError(VALUE_NOT_SET, "TargetDeclination has not been set")
            return self._target_dec_deg
        if name == "TargetRightAscension":
            if self._target_ra_deg is None:
                raise AlpacaError(VALUE_NOT_SET, "TargetRightAscension has not been set")
            return self._target_ra_deg / 15.0
        if name == "Tracking":
            return self._tracking
        if name == "TrackingRate":
            return 0  # driveSidereal
        if name == "TrackingRates":
            return [0]
        if name == "UTCDate":
            # ASCOM Alpaca requires strict "...Z" Zulu format, not a "+00:00"
            # offset -- some clients fail to parse the latter.
            return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        raise AlpacaError(NOT_IMPLEMENTED, f"{name} not implemented by mock backend")

    def _put_sync(self, member: Member, params: dict):
        w = self._world
        name = member.name
        if name == "Connected":
            self._connected = bool(params["Connected"])
            return None
        if name == "Tracking":
            self._tracking = bool(params["Tracking"])
            return None
        if name in (
            "DeclinationRate",
            "RightAscensionRate",
            "GuideRateDeclination",
            "GuideRateRightAscension",
            "DoesRefraction",
            "SideOfPier",
            "SlewSettleTime",
            "TrackingRate",
            "UTCDate",
        ):
            return None  # accepted, not modeled
        if name == "SiteLatitude":
            self._site_latitude = params["SiteLatitude"]
            return None
        if name == "SiteLongitude":
            self._site_longitude = params["SiteLongitude"]
            return None
        if name == "SiteElevation":
            self._site_elevation = params["SiteElevation"]
            return None
        if name == "TargetRightAscension":
            self._target_ra_deg = params["TargetRightAscension"] * 15.0
            return None
        if name == "TargetDeclination":
            self._target_dec_deg = params["TargetDeclination"]
            return None
        if name == "AbortSlew":
            w.abort()
            return None
        if name in ("FindHome", "Park", "SetPark", "Unpark"):
            raise AlpacaError(NOT_IMPLEMENTED, f"{name} not supported by mock backend")
        if name == "SlewToCoordinatesAsync":
            self._command_slew(params["RightAscension"], params["Declination"])
            return None
        if name == "SyncToCoordinates":
            self._sync(params["RightAscension"], params["Declination"])
            return None
        if name in ("SlewToTarget", "SlewToTargetAsync"):
            self._require_target()
            self._command_slew(self._target_ra_deg / 15.0, self._target_dec_deg)
            return None
        if name == "SyncToTarget":
            self._require_target()
            self._sync(self._target_ra_deg / 15.0, self._target_dec_deg)
            return None
        if name in ("SlewToAltAz", "SlewToAltAzAsync", "SyncToAltAz"):
            raise AlpacaError(NOT_IMPLEMENTED, f"{name} not supported by mock backend")
        raise AlpacaError(NOT_IMPLEMENTED, f"{name} not implemented by mock backend")

    def _require_target(self) -> None:
        if self._target_ra_deg is None or self._target_dec_deg is None:
            raise AlpacaError(VALUE_NOT_SET, "Target RA/Dec has not been set")

    def _command_slew(self, ra_hours: float, dec_deg: float) -> None:
        self._world.command_slew(CelestialCoord(ra_deg=ra_hours * 15.0, dec_deg=dec_deg, epoch=J2000))

    def _sync(self, ra_hours: float, dec_deg: float) -> None:
        self._world.sync(CelestialCoord(ra_deg=ra_hours * 15.0, dec_deg=dec_deg, epoch=J2000))
