"""Persists select runtime UI state (currently just the auto-correction
toggle, DESIGN.md §8) across restarts -- deliberately a separate file from
config.toml, not a rewrite of it: install.sh already promises config.toml
is never touched by an upgrade (README.md "Deployment"), and this file
needs that same guarantee plus one config.toml doesn't need -- being
written at runtime, from the web UI, not just read at startup.
"""
from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PersistedState(BaseModel):
    correction_enabled: bool = True


def load_state(path: Path, default_correction_enabled: bool) -> PersistedState:
    """default_correction_enabled backstops a state file that doesn't exist
    yet (fresh install) or fails to parse -- config.toml's
    [loop].correction_enabled, so that setting still means something before
    the toggle has ever been flipped from the web UI."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return PersistedState(correction_enabled=default_correction_enabled)
    except Exception:
        logger.warning("failed to read persisted state at %s, using config default", path, exc_info=True)
        return PersistedState(correction_enabled=default_correction_enabled)
    return PersistedState.model_validate(data)


def save_state(path: Path, state: PersistedState) -> None:
    # Atomic write (temp file + os.replace) -- this runs on a Pi that may
    # lose power mid-write with no graceful shutdown (dark-site field use,
    # no UPS), and a torn write here must not corrupt the file for the next
    # boot.
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(f"correction_enabled = {'true' if state.correction_enabled else 'false'}\n")
    os.replace(tmp_path, path)
