"""Live end-to-end test against the REAL mount, with a mock plate solver.

    *** SAFETY: THIS TEST MOVES A REAL TELESCOPE. ***

    Before running it, physically look at the mount and confirm it is safe
    to slew: nothing is in the way, no cables/dew shield/counterweight can
    snag, the tube can swing freely through the pole and back, and no one
    is standing in its path. The test unparks, slews to three stars (alpha
    UMa, alpha Cas, Polaris), corrects around Polaris, then parks. Nothing
    here asks for confirmation once it starts -- check first, and stay
    within reach of the power switch.

Disabled by default: it needs the real indiserver and it takes minutes of
real slewing. Enable it explicitly with

    CEDAR_GOTO_LIVE_INDI=1 pytest tests/test_live_indi_correction.py -s

Optional overrides: CEDAR_GOTO_INDI_HOST (default cedar.home.colyn.be),
CEDAR_GOTO_INDI_PORT (7624), CEDAR_GOTO_INDI_DEVICE ("Skywatcher Alt-Az").
Requires the "indi" extra (pyindi-client) installed.

What it exercises -- the things confirmed (and left open) live on the night
of 2026-07-25/26, see commit b839170:

  * that the closed loop's per-iteration PRESYNC really is a sync-then-GOTO
    -then-delete cycle against the real driver, in that order;
  * that IndiMountClient.delete_sync_point() actually works against real
    hardware, which was the explicit open caveat of that commit ("verify it
    live ... before relying on it in the field"). If DELETE silently does
    nothing, or deletes by a 1-based index, the sync-point count at the end
    is not 2 and this test fails -- which is the whole point;
  * that a correction triggered from the web UI's "correct now" path
    converges and leaves the mount pointing at the requested target.

The solve source is a mock (ScriptedPlateSolver): it reports the mount's
own position back as the plate-solved truth, plus a scripted offset. So no
cedar-server, no stars, no clear sky needed -- this runs in daylight. Only
the mount side is real.

Runtime is dominated by the correction slews: ClosedLoopSlew calls
IndiMountClient.prepare_for_correction(), which drops TELESCOPE_SLEW_RATE
to its slowest preset for the duration, so a 10' correction is a slow
crawl. Budget ~5-10 minutes.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import AsyncIterator

import pytest

from cedar_goto.config import PositionSourceConfig
from cedar_goto.core._precession import precess, precess_to_j2000
from cedar_goto.core.coords import J2000, CelestialCoord, angular_separation_deg
from cedar_goto.core.epoch_normalizing_solve_source import EpochNormalizingSolveSource
from cedar_goto.core.loop import LoopConfigCore
from cedar_goto.core.ports import MountControl, SolveSource
from cedar_goto.core.solve import SolveAcceptance, SolveResult
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION
from cedar_goto.web.closed_loop_backend import ClosedLoopTelescopeBackend

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CEDAR_GOTO_LIVE_INDI") != "1",
        reason="live-hardware test: set CEDAR_GOTO_LIVE_INDI=1 (and read the safety note first)",
    ),
]

_HOST = os.environ.get("CEDAR_GOTO_INDI_HOST", "cedar.home.colyn.be")
_PORT = int(os.environ.get("CEDAR_GOTO_INDI_PORT", "7624"))
_DEVICE = os.environ.get("CEDAR_GOTO_INDI_DEVICE", "Skywatcher Alt-Az")

# J2000 catalog positions.
ALPHA_UMA = CelestialCoord(ra_deg=165.9320, dec_deg=61.7510)   # Dubhe
ALPHA_CAS = CelestialCoord(ra_deg=10.1268, dec_deg=56.5373)    # Schedar
POLARIS = CelestialCoord(ra_deg=37.9546, dec_deg=89.2641)      # alpha UMi

GOTO_ERROR_ARCMIN = 10.0
"""How far off the first plate solve after the GoTo claims the mount is --
applied in Dec, not RA: at Polaris' declination an RA offset of 10' is only
~8" of real angle, which would be inside tolerance and correct nothing."""

_TOLERANCE_ARCMIN = 2.0
"""Deliberately looser than the 1' production default: the loop's
"converged" test compares the *solve* to the target, and here the solve is
the mount's own reported position, so this is really asking how exactly
this driver reports the coordinate it was just GoTo'd to. 2' absorbs that
residual without coming anywhere near the 10' error under test."""

_FINAL_POINTING_TOLERANCE_ARCMIN = 5.0
_SYNC_POINT_MATCH_ARCMIN = 2.0
"""How close a stored alignment point must be to a setup star to count as
that star. Tight on purpose -- a point reads back as exactly what was sent
(confirmed live, identical to five decimals) and the two setup stars are
~50 degrees apart, so anything near this threshold means the wrong point
survived, not a rounding difference."""
_SETUP_SLEW_TIMEOUT_S = 240.0
_LOOP_TIMEOUT_S = 900.0
_PARK_TIMEOUT_S = 240.0


class RecordingMount(MountControl):
    """Wraps IndiMountClient, forwarding everything and recording the calls
    the closed loop makes. Every optional capability ClosedLoopSlew
    getattr's off the mount (prepare/restore_for_correction,
    get_sync_point_count, delete_sync_point) is forwarded explicitly --
    a __getattr__ passthrough would work too, but then a renamed capability
    would silently stop being exercised here."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.events: list[tuple] = []
        self.sync_point_counts: list[int] = []

    async def slew_to(self, target: CelestialCoord) -> None:
        self.events.append(("slew_to", target))
        await self._inner.slew_to(target)

    async def is_slewing(self) -> bool:
        return await self._inner.is_slewing()

    async def sync_to(self, coord: CelestialCoord) -> None:
        self.events.append(("sync_to", coord))
        await self._inner.sync_to(coord)

    async def get_equatorial_system(self) -> float:
        return await self._inner.get_equatorial_system()

    async def get_position(self) -> CelestialCoord:
        return await self._inner.get_position()

    async def abort_slew(self) -> None:
        self.events.append(("abort_slew",))
        await self._inner.abort_slew()

    async def prepare_for_correction(self) -> None:
        self.events.append(("prepare_for_correction",))
        await self._inner.prepare_for_correction()

    async def restore_after_correction(self) -> None:
        self.events.append(("restore_after_correction",))
        await self._inner.restore_after_correction()

    async def get_sync_point_count(self) -> int:
        count = await self._inner.get_sync_point_count()
        self.sync_point_counts.append(count)
        return count

    async def delete_sync_point(self, index: int) -> None:
        self.events.append(("delete_sync_point", index))
        await self._inner.delete_sync_point(index)

    def call_names(self, *names: str) -> list[str]:
        return [e[0] for e in self.events if e[0] in names]


class ScriptedPlateSolver(SolveSource):
    """Mock cedar-server: reports the mount's own reported position (in
    J2000, like a real solve) as ground truth, plus a scripted Dec offset.

    The offsets are consumed one per solve handed to the closed loop, in
    the order the loop asks for them. Each iteration asks exactly twice --
    once for its PRESYNC sync point, once for the post-GoTo evaluation --
    so `offsets_arcmin=[0.0, 10.0]` means: presync sees the mount exactly
    where it says it is, then the first solve after the GoTo reports the
    mount 10' off target. Once the list runs out every solve is truthful
    again (offset 0).

    Consequence worth understanding before reading the assertions: because
    the injected error is transient, the loop needs two correction GoTos,
    not one. It commands Polaris - 10' to cancel the reported error, the
    now-truthful solve reports it 10' off the *other* way, and the third
    GoTo lands back on Polaris and converges. A permanent 10' offset would
    instead converge in one correction and leave the mount deliberately
    commanded 10' off Polaris -- correct behavior, but it couldn't satisfy
    "the mount ends up pointing at Polaris", which is what we want to
    assert here.
    """

    def __init__(self, mount: MountControl, offsets_arcmin: list[float], poll_interval_s: float = 0.2) -> None:
        self._mount = mount
        self._offsets = list(offsets_arcmin)
        self._poll_interval_s = poll_interval_s
        self.backend: ClosedLoopTelescopeBackend | None = None
        self.served: list[SolveResult] = []
        self.states_when_asked: list[str] = []
        self.slew_started_calls: list[CelestialCoord] = []
        self.slew_stopped_count = 0

    async def _make_solve(self, consume: bool) -> SolveResult:
        pos = precess_to_j2000(await self._mount.get_position())
        offset_arcmin = (self._offsets.pop(0) if self._offsets else 0.0) if consume else 0.0
        coord = CelestialCoord(
            ra_deg=pos.ra_deg,
            dec_deg=min(90.0, pos.dec_deg + offset_arcmin / 60.0),
            epoch=J2000,
        )
        # Comfortably inside the default SolveAcceptance gates, and
        # is_plate_solve=True (the default) -- PRESYNC skips syncing the
        # mount for anything that isn't a real plate solve.
        return SolveResult(
            sky_coord=coord,
            capture_time_unix=time.time(),
            num_matches=42,
            prob=1e-20,
            p90_error_arcsec=8.0,
            solution_from_imu=False,
        )

    async def stream_solves(self) -> AsyncIterator[SolveResult]:
        while True:
            # Recorded here rather than sampled by a polling task: the loop
            # is blocked inside this generator waiting for us, so its last
            # published state is exactly the step that asked -- PRESYNC or
            # AWAIT_SOLVE -- with no race to lose.
            if self.backend is not None:
                self.states_when_asked.append(self.backend.status_snapshot()["state"])
            solve = await self._make_solve(consume=True)
            self.served.append(solve)
            yield solve
            await asyncio.sleep(self._poll_interval_s)

    async def get_latest_solve(self) -> SolveResult | None:
        # Not on the closed loop's path (only stream_solves is), so it
        # deliberately doesn't consume the offset schedule.
        return await self._make_solve(consume=False)

    async def notify_slew_started(self, target: CelestialCoord) -> None:
        self.slew_started_calls.append(target)

    async def notify_slew_stopped(self) -> None:
        self.slew_stopped_count += 1


class Rig:
    def __init__(self, backend, mount: RecordingMount, inner, solver: ScriptedPlateSolver, indi_mount) -> None:
        self.backend = backend
        self.mount = mount
        self.inner = inner
        self.solver = solver
        self.indi_mount = indi_mount
        """The unwrapped IndiMountClient -- for reading the alignment
        database back directly, which the closed loop never does."""


async def _wait_until(predicate, timeout_s: float, what: str, interval_s: float = 0.5):
    deadline = time.monotonic() + timeout_s
    while True:
        result = await predicate()
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout_s:.0f}s waiting for {what}")
        await asyncio.sleep(interval_s)


async def _settle(mount: MountControl) -> None:
    # is_slewing() reads EQUATORIAL_EOD_COORD's BUSY state, which the
    # driver sets slightly *after* accepting the coordinate -- so give it a
    # moment before believing an immediate "not slewing".
    await asyncio.sleep(2.0)
    await _wait_until(
        lambda: _not_slewing(mount), _SETUP_SLEW_TIMEOUT_S, "the mount to finish slewing"
    )
    await asyncio.sleep(2.0)


async def _not_slewing(mount: MountControl) -> bool:
    return not await mount.is_slewing()


async def _separation_arcmin(mount: MountControl, target: CelestialCoord) -> float:
    """The mount reports JNow; the targets here are J2000. At Polaris'
    declination 26 years of precession is several arcminutes, so comparing
    without converting would fail this test for entirely the wrong reason."""
    return angular_separation_deg(precess_to_j2000(await mount.get_position()), target) * 60.0


@pytest.fixture
async def rig():
    from cedar_goto.adapters.indi.client import IndiConnection
    from cedar_goto.adapters.indi.mount_client import IndiMountClient
    from cedar_goto.adapters.indi.telescope_backend import IndiTelescopeBackend

    print(
        f"\n*** LIVE MOUNT TEST: about to unpark and slew {_DEVICE} at {_HOST}:{_PORT}. ***"
        "\n*** Confirm by eye that the mount is clear to move before this runs. ***\n"
    )

    conn = IndiConnection(_HOST, _PORT, _DEVICE)
    inner = IndiTelescopeBackend(conn)
    indi_mount = IndiMountClient(conn)
    mount = RecordingMount(indi_mount)
    solver = ScriptedPlateSolver(mount, offsets_arcmin=[0.0, GOTO_ERROR_ARCMIN])
    # Mirrors __main__._build_backend's wiring: ScriptedPlateSolver emits
    # J2000 (like any SolveSource), the closed loop works in the mount's own
    # epoch (JNow for this real INDI mount) -- EpochNormalizingSolveSource is
    # the seam between them (epoch-seam decision, 2026-07-26). Without this
    # wrap, core/loop.py's angular_separation_deg()/offset_correction() would
    # immediately raise EpochMismatchError comparing a JNow target against a
    # J2000 solve.
    cedar = EpochNormalizingSolveSource(solver, mount.get_equatorial_system)
    backend = ClosedLoopTelescopeBackend(
        inner,
        mount,
        cedar,
        LoopConfigCore(
            tolerance_arcmin=_TOLERANCE_ARCMIN,
            max_correction_arcmin=None,  # must not trip on the injected 10' error
            max_iterations=5,            # the scripted scenario needs 3; leave headroom
            settle_s=2.0,
            mount_slewing_timeout_s=300.0,  # correction slews run at the slowest preset
        ),
        SolveAcceptance(),
        PositionSourceConfig(source="mount"),
        correction_enabled=False,  # the GoTo below must be a bare proxy slew, not a loop
    )
    solver.backend = backend

    # --- setup, straight through INDI ---
    await conn.ensure_connected()
    # ensure_connected() only reaches indiserver. If the *driver* isn't
    # connected to the mount, the device is still published and everything
    # below would fail one property at a time with 10s "never appeared"
    # timeouts -- so say what's actually wrong, before anything moves.
    if not await conn.is_device_connected():
        pytest.fail(
            f"the INDI driver for {_DEVICE!r} is not connected to the mount hardware. "
            "Connect it (KStars/Cedar, or CONNECTION=CONNECT) and check DEVICE_PORT names "
            "the cable actually in use -- /dev/serial/by-id changes with the cable. "
            "Nothing was moved."
        )
    await inner.put(ALL_MEMBERS_BY_ACTION["connected"], {"Connected": True})
    await inner.put(ALL_MEMBERS_BY_ACTION["unpark"], {})
    await _wait_until(
        lambda: _is_unparked(inner), _PARK_TIMEOUT_S, "the mount to report unparked"
    )

    # Start from a known-empty alignment database so "2 sync points at the
    # end" means the two this test made, and nothing left over from an
    # earlier session (or an earlier run of this test).
    await indi_mount.clear_sync_points()
    await asyncio.sleep(1.0)
    assert await indi_mount.get_sync_point_count() == 0, "sync points did not clear"

    for star, name in ((ALPHA_UMA, "alpha UMa"), (ALPHA_CAS, "alpha Cas")):
        print(f"setup: slewing to {name} and syncing")
        # star is a J2000 catalog position; IndiMountClient no longer
        # converts epochs itself (epoch-seam decision, 2026-07-26) -- this
        # test drives it directly, bypassing the closed loop, so it must
        # convert here the same way EpochNormalizingSolveSource would.
        star_jnow = precess(star, await indi_mount.get_equatorial_system())
        await indi_mount.slew_to(star_jnow)
        await _settle(indi_mount)
        # Syncing to the catalog position the mount was just sent to is a
        # near-zero correction on purpose: this is building an alignment
        # database for the test to count, not re-aligning the mount, and a
        # real offset here would move the pointing model out from under the
        # correction we're actually measuring.
        await indi_mount.sync_to(star_jnow)
        await asyncio.sleep(1.0)

    baseline = await indi_mount.get_sync_point_count()
    assert baseline == 2, f"setup should leave exactly 2 sync points, got {baseline}"

    # The loop's own calls are what the assertions read -- drop the setup's.
    mount.events.clear()
    mount.sync_point_counts.clear()

    try:
        yield Rig(backend, mount, inner, solver, indi_mount)
    finally:
        # Teardown runs even when the test fails mid-slew: stop the loop
        # first (abort() also cancels a task blocked in AWAIT_SOLVE), then
        # leave the mount parked and its alignment database empty.
        try:
            await backend.abort()
            await indi_mount.clear_sync_points()
            await asyncio.sleep(1.0)
            print("teardown: parking")
            await inner.put(ALL_MEMBERS_BY_ACTION["park"], {})
            await _wait_until(
                lambda: _is_parked(inner), _PARK_TIMEOUT_S, "the mount to report parked", interval_s=2.0
            )
        finally:
            await inner.put(ALL_MEMBERS_BY_ACTION["connected"], {"Connected": False})


async def _is_parked(inner) -> bool:
    return await inner.get(ALL_MEMBERS_BY_ACTION["atpark"])


async def _is_unparked(inner) -> bool:
    return not await inner.get(ALL_MEMBERS_BY_ACTION["atpark"])


async def test_correct_now_converges_on_polaris_and_cleans_up_its_sync_points(rig: Rig):
    backend, mount, solver, indi_mount = rig.backend, rig.mount, rig.solver, rig.indi_mount

    # GoTo Polaris through the real Alpaca surface. Auto-correction is off,
    # so this is a bare proxy slew -- exactly the situation "correct now"
    # exists for: the slew is done, and only then does the user ask for a
    # cedar-driven correction.
    #
    # RightAscension/Declination must be sent in this device's advertised
    # EquatorialSystem (JNow), same as any real Alpaca/INDI client -- both
    # the bare-proxy slew path and (since the epoch-seam decision,
    # 2026-07-26) the closed-loop path now honor that consistently, so the
    # loop's first presync only has the injected 10' error to correct, not
    # ~9' of genuine mis-tagged-epoch drift on top of it.
    polaris_jnow = precess(POLARIS, await indi_mount.get_equatorial_system())
    await backend.put(
        ALL_MEMBERS_BY_ACTION["slewtocoordinatesasync"],
        {"RightAscension": polaris_jnow.ra_deg / 15.0, "Declination": polaris_jnow.dec_deg},
    )
    await _settle(mount)
    assert mount.events == [], "a bare proxy slew must not drive the mount client at all"

    target = await backend.correct_now()
    assert target is not None, "correct_now() found no commanded target to correct to"

    seen_states: list[str] = []

    async def _loop_finished() -> bool:
        state = backend.status_snapshot()["state"]
        if not seen_states or seen_states[-1] != state:
            seen_states.append(state)
        return state in ("CONVERGED", "FAILED", "OUT_OF_RANGE")

    await _wait_until(_loop_finished, _LOOP_TIMEOUT_S, "the correction loop to finish", interval_s=0.1)

    snapshot = backend.status_snapshot()
    # Worth reading with -s on a live run: what the loop actually did, in
    # order, next to what the mock told it.
    print(f"\nloop states seen: {seen_states}")
    print(f"mount calls: {[e[0] for e in mount.events]}")
    print(f"sync point counts during run: {mount.sync_point_counts}")
    print(
        "solves served (arcmin from Polaris): "
        f"{[round(angular_separation_deg(s.sky_coord, POLARIS) * 60.0, 2) for s in solver.served]}"
    )
    assert snapshot["state"] == "CONVERGED", f"{snapshot}, states seen: {seen_states}"
    assert snapshot["error_arcmin"] <= _TOLERANCE_ARCMIN

    # --- intermediate states ---
    # Every solve the loop asked for, tagged with the step that asked. Each
    # iteration presyncs (one solve) then evaluates its GoTo (one more), so
    # this pins the per-iteration shape of the run, not just its outcome.
    assert solver.states_when_asked == ["PRESYNC", "AWAIT_SOLVE"] * (len(solver.states_when_asked) // 2)
    iterations = len(solver.states_when_asked) // 2
    assert iterations >= 2, f"no correction happened -- only {iterations} iteration(s): {seen_states}"

    # The presync cycle from commit b839170, in order, once per iteration:
    # sync the mount to a fresh solve of where it is, GoTo, then delete
    # only the point that sync just added.
    cycle = mount.call_names("sync_to", "slew_to", "delete_sync_point")
    assert cycle == ["sync_to", "slew_to", "delete_sync_point"] * iterations, cycle
    assert mount.call_names("prepare_for_correction", "restore_after_correction") == [
        "prepare_for_correction",
        "restore_after_correction",
    ], "the correction slew rate must be lowered once and always restored"

    # Each presync must have been deleted by index, never by clearing the
    # set -- the user's own alignment points aren't ours to discard.
    deleted = [e[1] for e in mount.events if e[0] == "delete_sync_point"]
    assert deleted == [2] * iterations, f"expected the freshly-appended point (index 2) each time: {deleted}"

    # The first solve after the GoTo claimed a 10' error; the loop had to
    # act on it, and the last solve it acted on must be inside tolerance.
    first_eval = solver.served[1]
    assert abs(angular_separation_deg(first_eval.sky_coord, POLARIS) * 60.0 - GOTO_ERROR_ARCMIN) < 1.0

    # --- the two headline assertions ---
    # This is the live check the delete_sync_point() caveat in b839170 asked
    # for: if DELETE is a no-op, or is 1-based, the presync points are still
    # there and this is 2 + iterations.
    counts_during_run = list(mount.sync_point_counts)
    final_count = await mount.get_sync_point_count()
    assert final_count == 2, (
        f"presync points were not cleaned up: {final_count} sync points remain after "
        f"{iterations} iteration(s); counts observed during the run: {counts_during_run}"
    )

    # ...and the right *two*, not merely two. The count alone can't tell a
    # correct run from one where the loop deleted a setup point and left its
    # own behind -- e.g. if this driver ever stopped appending at the end,
    # making `new_count - 1` the wrong index. Read the database back and
    # match by position: the points are stored in the epoch they were sent
    # in (JNow), so precess before comparing.
    remaining = [precess_to_j2000(await rig.indi_mount.read_sync_point(i)) for i in range(final_count)]
    print(f"surviving sync points: {[(round(p.ra_deg, 3), round(p.dec_deg, 3)) for p in remaining]}")
    matched: dict[str, int] = {}
    for star, name in ((ALPHA_UMA, "alpha UMa"), (ALPHA_CAS, "alpha Cas")):
        separations = [angular_separation_deg(p, star) * 60.0 for p in remaining]
        best = min(range(len(remaining)), key=lambda i: separations[i])
        assert separations[best] <= _SYNC_POINT_MATCH_ARCMIN, (
            f"no surviving sync point matches {name}: nearest is {separations[best]:.1f}' away "
            f"-- the loop deleted one of the setup points instead of its own presync point"
        )
        matched[name] = best
    assert len(set(matched.values())) == 2, (
        f"both setup stars matched the same stored point ({matched}) -- the other survivor "
        "is not one of ours"
    )

    separation = await _separation_arcmin(mount, POLARIS)
    assert separation <= _FINAL_POINTING_TOLERANCE_ARCMIN, (
        f"mount ended {separation:.1f}' from Polaris after correcting"
    )
