"""The web UI (DESIGN.md §8) -- status snapshot, SSE events, and the
mount/target/cedar actions (park/unpark/stop, slew/sync-to-target,
sync-to-cedar)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from cedar_goto.adapters.mock.cedar import MockCedar
from cedar_goto.adapters.mock.mount import MockMount
from cedar_goto.adapters.mock.telescope_backend import MockTelescopeBackend
from cedar_goto.adapters.mock.world import HarmonicErrorModel, World
from cedar_goto.config import PositionSourceConfig
from cedar_goto.core.solve import SolveAcceptance
from cedar_goto.web.app import create_app
from cedar_goto.web.cedar_backend import CedarTelescopeBackend
from cedar_goto.web.ui import cedar_address_is_loopback

BASE = "http://testserver"


@pytest.mark.parametrize(
    "address,expected",
    [
        ("localhost:80", True),
        ("127.0.0.1:80", True),
        ("cedar.home.colyn.be:80", False),
        # A previous version substring-matched "localhost" -- these must
        # NOT false-positive on a bare substring/prefix match.
        ("127.0.0.100:80", False),
        ("notlocalhost.example.com:80", False),
    ],
)
def test_cedar_address_is_loopback(address, expected):
    assert cedar_address_is_loopback(address) is expected


def make_client(
    world: World, cedar_address: str | None = None, cedar_same_host: bool = False
) -> httpx.AsyncClient:
    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), MockCedar(world)
    backend = CedarTelescopeBackend(inner, mount, cedar, SolveAcceptance(), PositionSourceConfig(source="mount"))
    app = create_app(backend, cedar_address=cedar_address, cedar_same_host=cedar_same_host)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


async def test_index_page_serves_html():
    async with make_client(World()) as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "cedar-goto" in resp.text


async def test_index_page_has_no_cedar_link_by_default():
    async with make_client(World()) as client:
        resp = await client.get("/")
        assert "link: null," in resp.text


async def test_index_page_embeds_the_cedar_ui_url_when_configured():
    async with make_client(World(), cedar_address="cedar.example.com:80") as client:
        resp = await client.get("/")
        assert 'link: "http://cedar.example.com:80/",' in resp.text


async def test_index_page_resolves_a_loopback_cedar_address_against_the_request_host():
    """A same-host deployment configures [cedar].address as "localhost:80"
    or "127.0.0.1:80" -- the link must resolve against whatever host the
    client actually used to reach cedar-goto (same box as cedar-server),
    not "localhost", which would resolve on the client's own device
    instead when opened from a phone."""
    async with make_client(World(), cedar_address="localhost:80") as client:
        resp = await client.get("/")
        assert 'link: "http://testserver:80/",' in resp.text

    async with make_client(World(), cedar_address="127.0.0.1:80") as client:
        resp = await client.get("/")
        assert 'link: "http://testserver:80/",' in resp.text


async def test_index_page_hides_cedar_service_row_by_default():
    async with make_client(World()) as client:
        resp = await client.get("/")
        assert "if (false) {" in resp.text


async def test_index_page_shows_cedar_service_row_when_same_host():
    async with make_client(World(), cedar_same_host=True) as client:
        resp = await client.get("/")
        assert "if (true) {" in resp.text


async def test_cedar_start_stop_refused_when_not_same_host():
    async with make_client(World()) as client:
        for action in ("cedar-start", "cedar-stop"):
            resp = await client.post(f"/api/ui/actions/{action}")
            body = resp.json()
            assert body["ok"] is False
            assert "not on this host" in body["message"]


async def test_cedar_start_stop_call_systemctl_when_same_host():
    from unittest.mock import AsyncMock, patch

    async with make_client(World(), cedar_same_host=True) as client:
        with patch(
            "cedar_goto.web.ui.cedar_systemctl", AsyncMock(return_value=(True, "cedar-server started"))
        ) as mock_systemctl:
            resp = await client.post("/api/ui/actions/cedar-start")
        body = resp.json()
        assert body["ok"] is True
        assert body["message"] == "cedar-server started"
        mock_systemctl.assert_awaited_once_with("start")


async def test_status_reflects_connected_and_solve():
    world = World(error_model=HarmonicErrorModel())
    async with make_client(world) as client:
        idle = (await client.get("/api/ui/status")).json()
        assert idle["connected"] is False
        assert idle["last_target"] is None
        # MockCedar always has a live solve ready -- reflects cedar's
        # current state, not a cached result from any prior action.
        assert idle["last_solve"] is not None
        assert idle["cedar_connected"] is True

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

        status = (await client.get("/api/ui/status")).json()
        assert status["connected"] is True
        assert status["last_target"]["ra_deg"] == pytest.approx(60.0)


async def test_sync_now_action():
    world = World(error_model=HarmonicErrorModel())
    async with make_client(world) as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.post("/api/ui/actions/sync-now")
        body = resp.json()
        assert body["ok"] is True
        assert "RA" in body["message"]


async def test_realign_action():
    world = World()
    async with make_client(world) as client:
        resp = await client.post("/api/ui/actions/realign")
        body = resp.json()
        assert body["ok"] is True


async def test_log_action_returns_lines():
    world = World()
    async with make_client(world) as client:
        resp = await client.get("/api/ui/log")
        body = resp.json()
        assert isinstance(body["lines"], list)


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


async def test_reslew_to_target_reports_no_target_yet():
    async with make_client(World()) as client:
        resp = await client.post("/api/ui/actions/reslew-to-target")
        body = resp.json()
        assert body["ok"] is False
        assert "no target" in body["message"]


async def test_reslew_to_target_reissues_a_bare_slew():
    """A single mount.slew_to() repeat -- no cedar solving, no iteration."""
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
            pytest.fail("bare slew never settled")

        resp = await client.post("/api/ui/actions/reslew-to-target")
        body = resp.json()
        assert body["ok"] is True
        assert "RA 4.000h Dec 15.000" in body["message"]

        for _ in range(200):
            await asyncio.sleep(0.02)
            if (await client.get("/api/v1/telescope/0/slewing")).json()["Value"] is False:
                break
        else:
            pytest.fail("re-slew never settled")


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
    async with make_client(world) as client:
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
