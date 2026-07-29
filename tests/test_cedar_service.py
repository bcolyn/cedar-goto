"""cedar_service.cedar_systemctl() -- the web UI's Start/Stop cedar-server
actions. Mocks asyncio.create_subprocess_exec throughout: this must never
actually shell out to sudo/systemctl in a test run."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from cedar_goto.web.cedar_service import cedar_systemctl


class _FakeProcess:
    def __init__(self, returncode: int, output: bytes) -> None:
        self.returncode = returncode
        self._output = output
        self.killed = False

    async def communicate(self):
        return self._output, b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> None:
        pass


async def test_start_success():
    proc = _FakeProcess(returncode=0, output=b"")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        ok, message = await cedar_systemctl("start")
    assert ok is True
    assert message == "cedar-server started"
    args = mock_exec.call_args.args
    assert args == ("sudo", "systemctl", "start", "cedar")


async def test_stop_success():
    proc = _FakeProcess(returncode=0, output=b"")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        ok, message = await cedar_systemctl("stop")
    assert ok is True
    assert message == "cedar-server stopped"


async def test_failure_surfaces_process_output():
    proc = _FakeProcess(returncode=1, output=b"Failed to start cedar.service: Unit not found.")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        ok, message = await cedar_systemctl("start")
    assert ok is False
    assert "Unit not found" in message


async def test_no_sudo_password_configured_reports_cleanly():
    """The realistic failure mode when sudoers isn't set up for passwordless
    execution -- must surface as a clean ok:False, not hang or crash."""
    proc = _FakeProcess(returncode=1, output=b"sudo: a password is required")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        ok, message = await cedar_systemctl("start")
    assert ok is False
    assert "password is required" in message


async def test_timeout_kills_the_process_and_reports_cleanly():
    proc = _FakeProcess(returncode=None, output=b"")

    async def hang_forever():
        await asyncio.sleep(999)

    proc.communicate = hang_forever
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with patch("cedar_goto.web.cedar_service._TIMEOUT_S", 0.05):
            ok, message = await cedar_systemctl("stop")
    assert ok is False
    assert "timed out" in message
    assert proc.killed is True
