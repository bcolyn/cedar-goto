"""Shared simulated-sky state for the mock mount + mock cedar (DESIGN.md §9a)."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from cedar_goto.core.coords import CelestialCoord


@dataclass
class HarmonicErrorModel:
    """Strain-wave-drive pointing error signature (Wave 150i, DESIGN.md §3a).

    error(axis_angle) = constant_offset + amplitude * sin(cycles * axis_angle)
    applied independently (with different phases) to RA and Dec, plus small
    Gaussian settle noise.
    """

    ra_offset_arcmin: float = 3.0
    dec_offset_arcmin: float = -2.0
    ra_cyclic_amplitude_arcmin: float = 1.5
    dec_cyclic_amplitude_arcmin: float = 1.0
    cycles_per_revolution: float = 3.0
    noise_stddev_arcmin: float = 0.2
    rng: random.Random = field(default_factory=random.Random)

    def apply(self, commanded: CelestialCoord) -> CelestialCoord:
        axis_angle_rad = math.radians(commanded.ra_deg)
        ra_error = (
            self.ra_offset_arcmin
            + self.ra_cyclic_amplitude_arcmin * math.sin(self.cycles_per_revolution * axis_angle_rad)
            + self.rng.gauss(0.0, self.noise_stddev_arcmin)
        ) / 60.0
        dec_error = (
            self.dec_offset_arcmin
            + self.dec_cyclic_amplitude_arcmin * math.cos(self.cycles_per_revolution * axis_angle_rad)
            + self.rng.gauss(0.0, self.noise_stddev_arcmin)
        ) / 60.0
        new_ra = (commanded.ra_deg + ra_error) % 360.0
        new_dec = max(-90.0, min(90.0, commanded.dec_deg + dec_error))
        return CelestialCoord(ra_deg=new_ra, dec_deg=new_dec, epoch=commanded.epoch)


def _signed_ra_delta_deg(a_deg: float, b_deg: float) -> float:
    """Shortest signed a-b, wrapped into [-180, 180) — for RA arithmetic near 0/360."""
    return ((a_deg - b_deg + 180.0) % 360.0) - 180.0


@dataclass
class World:
    """The ground truth the mock mount moves in and the mock cedar solves against."""

    error_model: HarmonicErrorModel = field(default_factory=HarmonicErrorModel)
    true_pointing: CelestialCoord = field(
        default_factory=lambda: CelestialCoord(ra_deg=0.0, dec_deg=0.0)
    )
    settle_s: float = 0.05
    """Simulated slew settle time — kept short so mock-driven tests run fast."""

    slewing_until: float = 0.0
    solve_failure_countdown: int = 0
    """When > 0, the next N solve requests report a rejected/low-quality solve."""

    alignment_offset_ra_deg: float = 0.0
    alignment_offset_dec_deg: float = 0.0
    """Cumulative correction learned from Sync calls — models a mount's internal
    alignment model, which a real Sync recalibrates (DESIGN.md §5 sync_reslew
    strategy). Without this, sync_reslew could never converge in simulation:
    re-commanding the same target would reproduce the exact same deterministic
    error every time."""

    _last_commanded: CelestialCoord | None = None

    def command_slew(self, target: CelestialCoord) -> None:
        self._last_commanded = target
        raw = self.error_model.apply(target)
        new_ra = (raw.ra_deg - self.alignment_offset_ra_deg) % 360.0
        new_dec = max(-90.0, min(90.0, raw.dec_deg - self.alignment_offset_dec_deg))
        self.true_pointing = CelestialCoord(ra_deg=new_ra, dec_deg=new_dec, epoch=raw.epoch)
        self.slewing_until = time.monotonic() + self.settle_s

    def sync(self, coord: CelestialCoord) -> None:
        """Models a real Sync: the mount is told "you are at `coord`", and
        recalibrates its alignment model accordingly. We learn the offset
        between the last commanded target and where we actually ended up
        (post-alignment), same as a single-point mount alignment would."""
        if self._last_commanded is not None:
            self.alignment_offset_ra_deg += _signed_ra_delta_deg(
                self.true_pointing.ra_deg, self._last_commanded.ra_deg
            )
            self.alignment_offset_dec_deg += self.true_pointing.dec_deg - self._last_commanded.dec_deg
        self.true_pointing = coord

    def is_slewing(self) -> bool:
        return time.monotonic() < self.slewing_until

    def abort(self) -> None:
        self.slewing_until = 0.0

    def inject_solve_failures(self, count: int) -> None:
        self.solve_failure_countdown = count
