"""Assembles the external Alpaca-facing FastAPI app (DESIGN.md §3, §7)."""
from __future__ import annotations

from fastapi import FastAPI

from cedar_goto.web.backend import TelescopeBackend
from cedar_goto.web.management import router as management_router
from cedar_goto.web.telescope_api import router as telescope_router
from cedar_goto.web.ui import router as ui_router


def create_app(backend: TelescopeBackend) -> FastAPI:
    app = FastAPI(title="cedar-goto")
    app.state.telescope_backend = backend
    app.include_router(telescope_router)
    app.include_router(management_router)
    app.include_router(ui_router)
    return app
