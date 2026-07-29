# cedar-goto

cedar-goto facilitates using [cedar-server](https://github.com/smroid/cedar-server)
(a plate-solving electronic finder) with a GoTo telescope mount. It shows up
to your planetarium app as an ordinary ASCOM Alpaca telescope, and gives you
a small web dashboard with the manual controls to build a good mount
pointing model using cedar's plate solves, and to sync/re-slew against that
model on demand. It does not drive the mount automatically -- every slew is
a plain GoTo, and any cedar-assisted correction is something you explicitly
ask for. See [Field workflow](#field-workflow-on-sky) for how the two fit
together on-sky.

It's been tested against real Alpaca mount hardware, a real INDI-driven
mount, real cedar-server, and real SkySafari 8. There's also a
simulated-sky mock mode, so you can try the whole thing out with no
hardware at all.

Highlights:
- A small web UI, grouped by Mount / Target / Cedar, for live status plus
  manual controls: park/unpark/stop, slew-to-target, sync-to-target,
  sync-to-cedar, clear sync points.
- Reported position can come from cedar's plate solve instead of the
  mount's own idea of where it's pointed, falling back to the mount
  automatically if cedar isn't available.
- systemd packaging for easy Raspberry Pi deployment.

## Field workflow (on-sky)

cedar-goto doesn't replace the mount's own alignment model -- it helps you
build a good one and corrects what's left over. Two alignments decide how
well the whole thing points, and both want to be done on a real star:
cedar's boresight alignment to the main scope, and the mount's own
alignment/sync points.

Do cedar's boresight alignment on a star, not in daylight mode. With stars
in view, cedar detects the star you pick and centroids it to sub-pixel
accuracy; in daylight mode all it has is the image coordinate your finger
landed on (`designate_boresight` in `proto/cedar.proto`), which is as
accurate as your tap and no more. A daytime alignment is fine for finding a
first star in the main scope -- redo it on that star before trusting
anything downstream of it.

The routine that works (C9.25, long focal length, 2026-07 field testing):

1. Power up the mount and cedar-server.
2. GoTo a bright star through cedar-goto, so cedar-server hears about the
   slew and can offer its own [push-to guidance](#web-ui). Find
   the star in the main scope -- red-dot finder, or cedar's push-to arrow
   if cedar still carries its daytime alignment -- and center it with a
   crosshair eyepiece.
3. With the star centered in the main scope, (re)align cedar's boresight on
   it, in star mode rather than daylight mode.
4. Press **Sync mount to target** to sync the mount to that star's
   commanded coordinate. That's alignment point one.
5. GoTo a second star. If the pointing is off, press **Slew mount to
   target** to retry the plain GoTo, or nudge by hand following cedar's
   push-to arrow. Center it in the main scope, then **Sync mount to
   target** again.
6. Repeat once more for a third star, then stop. Three carefully centered
   points is the sweet spot: accuracy comes from how precisely each point
   was centered, not from how many there are, and a sloppy point degrades
   the model rather than averaging out (**Clear sync points** to start
   over).
7. Observe using the mount's own GoTo from here on. With a good three-point
   model it lands accurately on its own -- pick the alignment back up
   (steps 5-6) only when working far from the alignment stars.

Sync through cedar-goto's **Sync mount to target**. Syncing from SkySafari over a
direct INDI connection to the mount corrupts the alignment model instead:
confirmed 3/3 times live (2026-07-24, incl. after a SkySafari update) that
its `ON_COORD_SET=SYNC` sends Declination in radians rather than degrees,
appending a permanent bad point that warps GoTos computed near it.

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

- `tests/test_alpaca_server.py` -- the external Alpaca proxy (management
  API, discovery gating, plain-proxy slew, capability flags, error
  envelopes) against the mock harness (`adapters/mock/`, which simulates a
  Skywatcher Wave 150i's harmonic-drive pointing error and cedar's
  plate-solve stream), via an in-process ASGI client (no real HTTP/sockets).
- `tests/test_cedar_backend.py` -- the cedar-facilitation actions
  (sync-to-cedar, sync-to-target, slew-to-target) driven through the HTTP
  layer, the park/parked-slew guards, cedar-preferred position reporting,
  and an epoch-tagging regression test.
- `tests/test_web_ui.py` -- the web UI's status/SSE snapshot (including
  mount info) and its sync-now/sync-to-target/slew-to-target/abort/park/
  unpark/clear-sync-points actions.
- `tests/test_indi_backend.py` -- the direct-INDI backend's property-mapping
  logic against a fake `IndiConnection` (no real sockets/`pyindi-client`
  needed, so this runs regardless of whether the `indi` extra is
  installed).

## Layout

```
src/cedar_goto/
  core/            # framework-free control logic
    coords.py       # CelestialCoord, epoch math
    solve.py        # SolveResult, solve-acceptance gating
    ports.py        # MountControl / SolveSource protocols -- the seam
    _precession.py  # astropy boundary for epoch conversion
  web/             # the external Alpaca face
    alpaca_spec.py  # declarative ITelescopeV3 member table (drives routing)
    alpaca_errors.py# ASCOM error numbers + response envelope
    backend.py      # TelescopeBackend protocol -- the full-surface proxy seam
    cedar_backend.py# adds the cedar-facilitation actions (sync-to-cedar,
                     # sync-to-target, slew-to-target); every Alpaca member,
                     # including the slew itself, proxies straight through
                     # to a plain TelescopeBackend
    telescope_api.py# GET/PUT /api/v1/telescope/{n}/{action}, table-driven
    management.py   # /management/* endpoints
    discovery.py    # UDP discovery responder (port 32227)
    http_utils.py   # shared Alpaca HTTP request/response plumbing
    ui.py           # web UI: status/SSE, mount info,
                     # sync-now/sync-to-target/slew-to-target/abort/park/
                     # unpark/clear-sync-points
    app.py          # FastAPI app assembly
  adapters/
    mock/           # World + MockMount + MockCedar + MockTelescopeBackend
                     # + MountEchoCedar (real mount, mocked cedar -- see below)
    alpaca/         # real mount client (alpyca): MountControl +
                     # TelescopeBackend (external proxy) adapters -- verified
                     # against real Alpaca hardware (see below)
    indi/           # direct-INDI mount client via pyindi-client.
                     # IndiConnection (shared low-level wrapper),
                     # IndiMountClient, IndiTelescopeBackend. Verified
                     # against real hardware.
    cedar_grpc/      # real cedar-server client (grpc) + generated/ stubs --
                     # verified against a live Cedar-Box (see below)
  config.py         # pydantic config, mirrors config.toml
proto/              # cedar-server's .proto sources (pulled from smroid/cedar-server)
scripts/
  generate_grpc_stubs.py  # regenerate adapters/cedar_grpc/generated/
packaging/
  cedar-goto.service # systemd unit
  install.sh         # install/upgrade script for a Pi/Linux host
```

`web.backend.TelescopeBackend` is deliberately a separate, larger interface
from `core.ports.MountControl`: the latter is the minimal seam
`CedarTelescopeBackend`'s cedar-facilitation actions need (slew_to/sync_to/
get_position/...), the former is the full ASCOM ITelescopeV3 surface the
external proxy forwards.

## Web UI

`http://<host>:<alpaca_port>/` (`11111` by default, see the port-conflict
note under Deployment if that's taken) serves a status/action dashboard via
SSE, grouped into three collapsible panels. No build step, no external
assets/CDN, so it works standalone on a Pi with no internet -- and it's
meant to be used from a phone.

- **Mount** -- location, mount UTC time, park state, sync point count.
  Actions: **Park**, **Unpark**, **Stop**, **Clear sync points**.
- **Target** -- whether a planetarium app is connected, the last commanded
  target, and how long ago it was commanded (so you can tell instructions
  are actually getting through). Actions: **Slew mount to target** (a
  single, direct GoTo repeat of the last commanded target -- no solving, no
  iteration) and **Sync mount to target**.
- **Cedar** -- cedar's last plate solve, how long ago it was received, and
  the pointing error between that solve and the last commanded target,
  decomposed onto the mount's own Alt/Az axes (not RA/Dec) so it maps
  directly onto "how far off is each mechanical axis". Action: **Sync
  mount to cedar**. When cedar-goto detects it's running on the same host
  as cedar-server (`[cedar].address`'s host is `localhost` or `127.0.0.1`),
  **Start cedar-server**/**Stop cedar-server** buttons also appear here, running
  `sudo systemctl start/stop cedar` locally -- see "Start/stop cedar-server"
  below for the sudoers setup this needs. Hidden entirely (and refused
  server-side even if called directly) otherwise.

**Sync mount to target** is the one to reach for while aligning (see
[Field workflow](#field-workflow-on-sky)): it syncs to the coordinate you
asked for, once *you* have confirmed the main scope is on it. **Sync mount
to cedar** is only ever as good as cedar's boresight alignment to the main
scope -- it's for when you trust that alignment and can't center the target
by hand. Both refuse to sync against a solve that isn't a real plate solve
(e.g. the `MountEchoCedar` loopback used to exercise a real mount without a
working cedar-server) -- otherwise it'd calibrate the mount's persistent
alignment/sync-point database against its own already-possibly-wrong belief
instead of real sky data.

cedar-goto does not drive the mount automatically: `SlewToCoordinates(Async)`
is always a plain GoTo, proxied straight through. GoTo accuracy is normally
good enough once there's a nearby sync point (see
[Field workflow](#field-workflow-on-sky)) -- if it's off, **Slew mount to
target** or a manual nudge (see push-to guidance below) is the explicit,
one-command fix, rather than an automatic correction loop running behind
your back.

Since cedar-goto intercepts the ASCOM slew and drives the mount itself,
cedar-server has no way to know a GoTo is happening unless told -- so every
slew calls cedar-server's `InitiateAction(initiate_slew=...)` (found missing
2026-07-24), letting it offer its own push-to guidance (the `SlewRequest`
fields in `FrameResult` -- distance/angle to target -- as shown by Cedar
Aim's live view) for manually nudging the mount, e.g. via a handset or an
LX200 bridge. This stays active until you're done -- cleared (`stop_slew`)
by **Stop**/**Park** or by pressing **Sync mount to target**. Best-effort: a
cedar-server error here is logged and swallowed, never breaks the actual
slew. `MockCedar`/`MountEchoCedar` no-op this (nothing real to notify).

Sync-point count and Clear are INDI-specific (no ASCOM Alpaca equivalent
exists); they show as "not supported" against the `alpyca`/`mock` backends.
Location and mount UTC time work identically against any backend.

## Deployment (Raspberry Pi / systemd)

```sh
sudo packaging/install.sh            # installs to /opt/cedar-goto by default
# edit /opt/cedar-goto/config.toml (mount/cedar addresses, [mount].backend = "indi"/"alpyca", [cedar].backend = "grpc")
sudo systemctl start cedar-goto
journalctl -u cedar-goto -f
```

Re-running `install.sh` upgrades the code + venv in place without touching
an existing `config.toml`. See `packaging/cedar-goto.service` for the unit
file.

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

### Start/stop cedar-server

The web UI's Start/Stop cedar-server buttons (Cedar panel, only shown when
`[cedar].address`'s host is `localhost` or `127.0.0.1`) shell out to `sudo
systemctl start/stop cedar` on the box cedar-goto itself is running on. This only
works if the service user (`cedar-goto` by default, see `packaging/
cedar-goto.service`) has **passwordless sudo** for exactly those two
commands -- `install.sh` does not set this up automatically (it's a system
security policy change, deliberately left as a manual step). Add a sudoers
drop-in:

```sh
echo 'cedar-goto ALL=(ALL) NOPASSWD: /usr/bin/systemctl start cedar, /usr/bin/systemctl stop cedar' \
  | sudo tee /etc/sudoers.d/cedar-goto-cedar-service
sudo visudo -c   # validate the file before trusting it
```

Without this, the buttons fail cleanly with whatever `sudo`/`systemctl`
printed (typically "sudo: a password is required") rather than hanging --
`cedar_service.cedar_systemctl()` runs with stdin closed and a timeout, so
a missing NOPASSWD entry can't leave a request stuck.

## Regenerating gRPC stubs

If cedar-server's protos change:

```sh
.venv/Scripts/python scripts/generate_grpc_stubs.py
```
