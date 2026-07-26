"""Celestial coordinates and epoch/angular-separation math.

No framework imports here (see DESIGN.md §12) — this module, and the rest of
`core/`, must stay portable to a future non-Python rewrite.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

J2000 = 2000.0

EPOCH_MATCH_TOLERANCE_YR = 1e-4
"""~52 minutes of Julian year. Two honestly-tagged coordinates that are
"the same epoch" in practice (e.g. two JNow reads a few seconds apart) never
land on the exact same float -- this absorbs that clock-skew noise while
still catching a real epoch bug, which differs by whole years to decades
(the mis-tag this tolerance was introduced to catch: ~26 years, see
epoch-seam decision 2026-07-26). Shared by the EpochMismatchError guards
below and by _precession.precess()'s no-op short-circuit."""


class EpochMismatchError(ValueError):
    """Raised by angular_separation_deg()/offset_correction() when the
    coordinates they were given carry different epochs (beyond
    EPOCH_MATCH_TOLERANCE_YR). Comparing across epochs silently produces a
    wrong-but-plausible answer (a few arcminutes near the pole per few
    decades) instead of an error -- exactly the bug the epoch-seam decision
    (2026-07-26, at the SolveSource port) closed. These two functions are
    the last line of defense against it recurring: every caller in
    core/loop.py is expected to already be working in one consistent
    (mount-advertised) epoch."""


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
    """Great-circle separation in degrees between two coordinates in the
    same epoch. Raises EpochMismatchError if they differ by more than
    EPOCH_MATCH_TOLERANCE_YR — this function does not convert.
    """
    if abs(a.epoch - b.epoch) > EPOCH_MATCH_TOLERANCE_YR:
        raise EpochMismatchError(
            f"angular_separation_deg: epoch mismatch (a.epoch={a.epoch}, b.epoch={b.epoch})"
        )
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

    Raises EpochMismatchError if true_target/commanded/actual don't all
    agree on epoch (within EPOCH_MATCH_TOLERANCE_YR) — see
    angular_separation_deg().
    """
    if true_target.epoch != commanded.epoch:
        raise EpochMismatchError(
            f"offset_correction: true_target/commanded epoch mismatch "
            f"(true_target.epoch={true_target.epoch}, commanded.epoch={commanded.epoch})"
        )
    if abs(true_target.epoch - actual.epoch) > EPOCH_MATCH_TOLERANCE_YR:
        raise EpochMismatchError(
            f"offset_correction: true_target/actual epoch mismatch "
            f"(true_target.epoch={true_target.epoch}, actual.epoch={actual.epoch})"
        )
    dra = true_target.ra_deg - actual.ra_deg
    ddec = true_target.dec_deg - actual.dec_deg
    new_ra = _wrap_ra(commanded.ra_deg + dra)
    new_dec = max(-90.0, min(90.0, commanded.dec_deg + ddec))
    return CelestialCoord(ra_deg=new_ra, dec_deg=new_dec, epoch=commanded.epoch)
