# cedar-goto

cedar-goto connects [cedar-server](https://github.com/smroid/cedar-server)
(a plate-solving electronic finder) to a GoTo telescope mount. It shows up
to your planetarium app as an ordinary ASCOM Alpaca telescope, but under the
hood, every slew is corrected in a closed loop using cedar's plate solves --
so "Go To" actually lands on target instead of wherever the mount's own
alignment model thinks it should.

It's been tested against real Alpaca mount hardware, a real INDI-driven
mount, real cedar-server, and real SkySafari 8. There's also a
simulated-sky mock mode, so you can try the whole thing out with no
hardware at all.

Highlights:
- Closed-loop slewing that corrects for mount pointing error using cedar's
  plate solves, with clean recovery (not a crash or a stuck state) if a
  solve gets rejected or the mount errors out.
- Reported position can come from cedar's plate solve instead of the
  mount's own idea of where it's pointed, falling back to the mount
  automatically if cedar isn't available.
- A small web UI for live status plus manual sync/abort/park controls.
- An optional GPIO buzzer for audible feedback on a headless Pi.
- systemd packaging for easy Raspberry Pi deployment.

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
- `backend = "indi"` (**recommended** for an INDI-driven mount) -- talks
  directly to `indiserver` over the real INDI protocol via `pyindi-client`.
  For a manual (non-`install.sh`) setup, install it with
  `pip install --no-deps pyindi-client` rather than a `[indi]` extra -- see
  the Deployment section below for why. See `config-indi.toml`.
- `backend = "alpyca"` -- talks to any real ASCOM Alpaca mount server over
  HTTP (`[mount] address`). See `config-ascom-sim.toml` for a config
  pointed at the official ASCOM Remote Server + simulator.

## Run the tests

```sh
.venv/Scripts/python -m pytest tests/ -v
```

- `tests/test_closed_loop.py` -- the closed-loop state machine against the
  mock harness (`adapters/mock/`), which simulates a Skywatcher Wave 150i's
  harmonic-drive pointing error and cedar's plate-solve stream.
- `tests/test_alpaca_server.py` -- the external Alpaca proxy (management
  API, discovery gating, plain-proxy slew, capability flags, error
  envelopes) against the same mock, via an in-process ASGI client (no real
  HTTP/sockets).
- `tests/test_closed_loop_alpaca.py` -- the closed loop driven through the
  HTTP layer (`SlewToCoordinatesAsync` -> `Slewing` -> converged position),
  the auto-correction toggle (bare-proxy slew when disabled, doesn't abort
  an in-progress corrected slew), abort, a new slew superseding one in
  progress, cedar-preferred position reporting, and the give-up paths
  (persistent solve rejection, non-convergence, unexpected mount/cedar
  errors) -- including that a fresh slew works normally after a prior one
  failed.
- `tests/test_web_ui.py` -- the web UI's status/SSE snapshot (including
  mount info) and its sync-now/sync-to-target/abort/park/unpark/
  clear-sync-points/correction-toggle actions.
- `tests/test_buzzer.py` -- the buzzer factory's graceful fallback with no
  GPIO hardware, and that the closed loop actually calls success()/
  failure() at the right times.
- `tests/test_indi_backend.py` -- the direct-INDI backend's property-mapping
  logic against a fake `IndiConnection` (no real sockets/`pyindi-client`
  needed, so this runs regardless of whether the `indi` extra is
  installed).

## Layout

```
src/cedar_goto/
  core/            # framework-free control logic
    coords.py       # CelestialCoord, angular separation, offset-correction math
    solve.py        # SolveResult, solve-acceptance gating
    ports.py        # MountControl / SolveSource protocols -- the seam
    loop.py         # ClosedLoopSlew state machine
    _precession.py  # astropy boundary for epoch conversion
  web/             # the external Alpaca face
    alpaca_spec.py  # declarative ITelescopeV3 member table (drives routing)
    alpaca_errors.py# ASCOM error numbers + response envelope
    backend.py      # TelescopeBackend protocol -- the full-surface proxy seam
    closed_loop_backend.py # intercepts slew/Slewing/AbortSlew, runs
                     # core.loop.ClosedLoopSlew, proxies everything else
                     # through to a plain TelescopeBackend
    telescope_api.py# GET/PUT /api/v1/telescope/{n}/{action}, table-driven
    management.py   # /management/* endpoints
    discovery.py    # UDP discovery responder (port 32227)
    http_utils.py   # shared Alpaca HTTP request/response plumbing
    ui.py           # web UI: status/SSE, mount info, auto-correction toggle,
                     # sync-now/sync-to-target/abort/park/unpark/clear-sync-points
    app.py          # FastAPI app assembly
  adapters/
    mock/           # World + MockMount + MockCedar + MockTelescopeBackend
                     # + MountEchoCedar (real mount, mocked cedar -- see below)
    alpaca/         # real mount client (alpyca): MountControl (closed-loop) +
                     # TelescopeBackend (external proxy) adapters -- verified
                     # against real Alpaca hardware (see below)
    indi/           # direct-INDI mount client via pyindi-client.
                     # IndiConnection (shared low-level wrapper),
                     # IndiMountClient, IndiTelescopeBackend. Verified
                     # against real hardware.
    cedar_grpc/      # real cedar-server client (grpc) + generated/ stubs --
                     # verified against a live Cedar-Box (see below)
    buzzer.py       # optional GPIO buzzer -- soft dependency, no-ops
                     # cleanly without real GPIO hardware
  config.py         # pydantic config, mirrors config.toml
proto/              # cedar-server's .proto sources (pulled from smroid/cedar-server)
scripts/
  generate_grpc_stubs.py  # regenerate adapters/cedar_grpc/generated/
packaging/
  cedar-goto.service # systemd unit
  install.sh         # install/upgrade script for a Pi/Linux host
```

`web.backend.TelescopeBackend` is deliberately a separate, larger interface
from `core.ports.MountControl`: the latter is the minimal seam the
closed-loop state machine needs, the former is the full ASCOM ITelescopeV3
surface the external proxy forwards.

## Web UI & buzzer

`http://<host>:<alpaca_port>/` (`11111` by default, see the port-conflict
note under Deployment if that's taken) serves a status page (live
state/iteration/error/last-solve via SSE, plus mount info -- location,
mount UTC date/time, sync-point count, park state). No build step, no
external assets/CDN, so it works standalone on a Pi with no internet.

Actions: **Sync now (cedar solve)** (syncs the mount straight to cedar's
current solve, bypassing the closed loop), **Sync to target**, **Abort**,
**Park**/**Unpark**, and **Clear sync points**. Park aborts any in-flight
closed-loop slew first.

The closed loop itself never syncs the mount on its own anymore: a plate
solve landing within `tolerance_arcmin` only proves cedar thinks the mount
is on target, not that it actually is for your optical path (a cedar box
mechanically offset from the main scope will confidently agree with itself
while still being wrong -- confirmed on-sky 2026-07-23, and exactly what
corrupted a real mount's own accurate alignment model). Instead: the closed
loop nudges the mount (via cedar's plate solves) only while the measured
error is between `tolerance_arcmin` ("min_move") and `max_correction_arcmin`
("max_move", disabled by default -- see config.toml) -- above that, it
reports **OUT_OF_RANGE** and does nothing further automatically, since an
error that large is more likely a bad solve than real pointing error.
Center the target in the main scope by hand, then press **Sync to target**
to sync the mount to the coordinate you originally requested (not to
cedar's solve). **Sync now (cedar solve)** and any automatic mount.sync_to()
still refuse to run against a solve that isn't a real plate solve (e.g. the
`MountEchoCedar` loopback used to exercise a real mount without a working
cedar-server) -- otherwise it'd calibrate the mount's persistent
alignment/sync-point database against its own already-possibly-wrong belief
instead of real sky data.

Since cedar-goto intercepts the ASCOM slew and drives the mount itself,
cedar-server has no way to know a GoTo is happening unless told -- so every
slew calls cedar-server's `InitiateAction(initiate_slew=...)` (found missing
2026-07-24), letting it offer its own push-to guidance (the `SlewRequest`
fields in `FrameResult` -- distance/angle to target -- as shown by Cedar
Aim's live view) for manually nudging the mount, e.g. via a handset or an
LX200 bridge. This stays active through `CONVERGED`/`FAILED`/`OUT_OF_RANGE`
-- the whole point of the design above is that a human may still need to
nudge onto target afterward -- and is only cleared (`stop_slew`) by
Abort/Park or by pressing **Sync to target**. Best-effort: a cedar-server
error here is logged and swallowed, never breaks the actual slew.
`MockCedar`/`MountEchoCedar` no-op this (nothing real to notify).

An **auto-correction** toggle on the dashboard disables the closed loop
entirely at runtime (no restart needed): with it off, SlewToCoordinates(Async)
is a bare proxy straight to the mount, same as before the closed loop
existed -- for when cedar's solves aren't trustworthy enough to act on right
now. cedar-goto still remembers the commanded target either way, so **Sync
to target** keeps working after a bare slew too.

Sync-point count and Clear are INDI-specific (no ASCOM Alpaca equivalent
exists); they show as "not supported" against the `alpyca`/`mock` backends.
Location and mount UTC date/time work identically against any backend.

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

`install.sh` also installs `pyindi-client` (needed for `[mount].backend =
"indi"`) with `--no-deps`, regardless of which backend you end up using --
it's a small, harmless extra otherwise. This works around `pyindi-client`
declaring `dbus-python` as a hard dependency it doesn't actually import at
runtime; `dbus-python` has no prebuilt wheels anywhere, so an unqualified
install would force a `meson`/`libdbus-1-dev` source build most deploy
targets don't have the toolchain for. See
[indi-refactor.md](indi-refactor.md) for the spike that confirmed this.

### Port conflict with cedar-server's own Alpaca server

`[server].alpaca_port` (default `11111`) and the UDP discovery responder
(port `32227`, `[server].discovery`) are the ASCOM *well-known* defaults --
convenient for auto-discovery, but only one process on a host can bind
either at a time. cedar-server itself already exposes its own Alpaca
server on exactly these ports (`ServerName: cedar-server`, confirmed via
its `/management/v1/description`) -- that's the interface it offers for
SkySafari/Cartes du Ciel/etc. to connect to it directly, separate from and
unaware of cedar-goto. Since both processes normally run on the same box
(cedar-goto talks to cedar-server locally over gRPC, see `[cedar].address`
above), cedar-goto will crash-loop on startup with `OSError: [Errno 98]
Address already in use` if it's left on the default port (check
`journalctl -u cedar-goto` for this if the service won't stay up).

Fix: pick a different `alpaca_port` and set `discovery = false`, since the
standard discovery port is unavailable either way -- e.g.:

```toml
[server]
bind = "0.0.0.0"
alpaca_port = 11112   # any free port; 11111 was already taken on this host
discovery = false
```

The tradeoff is that Alpaca clients (SkySafari, Cartes du Ciel, etc.) won't
auto-discover cedar-goto anymore -- enter `<host>:11112` (or whatever port
you chose) manually in the client instead.

## Regenerating gRPC stubs

If cedar-server's protos change:

```sh
.venv/Scripts/python scripts/generate_grpc_stubs.py
```
