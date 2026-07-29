"""Celestial coordinates and epoch math.

No framework imports here (see DESIGN.md §12) — this module, and the rest of
`core/`, must stay portable to a future non-Python rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass

J2000 = 2000.0

EPOCH_MATCH_TOLERANCE_YR = 1e-4
"""~52 minutes of Julian year. Two honestly-tagged coordinates that are
"the same epoch" in practice (e.g. two JNow reads a few seconds apart) never
land on the exact same float -- this absorbs that clock-skew noise while
still catching a real epoch bug, which differs by whole years to decades
(the mis-tag this tolerance was introduced to catch: ~26 years, see
epoch-seam decision 2026-07-26). Used by each adapter's own _check_epoch
tripwire and by _precession.precess()'s no-op short-circuit."""


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
