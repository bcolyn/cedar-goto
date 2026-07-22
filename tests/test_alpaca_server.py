"""Tests for the Phase 1 external Alpaca proxy (DESIGN.md §3, §10), driven
against the mock backend so it runs without hardware."""
from __future__ import annotations

import httpx
import pytest

from cedar_goto.adapters.mock.telescope_backend import MockTelescopeBackend
from cedar_goto.adapters.mock.world import World
from cedar_goto.web.app import create_app

BASE = "http://testserver"


async def make_client() -> httpx.AsyncClient:
    app = create_app(MockTelescopeBackend(World()))
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url=BASE)


async def test_management_api_lists_telescope_device():
    async with await make_client() as client:
        resp = await client.get("/management/apiversions")
        assert resp.json()["Value"] == [1]

        resp = await client.get("/management/v1/configureddevices")
        devices = resp.json()["Value"]
        assert devices[0]["DeviceType"] == "Telescope"
        assert devices[0]["DeviceNumber"] == 0


async def test_uses_client_transaction_id_and_increments_server_transaction_id():
    async with await make_client() as client:
        r1 = await client.get("/api/v1/telescope/0/connected?ClientTransactionID=42")
        r2 = await client.get("/api/v1/telescope/0/connected?ClientTransactionID=43")
        assert r1.json()["ClientTransactionID"] == 42
        assert r2.json()["ClientTransactionID"] == 43
        assert r2.json()["ServerTransactionID"] > r1.json()["ServerTransactionID"]


async def test_members_are_gated_until_connected():
    async with await make_client() as client:
        resp = await client.get("/api/v1/telescope/0/rightascension")
        body = resp.json()
        assert body["ErrorNumber"] == 1031  # NotConnectedException

        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.get("/api/v1/telescope/0/rightascension")
        assert resp.json()["ErrorNumber"] == 0


async def test_plain_proxy_slew_moves_the_mock_world():
    async with await make_client() as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})

        resp = await client.put(
            "/api/v1/telescope/0/slewtocoordinatesasync",
            data={"RightAscension": "5.0", "Declination": "20.0"},
        )
        assert resp.json()["ErrorNumber"] == 0

        slewing = await client.get("/api/v1/telescope/0/slewing")
        assert slewing.json()["Value"] is True

        # World.settle_s defaults to 0.05s; give it time to settle.
        import asyncio

        await asyncio.sleep(0.2)

        slewing = await client.get("/api/v1/telescope/0/slewing")
        assert slewing.json()["Value"] is False

        ra = (await client.get("/api/v1/telescope/0/rightascension")).json()["Value"]
        dec = (await client.get("/api/v1/telescope/0/declination")).json()["Value"]
        # Harmonic error model perturbs the commanded position by a few
        # arcminutes -- just assert it landed near the target, not exactly.
        assert abs(ra - 5.0) < 0.5
        assert abs(dec - 20.0) < 0.5


async def test_capability_flags_are_proxied():
    async with await make_client() as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.get("/api/v1/telescope/0/cansync")
        assert resp.json()["Value"] is True
        resp = await client.get("/api/v1/telescope/0/canpark")
        assert resp.json()["Value"] is False


async def test_unknown_action_returns_action_not_implemented():
    async with await make_client() as client:
        resp = await client.get("/api/v1/telescope/0/notarealmember")
        assert resp.json()["ErrorNumber"] == 1036


async def test_put_on_read_only_property_is_rejected():
    async with await make_client() as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.put("/api/v1/telescope/0/rightascension", data={"RightAscension": "5.0"})
        assert resp.json()["ErrorNumber"] == 1035  # InvalidOperationException


async def test_get_on_method_is_rejected():
    async with await make_client() as client:
        await client.put("/api/v1/telescope/0/connected", data={"Connected": "true"})
        resp = await client.get("/api/v1/telescope/0/abortslew")
        assert resp.json()["ErrorNumber"] == 1035
