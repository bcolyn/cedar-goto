"""cedar-goto entry point.

Facilitates using cedar-server (plate solver) with a GoTo mount: the
external Alpaca Telescope proxy, plus the web UI actions (web/ui.py) that
sync the mount to cedar's solve, sync to the last commanded target, or
re-slew to it. Slews themselves proxy straight through to the mount --
cedar-goto does not drive the mount automatically.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from cedar_goto.config import Config
from cedar_goto.core.solve import SolveAcceptance
from cedar_goto.web.app import create_app
from cedar_goto.web.backend import TelescopeBackend
from cedar_goto.web.cedar_backend import CedarTelescopeBackend
from cedar_goto.web.discovery import start_discovery_responder
from cedar_goto.web.log_buffer import install as install_log_buffer
from cedar_goto.web.ui import cedar_address_is_loopback

logger = logging.getLogger(__name__)


def _solve_acceptance(config: Config) -> SolveAcceptance:
    return SolveAcceptance(
        min_matches=config.solve.min_matches,
        max_prob_false_positive=config.solve.max_prob_false_positive,
        max_p90_error_arcsec=config.solve.max_p90_error_arcsec,
        reject_imu=config.solve.reject_imu,
    )


def _build_backend(config: Config) -> TelescopeBackend:
    # [mount].backend and [cedar].backend are independent -- e.g. a real
    # mount against a mock solve source when cedar-server can't solve
    # (daylight, no stars).
    world = None
    if config.mount.backend == "mock":
        from cedar_goto.adapters.mock.mount import MockMount
        from cedar_goto.adapters.mock.telescope_backend import MockTelescopeBackend
        from cedar_goto.adapters.mock.world import World

        logger.info("Using mock mount backend (simulated-sky harness, DESIGN.md §9a)")
        world = World()
        inner = MockTelescopeBackend(
            world,
            site_latitude_deg=config.site.latitude_deg,
            site_longitude_deg=config.site.longitude_deg,
            site_elevation_m=config.site.elevation_m,
        )
        mount = MockMount(world)
    elif config.mount.backend == "indi":
        from cedar_goto.adapters.indi.client import IndiConnection
        from cedar_goto.adapters.indi.mount_client import IndiMountClient
        from cedar_goto.adapters.indi.telescope_backend import IndiTelescopeBackend

        host, _, port_str = config.mount.address.partition(":")
        port = int(port_str) if port_str else 7624
        logger.info(
            "Using direct-INDI mount backend at %s:%s device %r (indi-refactor.md)",
            host, port, config.mount.indi_device_name,
        )
        conn = IndiConnection(host, port, config.mount.indi_device_name)
        inner = IndiTelescopeBackend(conn)
        mount = IndiMountClient(conn)
    else:
        from cedar_goto.adapters.alpaca.mount_client import AlpacaMountClient
        from cedar_goto.adapters.alpaca.telescope_backend import AlpycaTelescopeBackend

        logger.info(
            "Using real mount backend at %s device %s", config.mount.address, config.mount.device_number
        )
        inner = AlpycaTelescopeBackend(config.mount.address, config.mount.device_number)
        mount = AlpacaMountClient(config.mount.address, config.mount.device_number)

    if config.cedar.backend == "mock":
        if world is not None:
            from cedar_goto.adapters.mock.cedar import MockCedar

            logger.info("Using mock cedar solve source (shared simulated-sky World)")
            cedar = MockCedar(world)
        else:
            from cedar_goto.adapters.mock.echo_cedar import MountEchoCedar

            logger.info(
                "Using mount-echo solve source (reports the real mount's own position as "
                "ground truth -- for exercising a real mount without a working cedar-server)"
            )
            cedar = MountEchoCedar(mount)
    else:
        from cedar_goto.adapters.cedar_grpc.client import CedarGrpcClient

        logger.info("Using real cedar gRPC solve source at %s", config.cedar.address)
        cedar = CedarGrpcClient(config.cedar.address)

    from cedar_goto.core.epoch_normalizing_solve_source import EpochNormalizingSolveSource

    # The single epoch-conversion seam (epoch-seam decision, 2026-07-26):
    # every SolveSource emits J2000; cedar-goto works internally in whatever
    # epoch `mount` itself advertises. Applied uniformly, including to the
    # mock sources -- see EpochNormalizingSolveSource's docstring.
    cedar = EpochNormalizingSolveSource(cedar, mount.get_equatorial_system)

    return CedarTelescopeBackend(inner, mount, cedar, _solve_acceptance(config), config.position)


def _cedar_address_for_link(config: Config) -> str | None:
    # cedar-server serves its own web UI on the same host:port as its gRPC
    # (README "cedar-server serves gRPC on the same port as its web UI") --
    # None for "mock"/other backends, which have no real cedar-server UI to
    # link to. Deliberately the raw "host:port" from config, not a built
    # URL: when the host is "localhost" (a same-host deployment, same case
    # _cedar_same_host() checks for), web/ui.py's index() must resolve it
    # against the *request's* own host at request time, not this process's
    # -- "localhost" in a link opened from a phone resolves on the phone,
    # not on cedar-goto's box.
    if config.cedar.backend != "grpc":
        return None
    return config.cedar.address


def _cedar_same_host(config: Config) -> bool:
    # Gates the web UI's Start/Stop cedar-server buttons (web/cedar_service.py)
    # -- only meaningful when there's a real cedar-server to control at all
    # (backend == "grpc"), and only when it's reachable via loopback, i.e.
    # cedar-goto and cedar-server run on the same box, so a local `sudo
    # systemctl` call actually controls the right service.
    return config.cedar.backend == "grpc" and cedar_address_is_loopback(config.cedar.address)


async def _run(config: Config) -> None:
    backend = _build_backend(config)
    app = create_app(
        backend, cedar_address=_cedar_address_for_link(config), cedar_same_host=_cedar_same_host(config)
    )

    server = uvicorn.Server(
        uvicorn.Config(app, host=config.server.bind, port=config.server.alpaca_port, log_level="info")
    )

    tasks = [asyncio.create_task(server.serve())]
    if config.server.discovery:
        transport = await start_discovery_responder(config.server.bind, config.server.alpaca_port)
        logger.info("Alpaca discovery responder listening on UDP %s:32227", config.server.bind)
    else:
        transport = None

    try:
        await asyncio.gather(*tasks)
    finally:
        if transport is not None:
            transport.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    install_log_buffer()
    parser = argparse.ArgumentParser(prog="cedar-goto")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    config = Config.load(args.config)
    asyncio.run(_run(config))


if __name__ == "__main__":
    main()
