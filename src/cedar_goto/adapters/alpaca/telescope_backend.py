"""TelescopeBackend over a real Alpaca mount, via alpyca (DESIGN.md §3).

alpyca's Telescope class already implements the ASCOM ITelescopeV3 surface
with attribute/method names matching web.alpaca_spec's Member.name exactly,
so this backend is a thin generic getattr/setattr dispatch rather than one
hand-written method per member -- adding a member to alpaca_spec.py is
enough, no code here needs to change.
"""
from __future__ import annotations

import asyncio

from alpaca.exceptions import (
    ActionNotImplementedException,
    DriverException,
    InvalidOperationException,
    InvalidValueException,
    NotConnectedException,
    NotImplementedException,
    OperationCancelledException,
    ParkedException,
    SlavedException,
    ValueNotSetException,
)
from alpaca.telescope import Telescope, TelescopeAxes

from cedar_goto.web.alpaca_errors import AlpacaError
from cedar_goto.web.alpaca_spec import Member

# alpyca has no shared base exception -- each of these subclasses Exception
# directly but carries a `.number`/`.message` matching the ASCOM error it
# reports (confirmed against the installed alpyca version; not part of its
# public contract, so this list may need updating on an alpyca upgrade).
_ALPYCA_EXCEPTIONS = (
    ActionNotImplementedException,
    DriverException,
    InvalidOperationException,
    InvalidValueException,
    NotConnectedException,
    NotImplementedException,
    OperationCancelledException,
    ParkedException,
    SlavedException,
    ValueNotSetException,
)


class AlpycaTelescopeBackend:
    def __init__(self, address: str, device_number: int = 0) -> None:
        host, _, port = address.partition(":")
        self._telescope = Telescope(f"{host}:{port}" if port else address, device_number)

    async def get(self, member: Member):
        return await asyncio.to_thread(self._get_sync, member)

    async def put(self, member: Member, params: dict):
        return await asyncio.to_thread(self._put_sync, member, params)

    async def query(self, member: Member, params: dict):
        return await asyncio.to_thread(self._call_sync, member, params)

    def _get_sync(self, member: Member):
        try:
            return getattr(self._telescope, member.name)
        except _ALPYCA_EXCEPTIONS as exc:
            raise AlpacaError(exc.number, exc.message) from exc

    def _put_sync(self, member: Member, params: dict):
        try:
            if member.kind == "prop_rw":
                (param,) = member.params
                setattr(self._telescope, member.name, params[param.name])
                return None
            return self._call_sync(member, params)
        except _ALPYCA_EXCEPTIONS as exc:
            raise AlpacaError(exc.number, exc.message) from exc

    def _call_sync(self, member: Member, params: dict):
        # alpyca's Axis argument is a TelescopeAxes enum, not a raw int.
        kwargs = {
            p.name: (TelescopeAxes(params[p.name]) if p.name == "Axis" else params[p.name])
            for p in member.params
        }
        try:
            result = getattr(self._telescope, member.name)(**kwargs)
        except _ALPYCA_EXCEPTIONS as exc:
            raise AlpacaError(exc.number, exc.message) from exc
        if member.name == "AxisRates":
            # alpyca returns a list of Rate objects, not JSON-serializable.
            return [{"Maximum": r.Maximum, "Minimum": r.Minimum} for r in result]
        return result
