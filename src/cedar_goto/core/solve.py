"""Plate-solve result type and acceptance gating (DESIGN.md §5, §6)."""
from __future__ import annotations

from dataclasses import dataclass

from cedar_goto.core.coords import CelestialCoord


@dataclass(frozen=True, slots=True)
class SolveResult:
    """A single plate-solve frame result, trimmed to what the control loop needs."""

    sky_coord: CelestialCoord
    capture_time_unix: float
    num_matches: int
    prob: float
    p90_error_arcsec: float
    solution_from_imu: bool
    is_plate_solve: bool = True
    """False only for adapters.mock.echo_cedar.MountEchoCedar's loopback
    (mount's own reported position echoed back as a fake "solve", for
    exercising the plumbing against real hardware without cedar-server).
    Never independent ground truth -- mount.sync_to() must never be called
    with one of these, or the mount's persistent alignment/sync-point
    database gets calibrated against its own already-possibly-wrong belief
    instead of real sky data (found 2026-07-22)."""


@dataclass(frozen=True, slots=True)
class SolveAcceptance:
    min_matches: int = 10
    min_prob: float = 0.9
    max_p90_error_arcsec: float = 30.0
    reject_imu: bool = True

    def accepts(self, solve: SolveResult) -> bool:
        if self.reject_imu and solve.solution_from_imu:
            return False
        if solve.num_matches < self.min_matches:
            return False
        if solve.prob < self.min_prob:
            return False
        if solve.p90_error_arcsec > self.max_p90_error_arcsec:
            return False
        return True
