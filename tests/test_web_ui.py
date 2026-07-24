"""Phase 4: the minimal web UI (DESIGN.md §8) -- status snapshot, SSE
events, and the sync-now/abort actions."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from cedar_goto.adapters.mock.cedar import MockCedar
from cedar_goto.adapters.mock.mount import MockMount
from cedar_goto.adapters.mock.telescope_backend import MockTelescopeBackend
from cedar_goto.adapters.mock.world import HarmonicErrorModel, World
from cedar_goto.config import PositionSourceConfig
from cedar_goto.core.loop import LoopConfigCore
from cedar_goto.core.solve import SolveAcceptance
from cedar_goto.web.app import create_app
from cedar_goto.web.closed_loop_backend import ClosedLoopTelescopeBackend

BASE = "http://testserver"


def make_client(world: World, **loop_overrides) -> httpx.AsyncClient:
    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), MockCedar(world)
    defaults = dict(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    defaults.update(loop_overrides)
    backend = ClosedLoopTelescopeBackend(
        inner, mount, cedar, LoopConfigCore(**defaults), SolveAcceptance(), PositionSourceConfig(source="mount")
    )
    app = create_app(backend)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


async def test_index_page_serves_html():
    async with make_client(World()) as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "cedar-goto" in resp.text


async def test_status_reflects_idle_then_converged():
    world = World(error_model=HarmonicErrorModel())
    async with make_client(world) as client:
        idle = (await client.get("/api/ui/status")).json()
        assert idle["state"] == "IDLE"
        assert idle["connected"] is False

        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "4.0", "Declination": "15.0"},
        )

        for _ in range(200):
            await asyncio.sleep(0.02)
            status = (await client.get("/api/ui/status")).json()
            if status["state"] in ("CONVERGED", "FAILED"):
                break
        else:
            pytest.fail("slew never settled")

        assert status["state"] == "CONVERGED"
        assert status["connected"] is True
        assert status["last_solve"] is not None
        assert status["error_arcmin"] is not None


async def test_sync_now_action():
    world = World(error_model=HarmonicErrorModel())
    async with make_client(world) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.post("/api/ui/actions/sync-now")
        body = resp.json()
        assert body["ok"] is True
        assert "RA" in body["message"]


async def test_sync_to_target_action_reports_no_target_yet():
    world = World()
    async with make_client(world) as client:
        resp = await client.post("/api/ui/actions/sync-to-target")
        body = resp.json()
        assert body["ok"] is False


async def test_sync_to_target_action_syncs_to_the_commanded_target_not_the_solve():
    world = World(error_model=HarmonicErrorModel())
    async with make_client(world) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "4.0", "Declination": "15.0"},
        )
        for _ in range(200):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("slew never settled")

        resp = await client.post("/api/ui/actions/sync-to-target")
        body = resp.json()
        assert body["ok"] is True
        assert "RA 4.000h Dec 15.000" in body["message"]


async def test_correction_toggle_reflected_in_status_and_disables_the_loop():
    world = World(error_model=HarmonicErrorModel())
    async with make_client(world) as client:
        status = (await client.get("/api/ui/status")).json()
        assert status["correction_enabled"] is True

        resp = await client.post("/api/ui/actions/correction", data={"enabled": "false"})
        assert resp.json()["ok"] is True
        status = (await client.get("/api/ui/status")).json()
        assert status["correction_enabled"] is False

        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "4.0", "Declination": "15.0"},
        )
        # No closed loop should ever run -- state stays IDLE throughout.
        for _ in range(20):
            await asyncio.sleep(0.02)
            assert (await client.get("/api/ui/status")).json()["state"] == "IDLE"

        for _ in range(200):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("bare slew never settled")

        status = (await client.get("/api/ui/status")).json()
        assert status["last_target"]["ra_deg"] == pytest.approx(60.0)


async def test_status_includes_mount_info_with_sync_points_unsupported_by_mock():
    world = World()
    async with make_client(world) as client:
        status = (await client.get("/api/ui/status")).json()
        info = status["mount_info"]
        assert info is not None
        assert info["site_latitude_deg"] == pytest.approx(0.0)
        assert info["utc_date"].endswith("Z")
        # mock has no equivalent of INDI's alignment sync points.
        assert info["sync_point_count"] is None


async def test_status_includes_at_park():
    world = World()
    async with make_client(world) as client:
        status = (await client.get("/api/ui/status")).json()
        assert status["mount_info"]["at_park"] is False


async def test_park_and_unpark_actions_report_unsupported_for_mock():
    """MockTelescopeBackend doesn't implement Park/Unpark (DESIGN.md §9a
    scope) -- the UI routes must surface that as a clean ok:False, not a
    500 or an unhandled AlpacaError."""
    world = World()
    async with make_client(world) as client:
        resp = await client.post("/api/ui/actions/park")
        body = resp.json()
        assert body["ok"] is False

        resp = await client.post("/api/ui/actions/unpark")
        body = resp.json()
        assert body["ok"] is False


async def test_clear_sync_points_action_reports_unsupported_for_mock():
    world = World()
    async with make_client(world) as client:
        resp = await client.post("/api/ui/actions/clear-sync-points")
        body = resp.json()
        assert body["ok"] is False
        assert "not supported" in body["message"]


async def test_abort_action_stops_a_running_slew():
    world = World(error_model=HarmonicErrorModel())
    async with make_client(world, max_iterations=10) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "4.0", "Declination": "15.0"},
        )
        assert (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is True

        resp = await client.post("/api/ui/actions/abort")
        assert resp.json()["ok"] is True

        for _ in range(100):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("slew never stopped after the UI abort action")
