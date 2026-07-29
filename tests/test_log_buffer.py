"""log_buffer's ring buffer -- the web UI's "show server log" action."""
from __future__ import annotations

import logging

from cedar_goto.web import log_buffer


def _fresh_handler(maxlen: int = 200) -> log_buffer._RingBufferHandler:
    handler = log_buffer._RingBufferHandler(maxlen=maxlen)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    return handler


def test_emit_appends_formatted_lines():
    handler = _fresh_handler()
    logger = logging.getLogger("test_log_buffer.emit")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info("hello %s", "world")
    finally:
        logger.removeHandler(handler)
    assert list(handler.lines) == ["INFO hello world"]


def test_ring_buffer_drops_oldest_once_full():
    handler = _fresh_handler(maxlen=3)
    logger = logging.getLogger("test_log_buffer.ring")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        for i in range(5):
            logger.info("line %d", i)
    finally:
        logger.removeHandler(handler)
    assert list(handler.lines) == ["INFO line 2", "INFO line 3", "INFO line 4"]


def test_install_attaches_to_the_root_logger_and_recent_lines_reflects_it():
    root = logging.getLogger()
    before = len(root.handlers)
    log_buffer.install()
    try:
        assert len(root.handlers) == before + 1
        marker_logger = logging.getLogger("test_log_buffer.install")
        marker_logger.setLevel(logging.INFO)
        marker_logger.info("marker line for recent_lines test")
        assert any("marker line for recent_lines test" in line for line in log_buffer.recent_lines())
    finally:
        root.removeHandler(log_buffer._handler)
