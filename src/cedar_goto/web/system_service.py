"""Shuts down the host machine cedar-goto itself is running on (typically a
Raspberry Pi) via `sudo systemctl poweroff` -- for the web UI's Shutdown
button, so ending a session at the eyepiece doesn't need SSH or a physical
switch.

Requires the service user to have passwordless sudo for exactly this
invocation (sudoers), configured outside this codebase -- see the README's
"Shut down the host" section. Without that, this fails fast and reports it
(stdin is explicitly /dev/null so a misconfigured sudo can't hang the
request waiting on a TTY password prompt that will never come).
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15.0


async def shutdown_host() -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        "sudo", "systemctl", "poweroff",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("systemctl poweroff timed out after %ss", _TIMEOUT_S)
        return False, "systemctl poweroff timed out"

    output = stdout.decode(errors="replace").strip()
    if proc.returncode == 0:
        logger.info("systemctl poweroff succeeded")
        return True, "shutting down"
    logger.warning("systemctl poweroff failed (exit %s): %s", proc.returncode, output)
    return False, output or f"systemctl poweroff failed (exit {proc.returncode})"
