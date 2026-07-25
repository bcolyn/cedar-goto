"""Minimal web UI (DESIGN.md §8): live closed-loop status, connect state,
and "sync now" / "abort" actions. Plain HTML + vanilla-JS SSE, no build
step and no external assets/CDN -- this needs to work standalone on a Pi
with no internet.

Routes here assume `app.state.telescope_backend` is a
ClosedLoopTelescopeBackend (true for every composition in __main__.py) --
the plain TelescopeBackend protocol doesn't have status_snapshot/abort/
sync_to_cedar, since those are UI/closed-loop-specific, not part of the
Alpaca proxy surface.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from cedar_goto.web.alpaca_errors import AlpacaError
from cedar_goto.web.alpaca_spec import ALL_MEMBERS_BY_ACTION
from cedar_goto.web.closed_loop_backend import CorrectionRefused, SyncRefused

router = APIRouter()

_PROCESS_START_TIME = time.monotonic()

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
    snapshot = backend.status_snapshot()
    snapshot["connected"] = await backend.get(_CONNECTED_MEMBER)
    # _mount_info can block for IndiConnection's full 10s property-wait timeout
    # when nothing is Alpaca-connected yet (confirmed live: SSE ticks landing
    # ~10.5s apart instead of the intended 0.5s). Capping it here keeps every
    # other field -- correction_enabled, state, etc. -- flowing at full speed;
    # a timed-out tick just reports mount_info as unavailable and retries next
    # tick, same as any other _mount_info failure.
    try:
        snapshot["mount_info"] = await asyncio.wait_for(_mount_info(backend), timeout=_MOUNT_INFO_TIMEOUT_S)
    except asyncio.TimeoutError:
        snapshot["mount_info"] = None
    snapshot["uptime_s"] = time.monotonic() - _PROCESS_START_TIME
    return snapshot


async def _mount_info(backend) -> dict | None:
    # Not gated on Connected -- IndiTelescopeBackend/IndiConnection connect
    # lazily on first property access regardless, and this dashboard should
    # show something useful before any external Alpaca client has connected.
    # Defensive: a real mount/driver hiccup here must not take down the
    # whole status stream (matches telescope_api.py's/closed_loop_backend's
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


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _PAGE


@router.get("/api/ui/status")
async def status(request: Request) -> JSONResponse:
    return JSONResponse(await _snapshot(request.app.state.telescope_backend))


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


@router.post("/api/ui/actions/correct-now")
async def action_correct_now(request: Request) -> JSONResponse:
    try:
        target = await request.app.state.telescope_backend.correct_now()
    except CorrectionRefused as exc:
        return JSONResponse({"ok": False, "message": str(exc)})
    if target is None:
        return JSONResponse({"ok": False, "message": "no target yet -- slew somewhere first"})
    ra_hours = target.ra_deg / 15.0
    return JSONResponse(
        {"ok": True, "message": f"correcting to RA {ra_hours:.3f}h Dec {target.dec_deg:.3f}°"}
    )


@router.post("/api/ui/actions/correction")
async def action_set_correction(request: Request) -> JSONResponse:
    form = await request.form()
    enabled = form.get("enabled") == "true"
    request.app.state.telescope_backend.set_correction_enabled(enabled)
    return JSONResponse({"ok": True, "message": f"auto-correction {'enabled' if enabled else 'disabled'}"})


_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>cedar-goto</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 640px; background: #111; color: #eee; }
  h1 { font-size: 1.3rem; }
  .card { background: #1c1c1c; border-radius: 8px; padding: 1rem 1.5rem; margin-bottom: 1rem; }
  .row { display: flex; justify-content: space-between; padding: 0.3rem 0; border-bottom: 1px solid #333; }
  .row:last-child { border-bottom: none; }
  .state { font-weight: bold; padding: 0.1rem 0.6rem; border-radius: 4px; }
  .state-CONVERGED { background: #1a5c34; }
  .state-FAILED { background: #5c1a1a; }
  .state-OUT_OF_RANGE { background: #7a4a12; }
  .state-IDLE, .state-undefined { background: #444; }
  .state-SLEWING_MOUNT, .state-SETTLING, .state-AWAIT_SOLVE, .state-EVALUATE { background: #4a4a1a; }
  .park-badge { font-weight: bold; padding: 0.1rem 0.6rem; border-radius: 4px; }
  .park-badge.parked { background: #7a4a12; }
  .park-badge.not-parked { background: #444; }
  .button-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.5rem; }
  .button-row:last-of-type { margin-bottom: 0; }
  button { background: #2a6b3f; border: none; color: white; padding: 0.5rem 1.1rem; border-radius: 4px; cursor: pointer; font-size: 0.95rem; }
  button.danger { background: #6b2a2a; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  #message { color: #999; font-size: 0.85rem; margin-top: 0.6rem; min-height: 1.2em; }
</style>
</head>
<body>
<h1>cedar-goto</h1>
<div class="card">
  <div class="row"><span>Connected</span><span id="connected">–</span></div>
  <div class="row"><span>State</span><span id="state" class="state">–</span></div>
  <div class="row"><span>Iteration</span><span id="iteration">–</span></div>
  <div class="row"><span>Error</span><span id="error">–</span></div>
  <div class="row"><span>Target</span><span id="target">–</span></div>
  <div class="row"><span>Last solve</span><span id="solve">–</span></div>
  <div class="row"><span>Uptime</span><span id="uptime">–</span></div>
</div>
<div class="card">
  <div class="row"><span>Location</span><span id="location">–</span></div>
  <div class="row"><span>Mount UTC date/time</span><span id="utc-date">–</span></div>
  <div class="row"><span>Sync points</span><span id="sync-point-count">–</span></div>
  <div class="row"><span>Park state</span><span id="at-park" class="park-badge">–</span></div>
  <div class="row">
    <span>Auto-correction (nudge to cedar)</span>
    <span><input type="checkbox" id="correction-toggle" onchange="setCorrection(this.checked)"></span>
  </div>
</div>
<div class="card">
  <div class="button-row">
    <button onclick="post('/api/ui/actions/park')">Park</button>
    <button onclick="post('/api/ui/actions/unpark')">Unpark</button>
  </div>
  <div class="button-row">
    <button id="correct-now-btn" onclick="post('/api/ui/actions/correct-now')">Correct now (nudge to target)</button>
    <button class="danger" onclick="post('/api/ui/actions/abort')">Abort</button>
  </div>
  <div class="button-row">
    <button onclick="post('/api/ui/actions/sync-now')">Sync now (cedar solve)</button>
    <button onclick="post('/api/ui/actions/sync-to-target')">Sync to target</button>
    <button class="danger" onclick="clearSyncPoints()">Clear sync points</button>
  </div>
  <div id="message"></div>
</div>
<script>
const es = new EventSource('/api/ui/events');
es.onmessage = (e) => {
  const s = JSON.parse(e.data);
  document.getElementById('connected').textContent = s.connected ? 'yes' : 'no';
  const stateEl = document.getElementById('state');
  stateEl.textContent = s.state;
  stateEl.className = 'state state-' + s.state;
  document.getElementById('iteration').textContent = s.iteration ?? '–';
  document.getElementById('error').textContent = (s.error_arcmin != null) ? s.error_arcmin.toFixed(2) + "'" : '–';
  document.getElementById('target').textContent = s.last_target
    ? 'RA ' + (s.last_target.ra_deg / 15).toFixed(3) + 'h Dec ' + s.last_target.dec_deg.toFixed(3) + '°'
    : '–';
  document.getElementById('solve').textContent = s.last_solve
    ? 'RA ' + (s.last_solve.sky_coord.ra_deg / 15).toFixed(3) + 'h Dec ' + s.last_solve.sky_coord.dec_deg.toFixed(3) + '°'
    : '–';
  document.getElementById('uptime').textContent = (s.uptime_s != null) ? formatUptime(s.uptime_s) : '–';
  const info = s.mount_info;
  document.getElementById('location').textContent = info
    ? info.site_latitude_deg.toFixed(4) + '°, ' + info.site_longitude_deg.toFixed(4) + '°, ' + info.site_elevation_m.toFixed(0) + 'm'
    : '–';
  document.getElementById('utc-date').textContent = info ? info.utc_date : '–';
  document.getElementById('sync-point-count').textContent = info && info.sync_point_count != null
    ? info.sync_point_count
    : (info ? 'not supported' : '–');
  const atParkEl = document.getElementById('at-park');
  atParkEl.textContent = info ? (info.at_park ? 'PARKED' : 'not parked') : '–';
  atParkEl.className = 'park-badge' + (info ? (info.at_park ? ' parked' : ' not-parked') : '');
  document.getElementById('correction-toggle').checked = !!s.correction_enabled;
  document.getElementById('correct-now-btn').disabled = !!s.correction_enabled;
};
function formatUptime(totalSeconds) {
  const s = Math.floor(totalSeconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  if (days > 0) return days + 'd ' + hours + 'h ' + minutes + 'm';
  if (hours > 0) return hours + 'h ' + minutes + 'm';
  if (minutes > 0) return minutes + 'm ' + seconds + 's';
  return seconds + 's';
}
async function post(url) {
  const r = await fetch(url, {method: 'POST'});
  const body = await r.json();
  document.getElementById('message').textContent = body.message || (body.ok ? 'OK' : 'failed');
}
function clearSyncPoints() {
  if (confirm('Clear all mount sync points? This cannot be undone.')) {
    post('/api/ui/actions/clear-sync-points');
  }
}
async function setCorrection(enabled) {
  const r = await fetch('/api/ui/actions/correction', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'enabled=' + enabled,
  });
  const body = await r.json();
  document.getElementById('message').textContent = body.message || (body.ok ? 'OK' : 'failed');
}
</script>
</body>
</html>
"""
