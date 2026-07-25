"""Phase 2: the closed loop wired into the external Alpaca proxy
(DESIGN.md §5, §10), exercised through HTTP against the mock harness."""
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
from cedar_goto.core.loop import LoopConfigCore
from cedar_goto.core.solve import SolveAcceptance
from cedar_goto.web.alpaca_errors import PARKED
from cedar_goto.web.app import create_app
from cedar_goto.web.closed_loop_backend import ClosedLoopTelescopeBackend

BASE = "http://testserver"


def make_backend(world: World, **loop_overrides) -> ClosedLoopTelescopeBackend:
    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), MockCedar(world)
    defaults = dict(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    defaults.update(loop_overrides)
    config = LoopConfigCore(**defaults)
    return ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount")
    )


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
    pytest.fail("closed-loop slew never finished")


async def test_slew_converges_and_slewing_reflects_the_loop():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})

        resp = await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert resp.json()["ErrorNumber"] == 0

        slewing = (await client.get("/api/v1/telescope/0/slewing")).json()["Value"]
        assert slewing is True

        for _ in range(200):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("closed-loop slew never finished")

        assert backend.last_status is not None
        assert backend.last_status.state.name == "CONVERGED"
        # Closed-loop correction should land much closer than a raw
        # harmonic-error single slew (~2-3 arcmin uncorrected).
        assert backend.last_status.error_arcmin <= 1.0

        # cedar-server must learn a slew is happening (push-to guidance) --
        # and it should stay "active" through convergence, since the human
        # may still need to nudge onto target by hand afterward.
        assert len(backend._cedar.slew_started_calls) == 1
        assert backend._cedar.slew_started_calls[0].ra_deg == pytest.approx(120.0)
        assert backend._cedar.slew_started_calls[0].dec_deg == pytest.approx(30.0)
        assert backend._cedar.slew_stopped_count == 0


async def test_abort_notifies_cedar_the_slew_stopped():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world, max_iterations=10)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is True

        resp = await client.put("/api/v1/telescope/0/abortslew")
        assert resp.json()["ErrorNumber"] == 0

        assert backend._cedar.slew_stopped_count == 1


async def test_sync_to_target_notifies_cedar_the_slew_stopped():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)
        assert backend.last_status.state.name == "CONVERGED"
        assert backend._cedar.slew_stopped_count == 0

        target = await backend.sync_to_target()
        assert target is not None
        assert backend._cedar.slew_stopped_count == 1


async def test_abort_slew_stops_the_loop():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world, max_iterations=10)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is True

        resp = await client.put("/api/v1/telescope/0/abortslew")
        assert resp.json()["ErrorNumber"] == 0

        for _ in range(100):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("slew never stopped after AbortSlew")


async def test_park_aborts_a_running_slew_before_parking():
    class ParkCapableInner:
        """MockTelescopeBackend raises NOT_IMPLEMENTED for Park -- this
        wraps it with a Park that actually succeeds, to test the loop-abort
        sequencing without needing the real INDI/ASCOM plumbing."""

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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=10, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount")
    )
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is True

        resp = await client.put("/api/v1/telescope/0/park")
        assert resp.json()["ErrorNumber"] == 0
        assert inner.parked is True
        # Park() awaits the aborted task's completion before returning, so
        # this should already be settled -- no polling needed.
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False


async def test_slew_while_parked_is_refused_without_starting_the_loop():
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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=10, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount")
    )
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert resp.json()["ErrorNumber"] == PARKED
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False


async def test_new_slew_supersedes_a_running_one():
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world, max_iterations=10, settle_s=0.2)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is True

        resp = await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "10.0", "Declination": "-10.0"},
        )
        assert resp.json()["ErrorNumber"] == 0

        for _ in range(50):
            await asyncio.sleep(0.02)
            if backend.last_status is not None and backend.last_status.true_target.ra_deg == pytest.approx(150.0):
                break
        else:
            pytest.fail("new slew never took over the loop")


async def test_disabling_correction_does_not_abort_an_in_progress_loop():
    """set_correction_enabled(False) only affects the *next* slew -- flipping
    the web UI toggle mid-slew shouldn't yank control away from a
    closed-loop correction already underway."""
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world, max_iterations=10)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is True

        backend.set_correction_enabled(False)

        for _ in range(200):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("closed-loop slew never finished")

        assert backend.last_status is not None
        assert backend.last_status.state.name == "CONVERGED"


async def test_set_correction_enabled_invokes_the_persistence_callback():
    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), MockCedar(world)
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    calls: list[bool] = []
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount"),
        on_correction_changed=calls.append,
    )
    backend.set_correction_enabled(False)
    backend.set_correction_enabled(True)
    assert calls == [False, True]


async def test_correction_disabled_is_a_bare_proxy_slew():
    """With correction disabled, SlewToCoordinatesAsync must not run the
    closed loop at all -- no nudging, no mount.sync_to(), just the GoTo as
    commanded (Phase 1 behavior)."""
    world = World(error_model=HarmonicErrorModel())
    backend = make_backend(world)
    backend.set_correction_enabled(False)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "8.0", "Declination": "30.0"},
        )
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is True

        for _ in range(20):
            await asyncio.sleep(0.02)
            assert backend.last_status is None

        for _ in range(200):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("bare slew never settled")

        # No correction applied -- the raw harmonic pointing error (a few
        # arcmin, DESIGN.md §3a) is still present, unlike a converged
        # closed-loop slew.
        ra = (await client.get("/api/v1/telescope/0/rightascension")).json()["Value"]
        assert ra != pytest.approx(8.0, abs=1e-6)


async def test_gives_up_when_solves_are_never_accepted():
    """DESIGN.md §10 Phase 3: give-up path for persistent solve failures."""
    world = World(error_model=HarmonicErrorModel())
    world.inject_solve_failures(999999)
    backend = make_backend(world, max_iterations=3, solve_wait_timeout_s=0.3)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)

        assert backend.last_status is not None
        assert backend.last_status.state.name == "FAILED"
        assert "solve" in backend.last_status.message


async def test_gives_up_when_it_never_converges():
    """DESIGN.md §10 Phase 3: give-up path for non-convergence within max_iterations."""
    world = World(error_model=HarmonicErrorModel())
    # An unreachably tight tolerance forces FAILED after max_iterations,
    # even though solves keep succeeding normally.
    backend = make_backend(world, tolerance_arcmin=1e-6, max_iterations=2)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)

        assert backend.last_status is not None
        assert backend.last_status.state.name == "FAILED"
        assert "converge" in backend.last_status.message


async def test_mount_error_surfaces_as_failed_status_not_a_crash():
    """DESIGN.md §10 Phase 3: mount errors must produce a clean give-up, not
    a silently-dead background task (a real bug found testing real
    hardware -- see closed_loop_backend._run_loop)."""

    class ExplodingMount:
        async def slew_to(self, target):
            raise RuntimeError("simulated mount failure")

        async def is_slewing(self):
            return False

        async def sync_to(self, coord):
            pass

        async def get_equatorial_system(self):
            return 2000.0

        async def get_position(self):
            return CelestialCoord(ra_deg=0.0, dec_deg=0.0)

        async def abort_slew(self):
            pass

    world = World(error_model=HarmonicErrorModel())
    inner = MockTelescopeBackend(world)
    cedar = MockCedar(world)
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, ExplodingMount(), cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount")
    )
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)

        assert backend.last_status is not None
        assert backend.last_status.state.name == "FAILED"

        # The server itself must still be healthy -- not crashed/hung.
        resp = await client.get("/api/v1/telescope/0/rightascension")
        assert resp.json()["ErrorNumber"] == 0


async def test_a_new_slew_works_normally_after_a_failed_one():
    world = World(error_model=HarmonicErrorModel())
    world.inject_solve_failures(1)
    # 1 rejected solve then good ones -- forces one EVALUATE-less pass
    # through the acceptance gate before recovering. Use a tight timeout so
    # the countdown expiring mid-wait doesn't itself cause a FAILED giveup.
    backend = make_backend(world, max_iterations=1, tolerance_arcmin=1e-6, solve_wait_timeout_s=5.0)
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await _slew_and_wait(client, 8.0, 30.0)
        assert backend.last_status.state.name == "FAILED"

        # A fresh slew afterward should converge normally -- no stuck state
        # left behind by the previous failure.
        backend._loop_config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=5, settle_s=0.01)
        await _slew_and_wait(client, 9.0, -20.0)
        assert backend.last_status.state.name == "CONVERGED"


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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount")
    )
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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, NoSolveCedar(), config, SolveAcceptance(), PositionSourceConfig(source="mount")
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
    ClosedLoopTelescopeBackend must degrade gracefully, not crash."""
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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount")
    )
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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="mount")
    )
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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, UnreachableCedar(), config, SolveAcceptance(), PositionSourceConfig(source="cedar")
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
    config = LoopConfigCore(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, config, SolveAcceptance(), PositionSourceConfig(source="cedar")
    )
    async with await make_client(backend) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        ra = (await client.get("/api/v1/telescope/0/rightascension")).json()["Value"]
        # MockCedar reports the world's true pointing (0,0 initially) as an
        # accepted solve -- should be preferred over the mount's own report.
        assert ra == pytest.approx(0.0, abs=1e-6)
