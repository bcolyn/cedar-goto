"""Declarative table of the ASCOM Alpaca Telescope (ITelescopeV3) member surface.

DESIGN.md §3: cedar-goto is a *transparent proxy* for everything except the
slew methods (intercepted from Phase 2 onward). Driving the HTTP layer off
one table -- rather than one hand-written FastAPI route per member -- means
adding an override for a member later (e.g. slewtocoordinatesasync) doesn't
require touching the routing code, only the backend.

Alpaca convention: readable properties are GET, writable properties are PUT
with a single form field matching the property's own name, and methods
(void or not) are always PUT with their documented argument names. Value
types are declared here so the HTTP layer can coerce form-encoded strings
before calling the backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["prop_ro", "prop_rw", "method", "query_ro"]
"""prop_ro/prop_rw: plain properties (GET, +PUT for rw).
method: state-changing action, PUT-only (e.g. SlewToCoordinatesAsync).
query_ro: read-only query that takes parameters, GET-only (e.g.
CanMoveAxis(Axis) -- a "query" in ASCOM terms, not an "action", so unlike
methods it's accessed via GET with the params in the query string)."""
ParamType = Literal["str", "float", "int", "bool"]


@dataclass(frozen=True)
class Param:
    name: str
    type: ParamType = "float"


@dataclass(frozen=True)
class Member:
    name: str
    """PascalCase member name, e.g. 'RightAscension'. The Alpaca action id
    in the URL is this lowercased."""
    kind: Kind
    params: tuple[Param, ...] = field(default_factory=tuple)
    """For prop_rw: the single value param (named after the property itself).
    For method: the documented argument list, in order."""

    @property
    def action(self) -> str:
        return self.name.lower()


# Common members, shared by every Alpaca device type.
COMMON_MEMBERS: tuple[Member, ...] = (
    Member("Connected", "prop_rw", (Param("Connected", "bool"),)),
    Member("Description", "prop_ro"),
    Member("DriverInfo", "prop_ro"),
    Member("DriverVersion", "prop_ro"),
    Member("InterfaceVersion", "prop_ro"),
    Member("Name", "prop_ro"),
    Member("SupportedActions", "prop_ro"),
)

# ITelescopeV3 members implemented by this proxy. A handful of rarely-used
# members (Action, CommandBlind/Bool/String, MoveAxis, AxisRates,
# CanMoveAxis, DestinationSideOfPier) are intentionally left out for now --
# unknown actions correctly fall through to ActionNotImplementedError rather
# than a routing 404, so adding them later is additive.
TELESCOPE_MEMBERS: tuple[Member, ...] = (
    Member("AlignmentMode", "prop_ro"),
    Member("Altitude", "prop_ro"),
    Member("ApertureArea", "prop_ro"),
    Member("ApertureDiameter", "prop_ro"),
    Member("AtHome", "prop_ro"),
    Member("AtPark", "prop_ro"),
    Member("Azimuth", "prop_ro"),
    Member("CanFindHome", "prop_ro"),
    Member("CanPark", "prop_ro"),
    Member("CanPulseGuide", "prop_ro"),
    Member("CanSetDeclinationRate", "prop_ro"),
    Member("CanSetGuideRates", "prop_ro"),
    Member("CanSetPark", "prop_ro"),
    Member("CanSetPierSide", "prop_ro"),
    Member("CanSetRightAscensionRate", "prop_ro"),
    Member("CanSetTracking", "prop_ro"),
    Member("CanSlew", "prop_ro"),
    Member("CanSlewAltAz", "prop_ro"),
    Member("CanSlewAltAzAsync", "prop_ro"),
    Member("CanSlewAsync", "prop_ro"),
    Member("CanSync", "prop_ro"),
    Member("CanSyncAltAz", "prop_ro"),
    Member("CanUnpark", "prop_ro"),
    Member("Declination", "prop_ro"),
    Member("DeclinationRate", "prop_rw", (Param("DeclinationRate"),)),
    Member("DoesRefraction", "prop_rw", (Param("DoesRefraction", "bool"),)),
    Member("EquatorialSystem", "prop_ro"),
    Member("FocalLength", "prop_ro"),
    Member("GuideRateDeclination", "prop_rw", (Param("GuideRateDeclination"),)),
    Member("GuideRateRightAscension", "prop_rw", (Param("GuideRateRightAscension"),)),
    Member("IsPulseGuiding", "prop_ro"),
    Member("RightAscension", "prop_ro"),
    Member("RightAscensionRate", "prop_rw", (Param("RightAscensionRate"),)),
    Member("SideOfPier", "prop_rw", (Param("SideOfPier", "int"),)),
    Member("SiderealTime", "prop_ro"),
    Member("SiteElevation", "prop_rw", (Param("SiteElevation"),)),
    Member("SiteLatitude", "prop_rw", (Param("SiteLatitude"),)),
    Member("SiteLongitude", "prop_rw", (Param("SiteLongitude"),)),
    Member("Slewing", "prop_ro"),
    Member("SlewSettleTime", "prop_rw", (Param("SlewSettleTime", "int"),)),
    Member("TargetDeclination", "prop_rw", (Param("TargetDeclination"),)),
    Member("TargetRightAscension", "prop_rw", (Param("TargetRightAscension"),)),
    Member("Tracking", "prop_rw", (Param("Tracking", "bool"),)),
    Member("TrackingRate", "prop_rw", (Param("TrackingRate", "int"),)),
    Member("TrackingRates", "prop_ro"),
    Member("UTCDate", "prop_rw", (Param("UTCDate", "str"),)),
    Member("AbortSlew", "method"),
    Member("FindHome", "method"),
    Member("Park", "method"),
    Member("SetPark", "method"),
    Member("Unpark", "method"),
    Member(
        "SlewToCoordinates", "method", (Param("RightAscension"), Param("Declination"))
    ),
    Member(
        "SlewToCoordinatesAsync",
        "method",
        (Param("RightAscension"), Param("Declination")),
    ),
    Member("SlewToTarget", "method"),
    Member("SlewToTargetAsync", "method"),
    Member("SyncToCoordinates", "method", (Param("RightAscension"), Param("Declination"))),
    Member("SyncToTarget", "method"),
    Member("SlewToAltAz", "method", (Param("Azimuth"), Param("Altitude"))),
    Member("SlewToAltAzAsync", "method", (Param("Azimuth"), Param("Altitude"))),
    Member("SyncToAltAz", "method", (Param("Azimuth"), Param("Altitude"))),
    Member("CanMoveAxis", "query_ro", (Param("Axis", "int"),)),
    Member("AxisRates", "query_ro", (Param("Axis", "int"),)),
    Member(
        "DestinationSideOfPier",
        "query_ro",
        (Param("RightAscension"), Param("Declination")),
    ),
)

ALL_MEMBERS_BY_ACTION: dict[str, Member] = {
    m.action: m for m in (*COMMON_MEMBERS, *TELESCOPE_MEMBERS)
}

# Members callable before Connected (ASCOM common members + Connected itself).
UNGATED_ACTIONS: frozenset[str] = frozenset(m.action for m in COMMON_MEMBERS)
