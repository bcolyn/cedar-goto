# cedar-goto

Closed-loop ASCOM Alpaca pointing bridge between [cedar-server](https://github.com/smroid/cedar-server)
(plate-solving electronic finder) and a GoTo mount. See [DESIGN.md](DESIGN.md)
for the full design and [GOALS.md](GOALS.md) for the original brief.

Status: **Phase 5 + direct-INDI mount backend** — the full plan (DESIGN.md
§10) is implemented and tested against the mock harness, real cedar-server,
real SkySafari 8, and real Alpaca hardware (ASCOM Remote Server simulator).
The originally-planned mount link (a real Skywatcher Alt-Az mount via an
INDI→Alpaca bridge) turned out to have a confirmed, unfixable-on-our-side
bug in that bridge; it's been replaced with a backend that talks to
`indiserver` directly (`[mount].backend = "indi"`, see
[indi-refactor.md](indi-refactor.md)) and is now verified end-to-end against
real hardware: slew, sync, abort, park/unpark, epoch precession. What's
genuinely outstanding is on-sky tuning and a real Pi/systemd dry run.

- `SlewToCoordinates(Async)` runs the closed-loop correction against cedar
  (`offset` or `sync_reslew`, `[loop].strategy`); `Slewing`/`AbortSlew`
  reflect it; give-up paths (solve rejection, non-convergence, mount/cedar
  errors) land cleanly in `FAILED` without crashing or getting stuck.
- Reported position can prefer cedar's plate-solved coordinate over the
  mount's own (`[position] source`), with a mount fallback that now also
  covers a cedar-server outage, not just "no solve yet".
- A web UI at `/`: live status via SSE, mount info (location, mount UTC
  date/time, sync-point count, park state), and Sync now / Abort / Park /
  Unpark / Clear sync points actions. Sync now (and the closed loop's own
  `final_sync`/`sync_reslew`) refuse to sync the mount using anything that
  isn't a real plate solve, so a loopback/echo solve source can never
  corrupt the mount's persistent alignment database.
- An optional GPIO buzzer (beeps on convergence/failure; a soft dependency
  -- `pip install cedar-goto[buzzer]`, and it silently no-ops if GPIO
  hardware isn't available even when enabled).
- systemd service + install script (`packaging/`) for Pi deployment.

Cartes du Ciel connects but its Slew/Disconnect controls don't work against
cedar-goto -- confirmed as a limitation in CdC's own Alpaca client
(reproduces identically against the official ASCOM Remote Server +
simulator), not a cedar-goto bug.

## Setup

```sh
uv venv
uv pip install -e ".[dev]"
```

## Run it

```sh
.venv/Scripts/python -m cedar_goto --config config.toml
```

By default (`[mount] backend = "mock"` in `config.toml`) this drives the
simulated-sky harness, so you can point SkySafari/Cartes du Ciel at
`<host>:11111` and try discovery/connect/goto without any hardware.

For a real mount, two backends are available:
- `backend = "indi"` (**recommended** for an INDI-driven mount) — talks
  directly to `indiserver` over the real INDI protocol via `pyindi-client`
  (`pip install cedar-goto[indi]`). Bypasses `indi_alpaca_server`, which has
  a confirmed bug that silently breaks Alpaca-driven slews. See
  [indi-refactor.md](indi-refactor.md) and `config-indi.toml`.
- `backend = "alpyca"` — talks to any real ASCOM Alpaca mount server over
  HTTP (`[mount] address`). See `config-ascom-sim.toml` for a config
  pointed at the official ASCOM Remote Server + simulator.

## Run the tests

```sh
.venv/Scripts/python -m pytest tests/ -v
```

- `tests/test_closed_loop.py` — the closed-loop state machine (DESIGN.md §5)
  against the mock harness (`adapters/mock/`), which simulates a Skywatcher
  Wave 150i's harmonic-drive pointing error and cedar's plate-solve stream.
- `tests/test_alpaca_server.py` — the external Alpaca proxy (management API,
  discovery gating, plain-proxy slew, capability flags, error envelopes)
  against the same mock, via an in-process ASGI client (no real HTTP/sockets).
- `tests/test_closed_loop_alpaca.py` — the closed loop driven through the
  HTTP layer (`SlewToCoordinatesAsync` → `Slewing` → converged position,
  both strategies), abort, a new slew superseding one in progress, cedar-
  preferred position reporting, and Phase 3's give-up paths (persistent
  solve rejection, non-convergence, unexpected mount/cedar errors) --
  including that a fresh slew works normally after a prior one failed.
- `tests/test_web_ui.py` — the web UI's status/SSE snapshot (including
  mount info) and its sync-now/abort/park/unpark/clear-sync-points actions.
- `tests/test_buzzer.py` — the buzzer factory's graceful fallback with no
  GPIO hardware, and that the closed loop actually calls success()/
  failure() at the right times.
- `tests/test_indi_backend.py` — the direct-INDI backend's property-mapping
  logic against a fake `IndiConnection` (no real sockets/`pyindi-client`
  needed, so this runs regardless of whether the `indi` extra is
  installed). See [indi-refactor.md](indi-refactor.md) for how this was
  additionally verified against real hardware.

## Layout

```
src/cedar_goto/
  core/            # framework-free control logic — the part worth porting
                    # carefully if this is ever rewritten in Go (DESIGN.md §12)
    coords.py       # CelestialCoord, angular separation, offset-correction math
    solve.py        # SolveResult, solve-acceptance gating
    ports.py        # MountControl / SolveSource protocols — the seam
    loop.py         # ClosedLoopSlew state machine (DESIGN.md §5)
    _precession.py  # astropy boundary for epoch conversion
  web/             # the external Alpaca face (DESIGN.md §3)
    alpaca_spec.py  # declarative ITelescopeV3 member table (drives routing)
    alpaca_errors.py# ASCOM error numbers + response envelope
    backend.py      # TelescopeBackend protocol — the full-surface proxy seam
    closed_loop_backend.py # Phase 2: intercepts slew/Slewing/AbortSlew,
                     # runs core.loop.ClosedLoopSlew, proxies everything
                     # else through to a plain TelescopeBackend
    telescope_api.py# GET/PUT /api/v1/telescope/{n}/{action}, table-driven
    management.py   # /management/* endpoints
    discovery.py    # UDP discovery responder (port 32227)
    ui.py           # web UI (DESIGN.md §8): status/SSE, mount info,
                     # sync-now/abort/park/unpark/clear-sync-points
    app.py          # FastAPI app assembly
  adapters/
    mock/           # World + MockMount + MockCedar + MockTelescopeBackend — DESIGN.md §9a
                     # + MountEchoCedar (real mount, mocked cedar -- see below)
    alpaca/         # real mount client (alpyca): MountControl (closed-loop) +
                     # TelescopeBackend (external proxy) adapters — verified
                     # against real Alpaca hardware (see below)
    indi/           # direct-INDI mount client via pyindi-client -- bypasses
                     # indi_alpaca_server's confirmed stale-property-snapshot
                     # bug. IndiConnection (shared low-level wrapper),
                     # IndiMountClient, IndiTelescopeBackend. See
                     # indi-refactor.md; verified against real hardware.
    cedar_grpc/      # real cedar-server client (grpc) + generated/ stubs —
                     # verified against a live Cedar-Box (see below)
    buzzer.py       # optional GPIO buzzer (DESIGN.md §7) -- soft dependency,
                     # no-ops cleanly without real GPIO hardware
  config.py         # pydantic config, mirrors config.toml / DESIGN.md §6
proto/              # cedar-server's .proto sources (pulled from smroid/cedar-server)
scripts/
  generate_grpc_stubs.py  # regenerate adapters/cedar_grpc/generated/
packaging/
  cedar-goto.service # systemd unit (DESIGN.md §9)
  install.sh         # install/upgrade script for a Pi/Linux host
```

`web.backend.TelescopeBackend` is deliberately a separate, larger interface
from `core.ports.MountControl`: the latter is the minimal seam the
closed-loop state machine needs, the former is the full ASCOM
ITelescopeV3 surface the external proxy forwards (DESIGN.md §3/§12).

## Web UI & buzzer

`http://<host>:11111/` serves a status page (live state/iteration/
error/last-solve via SSE, plus mount info -- location, mount UTC date/time,
sync-point count, park state) -- DESIGN.md §8. No build step, no external
assets/CDN, so it works standalone on a Pi with no internet.

Actions: **Sync now** (syncs the mount to cedar's current solve, bypassing
the closed loop), **Abort**, **Park**/**Unpark**, and **Clear sync points**.
Park aborts any in-flight closed-loop slew first. Sync now (and any
mount.sync_to() call from the closed loop itself) refuses to run against a
solve that isn't a real plate solve (e.g. the `MountEchoCedar` loopback used
to exercise a real mount without a working cedar-server) -- otherwise it'd
calibrate the mount's persistent alignment/sync-point database against its
own already-possibly-wrong belief instead of real sky data. Sync-point count
and Clear are INDI-specific (no ASCOM Alpaca equivalent exists); they show
as "not supported" against the `alpyca`/`mock` backends. Location and mount
UTC date/time work identically against any backend.

The GPIO buzzer (`[buzzer]` in config) is a soft dependency by design: it's
an optional extra (`pip install cedar-goto[buzzer]`), gpiozero is imported
lazily, and if it's enabled but no GPIO hardware is actually available
(dev machine, missing package, bad pin), it logs a warning and silently
no-ops rather than crashing the app.

## Deployment (Raspberry Pi / systemd)

```sh
sudo packaging/install.sh            # installs to /opt/cedar-goto by default
# edit /opt/cedar-goto/config.toml (mount/cedar addresses, [mount].backend = "indi"/"alpyca", [cedar].backend = "grpc")
sudo systemctl start cedar-goto
journalctl -u cedar-goto -f
```

Re-running `install.sh` upgrades the code + venv in place without touching
an existing `config.toml`. See `packaging/cedar-goto.service` for the unit
file (adds the service user to the `gpio` group for the buzzer; harmless
if unused).

## Regenerating gRPC stubs

If cedar-server's protos change:

```sh
.venv/Scripts/python scripts/generate_grpc_stubs.py
```

## Not yet done

- Reported position (`[position] source = "cedar"`) reports cedar's
  coordinate directly in J2000 without converting to the mount's advertised
  `EquatorialSystem` (e.g. JNow) — fine while cedar-goto's own device always
  advertises J2000, a gap to close if/when that changes.
- `adapters/cedar_grpc` has been verified against a live Cedar-Box over the
  network: `GetFrame` connects and returns real `FrameResult` messages.
  Important finding: cedar-server serves gRPC on the **same port as its web
  UI** (tonic's `GrpcWebLayer`, default port 80) — there's no separate gRPC
  port, unlike the original `50051` placeholder (now fixed in
  `config.toml`). Testing so far is daytime-only, so no accepted
  `plate_solution` has been observed yet — the solve-acceptance path is
  still unverified against a real solve.
- `adapters/alpaca` has been verified against a **real Alpaca server** (the
  official ASCOM Remote Server + simulator device, multiple devices, both
  equatorial and Alt-Az `AlignmentMode`, real `EquatorialSystem =
  equTopocentric`/JNow) — full closed loop converges correctly with proper
  JNow↔J2000 conversion. See `config-ascom-sim.toml` for that test config.
- The real Skywatcher Alt-Az mount was originally planned to go through an
  INDI→Alpaca bridge (`indi_alpaca_server`) in front of it. That bridge
  turned out to have a confirmed bug (it snapshots the mount's INDI
  property list once at its own connect time and never re-syncs, silently
  breaking Alpaca-driven slews) — replaced with `adapters/indi`, a backend
  that talks to `indiserver` directly. Verified end-to-end against the real
  mount: slew, sync, abort, park/unpark, epoch precession (JNow↔J2000). See
  [indi-refactor.md](indi-refactor.md) for the full story and
  `config-indi.toml` for that test config. `[cedar].backend = "mock"` with
  a real mount backend uses `MountEchoCedar` (echoes the real mount's own
  position as ground truth) so the mount plumbing can be exercised without
  a working cedar-server -- but see the sync-safety note above, its solves
  are never allowed to actually sync the mount.
- SkySafari 8 verified live (see DESIGN.md §11); Cartes du Ciel confirmed
  as a client-side limitation, not a cedar-goto issue.
- `packaging/install.sh` is written to spec but not yet run against a real
  Pi -- worth a dry run at first hardware bring-up.
- On-sky tuning of tolerances/thresholds once the real mount + a working
  (dark-sky) cedar-server are both live (Phase 5, DESIGN.md §10).
