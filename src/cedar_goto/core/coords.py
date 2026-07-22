"""Celestial coordinates and epoch/angular-separation math.

No framework imports here (see DESIGN.md §12) — this module, and the rest of
`core/`, must stay portable to a future non-Python rewrite.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

J2000 = 2000.0


@dataclass(frozen=True, slots=True)
class CelestialCoord:
    """RA/Dec in degrees, at a given Julian-year epoch."""

    ra_deg: float
    dec_deg: float
    epoch: float = J2000

    def __post_init__(self) -> None:
        if not (0.0 <= self.ra_deg < 360.0):
            raise ValueError(f"ra_deg out of range [0, 360): {self.ra_deg}")
        if not (-90.0 <= self.dec_deg <= 90.0):
            raise ValueError(f"dec_deg out of range [-90, 90]: {self.dec_deg}")

    def to_j2000(self) -> "CelestialCoord":
        """Precess to J2000. Uses astropy for correctness; see adapters for the boundary."""
        if self.epoch == J2000:
            return self
        from cedar_goto.core._precession import precess_to_j2000

        return precess_to_j2000(self)


def angular_separation_deg(a: CelestialCoord, b: CelestialCoord) -> float:
    """Great-circle separation in degrees between two J2000 coordinates.

    Both inputs must already be in the same epoch (normalize with to_j2000()
    first) — this function does not convert.
    """
    ra1, dec1 = math.radians(a.ra_deg), math.radians(a.dec_deg)
    ra2, dec2 = math.radians(b.ra_deg), math.radians(b.dec_deg)

    # Vincenty formula: numerically stable for both small and large separations.
    dra = ra2 - ra1
    numerator = math.sqrt(
        (math.cos(dec2) * math.sin(dra)) ** 2
        + (math.cos(dec1) * math.sin(dec2) - math.sin(dec1) * math.cos(dec2) * math.cos(dra)) ** 2
    )
    denominator = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(dra)
    return math.degrees(math.atan2(numerator, denominator))


def _wrap_ra(ra_deg: float) -> float:
    return ra_deg % 360.0


def offset_correction(true_target: CelestialCoord, commanded: CelestialCoord, actual: CelestialCoord) -> CelestialCoord:
    """Offset/adjust-target strategy (DESIGN.md §5).

    G_next = G + (T - A), i.e. nudge the commanded coordinate by however far
    off the *true* target the last solve landed. Accumulates across
    iterations so a roughly-constant local pointing offset is cancelled in
    2-3 passes. Dec is clamped to the valid range; RA wraps mod 360.
    """
    dra = true_target.ra_deg - actual.ra_deg
    ddec = true_target.dec_deg - actual.dec_deg
    new_ra = _wrap_ra(commanded.ra_deg + dra)
    new_dec = max(-90.0, min(90.0, commanded.dec_deg + ddec))
    return CelestialCoord(ra_deg=new_ra, dec_deg=new_dec, epoch=commanded.epoch)
