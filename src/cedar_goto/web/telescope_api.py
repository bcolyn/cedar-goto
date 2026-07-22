"""The external Alpaca Telescope device (DESIGN.md §3).

One route handles every member declared in web.alpaca_spec, dispatching
generically to whatever TelescopeBackend is attached to the FastAPI app.
This is the "transparent proxy" — adding a per-member override later (the
closed loop intercepting SlewToCoordinatesAsync, Phase 2) means adding a
branch here or swapping the backend, not adding new routes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from cedar_goto.web.alpaca_errors import (
    ActionNotImplementedError,
    AlpacaError,
    DRIVER_ERROR_BASE,
    INVALID_OPERATION,
    InvalidValueError,
    NotConnectedError,
)
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION, UNGATED_ACTIONS
from cedar_goto.web.backend import TelescopeBackend
from cedar_goto.web.http_utils import alpaca_response, client_transaction_id, coerce, collect_params

logger = logging.getLogger(__name__)

router = APIRouter()

_CONNECTED_MEMBER = ALL_MEMBERS_BY_ACTION["connected"]


@router.api_route("/api/v1/telescope/{device_number}/{action}", methods=["GET", "PUT"])
async def telescope_endpoint(device_number: int, action: str, request: Request):
    backend: TelescopeBackend = request.app.state.telescope_backend
    params = await collect_params(request)
    txn_id = client_transaction_id(params)
    try:
        value = await _dispatch(backend, action.lower(), request.method, params)
        return alpaca_response(txn_id, value=value)
    except AlpacaError as exc:
        return alpaca_response(txn_id, error=exc)
    except Exception as exc:
        # A backend surprise here (real-hardware network timeout, an
        # unexpected library exception, etc.) must not become a raw HTTP
        # 500 -- Alpaca clients only understand ErrorNumber/ErrorMessage in
        # a normal 200 envelope. Seen live: a real mount's Park() call
        # timing out at the socket level (requests.exceptions.ReadTimeout,
        # not one of alpyca's ASCOM exception types).
        logger.exception("unhandled error dispatching %s %s", request.method, action)
        return alpaca_response(txn_id, error=AlpacaError(DRIVER_ERROR_BASE, f"{type(exc).__name__}: {exc}"))


async def _dispatch(backend: TelescopeBackend, action: str, method: str, params: dict):
    member = ALL_MEMBERS_BY_ACTION.get(action)
    if member is None:
        raise ActionNotImplementedError(action)

    if action not in UNGATED_ACTIONS:
        if not await backend.get(_CONNECTED_MEMBER):
            raise NotConnectedError()

    if method == "GET":
        if member.kind == "method":
            raise AlpacaError(INVALID_OPERATION, f"{member.name} requires PUT")
        if member.kind == "query_ro":
            return await backend.query(member, _coerce_params(member, params))
        return await backend.get(member)

    if member.kind in ("prop_ro", "query_ro"):
        raise AlpacaError(INVALID_OPERATION, f"{member.name} is read-only")

    return await backend.put(member, _coerce_params(member, params))


def _coerce_params(member, params: dict) -> dict:
    coerced = {}
    for p in member.params:
        raw = params.get(p.name.lower())
        if raw is None:
            raise InvalidValueError(f"Missing required parameter: {p.name}")
        coerced[p.name] = coerce(raw, p.type)
    return coerced
