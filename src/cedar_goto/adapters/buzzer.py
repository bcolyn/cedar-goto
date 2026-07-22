"""GPIO buzzer (DESIGN.md §7, §10 Phase 4) -- beep on convergence, a
distinct pattern on failure.

Deliberately a soft dependency: gpiozero is an optional extra
(`pip install cedar-goto[buzzer]`), imported lazily here rather than at
module load time, and any failure to construct real hardware (missing
package, no GPIO backend, wrong pin) falls back to a silent no-op instead
of crashing the app. A buzzer is a nice-to-have; cedar-goto must run fine
on a dev machine with no GPIO at all.
"""
from __future__ import annotations

import logging
from typing import Protocol

from cedar_goto.config import BuzzerConfig

logger = logging.getLogger(__name__)


class Buzzer(Protocol):
    def success(self) -> None: ...

    def failure(self) -> None: ...


class NullBuzzer:
    def success(self) -> None:
        pass

    def failure(self) -> None:
        pass


class GpioBuzzer:
    """Wraps gpiozero.Buzzer. `.beep()` with background=True (the default)
    returns immediately -- gpiozero times the pattern on its own thread."""

    def __init__(self, gpio_pin: int) -> None:
        from gpiozero import Buzzer as GpiozeroBuzzer

        self._buzzer = GpiozeroBuzzer(gpio_pin)

    def success(self) -> None:
        self._buzzer.beep(on_time=0.15, off_time=0.1, n=1)

    def failure(self) -> None:
        self._buzzer.beep(on_time=0.1, off_time=0.1, n=3)


def build_buzzer(config: BuzzerConfig) -> Buzzer:
    if not config.enabled:
        return NullBuzzer()
    try:
        return GpioBuzzer(config.gpio_pin)
    except Exception:
        logger.warning(
            "Buzzer enabled in config but GPIO hardware unavailable (no gpiozero, "
            "no GPIO backend, or bad pin) -- continuing without it.",
            exc_info=True,
        )
        return NullBuzzer()
