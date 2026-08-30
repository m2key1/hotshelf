import os

import pytest

from hotshelf.config import Config, DEFAULTS, _merge


def make(tmp_path, text=""):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return Config(str(path))


def test_defaults_fill_missing_keys(tmp_path):
    cfg = make(tmp_path, "budget:\n  size_gb: 42\n")
    assert cfg["budget"]["size_gb"] == 42
    assert cfg["budget"]["mode"] == DEFAULTS["budget"]["mode"]
    assert cfg["policy"]["resume"] == "recent"


def test_merge_does_not_mutate_defaults():
    _merge(DEFAULTS, {"budget": {"size_gb": 1}})
    assert DEFAULTS["budget"]["size_gb"] == 150


@pytest.mark.parametrize("text,message", [
    ("budget:\n  mode: bogus\n", "size or count"),
    ("policy:\n  resume: sometimes\n", "recent, always or off"),
    ("policy:\n  episodes_ahead: -1\n", "positive int"),
    ("mover:\n  verify: maybe\n", "checksum or size"),
])
def test_validation_rejects(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        make(tmp_path, text)


def test_save_rejects_invalid_and_keeps_file(tmp_path):
    cfg = make(tmp_path, "budget:\n  size_gb: 42\n")
    with pytest.raises(ValueError):
        cfg.save("budget:\n  mode: bogus\n")
    assert cfg["budget"]["size_gb"] == 42


def test_env_key_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HOTSHELF_JELLYFIN_KEY", "from-env")
    cfg = make(tmp_path, 'jellyfin:\n  api_key: "from-file"\n')
    assert cfg["jellyfin"]["api_key"] == "from-env"


def test_config_supports_get_like_a_mapping(tmp_path):
    cfg = make(tmp_path)
    assert cfg.get("library")["movies_dir"] == "movies"
    assert cfg.get("missing", 7) == 7


def test_move_window_validation(tmp_path):
    with pytest.raises(ValueError, match="HH:MM"):
        make(tmp_path, 'run:\n  move_window_start: "25:00"\n')
    cfg = make(tmp_path, 'run:\n  move_window_start: "23:30"\n')
    assert cfg["run"]["move_window_start"] == "23:30"
