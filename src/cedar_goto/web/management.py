"""Alpaca management API (DESIGN.md §3): required for client discovery to
enumerate what devices this server exposes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from cedar_goto.web.http_utils import alpaca_response, client_transaction_id, collect_params

router = APIRouter()

# Some Alpaca clients (observed: SkySafari) parse UniqueID as a strict GUID
# and silently drop the device from setup if it isn't one -- deterministic
# so it's stable across restarts (clients may cache by this ID).
_TELESCOPE_UNIQUE_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "cedar-goto.telescope.0"))


@router.get("/management/apiversions")
async def api_versions(request: Request):
    params = await collect_params(request)
    return alpaca_response(client_transaction_id(params), value=[1])


@router.get("/management/v1/description")
async def server_description(request: Request):
    params = await collect_params(request)
    return alpaca_response(
        client_transaction_id(params),
        value={
            "ServerName": "cedar-goto",
            "Manufacturer": "cedar-goto",
            "ManufacturerVersion": "0.1",
            "Location": "cedar-goto closed-loop pointing bridge",
        },
    )


@router.get("/management/v1/configureddevices")
async def configured_devices(request: Request):
    params = await collect_params(request)
    return alpaca_response(
        client_transaction_id(params),
        value=[
            {
                "DeviceName": "cedar-goto Telescope",
                "DeviceType": "Telescope",
                "DeviceNumber": 0,
                "UniqueID": _TELESCOPE_UNIQUE_ID,
            }
        ],
    )
