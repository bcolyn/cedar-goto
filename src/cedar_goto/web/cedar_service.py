"""Starts/stops cedar-server's systemd unit via `sudo systemctl` -- only
offered by the web UI when cedar-goto is running on the same host as
cedar-server (__main__._cedar_same_host()'s "localhost" in [cedar].address
check), since otherwise there's no local systemd unit to control.

Requires the service user to have passwordless sudo for exactly these two
invocations (sudoers), configured outside this codebase -- see the README's
"Start/stop cedar-server" section. Without that, this fails fast and
reports it (stdin is explicitly /dev/null so a misconfigured sudo can't
hang the request waiting on a TTY password prompt that will never come).
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_SERVICE_NAME = "cedar"
_TIMEOUT_S = 15.0
_PAST_TENSE = {"start": "started", "stop": "stopped"}


async def cedar_systemctl(action: str) -> tuple[bool, str]:
    """action is "start" or "stop". Returns (ok, message)."""
    proc = await asyncio.create_subprocess_exec(
        "sudo", "systemctl", action, _SERVICE_NAME,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("systemctl %s %s timed out after %ss", action, _SERVICE_NAME, _TIMEOUT_S)
        return False, f"systemctl {action} timed out"

    output = stdout.decode(errors="replace").strip()
    if proc.returncode == 0:
        logger.info("systemctl %s %s succeeded", action, _SERVICE_NAME)
        return True, f"cedar-server {_PAST_TENSE[action]}"
    logger.warning("systemctl %s %s failed (exit %s): %s", action, _SERVICE_NAME, proc.returncode, output)
    return False, output or f"systemctl {action} failed (exit {proc.returncode})"
