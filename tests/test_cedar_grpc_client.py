"""notify_slew_started/notify_slew_stopped against CedarGrpcClient (2026-07-24:
teaches cedar-server about a slew cedar-goto's own closed loop is driving, so
it can offer push-to guidance -- previously cedar-server had no idea a slew
was even happening, since cedar-goto intercepts the ASCOM slew instead of
forwarding it)."""
from __future__ import annotations

import grpc
import pytest

from cedar_goto.adapters.cedar_grpc.client import CedarGrpcClient
from cedar_goto.core.coords import CelestialCoord


class _FakeStub:
    def __init__(self, raise_error: bool = False) -> None:
        self.calls: list = []
        self._raise_error = raise_error

    async def InitiateAction(self, request):
        self.calls.append(request)
        if self._raise_error:
            raise grpc.RpcError("simulated cedar-server outage")


def make_client() -> CedarGrpcClient:
    # grpc.aio channels connect lazily -- safe to construct without a real
    # server, as long as we swap in a fake stub before making any RPC calls.
    return CedarGrpcClient("127.0.0.1:1")


async def test_notify_slew_started_sends_initiate_slew_with_the_target():
    client = make_client()
    stub = _FakeStub()
    client._stub = stub

    await client.notify_slew_started(CelestialCoord(ra_deg=120.0, dec_deg=30.0))

    assert len(stub.calls) == 1
    request = stub.calls[0]
    assert request.HasField("initiate_slew")
    assert request.initiate_slew.ra == pytest.approx(120.0)
    assert request.initiate_slew.dec == pytest.approx(30.0)


async def test_notify_slew_stopped_sends_stop_slew():
    client = make_client()
    stub = _FakeStub()
    client._stub = stub

    await client.notify_slew_stopped()

    assert len(stub.calls) == 1
    assert stub.calls[0].stop_slew is True


async def test_notify_slew_started_swallows_rpc_errors():
    """Push-to notification is best-effort -- a cedar-server hiccup here
    must not propagate and break the actual mount-nudging slew."""
    client = make_client()
    client._stub = _FakeStub(raise_error=True)

    await client.notify_slew_started(CelestialCoord(ra_deg=0.0, dec_deg=0.0))


async def test_notify_slew_stopped_swallows_rpc_errors():
    client = make_client()
    client._stub = _FakeStub(raise_error=True)

    await client.notify_slew_stopped()
