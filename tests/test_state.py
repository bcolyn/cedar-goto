"""state.py: persisting the web UI's auto-correction toggle across restarts
(separate from config.toml -- see __main__.py)."""
from __future__ import annotations

from cedar_goto.state import PersistedState, load_state, save_state


def test_load_state_falls_back_to_default_when_file_missing(tmp_path):
    path = tmp_path / "state.toml"
    assert load_state(path, default_correction_enabled=True).correction_enabled is True
    assert load_state(path, default_correction_enabled=False).correction_enabled is False


def test_load_state_falls_back_to_default_on_corrupt_file(tmp_path):
    path = tmp_path / "state.toml"
    path.write_text("not valid toml {{{")
    assert load_state(path, default_correction_enabled=False).correction_enabled is False


def test_save_then_load_roundtrips(tmp_path):
    path = tmp_path / "state.toml"
    save_state(path, PersistedState(correction_enabled=False))
    assert load_state(path, default_correction_enabled=True).correction_enabled is False

    save_state(path, PersistedState(correction_enabled=True))
    assert load_state(path, default_correction_enabled=False).correction_enabled is True


def test_save_state_does_not_leave_a_temp_file_behind(tmp_path):
    path = tmp_path / "state.toml"
    save_state(path, PersistedState(correction_enabled=True))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.toml"]
