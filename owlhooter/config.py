"""Configuration loading and validation for OwlHooter."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import time
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config.toml")


class ConfigError(Exception):
    """The configuration file is missing, malformed, or contains invalid values."""


@dataclass(frozen=True)
class Config:
    window_start: time
    window_end: time
    interval_min_s: int
    interval_max_s: int
    max_events_per_night: int
    silent_night_probability: float
    burst_probability: float
    burst_min_calls: int
    burst_max_calls: int
    burst_gap_min_s: float
    burst_gap_max_s: float
    volume_min: float
    volume_max: float
    alsa_device: str
    sounds_dir: Path
    no_repeat_memory: int


def _parse_time(value: object, field: str) -> time:
    try:
        hours, minutes = str(value).split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise ConfigError(f'{field}: expected a "HH:MM" time, got {value!r}') from exc


def load_config(path: Path) -> Config:
    """Read and validate a config file, raising ConfigError on any problem."""
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file is not valid TOML: {path}: {exc}") from exc

    schedule = raw.get("schedule", {})
    burst = raw.get("burst", {})
    audio = raw.get("audio", {})
    library = raw.get("library", {})

    try:
        config = Config(
            window_start=_parse_time(schedule.get("window_start", "21:00"), "schedule.window_start"),
            window_end=_parse_time(schedule.get("window_end", "06:00"), "schedule.window_end"),
            interval_min_s=int(schedule.get("interval_min_minutes", 10)) * 60,
            interval_max_s=int(schedule.get("interval_max_minutes", 30)) * 60,
            max_events_per_night=int(schedule.get("max_events_per_night", 25)),
            silent_night_probability=float(schedule.get("silent_night_probability", 0.15)),
            burst_probability=float(burst.get("probability", 0.30)),
            burst_min_calls=int(burst.get("min_calls", 2)),
            burst_max_calls=int(burst.get("max_calls", 3)),
            burst_gap_min_s=float(burst.get("gap_min_seconds", 2.0)),
            burst_gap_max_s=float(burst.get("gap_max_seconds", 6.0)),
            volume_min=float(audio.get("volume_min", 0.85)),
            volume_max=float(audio.get("volume_max", 1.0)),
            alsa_device=str(audio.get("alsa_device", "plughw:CARD=Device")),
            sounds_dir=Path(str(library.get("sounds_dir", "sounds"))),
            no_repeat_memory=int(library.get("no_repeat_memory", 5)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"config file contains a value of the wrong type: {exc}") from exc

    _validate(config)
    return config


def _validate(config: Config) -> None:
    if config.window_start == config.window_end:
        raise ConfigError("schedule.window_start and schedule.window_end must differ")
    if config.interval_min_s <= 0:
        raise ConfigError("schedule.interval_min_minutes must be greater than zero")
    if config.interval_min_s > config.interval_max_s:
        raise ConfigError(
            "schedule.interval_min_minutes must not exceed schedule.interval_max_minutes"
        )
    if config.max_events_per_night < 1:
        raise ConfigError("schedule.max_events_per_night must be at least 1")
    if not 0.0 <= config.silent_night_probability <= 1.0:
        raise ConfigError("schedule.silent_night_probability must be between 0.0 and 1.0")
    if not 0.0 <= config.burst_probability <= 1.0:
        raise ConfigError("burst.probability must be between 0.0 and 1.0")
    if config.burst_min_calls < 1:
        raise ConfigError("burst.min_calls must be at least 1")
    if config.burst_min_calls > config.burst_max_calls:
        raise ConfigError("burst.min_calls must not exceed burst.max_calls")
    if config.burst_gap_min_s < 0:
        raise ConfigError("burst.gap_min_seconds must not be negative")
    if config.burst_gap_min_s > config.burst_gap_max_s:
        raise ConfigError("burst.gap_min_seconds must not exceed burst.gap_max_seconds")
    if config.volume_min <= 0:
        raise ConfigError("audio.volume_min must be greater than zero")
    if config.volume_min > config.volume_max:
        raise ConfigError("audio.volume_min must not exceed audio.volume_max")
    # Deliberately no upper bound on volume_max: the sound must carry through a ceiling.
    if config.no_repeat_memory < 0:
        raise ConfigError("library.no_repeat_memory must be zero or greater")
