from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from owlhooter.config import Config, ConfigError, load_config

VALID_TOML = """
[schedule]
window_start = "21:00"
window_end = "06:00"
interval_min_minutes = 10
interval_max_minutes = 30
max_events_per_night = 25
silent_night_probability = 0.15

[burst]
probability = 0.3
min_calls = 2
max_calls = 3
gap_min_seconds = 2.0
gap_max_seconds = 6.0

[audio]
alsa_device = "plughw:CARD=Device"
volume_min = 0.85
volume_max = 1.0

[library]
sounds_dir = "sounds"
no_repeat_memory = 5
"""


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_a_valid_config(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_TOML))

    assert isinstance(config, Config)
    assert config.window_start == time(21, 0)
    assert config.window_end == time(6, 0)
    assert config.interval_min_s == 600
    assert config.interval_max_s == 1800
    assert config.max_events_per_night == 25
    assert config.burst_max_calls == 3
    assert config.volume_max == 1.0
    assert config.alsa_device == "plughw:CARD=Device"
    assert config.sounds_dir == Path("sounds")
    assert config.no_repeat_memory == 5


def test_minutes_are_converted_to_seconds(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_TOML))
    assert config.interval_min_s == 10 * 60
    assert config.interval_max_s == 30 * 60


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")


def test_malformed_toml_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="valid TOML"):
        load_config(write_config(tmp_path, "this is not toml ["))


def test_bad_time_format_raises_config_error(tmp_path: Path) -> None:
    text = VALID_TOML.replace('window_start = "21:00"', 'window_start = "9pm"')
    with pytest.raises(ConfigError, match="window_start"):
        load_config(write_config(tmp_path, text))


def test_interval_min_above_max_is_rejected(tmp_path: Path) -> None:
    text = VALID_TOML.replace("interval_min_minutes = 10", "interval_min_minutes = 40")
    with pytest.raises(ConfigError, match="interval_min_minutes"):
        load_config(write_config(tmp_path, text))


def test_identical_window_bounds_are_rejected(tmp_path: Path) -> None:
    text = VALID_TOML.replace('window_end = "06:00"', 'window_end = "21:00"')
    with pytest.raises(ConfigError, match="must differ"):
        load_config(write_config(tmp_path, text))


def test_probability_above_one_is_rejected(tmp_path: Path) -> None:
    text = VALID_TOML.replace("probability = 0.3", "probability = 1.4")
    with pytest.raises(ConfigError, match="burst.probability"):
        load_config(write_config(tmp_path, text))


def test_volume_min_above_max_is_rejected(tmp_path: Path) -> None:
    text = VALID_TOML.replace("volume_min = 0.85", "volume_min = 1.5")
    with pytest.raises(ConfigError, match="volume_min"):
        load_config(write_config(tmp_path, text))


def test_volume_max_above_one_is_allowed(tmp_path: Path) -> None:
    # Deliberate: the sound must penetrate a ceiling, so there is no upper cap.
    text = VALID_TOML.replace("volume_max = 1.0", "volume_max = 2.5")
    config = load_config(write_config(tmp_path, text))
    assert config.volume_max == 2.5


def test_zero_no_repeat_memory_is_allowed(tmp_path: Path) -> None:
    text = VALID_TOML.replace("no_repeat_memory = 5", "no_repeat_memory = 0")
    assert load_config(write_config(tmp_path, text)).no_repeat_memory == 0


def test_shipped_config_file_is_valid() -> None:
    config = load_config(Path("config.toml"))
    assert config.window_start == time(21, 0)
