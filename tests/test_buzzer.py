"""Phase 4: the GPIO buzzer (DESIGN.md §7) -- must never be a hard
dependency on real hardware, and the closed loop must beep appropriately."""
from __future__ import annotations

import asyncio

from cedar_goto.adapters.buzzer import NullBuzzer, build_buzzer
from cedar_goto.adapters.mock.cedar import MockCedar
from cedar_goto.adapters.mock.mount import MockMount
from cedar_goto.adapters.mock.world import HarmonicErrorModel, World
from cedar_goto.config import BuzzerConfig, PositionSourceConfig
from cedar_goto.core.loop import LoopConfigCore
from cedar_goto.core.solve import SolveAcceptance
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION
from cedar_goto.web.closed_loop_backend import ClosedLoopTelescopeBackend


def test_disabled_buzzer_is_a_null_buzzer():
    buzzer = build_buzzer(BuzzerConfig(enabled=False))
    assert isinstance(buzzer, NullBuzzer)
    buzzer.success()  # must not raise
    buzzer.failure()


def test_enabled_buzzer_falls_back_gracefully_without_gpio_hardware():
    # This dev machine has no GPIO backend -- build_buzzer must not raise,
    # regardless of whether gpiozero itself is even installed.
    buzzer = build_buzzer(BuzzerConfig(enabled=True, gpio_pin=18))
    buzzer.success()
    buzzer.failure()


class FakeBuzzer:
    def __init__(self) -> None:
        self.successes = 0
        self.failures = 0

    def success(self) -> None:
        self.successes += 1

    def failure(self) -> None:
        self.failures += 1


def _make_backend(world: World, buzzer: FakeBuzzer, **loop_overrides) -> ClosedLoopTelescopeBackend:
    from cedar_goto.adapters.mock.telescope_backend import MockTelescopeBackend

    inner = MockTelescopeBackend(world)
    mount, cedar = MockMount(world), MockCedar(world)
    defaults = dict(tolerance_arcmin=1.0, max_iterations=3, settle_s=0.01)
    defaults.update(loop_overrides)
    return ClosedLoopTelescopeBackend(
        inner,
        mount,
        cedar,
        LoopConfigCore(**defaults),
        SolveAcceptance(),
        PositionSourceConfig(source="mount"),
        buzzer=buzzer,
    )


async def _slew_via_backend(backend: ClosedLoopTelescopeBackend, ra_hours: float, dec_deg: float) -> None:
    member = ALL_MEMBERS_BY_ACTION["slewtocoordinatesasync"]
    await backend.put(member, {"RightAscension": ra_hours, "Declination": dec_deg})
    for _ in range(200):
        await asyncio.sleep(0.02)
        if not await backend.get(ALL_MEMBERS_BY_ACTION["slewing"]):
            return
    raise AssertionError("slew never finished")


async def test_buzzer_success_on_convergence():
    world = World(error_model=HarmonicErrorModel())
    buzzer = FakeBuzzer()
    backend = _make_backend(world, buzzer)
    await _slew_via_backend(backend, 8.0, 30.0)
    assert backend.last_status.state.name == "CONVERGED"
    assert buzzer.successes == 1
    assert buzzer.failures == 0


async def test_buzzer_failure_on_giveup():
    world = World(error_model=HarmonicErrorModel())
    buzzer = FakeBuzzer()
    backend = _make_backend(world, buzzer, tolerance_arcmin=1e-6, max_iterations=1)
    await _slew_via_backend(backend, 8.0, 30.0)
    assert backend.last_status.state.name == "FAILED"
    assert buzzer.failures == 1
    assert buzzer.successes == 0
