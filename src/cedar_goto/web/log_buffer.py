"""In-memory ring buffer of recent log records, for the web UI's "show
server log" action -- lets Benny see what cedar-goto is actually doing
without shell/journalctl access, e.g. from a phone in the field (motivated
by the 2026-07-29 live-hardware session, where diagnosing a disconnected
mount driver needed manual out-of-band debugging).
"""
from __future__ import annotations

import logging
from collections import deque

_MAX_LINES = 200


class _RingBufferHandler(logging.Handler):
    def __init__(self, maxlen: int = _MAX_LINES) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


_handler = _RingBufferHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))


def install() -> None:
    """Attach the ring buffer to the root logger -- call once at startup
    (__main__.main(), alongside logging.basicConfig), so every log record
    already being emitted also lands here, not just on stderr/console."""
    logging.getLogger().addHandler(_handler)


def recent_lines() -> list[str]:
    return list(_handler.lines)
