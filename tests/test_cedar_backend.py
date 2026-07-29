"""CedarTelescopeBackend: the external Alpaca proxy plus the cedar-
facilitation actions the web UI exposes (sync-to-cedar, sync-to-target,
slew-to-target), exercised through HTTP against the mock harness.

Every slew is a bare proxy to the mount -- there is no automatic
correction loop (2026-07-29 redesign: GoTo accuracy is normally good
enough once there's a nearby sync point, and the human decides explicitly
when cedar should get involved)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from cedar_goto.adapters.mock.cedar import MockCedar
from cedar_goto.adapters.mock.mount import MockMount
from cedar_goto.adapters.mock.telescope_backend import MockTelescopeBackend
from cedar_goto.adapters.mock.world import HarmonicErrorModel, World
from cedar_goto.config import PositionSourceConfig
from cedar_goto.core.coords import CelestialCoord
from cedar_goto.core.solve import SolveAcceptance
from cedar_goto.web.alpaca_errors import PARKED
from cedar_goto.web.app import create_app
from cedar_goto.web.cedar_backend import CedarTelescopeBackend

BASE = "http://testserver"


def make_backend(world: World) -> CedarTelescopeBackend:
    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), MockCedar(world)
    return CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))


async def make_client(backend) -> httpx.AsyncClient:
    app = create_app(backend)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url=BASE)


async def _slew_and_wait(client: httpx.AsyncClient, ra_hours: float, dec_deg: float, tries: int = 200):
    resp = await client.put(
        "/api/v1/telescope/0/slewtocoordinatesasync",
        data={"RightAscension": str(ra_hours), "Declination": str(dec_deg)},
    )
    assert resp.json()["ErrorNumber"] == 0
    for _ in range(tries):
        await asyncio.sleep(0.02)
        if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
            return
    pytest.fail("slew never finished")


async def test_slew_is_always_a_bare_proxy():
    """SlewToCoordinatesAsync must never nudge or correct -- just the GoTo
    as commanded. The raw harmonic pointing error (a few arcmin) is still
    present afterward, unlike the old closed loop's converged result."""
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)

        ra = (await client.get("/api/v1/telescope/0/rightascension")).json()["Value"]
        assert ra != pytest.approx(8.0, abs=1e-6)

        # cedar-server must still learn a slew happened (push-to guidance),
        # and it stays "active" until the user explicitly ends it.
        assert len(backend._cedar.slew_started_calls) == 1
        assert backend._cedar.slew_started_calls[0].ra_deg == pytest.approx(120.0)
        assert backend._cedar.slew_started_calls[0].dec_deg == pytest.approx(30.0)
        assert backend._cedar.slew_stopped_count == 0


async def test_abort_notifies_cedar_the_slew_stopped():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        resp = await client.put("/api/v1/telescope/0/abortslew")
        assert resp.json()["ErrorNumber"] == 0
        assert backend._cedar.slew_stopped_count == 1


async def test_realign_cedar_calls_capture_boresight():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    assert backend._cedar.capture_boresight_count == 0

    await backend.realign_cedar()

    assert backend._cedar.capture_boresight_count == 1


async def test_sync_to_target_notifies_cedar_the_slew_stopped():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)
        assert backend._cedar.slew_stopped_count == 0

        target = await backend.sync_to_target()
        assert target is not None
        assert backend._cedar.slew_stopped_count == 1


async def test_park_notifies_cedar_and_proxies_through():
    class ParkCapableInner:
        """MockTelescopeBackend raises NOT_IMPLEMENTED for Park -- this
        wraps it with a Park that actually succeeds."""

        def __init__(self, mock_inner: MockTelescopeBackend) -> None:
            self._mock = mock_inner
            self.parked = False

        async def get(self, member):
            return await self._mock.get(member)

        async def put(self, member, params):
            if member.name == "Park":
                self.parked = True
                return None
            return await self._mock.put(member, params)

        async def query(self, member, params):
            return await self._mock.query(member, params)

    world = World(error_model=HarmonicErrorModel())
    inner = ParkCapableInner(MockTelescopeBackend(world))
    mount, cedar = MockMount(world), MockCedar(world)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )

        resp = await client.put("/api/v1/telescope/0/park")
        assert resp.json()["ErrorNumber"] == 0
        assert inner.parked is True
        assert backend._cedar.slew_stopped_count == 1


async def test_slew_while_parked_is_refused():
    class AlwaysParkedInner:
        """MockTelescopeBackend hardcodes AtPark=False -- this wraps it to
        report parked, to test the pre-slew guard without needing the real
        INDI/ASCOM plumbing."""

        def __init__(self, mock_inner: MockTelescopeBackend) -> None:
            self._mock = mock_inner

        async def get(self, member):
            if member.name == "AtPark":
                return True
            return await self._mock.get(member)

        async def put(self, member, params):
            return await self._mock.put(member, params)

        async def query(self, member, params):
            return await self._mock.query(member, params)

    world = World(error_model=HarmonicErrorModel())
    inner = AlwaysParkedInner(MockTelescopeBackend(world))
    mount, cedar = MockMount(world), MockCedar(world)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert resp.json()["ErrorNumber"] == PARKED
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False


async def test_status_snapshot_reflects_cedars_live_solve():
    """No background task tracks this anymore -- status_snapshot()'s
    last_solve must reflect whatever cedar reports right now, queried live,
    not a cached result from a prior action."""
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)

    before = await backend.status_snapshot()
    assert before["last_solve"] is not None  # MockCedar always has a solve ready

    snapshot = await backend.status_snapshot()
    assert snapshot["last_target"] is None
    assert snapshot["last_target_time_unix"] is None

    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)

    after = await backend.status_snapshot()
    assert after["last_target"]["ra_deg"] == pytest.approx(120.0)
    assert after["last_target_time_unix"] is not None


async def test_status_snapshot_reports_cedar_connected_true_when_reachable():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    snapshot = await backend.status_snapshot()
    assert snapshot["cedar_connected"] is True


async def test_status_snapshot_reports_cedar_connected_false_when_unreachable():
    class UnreachableCedar:
        async def get_latest_solve(self):
            raise RuntimeError("simulated cedar-server outage")

        def stream_solves(self):
            raise NotImplementedError

    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    mount = MockMount(world)
    backend = CedarTelescopeBackend(
        inner, mount, UnreachableCedar(), SolveAcceptance(), PositionSourceConfig(source="mount")
    )
    snapshot = await backend.status_snapshot()
    assert snapshot["cedar_connected"] is False
    assert snapshot["last_solve"] is None


async def test_set_cedar_stopped_by_us_silences_the_unavailable_warning(caplog):
    """web/ui.py's cedar-stop action route calls this after a successful
    `sudo systemctl stop cedar`, so an intentional stop doesn't flood the
    log with "cedar solve source unavailable" on every position poll for
    however long the user leaves it stopped."""

    class UnreachableCedar:
        async def get_latest_solve(self):
            raise RuntimeError("simulated cedar-server outage")

        def stream_solves(self):
            raise NotImplementedError

    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    mount = MockMount(world)
    backend = CedarTelescopeBackend(
        inner, mount, UnreachableCedar(), SolveAcceptance(), PositionSourceConfig(source="mount")
    )

    backend.set_cedar_stopped_by_us(True)
    with caplog.at_level("WARNING"):
        snapshot = await backend.status_snapshot()
    assert snapshot["cedar_connected"] is False
    assert not caplog.records

    backend.set_cedar_stopped_by_us(False)
    with caplog.at_level("WARNING"):
        await backend.status_snapshot()
    assert any("cedar solve source unavailable" in r.message for r in caplog.records)


async def test_sync_to_cedar_refuses_a_non_plate_solve():
    """MountEchoCedar-like loopback solves (SolveResult.is_plate_solve=False)
    must never reach mount.sync_to() via the "Sync now" action either --
    would otherwise calibrate the mount's persistent alignment/sync-point
    database against its own already-possibly-wrong belief."""

    class NonPlateSolveCedar:
        def __init__(self, world: World) -> None:
            self._mock = MockCedar(world)

        async def get_latest_solve(self):
            import dataclasses

            solve = await self._mock.get_latest_solve()
            return solve if solve is None else dataclasses.replace(solve, is_plate_solve=False)

        async def stream_solves(self):
            async for solve in self._mock.stream_solves():
                yield solve

    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), NonPlateSolveCedar(world)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.post("/api/ui/actions/sync-now")
        body = resp.json()
        assert body["ok"] is False
        assert "not a real plate solve" in body["message"]
        # Distinct from the routine "nothing available yet" message.
        assert "no acceptable" not in body["message"]


async def test_sync_to_cedar_reports_no_solve_yet_distinctly():
    """The routine "cedar hasn't produced anything good yet" case must keep
    its own message, not get folded into the SyncRefused (non-plate-solve)
    one."""

    class NoSolveCedar:
        async def get_latest_solve(self):
            return None

        async def stream_solves(self):
            return
            yield  # pragma: no cover -- makes this an async generator

    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    mount = MockMount(world)
    backend = CedarTelescopeBackend(
        inner, mount, NoSolveCedar(), SolveAcceptance(), PositionSourceConfig(source="mount")
    )
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.post("/api/ui/actions/sync-now")
        body = resp.json()
        assert body["ok"] is False
        assert "no acceptable cedar solve" in body["message"]
        assert "plate solve" not in body["message"]


async def test_sync_point_methods_report_unsupported_for_backends_without_it():
    """mock/alpyca have no equivalent of INDI's alignment sync points --
    CedarTelescopeBackend must degrade gracefully, not crash."""
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    assert await backend.get_sync_point_count() is None
    assert await backend.clear_sync_points() is False


async def test_sync_point_methods_report_unsupported_for_the_real_alpyca_backend():
    """Not just the mock -- confirms the actual AlpycaTelescopeBackend class
    (no network call needed: alpyca's Telescope client connects lazily per
    call, same as AlpacaMountClient) has no get_sync_point_count/
    clear_sync_points methods, so the passthrough degrades cleanly. ASCOM
    ITelescopeV3 has no such concept -- it's specific to INDI's Alignment
    Subsystem (adapters/indi/telescope_backend.py)."""
    from cedar_goto.adapters.alpaca.telescope_backend import AlpycaTelescopeBackend

    world = World(error_model=HarmonicErrorModel())
    inner = AlpycaTelescopeBackend("127.0.0.1:11111", 0)
    mount, cedar = MockMount(world), MockCedar(world)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))
    assert await backend.get_sync_point_count() is None
    assert await backend.clear_sync_points() is False


async def test_sync_point_methods_pass_through_when_inner_supports_it():
    class SyncPointCapableInner:
        def __init__(self) -> None:
            self.count = 3
            self.cleared = False

        async def get_sync_point_count(self) -> int:
            return self.count

        async def clear_sync_points(self) -> None:
            self.cleared = True
            self.count = 0

    world = World(error_model=HarmonicErrorModel())
    inner = SyncPointCapableInner()
    mount, cedar = MockMount(world), MockCedar(world)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))
    assert await backend.get_sync_point_count() == 3
    assert await backend.clear_sync_points() is True
    assert inner.cleared is True
    assert await backend.get_sync_point_count() == 0


async def test_position_falls_back_to_mount_when_cedar_is_unreachable():
    """A cedar-server outage (gRPC error, not just "no solve yet") must
    degrade the same way "cedar_fallback_mount" already does for a missing
    solve -- fall back to the mount, not surface a driver error on every
    position poll (bug found 2026-07-22, _cedar_position was unguarded)."""

    class UnreachableCedar:
        async def get_latest_solve(self):
            raise RuntimeError("simulated cedar-server outage")

        def stream_solves(self):
            raise NotImplementedError

    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    mount = MockMount(world)
    backend = CedarTelescopeBackend(
        inner, mount, UnreachableCedar(), SolveAcceptance(), PositionSourceConfig(source="cedar")
    )
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.get("/api/v1/telescope/0/rightascension")
        assert resp.json()["ErrorNumber"] == 0
        # World's true_pointing starts at (0, 0) -- same value the mock
        # mount itself reports, confirming this came from the fallback.
        assert resp.json()["Value"] == pytest.approx(0.0, abs=1e-6)


async def test_position_prefers_cedar_when_configured_and_fresh():
    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), MockCedar(world)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="cedar"))
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        ra = (await client.get("/api/v1/telescope/0/rightascension")).json()["Value"]
        # MockCedar reports the world's true pointing (0,0 initially) as an
        # accepted solve -- should be preferred over the mount's own report.
        assert ra == pytest.approx(0.0, abs=1e-6)


class _RecordingMount:
    """Wraps a MountControl, recording every slew_to() target -- for
    asserting exactly what reaches the mount, unlike World's true_pointing
    which has the harmonic error model applied on top."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.slew_targets: list[CelestialCoord] = []

    async def slew_to(self, target: CelestialCoord) -> None:
        self.slew_targets.append(target)
        await self._inner.slew_to(target)

    async def is_slewing(self) -> bool:
        return await self._inner.is_slewing()

    async def sync_to(self, coord: CelestialCoord) -> None:
        await self._inner.sync_to(coord)

    async def get_equatorial_system(self) -> float:
        return await self._inner.get_equatorial_system()

    async def get_position(self) -> CelestialCoord:
        return await self._inner.get_position()

    async def abort_slew(self) -> None:
        await self._inner.abort_slew()


async def test_reslew_target_carries_the_mounts_own_unconverted_epoch():
    """Epoch-seam decision (2026-07-26) regression test: the target recorded
    from a client's raw RightAscension/Declination numbers must carry
    exactly the epoch this device itself advertises -- not silently
    re-tagged J2000 and precessed away from what the client actually sent,
    the double-conversion that caused the ~9' Polaris bug this decision
    fixed. A plain SlewToCoordinatesAsync is a bare proxy straight to
    `inner` and never touches mount.slew_to() at all now, so this exercises
    the epoch tag via reslew_to_target(), which does call mount.slew_to()
    directly with the recorded target. Uses a non-J2000 advertised epoch
    (unlike every other test in this file, which defaults to J2000 and so
    couldn't tell a fixed epoch-tag bug from a bit-for-bit pass-through)."""
    from cedar_goto.core.epoch_normalizing_solve_source import EpochNormalizingSolveSource

    world = World(error_model=HarmonicErrorModel())
    non_j2000_epoch = 1950.0
    mount = _RecordingMount(MockMount(world, equatorial_system=non_j2000_epoch))
    inner = MockTelescopeBackend(world)
    cedar = EpochNormalizingSolveSource(MockCedar(world), mount.get_equatorial_system)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )

    await backend.reslew_to_target()

    assert mount.slew_targets
    target = mount.slew_targets[0]
    assert target.epoch == pytest.approx(non_j2000_epoch)
    # Bit-for-bit the client's input (8.0h * 15 = 120.0deg), not precessed.
    assert target.ra_deg == pytest.approx(120.0, abs=1e-9)
    assert target.dec_deg == pytest.approx(30.0, abs=1e-9)
