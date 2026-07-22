"""Mock MountControl implementation driving a shared World (DESIGN.md §9a)."""
from __future__ import annotations

import asyncio

from cedar_goto.adapters.mock.world import World
from cedar_goto.core.coords import J2000, CelestialCoord
from cedar_goto.core.ports import MountControl


class MockMount(MountControl):
    def __init__(self, world: World, equatorial_system: float = J2000) -> None:
        self._world = world
        self._equatorial_system = equatorial_system

    async def slew_to(self, target: CelestialCoord) -> None:
        await asyncio.sleep(0)  # cooperative yield, mirrors a real network call
        self._world.command_slew(target)

    async def is_slewing(self) -> bool:
        return self._world.is_slewing()

    async def sync_to(self, coord: CelestialCoord) -> None:
        await asyncio.sleep(0)
        self._world.sync(coord)

    async def get_equatorial_system(self) -> float:
        return self._equatorial_system

    async def get_position(self) -> CelestialCoord:
        return self._world.true_pointing

    async def abort_slew(self) -> None:
        self._world.slewing_until = 0.0
