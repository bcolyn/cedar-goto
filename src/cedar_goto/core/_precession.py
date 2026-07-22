"""Astropy boundary for epoch precession — isolated so core.coords stays import-light.

DESIGN.md §12: keep framework/library dependencies at the edges of core/.
"""
from __future__ import annotations

from astropy.coordinates import FK5
from astropy.time import Time

from cedar_goto.core.coords import J2000, CelestialCoord


def precess(coord: CelestialCoord, target_epoch: float) -> CelestialCoord:
    """Precess `coord` from its own epoch to `target_epoch` (both Julian years)."""
    if abs(coord.epoch - target_epoch) < 1e-9:
        return coord

    from astropy.coordinates import SkyCoord

    src_frame = FK5(equinox=Time(coord.epoch, format="jyear"))
    dst_frame = FK5(equinox=Time(target_epoch, format="jyear"))
    sc = SkyCoord(ra=coord.ra_deg, dec=coord.dec_deg, unit="deg", frame=src_frame)
    precessed = sc.transform_to(dst_frame)
    return CelestialCoord(ra_deg=float(precessed.ra.deg), dec_deg=float(precessed.dec.deg), epoch=target_epoch)


def precess_to_j2000(coord: CelestialCoord) -> CelestialCoord:
    return precess(coord, J2000)
