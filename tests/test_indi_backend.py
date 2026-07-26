"""IndiMountClient / IndiTelescopeBackend (indi-refactor.md) against a fake
IndiConnection -- exercises the property-mapping logic in isolation from
pyindi-client/real sockets, so this suite runs anywhere regardless of
whether the optional "indi" extra is installed (mirrors how
test_closed_loop*.py exercise the mock harness, not real hardware).
"""
from __future__ import annotations

import pytest

from cedar_goto.adapters.indi.mount_client import IndiMountClient, _current_jyear
from cedar_goto.adapters.indi.telescope_backend import IndiTelescopeBackend
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.web.alpaca_errors import AlpacaError, ParkedError
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION

_EQUATORIAL_EOD_COORD = "EQUATORIAL_EOD_COORD"
_ON_COORD_SET = "ON_COORD_SET"
_GEOGRAPHIC_COORD = "GEOGRAPHIC_COORD"


class FakeIndiConnection:
    """Stands in for adapters.indi.client.IndiConnection's public surface."""

    def __init__(self) -> None:
        self.ensure_connected_calls = 0
        self.connect_error: Exception | None = None
        self.numbers = {
            _EQUATORIAL_EOD_COORD: {"RA": 0.0, "DEC": 0.0},
            _GEOGRAPHIC_COORD: {"LAT": 51.0, "LONG": 3.7, "ELEV": 10.0},
            "ALIGNMENT_POINTSET_SIZE": {"ALIGNMENT_POINTSET_SIZE": 2.0},
        }
        self.switches = {
            _ON_COORD_SET: {"TRACK": False, "SLEW": False, "SYNC": False},
            "TELESCOPE_PARK": {"PARK": False, "UNPARK": True},
            "TELESCOPE_TRACK_STATE": {"TRACK_ON": True, "TRACK_OFF": False},
            "TELESCOPE_ABORT_MOTION": {"ABORT": False},
            "ALIGNMENT_POINTSET_ACTION": {"APPEND": True, "CLEAR": False},
            "ALIGNMENT_POINTSET_COMMIT": {"ALIGNMENT_POINTSET_COMMIT": False},
        }
        self._busy = {_EQUATORIAL_EOD_COORD: False}
        self.sent_switches: list[tuple[str, str]] = []
        self.sent_numbers: list[tuple[str, dict]] = []

    async def ensure_connected(self) -> None:
        self.ensure_connected_calls += 1
        if self.connect_error is not None:
            raise self.connect_error

    async def get_numbers(self, prop: str) -> dict:
        return dict(self.numbers[prop])

    async def get_switch(self, prop: str, elem: str) -> bool:
        return self.switches[prop][elem]

    async def is_property_busy(self, prop: str) -> bool:
        return self._busy[prop]

    async def wait_for_switch_confirmed(self, prop: str, elem: str) -> None:
        pass  # the fake applies switch changes synchronously -- nothing to race

    async def set_switch(self, prop: str, elem: str) -> None:
        self.sent_switches.append((prop, elem))
        if prop == "TELESCOPE_ABORT_MOTION":
            self.switches[prop][elem] = True
            self._busy[_EQUATORIAL_EOD_COORD] = False
            return
        if prop == "ALIGNMENT_POINTSET_COMMIT":
            if self.switches["ALIGNMENT_POINTSET_ACTION"]["CLEAR"]:
                self.numbers["ALIGNMENT_POINTSET_SIZE"]["ALIGNMENT_POINTSET_SIZE"] = 0.0
            return
        for k in self.switches[prop]:
            self.switches[prop][k] = k == elem

    async def set_numbers(self, prop: str, values: dict) -> None:
        self.sent_numbers.append((prop, dict(values)))
        self.numbers[prop].update(values)
        if prop == _EQUATORIAL_EOD_COORD:
            # Real driver: SYNC lands instantly; TRACK/SLEW goes Busy until settled.
            self._busy[prop] = not self.switches[_ON_COORD_SET]["SYNC"]

    def settle(self) -> None:
        self._busy[_EQUATORIAL_EOD_COORD] = False


@pytest.fixture
def fake() -> FakeIndiConnection:
    return FakeIndiConnection()


@pytest.fixture
def mount(fake: FakeIndiConnection) -> IndiMountClient:
    return IndiMountClient(fake)


@pytest.fixture
def backend(fake: FakeIndiConnection) -> IndiTelescopeBackend:
    return IndiTelescopeBackend(fake)


# --- IndiMountClient ---------------------------------------------------


async def test_slew_to_sets_track_then_coordinates(mount, fake):
    await mount.slew_to(CelestialCoord(ra_deg=120.0, dec_deg=30.0, epoch=_current_jyear()))
    assert fake.sent_switches == [(_ON_COORD_SET, "TRACK")]
    sent_prop, sent_values = fake.sent_numbers[-1]
    assert sent_prop == _EQUATORIAL_EOD_COORD
    assert sent_values["RA"] == pytest.approx(8.0)
    assert sent_values["DEC"] == pytest.approx(30.0)


async def test_slew_to_passes_coordinates_through_unconverted(mount, fake, caplog):
    """Epoch-seam decision (2026-07-26): IndiMountClient no longer converts
    epochs itself -- a J2000-tagged coordinate (the default) is sent to the
    driver exactly as given, not precessed to JNow. The mismatch is only
    logged (_check_epoch's regression tripwire), never silently fixed up."""
    import logging

    with caplog.at_level(logging.WARNING):
        await mount.slew_to(CelestialCoord(ra_deg=120.0, dec_deg=30.0))  # default epoch=J2000
    sent_values = fake.sent_numbers[-1][1]
    assert sent_values["RA"] == pytest.approx(8.0)
    assert sent_values["DEC"] == pytest.approx(30.0)
    assert "epoch=2000" in caplog.text


async def test_is_slewing_reflects_busy_state(mount, fake):
    assert await mount.is_slewing() is False
    await mount.slew_to(CelestialCoord(ra_deg=120.0, dec_deg=30.0, epoch=_current_jyear()))
    assert await mount.is_slewing() is True
    fake.settle()
    assert await mount.is_slewing() is False


async def test_sync_to_sets_sync_then_coordinates(mount, fake):
    await mount.sync_to(CelestialCoord(ra_deg=45.0, dec_deg=-10.0, epoch=_current_jyear()))
    assert fake.sent_switches == [(_ON_COORD_SET, "SYNC")]
    sent_prop, sent_values = fake.sent_numbers[-1]
    assert sent_prop == _EQUATORIAL_EOD_COORD
    assert sent_values["RA"] == pytest.approx(3.0)
    assert sent_values["DEC"] == pytest.approx(-10.0)
    # SYNC lands instantly, no Busy state.
    assert await mount.is_slewing() is False


async def test_get_equatorial_system_returns_current_jyear(mount):
    epoch = await mount.get_equatorial_system()
    assert 2020.0 < epoch < 2100.0


async def test_get_position_reads_ra_dec_and_epoch(mount, fake):
    fake.numbers[_EQUATORIAL_EOD_COORD] = {"RA": 8.0, "DEC": 30.0}
    coord = await mount.get_position()
    assert coord.ra_deg == pytest.approx(120.0)
    assert coord.dec_deg == pytest.approx(30.0)
    assert coord.epoch > 2000.0


async def test_abort_slew_sends_abort_switch(mount, fake):
    await mount.abort_slew()
    assert fake.sent_switches == [("TELESCOPE_ABORT_MOTION", "ABORT")]


# --- IndiTelescopeBackend -----------------------------------------------


async def test_connected_put_true_connects_and_get_reflects_it(backend, fake):
    assert await backend.get(ALL_MEMBERS_BY_ACTION["connected"]) is False
    await backend.put(ALL_MEMBERS_BY_ACTION["connected"], {"Connected": True})
    assert fake.ensure_connected_calls == 1
    assert await backend.get(ALL_MEMBERS_BY_ACTION["connected"]) is True
    await backend.put(ALL_MEMBERS_BY_ACTION["connected"], {"Connected": False})
    assert await backend.get(ALL_MEMBERS_BY_ACTION["connected"]) is False


async def test_connected_put_true_propagates_connection_failure(backend, fake):
    fake.connect_error = RuntimeError("no route to indiserver")
    with pytest.raises(RuntimeError):
        await backend.put(ALL_MEMBERS_BY_ACTION["connected"], {"Connected": True})


async def test_capability_flags_match_real_driver(backend):
    assert await backend.get(ALL_MEMBERS_BY_ACTION["canpark"]) is True
    assert await backend.get(ALL_MEMBERS_BY_ACTION["canunpark"]) is True
    assert await backend.get(ALL_MEMBERS_BY_ACTION["cansettracking"]) is True
    assert await backend.get(ALL_MEMBERS_BY_ACTION["canslewaltaz"]) is False
    assert await backend.get(ALL_MEMBERS_BY_ACTION["canpulseguide"]) is False


async def test_at_park_reads_park_switch(backend, fake):
    assert await backend.get(ALL_MEMBERS_BY_ACTION["atpark"]) is False
    fake.switches["TELESCOPE_PARK"] = {"PARK": True, "UNPARK": False}
    assert await backend.get(ALL_MEMBERS_BY_ACTION["atpark"]) is True


async def test_right_ascension_and_declination_read_from_eod_coord(backend, fake):
    fake.numbers[_EQUATORIAL_EOD_COORD] = {"RA": 5.0, "DEC": -20.0}
    assert await backend.get(ALL_MEMBERS_BY_ACTION["rightascension"]) == pytest.approx(5.0)
    assert await backend.get(ALL_MEMBERS_BY_ACTION["declination"]) == pytest.approx(-20.0)


async def test_target_not_set_raises_value_not_set(backend):
    with pytest.raises(AlpacaError):
        await backend.get(ALL_MEMBERS_BY_ACTION["targetrightascension"])
    with pytest.raises(AlpacaError):
        await backend.get(ALL_MEMBERS_BY_ACTION["targetdeclination"])


async def test_sync_to_coordinates_puts_sync_switch_and_numbers(backend, fake):
    await backend.put(
        ALL_MEMBERS_BY_ACTION["synctocoordinates"], {"RightAscension": 4.0, "Declination": 15.0}
    )
    assert fake.sent_switches == [(_ON_COORD_SET, "SYNC")]
    assert fake.sent_numbers[-1] == (_EQUATORIAL_EOD_COORD, {"RA": 4.0, "DEC": 15.0})


async def test_sync_to_target_requires_target_then_syncs(backend, fake):
    with pytest.raises(AlpacaError):
        await backend.put(ALL_MEMBERS_BY_ACTION["synctotarget"], {})
    await backend.put(
        ALL_MEMBERS_BY_ACTION["targetrightascension"], {"TargetRightAscension": 6.0}
    )
    await backend.put(ALL_MEMBERS_BY_ACTION["targetdeclination"], {"TargetDeclination": 25.0})
    await backend.put(ALL_MEMBERS_BY_ACTION["synctotarget"], {})
    assert fake.sent_switches[-1] == (_ON_COORD_SET, "SYNC")
    assert fake.sent_numbers[-1] == (_EQUATORIAL_EOD_COORD, {"RA": 6.0, "DEC": 25.0})


async def test_slew_while_parked_raises_parked_error_without_sending_anything(backend, fake):
    fake.switches["TELESCOPE_PARK"] = {"PARK": True, "UNPARK": False}
    with pytest.raises(ParkedError):
        await backend.put(
            ALL_MEMBERS_BY_ACTION["slewtocoordinatesasync"], {"RightAscension": 4.0, "Declination": 15.0}
        )
    assert fake.sent_switches == []
    assert fake.sent_numbers == []


async def test_slew_to_target_async_sets_track(backend, fake):
    await backend.put(ALL_MEMBERS_BY_ACTION["targetrightascension"], {"TargetRightAscension": 6.0})
    await backend.put(ALL_MEMBERS_BY_ACTION["targetdeclination"], {"TargetDeclination": 25.0})
    await backend.put(ALL_MEMBERS_BY_ACTION["slewtotargetasync"], {})
    assert fake.sent_switches[-1] == (_ON_COORD_SET, "TRACK")
    assert fake.sent_numbers[-1] == (_EQUATORIAL_EOD_COORD, {"RA": 6.0, "DEC": 25.0})


async def test_abort_slew_sends_abort(backend, fake):
    await backend.put(ALL_MEMBERS_BY_ACTION["abortslew"], {})
    assert fake.sent_switches == [("TELESCOPE_ABORT_MOTION", "ABORT")]


async def test_park_and_unpark(backend, fake):
    await backend.put(ALL_MEMBERS_BY_ACTION["park"], {})
    assert fake.sent_switches[-1] == ("TELESCOPE_PARK", "PARK")
    await backend.put(ALL_MEMBERS_BY_ACTION["unpark"], {})
    assert fake.sent_switches[-1] == ("TELESCOPE_PARK", "UNPARK")


async def test_tracking_get_and_put(backend, fake):
    assert await backend.get(ALL_MEMBERS_BY_ACTION["tracking"]) is True
    await backend.put(ALL_MEMBERS_BY_ACTION["tracking"], {"Tracking": False})
    assert fake.sent_switches[-1] == ("TELESCOPE_TRACK_STATE", "TRACK_OFF")
    assert await backend.get(ALL_MEMBERS_BY_ACTION["tracking"]) is False


async def test_site_lat_long_elev_get_and_put(backend, fake):
    assert await backend.get(ALL_MEMBERS_BY_ACTION["sitelatitude"]) == pytest.approx(51.0)
    await backend.put(ALL_MEMBERS_BY_ACTION["sitelatitude"], {"SiteLatitude": 52.5})
    assert fake.sent_numbers[-1] == (_GEOGRAPHIC_COORD, {"LAT": 52.5})
    assert await backend.get(ALL_MEMBERS_BY_ACTION["sitelatitude"]) == pytest.approx(52.5)


async def test_alt_az_slew_not_implemented(backend):
    with pytest.raises(AlpacaError):
        await backend.put(ALL_MEMBERS_BY_ACTION["slewtoaltazasync"], {"Azimuth": 180.0, "Altitude": 45.0})


async def test_get_sync_point_count_reads_alignment_pointset_size(backend):
    assert await backend.get_sync_point_count() == 2


async def test_clear_sync_points_selects_clear_then_commits(backend, fake):
    await backend.clear_sync_points()
    assert fake.sent_switches == [
        ("ALIGNMENT_POINTSET_ACTION", "CLEAR"),
        ("ALIGNMENT_POINTSET_COMMIT", "ALIGNMENT_POINTSET_COMMIT"),
    ]
    assert await backend.get_sync_point_count() == 0


async def test_altitude_azimuth_sidereal_time_compute_without_error(backend, fake):
    fake.numbers[_EQUATORIAL_EOD_COORD] = {"RA": 8.0, "DEC": 30.0}
    assert isinstance(await backend.get(ALL_MEMBERS_BY_ACTION["altitude"]), float)
    assert isinstance(await backend.get(ALL_MEMBERS_BY_ACTION["azimuth"]), float)
    assert isinstance(await backend.get(ALL_MEMBERS_BY_ACTION["siderealtime"]), float)
