"""TelescopeBackend over direct INDI (indi-refactor.md) -- hand-maps each
member in web.alpaca_spec.TELESCOPE_MEMBERS to a specific INDI
property/element, unlike AlpycaTelescopeBackend's generic getattr/setattr
dispatch (alpyca happens to name-match Alpaca 1:1; INDI has no such
correspondence). Shares one IndiConnection with IndiMountClient (see
__main__._build_backend) rather than opening a second socket.

Note MoveAxis/PulseGuide/CanMoveAxis-with-real-motion aren't handled here --
cedar-goto's own Alpaca surface (web/alpaca_spec.py) never exposes MoveAxis
at all, and CanPulseGuide is just a capability flag (False, no PulseGuide
method implemented).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cedar_goto.adapters.indi.client import IndiConnection
from cedar_goto.web.alpaca_errors import AlpacaError, NOT_IMPLEMENTED, VALUE_NOT_SET
from cedar_goto.web.alpaca_spec import Member

_EQUATORIAL_EOD_COORD = "EQUATORIAL_EOD_COORD"
_ON_COORD_SET = "ON_COORD_SET"
_GEOGRAPHIC_COORD = "GEOGRAPHIC_COORD"
_TELESCOPE_PARK = "TELESCOPE_PARK"
_TELESCOPE_TRACK_STATE = "TELESCOPE_TRACK_STATE"
_TELESCOPE_ABORT_MOTION = "TELESCOPE_ABORT_MOTION"
_ALIGNMENT_POINTSET_SIZE = "ALIGNMENT_POINTSET_SIZE"
_ALIGNMENT_POINTSET_ACTION = "ALIGNMENT_POINTSET_ACTION"
_ALIGNMENT_POINTSET_COMMIT = "ALIGNMENT_POINTSET_COMMIT"

# equTopocentric (alpyca's EquatorialCoordinateType) -- this driver family
# only ever reports JNow, confirmed against the real driver (indi-refactor.md).
_EQUATORIAL_SYSTEM_JNOW = 1

# algAltAz (ASCOM AlignmentModes) -- a real Alt-Az mount, unlike the mock's
# fake German-equatorial stub.
_ALIGNMENT_MODE_ALTAZ = 0

# Confirmed against the real driver's property list (indi-refactor.md spike,
# 2026-07-22): TELESCOPE_PARK, TELESCOPE_TRACK_STATE both present, no
# HORIZONTAL_COORD (no Alt-Az slew support at the INDI protocol level).
_CAPABILITY_FLAGS = {
    "CanFindHome": False,
    "CanPark": True,
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
    "CanUnpark": True,
}


class IndiTelescopeBackend:
    def __init__(self, conn: IndiConnection) -> None:
        self._conn = conn
        self._connected = False
        self._target_ra_deg: float | None = None
        self._target_dec_deg: float | None = None

    async def get(self, member: Member):
        name = member.name
        if name == "Connected":
            return self._connected
        if name == "Description":
            return "cedar-goto direct-INDI mount backend"
        if name == "DriverInfo":
            return "cedar-goto INDI telescope backend"
        if name == "DriverVersion":
            return "0.1"
        if name == "InterfaceVersion":
            return 3
        if name == "Name":
            return "cedar-goto INDI Telescope"
        if name == "SupportedActions":
            return []
        if name in _CAPABILITY_FLAGS:
            return _CAPABILITY_FLAGS[name]
        if name == "AlignmentMode":
            return _ALIGNMENT_MODE_ALTAZ
        if name in ("ApertureArea", "ApertureDiameter", "FocalLength"):
            return 0.0
        if name == "AtHome":
            return False
        if name == "AtPark":
            return await self._conn.get_switch(_TELESCOPE_PARK, "PARK")
        if name in ("Altitude", "Azimuth", "SiderealTime"):
            return await self._observer_derived(name)
        if name == "Declination":
            return (await self._conn.get_numbers(_EQUATORIAL_EOD_COORD))["DEC"]
        if name in (
            "DeclinationRate", "RightAscensionRate", "GuideRateDeclination", "GuideRateRightAscension",
        ):
            return 0.0
        if name == "DoesRefraction":
            return False
        if name == "EquatorialSystem":
            return _EQUATORIAL_SYSTEM_JNOW
        if name == "IsPulseGuiding":
            return False
        if name == "RightAscension":
            return (await self._conn.get_numbers(_EQUATORIAL_EOD_COORD))["RA"]
        if name == "SideOfPier":
            return -1  # pierUnknown -- no side-of-pier concept for Alt-Az
        if name == "SiteElevation":
            return (await self._conn.get_numbers(_GEOGRAPHIC_COORD))["ELEV"]
        if name == "SiteLatitude":
            return (await self._conn.get_numbers(_GEOGRAPHIC_COORD))["LAT"]
        if name == "SiteLongitude":
            return (await self._conn.get_numbers(_GEOGRAPHIC_COORD))["LONG"]
        if name == "Slewing":
            return await self._is_slewing()
        if name == "SlewSettleTime":
            return 0
        if name == "TargetDeclination":
            if self._target_dec_deg is None:
                raise AlpacaError(VALUE_NOT_SET, "TargetDeclination has not been set")
            return self._target_dec_deg
        if name == "TargetRightAscension":
            if self._target_ra_deg is None:
                raise AlpacaError(VALUE_NOT_SET, "TargetRightAscension has not been set")
            return self._target_ra_deg / 15.0
        if name == "Tracking":
            return await self._conn.get_switch(_TELESCOPE_TRACK_STATE, "TRACK_ON")
        if name == "TrackingRate":
            return 0  # driveSidereal -- the only rate this driver supports
        if name == "TrackingRates":
            return [0]
        if name == "UTCDate":
            # ASCOM Alpaca requires strict "...Z" Zulu format.
            return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        raise AlpacaError(NOT_IMPLEMENTED, f"{name} not implemented by INDI backend")

    async def put(self, member: Member, params: dict):
        name = member.name
        if name == "Connected":
            if params["Connected"]:
                await self._conn.ensure_connected()
            self._connected = bool(params["Connected"])
            return None
        if name == "Tracking":
            elem = "TRACK_ON" if params["Tracking"] else "TRACK_OFF"
            await self._conn.set_switch(_TELESCOPE_TRACK_STATE, elem)
            return None
        if name in (
            "DeclinationRate", "RightAscensionRate", "GuideRateDeclination", "GuideRateRightAscension",
            "DoesRefraction", "SideOfPier", "SlewSettleTime", "TrackingRate", "UTCDate",
        ):
            return None  # accepted, not modeled -- matches the capability flags above
        if name == "SiteLatitude":
            await self._conn.set_numbers(_GEOGRAPHIC_COORD, {"LAT": params["SiteLatitude"]})
            return None
        if name == "SiteLongitude":
            await self._conn.set_numbers(_GEOGRAPHIC_COORD, {"LONG": params["SiteLongitude"]})
            return None
        if name == "SiteElevation":
            await self._conn.set_numbers(_GEOGRAPHIC_COORD, {"ELEV": params["SiteElevation"]})
            return None
        if name == "TargetRightAscension":
            self._target_ra_deg = params["TargetRightAscension"] * 15.0
            return None
        if name == "TargetDeclination":
            self._target_dec_deg = params["TargetDeclination"]
            return None
        if name == "AbortSlew":
            await self._conn.set_switch(_TELESCOPE_ABORT_MOTION, "ABORT")
            return None
        if name in ("FindHome", "SetPark"):
            raise AlpacaError(NOT_IMPLEMENTED, f"{name} not supported by INDI backend")
        if name == "Park":
            await self._conn.set_switch(_TELESCOPE_PARK, "PARK")
            return None
        if name == "Unpark":
            await self._conn.set_switch(_TELESCOPE_PARK, "UNPARK")
            return None
        if name == "SlewToCoordinatesAsync":
            await self._slew(params["RightAscension"], params["Declination"])
            return None
        if name == "SlewToCoordinates":
            await self._slew(params["RightAscension"], params["Declination"])
            await self._wait_settled()
            return None
        if name == "SyncToCoordinates":
            await self._sync(params["RightAscension"], params["Declination"])
            return None
        if name in ("SlewToTarget", "SlewToTargetAsync"):
            self._require_target()
            await self._slew(self._target_ra_deg / 15.0, self._target_dec_deg)
            if name == "SlewToTarget":
                await self._wait_settled()
            return None
        if name == "SyncToTarget":
            self._require_target()
            await self._sync(self._target_ra_deg / 15.0, self._target_dec_deg)
            return None
        if name in ("SlewToAltAz", "SlewToAltAzAsync", "SyncToAltAz"):
            raise AlpacaError(
                NOT_IMPLEMENTED, f"{name} not supported by INDI backend (no Alt-Az slew on this driver)"
            )
        raise AlpacaError(NOT_IMPLEMENTED, f"{name} not implemented by INDI backend")

    async def query(self, member: Member, params: dict):
        name = member.name
        if name == "CanMoveAxis":
            return False
        if name == "AxisRates":
            return []
        if name == "DestinationSideOfPier":
            return -1  # pierUnknown -- no side-of-pier concept for Alt-Az
        raise AlpacaError(NOT_IMPLEMENTED, f"{name} not implemented by INDI backend")

    async def get_sync_point_count(self) -> int:
        """Not part of ASCOM ITelescopeV3 -- INDI's generic Alignment
        Subsystem (docs.indilib.org/interfaces/alignment-subsystem.html),
        confirmed present and populated by Sync on this driver (spiked
        2026-07-22: a real sync_to() took ALIGNMENT_POINTSET_SIZE 0 -> 1).
        Exposed for the web UI (web/ui.py), not the Alpaca proxy surface."""
        values = await self._conn.get_numbers(_ALIGNMENT_POINTSET_SIZE)
        return int(values[_ALIGNMENT_POINTSET_SIZE])

    async def clear_sync_points(self) -> None:
        """Select the CLEAR action then fire COMMIT to execute it -- exact
        two-step protocol confirmed against indilib/indi's
        libs/alignment/MapPropertiesToInMemoryDatabase.cpp and verified live
        (SIZE 1 -> 0). COMMIT is momentary (driver resets it after
        processing), so unlike the ACTION selection it's not confirmed via
        wait_for_switch_confirmed."""
        await self._conn.set_switch(_ALIGNMENT_POINTSET_ACTION, "CLEAR")
        await self._conn.wait_for_switch_confirmed(_ALIGNMENT_POINTSET_ACTION, "CLEAR")
        await self._conn.set_switch(_ALIGNMENT_POINTSET_COMMIT, _ALIGNMENT_POINTSET_COMMIT)

    def _require_target(self) -> None:
        if self._target_ra_deg is None or self._target_dec_deg is None:
            raise AlpacaError(VALUE_NOT_SET, "Target RA/Dec has not been set")

    async def _slew(self, ra_hours: float, dec_deg: float) -> None:
        await self._conn.set_switch(_ON_COORD_SET, "TRACK")
        await self._conn.wait_for_switch_confirmed(_ON_COORD_SET, "TRACK")
        await self._conn.set_numbers(_EQUATORIAL_EOD_COORD, {"RA": ra_hours, "DEC": dec_deg})

    async def _sync(self, ra_hours: float, dec_deg: float) -> None:
        await self._conn.set_switch(_ON_COORD_SET, "SYNC")
        await self._conn.wait_for_switch_confirmed(_ON_COORD_SET, "SYNC")
        await self._conn.set_numbers(_EQUATORIAL_EOD_COORD, {"RA": ra_hours, "DEC": dec_deg})

    async def _wait_settled(self) -> None:
        while await self._is_slewing():
            await asyncio.sleep(0.25)

    async def _is_slewing(self) -> bool:
        return await self._conn.is_property_busy(_EQUATORIAL_EOD_COORD)

    async def _observer_derived(self, which: str) -> float:
        from astropy.coordinates import AltAz, EarthLocation, SkyCoord
        from astropy.time import Time

        geo = await self._conn.get_numbers(_GEOGRAPHIC_COORD)
        now = Time.now()
        if which == "SiderealTime":
            return now.sidereal_time("apparent", longitude=geo["LONG"]).hour
        coords = await self._conn.get_numbers(_EQUATORIAL_EOD_COORD)
        location = EarthLocation(lat=geo["LAT"], lon=geo["LONG"], height=geo["ELEV"])
        sky = SkyCoord(ra=coords["RA"] * 15.0, dec=coords["DEC"], unit="deg")
        altaz = sky.transform_to(AltAz(obstime=now, location=location))
        return altaz.alt.deg if which == "Altitude" else altaz.az.deg
