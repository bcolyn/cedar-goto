"""Assembles the external Alpaca-facing FastAPI app (DESIGN.md §3, §7)."""
from __future__ import annotations

from fastapi import FastAPI

from cedar_goto.web.backend import TelescopeBackend
from cedar_goto.web.management import router as management_router
from cedar_goto.web.telescope_api import router as telescope_router
from cedar_goto.web.ui import router as ui_router


def create_app(
    backend: TelescopeBackend, cedar_address: str | None = None, cedar_same_host: bool = False
) -> FastAPI:
    app = FastAPI(title="cedar-goto")
    app.state.telescope_backend = backend
    # Raw "host:port" from [cedar].address, not a built URL -- cedar-server
    # serves its own web UI on the same host:port as its gRPC (DESIGN.md,
    # README "cedar-server serves gRPC on the same port as its web UI").
    # None when [cedar].backend isn't "grpc" (mock/echo have no real
    # cedar-server UI to link to). web/ui.py's index() builds the actual
    # link per-request, resolving a loopback host against the request's own
    # host -- see _resolve_cedar_ui_url().
    app.state.cedar_address = cedar_address
    # Gates the Cedar card's Start/Stop cedar-server buttons (web/ui.py,
    # web/cedar_service.py) -- both server-side (the action routes refuse
    # regardless of what the client sends) and client-side (hides the
    # buttons entirely when there's no local cedar-server systemd unit to
    # control).
    app.state.cedar_same_host = cedar_same_host
    app.include_router(telescope_router)
    app.include_router(management_router)
    app.include_router(ui_router)
    return app
