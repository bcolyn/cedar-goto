"""Alpaca UDP discovery responder (DESIGN.md §3, §7).

Clients (SkySafari, Cartes du Ciel) broadcast the ASCII string
"alpacadiscovery1" to UDP port 32227; a compliant server replies with
{"AlpacaPort": <port>} so the client can find the REST API without manual
configuration.
"""
from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 32227
_DISCOVERY_MESSAGE = b"alpacadiscovery1"


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, alpaca_port: int) -> None:
        self._alpaca_port = alpaca_port
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if not data.startswith(_DISCOVERY_MESSAGE):
            return
        reply = json.dumps({"AlpacaPort": self._alpaca_port}).encode("utf-8")
        assert self._transport is not None
        self._transport.sendto(reply, addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning("Discovery UDP error: %s", exc)


async def start_discovery_responder(bind: str, alpaca_port: int) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DiscoveryProtocol(alpaca_port),
        local_addr=(bind, DISCOVERY_PORT),
        allow_broadcast=True,
    )
    return transport
