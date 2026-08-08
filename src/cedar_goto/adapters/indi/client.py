"""Shared low-level INDI client plumbing for the direct-INDI mount backend
(indi-refactor.md) -- both IndiMountClient and IndiTelescopeBackend share one
IndiConnection (see __main__._build_backend) rather than opening a second
socket to the same device.

Uses pyindi-client (PyPI, SWIG-wrapped INDI::BaseClient) -- spiked and
confirmed against the real mount 2026-07-22 (see indi-refactor.md). Its
declared `dbus-python` dependency has no prebuilt wheels anywhere and isn't
actually imported by the client at runtime; pyproject.toml's
tool.uv.dependency-metadata override strips it so a plain
`pip install cedar-goto[indi]` does the right thing.

PyIndi.BaseClient spawns its own background thread once connectServer()
succeeds, and delivers newDevice/newProperty/... callbacks from that thread.
Two consequences here:
  - Readiness waits (device/property not seen yet) are bridged to asyncio
    via call_soon_threadsafe onto an asyncio.Event.
  - Everything else -- reading a number/switch's current value -- goes
    straight through PyIndi's own already-thread-safe property cache
    (BaseDevice.getNumber/getSwitch), so no separate cache is kept here.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time

logger = logging.getLogger(__name__)

_TELESCOPE_PARK = "TELESCOPE_PARK"

# SkySafari's own request timeout is 3s, but its UI thread blocks on that
# wait (2026-08 field observation) -- anything the mount takes over ~1s to
# answer already reads as lag on the phone, well before SkySafari's timeout
# would fire and before this shows up as an error anywhere. Warn on it so a
# slow-but-succeeding INDI round-trip leaves a trace instead of nothing.
_SLOW_CALL_THRESHOLD_S = 1.0


def _log_slow_calls(fn):
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        start = time.monotonic()
        try:
            return await fn(self, *args, **kwargs)
        finally:
            elapsed = time.monotonic() - start
            if elapsed > _SLOW_CALL_THRESHOLD_S:
                logger.warning(
                    "IndiConnection.%s%r took %.2fs (device=%r)",
                    fn.__name__, args, elapsed, self._device_name,
                )
    return wrapper


class IndiConnectionError(Exception):
    pass


class IndiConnection:
    def __init__(self, host: str, port: int, device_name: str, timeout_s: float = 10.0) -> None:
        import PyIndi

        self._PyIndi = PyIndi
        self._device_name = device_name
        self._timeout_s = timeout_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._ready_events: dict[str, asyncio.Event] = {}
        self._connect_lock = asyncio.Lock()
        self._connected = False
        self._last_park_state: bool | None = None

        outer = self

        class _Client(PyIndi.BaseClient):
            def newDevice(self, d):
                outer._on_arrival("__device__", d.getDeviceName())

            def removeDevice(self, d):
                pass

            def newProperty(self, p):
                outer._on_arrival(p.getName(), p.getDeviceName())

            def updateProperty(self, p):
                outer._on_update(p.getDeviceName(), p.getName())

            def removeProperty(self, p):
                pass

            def newMessage(self, d, m):
                pass

            def serverConnected(self):
                pass

            def serverDisconnected(self, code):
                outer._connected = False

        self._client = _Client()
        self._client.setServer(host, port)

    def _on_arrival(self, key: str, device_name: str) -> None:
        if device_name != self._device_name:
            return
        event = self._event_for(key)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(event.set)

    def _on_update(self, device_name: str, prop_name: str) -> None:
        # Runs on PyIndi's own background thread (module docstring) --
        # logging is internally thread-safe, so no call_soon_threadsafe
        # needed here, unlike _on_arrival's asyncio.Event.
        if device_name != self._device_name or prop_name != _TELESCOPE_PARK:
            return
        widget = self._device().getSwitch(_TELESCOPE_PARK)
        if widget is None:
            return
        widget = widget.findWidgetByName("PARK")
        if widget is None:
            return
        parked = widget.getState() == self._PyIndi.ISS_ON
        if parked != self._last_park_state:
            logger.info("mount park state changed: %s", "parked" if parked else "unparked")
            self._last_park_state = parked

    def _event_for(self, key: str) -> asyncio.Event:
        with self._lock:
            event = self._ready_events.get(key)
            if event is None:
                event = self._ready_events[key] = asyncio.Event()
            return event

    @_log_slow_calls
    async def ensure_connected(self) -> None:
        """Idempotent -- safe to call at the top of every public method."""
        if self._connected:
            return
        async with self._connect_lock:
            if self._connected:
                return
            self._loop = asyncio.get_running_loop()
            ok = await asyncio.to_thread(self._client.connectServer)
            if not ok:
                raise IndiConnectionError(
                    f"could not connect to INDI server at "
                    f"{self._client.getHost()}:{self._client.getPort()}"
                )
            await self._wait_for("__device__", f"device {self._device_name!r} never appeared")
            self._connected = True

    async def is_device_connected(self) -> bool:
        """Whether the *driver* has connected to the mount hardware.

        Distinct from ensure_connected(), which only connects this client to
        indiserver. Found 2026-07-26: with the driver disconnected (mount
        powered off, or DEVICE_PORT naming a cable that isn't plugged in --
        the /dev/serial/by-id path changes with the cable), indiserver still
        publishes the device and ensure_connected() succeeds, but none of
        the properties that matter (TELESCOPE_PARK, EQUATORIAL_EOD_COORD,
        ON_COORD_SET) ever arrive. Every read then fails with a confusing
        "property never appeared" timeout instead of saying the mount isn't
        connected.
        """
        await self.ensure_connected()
        # ensure_connected() only waits for the device *name* to show up
        # (newDevice); its property definitions, CONNECTION among them,
        # stream in afterwards. Reading isConnected() before CONNECTION has
        # been parsed would report a connected mount as disconnected, so
        # wait for the property first rather than assume the ordering. A
        # CONNECTION that never arrives at all is a genuine "not usable".
        try:
            await self.wait_for_property("CONNECTION")
        except IndiConnectionError:
            return False
        device = self._device()
        return device.isValid() and device.isConnected()

    async def wait_for_property(self, name: str) -> None:
        await self.ensure_connected()
        device = self._client.getDevice(self._device_name)
        if device.isValid() and device.getProperty(name).isValid():
            return
        await self._wait_for(name, f"property {name!r} never appeared on {self._device_name!r}")

    async def _wait_for(self, key: str, timeout_message: str) -> None:
        event = self._event_for(key)
        try:
            await asyncio.wait_for(event.wait(), timeout=self._timeout_s)
        except asyncio.TimeoutError:
            raise IndiConnectionError(timeout_message) from None

    def _device(self):
        return self._client.getDevice(self._device_name)

    @_log_slow_calls
    async def get_numbers(self, prop: str) -> dict[str, float]:
        await self.wait_for_property(prop)
        vec = self._device().getNumber(prop)
        return {vec[i].getName(): vec[i].getValue() for i in range(len(vec))}

    @_log_slow_calls
    async def get_switch(self, prop: str, elem: str) -> bool:
        await self.wait_for_property(prop)
        widget = self._device().getSwitch(prop).findWidgetByName(elem)
        if widget is None:
            raise IndiConnectionError(f"{prop}.{elem} has no such element")
        return widget.getState() == self._PyIndi.ISS_ON

    @_log_slow_calls
    async def get_switch_selection(self, prop: str) -> str | None:
        """Name of the currently-On element of a one-of-many switch vector
        (e.g. TELESCOPE_SLEW_RATE), or None if none is On."""
        await self.wait_for_property(prop)
        vec = self._device().getSwitch(prop)
        for i in range(len(vec)):
            if vec[i].getState() == self._PyIndi.ISS_ON:
                return vec[i].getName()
        return None

    @_log_slow_calls
    async def is_property_busy(self, prop: str) -> bool:
        await self.wait_for_property(prop)
        return self._device().getPropertyState(prop) == self._PyIndi.IPS_BUSY

    @_log_slow_calls
    async def set_switch(self, prop: str, elem: str) -> None:
        """One-of-many switch vector: reset all elements, turn `elem` on, send.
        Also correct for single-element vectors (e.g. TELESCOPE_ABORT_MOTION)
        -- reset() on those is a harmless no-op."""
        await self.wait_for_property(prop)
        await asyncio.to_thread(self._set_switch_sync, prop, elem)

    def _set_switch_sync(self, prop: str, elem: str) -> None:
        vec = self._device().getSwitch(prop)
        widget = vec.findWidgetByName(elem)
        if widget is None:
            raise IndiConnectionError(f"{prop}.{elem} has no such element")
        vec.reset()
        widget.setState(self._PyIndi.ISS_ON)
        self._client.sendNewSwitch(vec)

    @_log_slow_calls
    async def clear_switch(self, prop: str) -> None:
        """Resets a one-of-many switch vector to all-off and sends it --
        used to stop a momentary jog (TELESCOPE_MOTION_NS/WE) without
        TELESCOPE_ABORT_MOTION's broader "stop everything" effect."""
        await self.wait_for_property(prop)
        await asyncio.to_thread(self._clear_switch_sync, prop)

    def _clear_switch_sync(self, prop: str) -> None:
        vec = self._device().getSwitch(prop)
        vec.reset()
        self._client.sendNewSwitch(vec)

    @_log_slow_calls
    async def wait_for_switch_confirmed(self, prop: str, elem: str, timeout_s: float = 3.0) -> None:
        """Poll until the driver's own echo confirms `elem` is On.

        Confirmed live against real hardware (indi-refactor.md): sending
        set_switch(ON_COORD_SET, ...) immediately followed by
        set_numbers(EQUATORIAL_EOD_COORD, ...) can race -- the number vector
        reaches the driver before it's finished processing the switch
        change, and gets interpreted under the *previous* ON_COORD_SET
        selection. Callers that chain a switch selection into a dependent
        write (slew/sync) must await this in between. Not folded into
        set_switch itself -- momentary switches (e.g.
        TELESCOPE_ABORT_MOTION) may not durably read back as On, so this is
        opt-in for the callers that actually need the confirmation."""
        widget = self._device().getSwitch(prop).findWidgetByName(elem)
        if widget is not None and widget.getState() == self._PyIndi.ISS_ON:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            await asyncio.sleep(0.05)
            widget = self._device().getSwitch(prop).findWidgetByName(elem)
            if widget is not None and widget.getState() == self._PyIndi.ISS_ON:
                return
            if loop.time() > deadline:
                raise IndiConnectionError(f"{prop}.{elem} was not confirmed On (timed out)")

    @_log_slow_calls
    async def set_numbers(self, prop: str, values: dict[str, float]) -> None:
        await self.wait_for_property(prop)
        await asyncio.to_thread(self._set_numbers_sync, prop, values)

    def _set_numbers_sync(self, prop: str, values: dict[str, float]) -> None:
        vec = self._device().getNumber(prop)
        for name, value in values.items():
            widget = vec.findWidgetByName(name)
            if widget is None:
                raise IndiConnectionError(f"{prop}.{name} has no such element")
            widget.setValue(value)
        self._client.sendNewNumber(vec)
