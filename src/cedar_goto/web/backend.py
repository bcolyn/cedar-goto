"""The full-surface Telescope backend the external Alpaca face proxies to.

Deliberately separate from core.ports.MountControl: that port is the
*minimal* interface the closed-loop state machine needs (DESIGN.md §12).
This one is I/O-facing and covers the much larger ASCOM ITelescopeV3
property/method surface the transparent proxy (DESIGN.md §3) forwards.
"""
from __future__ import annotations

from typing import Any, Protocol

from cedar_goto.web.alpaca_spec import Member


class TelescopeBackend(Protocol):
    async def get(self, member: Member) -> Any: ...

    async def put(self, member: Member, params: dict[str, Any]) -> Any: ...

    async def query(self, member: Member, params: dict[str, Any]) -> Any: ...
    """For 'query_ro' members: a read-only, parameterised GET (e.g.
    CanMoveAxis(Axis)) -- distinct from `get` (no params) and `put`
    (state-changing)."""
