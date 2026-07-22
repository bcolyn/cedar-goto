"""Shared Alpaca HTTP request/response plumbing (DESIGN.md §3, §7)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from cedar_goto.web.alpaca_errors import AlpacaError, response_envelope


async def collect_params(request: Request) -> dict[str, str]:
    """Alpaca clients send args as query params on GET, form-encoded body on
    PUT. Keys are matched case-insensitively (canonical case varies by
    client)."""
    params = {k.lower(): v for k, v in request.query_params.items()}
    if request.method == "PUT":
        form = await request.form()
        params.update({k.lower(): v for k, v in form.items()})
    return params


def client_transaction_id(params: dict) -> int:
    try:
        return int(params.get("clienttransactionid", 0))
    except (TypeError, ValueError):
        return 0


def coerce(value: str, type_: str):
    if type_ == "bool":
        return str(value).strip().lower() in ("true", "1")
    if type_ == "int":
        return int(float(value))
    if type_ == "float":
        return float(value)
    return value


def alpaca_response(client_txn_id: int, value: object = None, error: AlpacaError | None = None) -> JSONResponse:
    return JSONResponse(response_envelope(client_txn_id, value=value, error=error))
