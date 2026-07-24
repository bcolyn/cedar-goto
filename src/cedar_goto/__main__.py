"""cedar-goto entry point.

Phase 2 (DESIGN.md §5, §10): the external Alpaca Telescope proxy with the
closed loop wired into SlewToCoordinates(Async) -- slews are corrected
against cedar's plate-solved position, not just passed straight through.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from cedar_goto.adapters.buzzer import build_buzzer
from cedar_goto.config import Config
from cedar_goto.core.loop import LoopConfigCore
from cedar_goto.core.solve import SolveAcceptance
from cedar_goto.web.app import create_app
from cedar_goto.web.backend import TelescopeBackend
from cedar_goto.web.closed_loop_backend import ClosedLoopTelescopeBackend
from cedar_goto.web.discovery import start_discovery_responder

logger = logging.getLogger(__name__)


def _loop_config(config: Config) -> LoopConfigCore:
    return LoopConfigCore(
        tolerance_arcmin=config.loop.tolerance_arcmin,
        max_correction_arcmin=config.loop.max_correction_arcmin,
        max_iterations=config.loop.max_iterations,
        settle_s=config.loop.settle_ms / 1000.0,
    )


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

    return ClosedLoopTelescopeBackend(
        inner,
        mount,
        cedar,
        _loop_config(config),
        _solve_acceptance(config),
        config.position,
        buzzer=build_buzzer(config.buzzer),
        correction_enabled=config.loop.correction_enabled,
    )


async def _run(config: Config) -> None:
    backend = _build_backend(config)
    app = create_app(backend)

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
    parser = argparse.ArgumentParser(prog="cedar-goto")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    config = Config.load(args.config)
    asyncio.run(_run(config))


if __name__ == "__main__":
    main()
