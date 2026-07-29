"""Web UI (DESIGN.md §8): live mount/target/cedar status and the actions
that facilitate using cedar-server with a GoTo mount -- park/unpark/stop,
slew-to-target, sync-to-target, sync-to-cedar. Plain HTML + vanilla-JS SSE,
no build step and no external assets/CDN -- this needs to work standalone
on a Pi with no internet.

Routes here assume `app.state.telescope_backend` is a CedarTelescopeBackend
(true for every composition in __main__.py) -- the plain TelescopeBackend
protocol doesn't have status_snapshot/abort/sync_to_cedar, since those are
UI-specific, not part of the Alpaca proxy surface.
"""
from __future__ import annotations

import asyncio
import json
import time

import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, FK5, SkyCoord
from astropy.time import Time
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from cedar_goto.web.alpaca_errors import AlpacaError
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION
from cedar_goto.web.cedar_backend import SyncRefused
from cedar_goto.web.cedar_service import cedar_systemctl
from cedar_goto.web.log_buffer import recent_lines

router = APIRouter()

_CONNECTED_MEMBER = ALL_MEMBERS_BY_ACTION["connected"]
_SITE_LATITUDE_MEMBER = ALL_MEMBERS_BY_ACTION["sitelatitude"]
_SITE_LONGITUDE_MEMBER = ALL_MEMBERS_BY_ACTION["sitelongitude"]
_SITE_ELEVATION_MEMBER = ALL_MEMBERS_BY_ACTION["siteelevation"]
_UTC_DATE_MEMBER = ALL_MEMBERS_BY_ACTION["utcdate"]
_AT_PARK_MEMBER = ALL_MEMBERS_BY_ACTION["atpark"]
_PARK_MEMBER = ALL_MEMBERS_BY_ACTION["park"]
_UNPARK_MEMBER = ALL_MEMBERS_BY_ACTION["unpark"]


_MOUNT_INFO_TIMEOUT_S = 1.5


async def _snapshot(backend) -> dict:
    snapshot = await backend.status_snapshot()
    snapshot["connected"] = await backend.get(_CONNECTED_MEMBER)
    # _mount_info can block for IndiConnection's full 10s property-wait timeout
    # when nothing is Alpaca-connected yet (confirmed live: SSE ticks landing
    # ~10.5s apart instead of the intended 0.5s). Capping it here keeps every
    # other field flowing at full speed; a timed-out tick just reports
    # mount_info as unavailable and retries next tick, same as any other
    # _mount_info failure.
    try:
        snapshot["mount_info"] = await asyncio.wait_for(_mount_info(backend), timeout=_MOUNT_INFO_TIMEOUT_S)
    except asyncio.TimeoutError:
        snapshot["mount_info"] = None
    last_target_time = snapshot.get("last_target_time_unix")
    snapshot["target_age_s"] = (time.time() - last_target_time) if last_target_time is not None else None
    last_solve = snapshot.get("last_solve")
    solve_capture_time = last_solve["capture_time_unix"] if last_solve else None
    snapshot["solve_age_s"] = (time.time() - solve_capture_time) if solve_capture_time is not None else None
    snapshot["cedar_error"] = _cedar_altaz_error(
        snapshot.get("last_target"), snapshot.get("last_solve"), snapshot.get("mount_info")
    )
    return snapshot


def _cedar_altaz_error(target: dict | None, solve: dict | None, mount_info: dict | None) -> dict | None:
    """Cedar group's error row: how far cedar's last plate solve landed from
    the last commanded target, decomposed onto the mount's own Alt/Az axes
    rather than a single RA/Dec separation -- for an Alt-Az mount that maps
    directly onto "how far off is each mechanical axis". The az delta is the
    raw axis-angle difference (not cos(alt)-scaled): that's literally how
    far the azimuth axis has to turn, independent of how much sky angle it
    covers.
    """
    if target is None or solve is None or mount_info is None:
        return None
    try:
        location = EarthLocation(
            lat=mount_info["site_latitude_deg"] * u.deg,
            lon=mount_info["site_longitude_deg"] * u.deg,
            height=mount_info["site_elevation_m"] * u.m,
        )
        frame = AltAz(obstime=Time.now(), location=location)
        target_altaz = _to_altaz(target, frame)
        solve_altaz = _to_altaz(solve["sky_coord"], frame)
        delta_alt_arcmin = (solve_altaz.alt - target_altaz.alt).arcmin
        delta_az_arcmin = (solve_altaz.az - target_altaz.az).wrap_at(180 * u.deg).arcmin
        return {"alt_arcmin": float(delta_alt_arcmin), "az_arcmin": float(delta_az_arcmin)}
    except Exception:
        return None


def _to_altaz(coord: dict, frame: AltAz) -> SkyCoord:
    equinox_frame = FK5(equinox=Time(coord["epoch"], format="jyear"))
    return SkyCoord(ra=coord["ra_deg"] * u.deg, dec=coord["dec_deg"] * u.deg, frame=equinox_frame).transform_to(frame)


async def _mount_info(backend) -> dict | None:
    # Not gated on Connected -- IndiTelescopeBackend/IndiConnection connect
    # lazily on first property access regardless, and this dashboard should
    # show something useful before any external Alpaca client has connected.
    # Defensive: a real mount/driver hiccup here must not take down the
    # whole status stream (matches telescope_api.py's/cedar_backend's
    # existing "never let a backend surprise crash this" philosophy).
    try:
        return {
            "site_latitude_deg": await backend.get(_SITE_LATITUDE_MEMBER),
            "site_longitude_deg": await backend.get(_SITE_LONGITUDE_MEMBER),
            "site_elevation_m": await backend.get(_SITE_ELEVATION_MEMBER),
            "utc_date": await backend.get(_UTC_DATE_MEMBER),
            "sync_point_count": await backend.get_sync_point_count(),
            "at_park": await backend.get(_AT_PARK_MEMBER),
        }
    except Exception:
        return None


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})


def cedar_address_is_loopback(address: str) -> bool:
    """True if `address` ("host:port") points at loopback -- i.e. cedar-goto
    and cedar-server run on the same box. Checks the parsed host, not a bare
    substring match: "127.0.0.1" doesn't contain the substring "localhost",
    which under-detected same-host deployments configured with an IP
    instead of the name (confirmed live against the production Pi)."""
    host, _, _ = address.partition(":")
    return host in _LOOPBACK_HOSTS


def _resolve_cedar_ui_url(request: Request, cedar_address: str | None) -> str | None:
    """Builds the link to cedar-server's own UI from the raw configured
    [cedar].address. A loopback host must be resolved against the
    *request's* own host, not cedar-goto's -- "localhost"/"127.0.0.1" in a
    link opened from a phone resolves on the phone, not on cedar-goto's box
    (confirmed live: the link was dead on a same-host deployment)."""
    if cedar_address is None:
        return None
    host, sep, port = cedar_address.partition(":")
    if host in _LOOPBACK_HOSTS:
        host = request.url.hostname
    return f"http://{host}{sep}{port}/" if sep else f"http://{host}/"


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> str:
    cedar_ui_url = _resolve_cedar_ui_url(request, getattr(request.app.state, "cedar_address", None))
    cedar_same_host = getattr(request.app.state, "cedar_same_host", False)
    return (
        _PAGE.replace("__CEDAR_UI_LINK__", json.dumps(cedar_ui_url))
        .replace("__CEDAR_SAME_HOST__", json.dumps(cedar_same_host))
    )


@router.get("/api/ui/status")
async def status(request: Request) -> JSONResponse:
    return JSONResponse(await _snapshot(request.app.state.telescope_backend))


@router.get("/api/ui/log")
async def log() -> JSONResponse:
    return JSONResponse({"lines": recent_lines()})


@router.get("/api/ui/events")
async def events(request: Request) -> EventSourceResponse:
    backend = request.app.state.telescope_backend

    async def stream():
        while True:
            if await request.is_disconnected():
                break
            yield json.dumps(await _snapshot(backend))
            await asyncio.sleep(0.5)

    return EventSourceResponse(stream())


@router.post("/api/ui/actions/abort")
async def action_abort(request: Request) -> JSONResponse:
    await request.app.state.telescope_backend.abort()
    return JSONResponse({"ok": True})


@router.post("/api/ui/actions/clear-sync-points")
async def action_clear_sync_points(request: Request) -> JSONResponse:
    cleared = await request.app.state.telescope_backend.clear_sync_points()
    if not cleared:
        return JSONResponse({"ok": False, "message": "not supported by this mount backend"})
    return JSONResponse({"ok": True, "message": "sync points cleared"})


@router.post("/api/ui/actions/park")
async def action_park(request: Request) -> JSONResponse:
    backend = request.app.state.telescope_backend
    try:
        await backend.put(_PARK_MEMBER, {})
        return JSONResponse({"ok": True, "message": "parked"})
    except AlpacaError as exc:
        return JSONResponse({"ok": False, "message": exc.message})


@router.post("/api/ui/actions/unpark")
async def action_unpark(request: Request) -> JSONResponse:
    backend = request.app.state.telescope_backend
    try:
        await backend.put(_UNPARK_MEMBER, {})
        return JSONResponse({"ok": True, "message": "unparked"})
    except AlpacaError as exc:
        return JSONResponse({"ok": False, "message": exc.message})


@router.post("/api/ui/actions/sync-now")
async def action_sync_now(request: Request) -> JSONResponse:
    try:
        solve = await request.app.state.telescope_backend.sync_to_cedar()
    except SyncRefused as exc:
        return JSONResponse({"ok": False, "message": str(exc)})
    if solve is None:
        return JSONResponse({"ok": False, "message": "no acceptable cedar solve available right now"})
    ra_hours = solve.sky_coord.ra_deg / 15.0
    return JSONResponse(
        {"ok": True, "message": f"synced to RA {ra_hours:.3f}h Dec {solve.sky_coord.dec_deg:.3f}°"}
    )


@router.post("/api/ui/actions/realign")
async def action_realign(request: Request) -> JSONResponse:
    await request.app.state.telescope_backend.realign_cedar()
    return JSONResponse({"ok": True, "message": "told cedar-server to realign"})


@router.post("/api/ui/actions/cedar-start")
async def action_cedar_start(request: Request) -> JSONResponse:
    if not getattr(request.app.state, "cedar_same_host", False):
        return JSONResponse({"ok": False, "message": "cedar-server is not on this host"})
    ok, message = await cedar_systemctl("start")
    return JSONResponse({"ok": ok, "message": message})


@router.post("/api/ui/actions/cedar-stop")
async def action_cedar_stop(request: Request) -> JSONResponse:
    if not getattr(request.app.state, "cedar_same_host", False):
        return JSONResponse({"ok": False, "message": "cedar-server is not on this host"})
    ok, message = await cedar_systemctl("stop")
    return JSONResponse({"ok": ok, "message": message})


@router.post("/api/ui/actions/sync-to-target")
async def action_sync_to_target(request: Request) -> JSONResponse:
    target = await request.app.state.telescope_backend.sync_to_target()
    if target is None:
        return JSONResponse(
            {"ok": False, "message": "no completed slew to sync to yet (or one is still in progress)"}
        )
    ra_hours = target.ra_deg / 15.0
    return JSONResponse(
        {"ok": True, "message": f"synced to target RA {ra_hours:.3f}h Dec {target.dec_deg:.3f}°"}
    )


@router.post("/api/ui/actions/reslew-to-target")
async def action_reslew_to_target(request: Request) -> JSONResponse:
    target = await request.app.state.telescope_backend.reslew_to_target()
    if target is None:
        return JSONResponse({"ok": False, "message": "no target yet -- GoTo somewhere from your planetarium app first"})
    ra_hours = target.ra_deg / 15.0
    return JSONResponse(
        {"ok": True, "message": f"re-slewing to RA {ra_hours:.3f}h Dec {target.dec_deg:.3f}°"}
    )


_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cedar-goto</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0 auto; padding: 1rem; max-width: 640px; background: #111; color: #eee; }
  h1 { font-size: 1.3rem; margin: 0 0 1rem; }
  .card { background: #1c1c1c; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
  .card summary {
    margin: 0 0 0.6rem; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: #999; font-weight: 600; cursor: pointer; padding: 0.3rem 0;
    touch-action: manipulation; -webkit-tap-highlight-color: transparent;
  }
  .card:not([open]) summary { margin-bottom: 0; }
  #wizard-title { margin: 0 0 0.5rem; font-size: 1.05rem; }
  .wizard-list { margin: 0 0 0.8rem; padding-left: 1.3rem; }
  .wizard-list:empty { margin: 0; }
  .wizard-list li { margin-bottom: 0.5rem; line-height: 1.35; }
  .row { display: flex; justify-content: space-between; align-items: center; padding: 0.45rem 0; border-bottom: 1px solid #333; font-size: 1rem; }
  .row:last-child { border-bottom: none; }
  .park-badge { font-weight: bold; padding: 0.1rem 0.6rem; border-radius: 4px; }
  .park-badge.parked { background: #7a4a12; }
  .park-badge.not-parked { background: #444; }
  .button-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.6rem; margin-bottom: 0.6rem; }
  .button-row:last-of-type { margin-bottom: 0; }
  button, .button-row a {
    background: #2a6b3f; border: none; color: white; padding: 0.9rem 1rem; border-radius: 8px;
    cursor: pointer; font-size: 1rem; font-weight: 600; min-height: 3.25rem;
    touch-action: manipulation; -webkit-tap-highlight-color: transparent;
    transition: background-color 0.1s ease, transform 0.1s ease;
    display: flex; align-items: center; justify-content: center; text-decoration: none;
  }
  button:active, .button-row a:active { background: #1f5030; transform: scale(0.96); }
  button.danger { background: #6b2a2a; }
  button.danger:active { background: #4f1f1f; }
  button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
  #message { color: #999; font-size: 0.9rem; margin-top: 0.6rem; min-height: 1.2em; }
  #log-output {
    background: #111; border-radius: 6px; padding: 0.6rem; margin: 0;
    font-family: ui-monospace, monospace; font-size: 0.75rem; line-height: 1.4; color: #ccc;
    white-space: pre-wrap; word-break: break-all; max-height: 40vh; overflow-y: auto;
  }
</style>
</head>
<body>
<h1>cedar-goto</h1>
<details class="card" id="wizard-card" open>
  <summary>Setup wizard</summary>
  <h3 id="wizard-title"></h3>
  <ul class="wizard-list" id="wizard-body"></ul>
  <div class="button-row" id="wizard-link-row"></div>
  <div class="button-row" id="wizard-action-row"></div>
  <ul class="wizard-list" id="wizard-after"></ul>
  <div class="button-row">
    <button id="wizard-back-btn" onclick="wizardBack()">Back</button>
    <button id="wizard-next-btn" onclick="wizardNext()">Next</button>
  </div>
</details>
<details class="card" open>
  <summary>Mount</summary>
  <div class="row"><span>Location</span><span id="location">–</span></div>
  <div class="row"><span>Mount UTC time</span><span id="utc-date">–</span></div>
  <div class="row"><span>Park state</span><span id="at-park" class="park-badge">–</span></div>
  <div class="row"><span>Sync point count</span><span id="sync-point-count">–</span></div>
  <div class="button-row">
    <button id="park-btn" onclick="post('/api/ui/actions/park', this)">Park</button>
    <button id="unpark-btn" onclick="post('/api/ui/actions/unpark', this)">Unpark</button>
  </div>
  <div class="button-row">
    <button class="danger" onclick="post('/api/ui/actions/abort', this)">Stop</button>
    <button class="danger" onclick="clearSyncPoints(this)">Clear sync points</button>
  </div>
</details>
<details class="card" open>
  <summary>Target</summary>
  <div class="row"><span>Planetarium connected</span><span id="connected">–</span></div>
  <div class="row"><span>Target</span><span id="target">–</span></div>
  <div class="row"><span>Last commanded</span><span id="target-age">–</span></div>
  <div class="button-row">
    <button onclick="post('/api/ui/actions/reslew-to-target', this)">✥ Slew mount to target</button>
    <button onclick="post('/api/ui/actions/sync-to-target', this)">✓ Sync mount to target</button>
  </div>
</details>
<details class="card" open>
  <summary>Cedar</summary>
  <div class="row"><span>Last solve</span><span id="solve">–</span></div>
  <div class="row"><span>Received</span><span id="solve-age">–</span></div>
  <div class="row"><span>Error (alt/az)</span><span id="cedar-error">–</span></div>
  <div class="button-row">
    <button onclick="post('/api/ui/actions/sync-now', this)">✓ Sync mount to cedar</button>
  </div>
  <div class="button-row" id="cedar-service-row" style="display:none;">
    <button onclick="post('/api/ui/actions/cedar-start', this)">Start cedar-server</button>
    <button class="danger" onclick="post('/api/ui/actions/cedar-stop', this)">Stop cedar-server</button>
  </div>
</details>
<details class="card">
  <summary>Server log</summary>
  <div class="button-row">
    <button onclick="refreshLog()">Refresh log</button>
  </div>
  <pre id="log-output">–</pre>
</details>
<div id="message"></div>
<script>
const WIZARD_STEPS = [
  {
    title: 'Start of session',
    body: [
      'Unpark your mount. Do a ballpark alignment of cedar (daytime/distant object) or align a red dot finder.',
    ],
    action: { label: 'Unpark', endpoint: '/api/ui/actions/unpark' },
  },
  {
    title: 'First star',
    body: [
      'Go-to a bright star from planetarium.',
      'Find it using your red dot finder, or cedar-server.',
      'Center the bright star in the main scope. Use a crosshair eyepiece if you have one.',
      '"Sync mount to target" to tell the mount that it now really is pointing where it thought it was pointing.',
    ],
    link: __CEDAR_UI_LINK__,
    action: { label: 'Sync mount to target', endpoint: '/api/ui/actions/sync-to-target' },
    after: [
      'Re-check centering of star in main scope.',
      'Hit "Realign" in cedar-server so cedar-server is now properly aligned with the main scope.',
    ],
  },
  {
    title: 'Second star',
    body: [
      'Go-to a second bright star from planetarium.',
      'Find the second bright star using the now well-aligned cedar-server.',
      'Center the second bright star in the main scope.',
      '"Sync mount to target".',
    ],
    action: { label: 'Sync mount to target', endpoint: '/api/ui/actions/sync-to-target' },
  },
  {
    title: 'Third star (optional, but recommended)',
    body: [
      'Go-to a 3rd bright star from planetarium.',
      'Find the 3rd bright star using the now well-aligned cedar-server.',
      'Center the 3rd bright star in the main scope.',
      '"Sync mount to target".',
    ],
    action: { label: 'Sync mount to target', endpoint: '/api/ui/actions/sync-to-target' },
  },
  {
    title: 'Done',
    body: [
      'Done.',
    ],
  },
];
let wizardStep = 0;
function renderWizard() {
  const step = WIZARD_STEPS[wizardStep];
  document.getElementById('wizard-title').textContent = step.title;
  const bodyEl = document.getElementById('wizard-body');
  bodyEl.innerHTML = '';
  step.body.forEach((line) => {
    const li = document.createElement('li');
    li.textContent = line;
    bodyEl.appendChild(li);
  });
  renderWizardLinkRow('wizard-link-row', step.link);
  renderWizardActionRow('wizard-action-row', step.action);
  const afterEl = document.getElementById('wizard-after');
  afterEl.innerHTML = '';
  (step.after || []).forEach((line) => {
    const li = document.createElement('li');
    li.textContent = line;
    afterEl.appendChild(li);
  });
  document.getElementById('wizard-back-btn').disabled = wizardStep === 0;
  document.getElementById('wizard-next-btn').textContent =
    wizardStep === WIZARD_STEPS.length - 1 ? 'Close' : 'Next';
}
function renderWizardActionRow(rowId, action) {
  const row = document.getElementById(rowId);
  row.innerHTML = '';
  if (!action) {
    row.style.display = 'none';
    return;
  }
  row.style.display = '';
  const btn = document.createElement('button');
  btn.textContent = action.label;
  btn.onclick = () => post(action.endpoint, btn);
  row.appendChild(btn);
}
function renderWizardLinkRow(rowId, url) {
  const row = document.getElementById(rowId);
  row.innerHTML = '';
  if (!url) {
    row.style.display = 'none';
    return;
  }
  row.style.display = '';
  const link = document.createElement('a');
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = 'Open cedar-server ↗';
  row.appendChild(link);
}
function wizardNext() {
  if (wizardStep === WIZARD_STEPS.length - 1) {
    wizardStep = 0;
    renderWizard();
    document.getElementById('wizard-card').open = false;
    return;
  }
  wizardStep = Math.min(wizardStep + 1, WIZARD_STEPS.length - 1);
  renderWizard();
}
function wizardBack() {
  wizardStep = Math.max(wizardStep - 1, 0);
  renderWizard();
}
renderWizard();
if (__CEDAR_SAME_HOST__) {
  document.getElementById('cedar-service-row').style.display = '';
}
const es = new EventSource('/api/ui/events');
es.onmessage = (e) => {
  const s = JSON.parse(e.data);
  document.getElementById('connected').textContent = s.connected ? 'yes' : 'no';
  document.getElementById('target').textContent = s.last_target
    ? formatHMS(s.last_target.ra_deg) + ' ' + formatDMS(s.last_target.dec_deg)
    : '–';
  document.getElementById('target-age').textContent = (s.target_age_s != null) ? formatAge(s.target_age_s) : '–';
  document.getElementById('solve').textContent = s.last_solve
    ? formatHMS(s.last_solve.sky_coord.ra_deg) + ' ' + formatDMS(s.last_solve.sky_coord.dec_deg)
    : '–';
  document.getElementById('solve-age').textContent = (s.solve_age_s != null) ? formatAge(s.solve_age_s) : '–';
  document.getElementById('cedar-error').textContent = s.cedar_error
    ? 'alt ' + formatSignedArcmin(s.cedar_error.alt_arcmin) + ' / az ' + formatSignedArcmin(s.cedar_error.az_arcmin)
    : '–';
  const info = s.mount_info;
  document.getElementById('location').textContent = info
    ? info.site_latitude_deg.toFixed(4) + '°, ' + info.site_longitude_deg.toFixed(4) + '°, ' + info.site_elevation_m.toFixed(0) + 'm'
    : '–';
  document.getElementById('utc-date').textContent = info ? info.utc_date.replace('T', ' ').replace(/\\.\\d+Z$/, 'Z') : '–';
  document.getElementById('sync-point-count').textContent = info && info.sync_point_count != null
    ? info.sync_point_count
    : (info ? 'not supported' : '–');
  const atParkEl = document.getElementById('at-park');
  atParkEl.textContent = info ? (info.at_park ? 'PARKED' : 'not parked') : '–';
  atParkEl.className = 'park-badge' + (info ? (info.at_park ? ' parked' : ' not-parked') : '');
  // Unknown state (info === null) leaves both enabled -- can't be sure, so
  // don't block the user from trying.
  document.getElementById('park-btn').disabled = info ? info.at_park : false;
  document.getElementById('unpark-btn').disabled = info ? !info.at_park : false;
};
function formatHMS(raDeg) {
  const totalHours = raDeg / 15;
  const h = Math.floor(totalHours);
  const totalMinutes = (totalHours - h) * 60;
  const m = Math.floor(totalMinutes);
  const s = (totalMinutes - m) * 60;
  return h + 'h ' + String(m).padStart(2, '0') + 'm ' + s.toFixed(1) + 's';
}
function formatDMS(decDeg) {
  const sign = decDeg < 0 ? '-' : '+';
  const abs = Math.abs(decDeg);
  const d = Math.floor(abs);
  const totalMinutes = (abs - d) * 60;
  const m = Math.floor(totalMinutes);
  const s = (totalMinutes - m) * 60;
  return sign + d + "° " + String(m).padStart(2, '0') + "' " + s.toFixed(0) + '"';
}
function formatAge(totalSeconds) {
  const s = Math.floor(totalSeconds);
  // Small negative values happen from clock skew between this machine and
  // the mount/cedar-server's own clock, not a real "in the future" solve --
  // clamp rather than show a confusing "-2s ago".
  if (s <= 0) return 'just now';
  if (s < 60) return s + 's ago';
  const minutes = Math.floor(s / 60);
  if (minutes < 60) return minutes + 'm ago';
  const hours = Math.floor(minutes / 60);
  return hours + 'h ' + (minutes % 60) + 'm ago';
}
function formatSignedArcmin(arcmin) {
  const sign = arcmin >= 0 ? '+' : '-';
  return sign + Math.abs(arcmin).toFixed(1) + "'";
}
async function post(url, btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(url, {method: 'POST'});
    const body = await r.json();
    document.getElementById('message').textContent = body.message || (body.ok ? 'OK' : 'failed');
  } finally {
    if (btn) btn.disabled = false;
  }
}
function clearSyncPoints(btn) {
  if (confirm('Clear all mount sync points? This cannot be undone.')) {
    post('/api/ui/actions/clear-sync-points', btn);
  }
}
async function refreshLog() {
  const el = document.getElementById('log-output');
  el.textContent = 'Loading…';
  try {
    const r = await fetch('/api/ui/log');
    const body = await r.json();
    el.textContent = body.lines && body.lines.length ? body.lines.join('\\n') : '(no log lines yet)';
  } catch (e) {
    el.textContent = 'Failed to load log: ' + e;
  }
}
</script>
</body>
</html>
"""
