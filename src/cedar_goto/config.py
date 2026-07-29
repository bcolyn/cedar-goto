"""Pydantic config models mirroring DESIGN.md §6, loaded from TOML."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class MountConfig(BaseModel):
    address: str = "127.0.0.1:11111"
    device_number: int = 0
    backend: Literal["alpyca", "mock", "indi"] = "mock"
    """"mock" drives the simulated-sky harness (DESIGN.md §9a) instead of a
    real mount -- the safe default until the real mount link is verified
    (DESIGN.md §3a/§11). "indi" talks straight to indiserver (indi-refactor.md)
    instead of through indi_alpaca_server, bypassing that bridge's stale
    property snapshot bug."""
    indi_device_name: str = "Skywatcher Alt-Az"
    """Only used by the "indi" backend -- INDI addresses devices by name, not
    number, so device_number is ignored for that backend. `address` is
    reused as host:port of indiserver itself (default port 7624)."""


class CedarConfig(BaseModel):
    address: str = "127.0.0.1:80"
    """cedar-server serves gRPC on the same port as its web UI (tonic's
    GrpcWebLayer) -- default 80, not a dedicated gRPC port."""
    backend: Literal["grpc", "mock"] = "mock"
    """Independent of [mount].backend -- e.g. testing a real mount against
    the mock solve source when cedar-server can't solve (daylight, no
    stars)."""


class ServerConfig(BaseModel):
    bind: str = "0.0.0.0"
    alpaca_port: int = 11111
    discovery: bool = True


class SiteConfig(BaseModel):
    latitude_deg: float = 0.0
    longitude_deg: float = 0.0
    elevation_m: float = 0.0
    """Only used by the mock backend (a real mount reports its own
    configured site). Some Alpaca clients treat 0,0 as "unconfigured" and
    disable GoTo -- set this to your actual location when testing against
    the mock."""


class SolveConfig(BaseModel):
    min_matches: int = 10
    max_prob_false_positive: float = 1e-3
    """See SolveAcceptance.max_prob_false_positive (core/solve.py) --
    tetra3's reported "prob" is a false-positive probability, lower is
    better."""
    max_p90_error_arcsec: float = 30.0
    reject_imu: bool = True


class PositionSourceConfig(BaseModel):
    source: Literal["cedar", "mount", "cedar_fallback_mount"] = "cedar_fallback_mount"
    max_solve_age_s: float = 5.0


class Config(BaseModel):
    mount: MountConfig = MountConfig()
    cedar: CedarConfig = CedarConfig()
    server: ServerConfig = ServerConfig()
    site: SiteConfig = SiteConfig()
    solve: SolveConfig = SolveConfig()
    position: PositionSourceConfig = PositionSourceConfig()

    @classmethod
    def load(cls, path: Path | str) -> "Config":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> "Config":
        return cls()
