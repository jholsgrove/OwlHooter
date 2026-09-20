# OwlHooter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Raspberry Pi daemon that plays owl calls through a USB speaker at unpredictable intervals overnight, to deter mice in a roof space.

**Architecture:** A single long-running Python process managed by systemd. All timing and selection logic lives in `scheduler.py` as pure functions taking an injected clock and a seeded RNG, so it is testable instantly with no Pi and no waiting. `player.py` shells out to ffmpeg for playback. `main.py` wires them into a loop whose every dependency — clock, sleeper, player, RNG — is injectable.

**Tech Stack:** Python 3.11+ (standard library only at runtime: `tomllib`, `random`, `datetime`, `subprocess`, `logging`, `argparse`, `signal`, `threading`), ffmpeg for playback, ALSA for audio output, systemd for process management, pytest for tests (development only).

**Spec:** `docs/superpowers/specs/2026-09-20-owlhooter-design.md`

## Global Constraints

- **Runtime dependencies: Python standard library only.** No pip installs on the Pi. Pi OS Bookworm ships Python 3.11, which has `tomllib` built in.
- **Python 3.11+ syntax is fine** (`X | None` unions, `tomllib`). Include `from __future__ import annotations` in every module regardless.
- **pytest is a development dependency only.** Nothing under `owlhooter/` may import it.
- **No test may sleep, and no test may produce audio.** Every clock, sleeper, subprocess runner and player is injected. A test that calls `time.sleep` or spawns real ffmpeg is a defect.
- **No volume cap in code.** The speaker must drive sound through a plasterboard ceiling. `volume_max` is validated only against `volume_min`, never against an upper bound. This is deliberate — do not "fix" it.
- **The ALSA device is named, never indexed.** `plughw:CARD=Device`, not `hw:1`. Index order changes across reboots.
- **No audio clips are ever committed.** `sounds/` is gitignored apart from `.gitkeep` files.
- **Clip discovery is non-recursive.** `sounds/raw/` holds unprocessed downloads and must never be picked up as playable clips.
- **Timezone-naive local datetimes throughout.** The Pi runs in one place, in one timezone.

---

### Task 1: Project scaffolding and configuration

**Files:**
- Create: `owlhooter/__init__.py`
- Create: `owlhooter/config.py`
- Create: `config.toml`
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `owlhooter.config.Config` (frozen dataclass, fields listed below), `owlhooter.config.load_config(path: Path) -> Config`, `owlhooter.config.ConfigError`, `owlhooter.config.DEFAULT_CONFIG_PATH: Path`

`Config` fields, all read by later tasks:
`window_start: time`, `window_end: time`, `interval_min_s: int`, `interval_max_s: int`, `max_events_per_night: int`, `silent_night_probability: float`, `burst_probability: float`, `burst_min_calls: int`, `burst_max_calls: int`, `burst_gap_min_s: float`, `burst_gap_max_s: float`, `volume_min: float`, `volume_max: float`, `alsa_device: str`, `sounds_dir: Path`, `no_repeat_memory: int`

- [ ] **Step 1: Create the package and tooling files**

`owlhooter/__init__.py` and `tests/__init__.py` are both empty files.

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`requirements-dev.txt`:

```
pytest>=7.0
```

- [ ] **Step 2: Write `config.toml`**

```toml
# OwlHooter configuration.
# Times are local to the Pi. Restart the service after editing:
#   sudo systemctl restart owlhooter

[schedule]
window_start = "21:00"
window_end = "06:00"
interval_min_minutes = 10
interval_max_minutes = 30
# Safety valve against a runaway loop, not the governing constraint.
# A 9-hour window at a 20-minute mean interval yields roughly 27 events.
max_events_per_night = 25
# Chance of skipping an entire night, so there is no learnable pattern.
silent_night_probability = 0.15

[burst]
# Real owls call two or three times in sequence rather than once.
probability = 0.30
min_calls = 2
max_calls = 3
gap_min_seconds = 2.0
gap_max_seconds = 6.0

[audio]
# Find yours with: aplay -L | grep plughw
alsa_device = "plughw:CARD=Device"
# Digital gain applied by ffmpeg; 1.0 is unity. There is deliberately no cap,
# because the sound has to get through a ceiling. Above 1.0 will clip and
# distort - use alsamixer to find more level instead.
volume_min = 0.85
volume_max = 1.0

[library]
sounds_dir = "sounds"
no_repeat_memory = 5
```

- [ ] **Step 3: Write the failing tests**

`tests/test_config.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'owlhooter.config'`

- [ ] **Step 5: Write `owlhooter/config.py`**

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS, 12 tests

- [ ] **Step 7: Commit**

```bash
git add owlhooter/ tests/ config.toml pyproject.toml requirements-dev.txt
git commit -m "feat: add configuration loading and validation"
```

---

### Task 2: Scheduler — the active time window

**Files:**
- Create: `owlhooter/scheduler.py`
- Test: `tests/test_scheduler_window.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure module, imports only `datetime`)
- Produces:
  - `is_active(now: datetime, start: time, end: time) -> bool`
  - `night_key(now: datetime, start: time, end: time) -> date`
  - `seconds_until_window_opens(now: datetime, start: time) -> float`
  - `seconds_until_window_closes(now: datetime, end: time) -> float`

The midnight crossing is the whole difficulty here. A 21:00–06:00 window spans two calendar dates, so "which night is this?" is a distinct question from "what is today's date?". `night_key` answers it: everything from 21:00 Monday through 05:59 Tuesday belongs to night `Monday`. The daemon uses this to know when to reset the nightly budget.

- [ ] **Step 1: Write the failing tests**

`tests/test_scheduler_window.py`:

```python
from __future__ import annotations

from datetime import date, datetime, time

from owlhooter.scheduler import (
    is_active,
    night_key,
    seconds_until_window_closes,
    seconds_until_window_opens,
)

NIGHT_START = time(21, 0)
NIGHT_END = time(6, 0)
DAY_START = time(13, 0)
DAY_END = time(17, 0)


def test_active_in_the_evening_portion() -> None:
    assert is_active(datetime(2026, 9, 20, 22, 30), NIGHT_START, NIGHT_END) is True


def test_active_in_the_early_morning_portion() -> None:
    assert is_active(datetime(2026, 9, 21, 2, 0), NIGHT_START, NIGHT_END) is True


def test_active_exactly_at_window_start() -> None:
    assert is_active(datetime(2026, 9, 20, 21, 0), NIGHT_START, NIGHT_END) is True


def test_inactive_exactly_at_window_end() -> None:
    assert is_active(datetime(2026, 9, 21, 6, 0), NIGHT_START, NIGHT_END) is False


def test_inactive_during_the_day() -> None:
    assert is_active(datetime(2026, 9, 20, 14, 0), NIGHT_START, NIGHT_END) is False


def test_inactive_one_minute_before_the_window_opens() -> None:
    assert is_active(datetime(2026, 9, 20, 20, 59), NIGHT_START, NIGHT_END) is False


def test_non_crossing_window_is_supported() -> None:
    assert is_active(datetime(2026, 9, 20, 14, 0), DAY_START, DAY_END) is True
    assert is_active(datetime(2026, 9, 20, 18, 0), DAY_START, DAY_END) is False
    assert is_active(datetime(2026, 9, 20, 2, 0), DAY_START, DAY_END) is False


def test_night_key_in_the_evening_is_todays_date() -> None:
    assert night_key(datetime(2026, 9, 20, 23, 0), NIGHT_START, NIGHT_END) == date(2026, 9, 20)


def test_night_key_after_midnight_is_yesterdays_date() -> None:
    assert night_key(datetime(2026, 9, 21, 2, 0), NIGHT_START, NIGHT_END) == date(2026, 9, 20)


def test_night_key_is_stable_across_the_midnight_crossing() -> None:
    before = night_key(datetime(2026, 9, 20, 23, 59), NIGHT_START, NIGHT_END)
    after = night_key(datetime(2026, 9, 21, 0, 1), NIGHT_START, NIGHT_END)
    assert before == after == date(2026, 9, 20)


def test_night_key_across_a_month_boundary() -> None:
    assert night_key(datetime(2026, 10, 1, 3, 0), NIGHT_START, NIGHT_END) == date(2026, 9, 30)


def test_night_key_for_a_non_crossing_window_is_todays_date() -> None:
    assert night_key(datetime(2026, 9, 20, 14, 0), DAY_START, DAY_END) == date(2026, 9, 20)


def test_seconds_until_window_opens_later_today() -> None:
    now = datetime(2026, 9, 20, 20, 0)
    assert seconds_until_window_opens(now, NIGHT_START) == 3600.0


def test_seconds_until_window_opens_rolls_to_tomorrow() -> None:
    now = datetime(2026, 9, 21, 9, 0)
    assert seconds_until_window_opens(now, NIGHT_START) == 12 * 3600.0


def test_seconds_until_window_closes_after_midnight() -> None:
    now = datetime(2026, 9, 21, 5, 0)
    assert seconds_until_window_closes(now, NIGHT_END) == 3600.0


def test_seconds_until_window_closes_before_midnight() -> None:
    now = datetime(2026, 9, 20, 23, 0)
    assert seconds_until_window_closes(now, NIGHT_END) == 7 * 3600.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'owlhooter.scheduler'`

- [ ] **Step 3: Write `owlhooter/scheduler.py`**

```python
"""Pure scheduling logic.

Every function here takes its clock and its randomness as arguments and
performs no I/O, which is what makes the timing behaviour testable without a
Pi, a speaker, or any waiting around.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta


def is_active(now: datetime, start: time, end: time) -> bool:
    """Is `now` inside the active window? Handles windows crossing midnight."""
    current = now.time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def night_key(now: datetime, start: time, end: time) -> date:
    """The date a night belongs to.

    For a 21:00-06:00 window, everything from 21:00 Monday to 05:59 Tuesday is
    night `Monday`. The daemon keys its per-night budget on this, so the budget
    does not reset at midnight halfway through a night.
    """
    crosses_midnight = start > end
    if crosses_midnight and now.time() < end:
        return now.date() - timedelta(days=1)
    return now.date()


def _seconds_until(now: datetime, target: time) -> float:
    candidate = datetime.combine(now.date(), target)
    if candidate <= now:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()


def seconds_until_window_opens(now: datetime, start: time) -> float:
    return _seconds_until(now, start)


def seconds_until_window_closes(now: datetime, end: time) -> float:
    return _seconds_until(now, end)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler_window.py -v`
Expected: PASS, 16 tests

- [ ] **Step 5: Commit**

```bash
git add owlhooter/scheduler.py tests/test_scheduler_window.py
git commit -m "feat: add active-window and night-key scheduling logic"
```

---

### Task 3: Scheduler — randomised intervals, volume and bursts

**Files:**
- Modify: `owlhooter/scheduler.py` (append functions)
- Test: `tests/test_scheduler_random.py`

**Interfaces:**
- Consumes: `owlhooter/scheduler.py` from Task 2
- Produces:
  - `next_interval(rng: random.Random, min_s: float, max_s: float) -> float`
  - `pick_volume(rng: random.Random, min_v: float, max_v: float) -> float`
  - `burst_size(rng: random.Random, probability: float, min_calls: int, max_calls: int) -> int`
  - `burst_gap(rng: random.Random, min_s: float, max_s: float) -> float`
  - `is_silent_night(rng: random.Random, probability: float) -> bool`

`burst_size` returns `1` for an ordinary single call, or a number in `[min_calls, max_calls]` when the burst roll succeeds. Callers always treat the return value as "how many calls to play", so the single-call case needs no special handling downstream.

- [ ] **Step 1: Write the failing tests**

`tests/test_scheduler_random.py`:

```python
from __future__ import annotations

import random

from owlhooter.scheduler import (
    burst_gap,
    burst_size,
    is_silent_night,
    next_interval,
    pick_volume,
)


def test_interval_always_falls_within_bounds() -> None:
    rng = random.Random(1)
    for _ in range(1000):
        assert 600.0 <= next_interval(rng, 600.0, 1800.0) <= 1800.0


def test_interval_varies_between_calls() -> None:
    rng = random.Random(1)
    values = {next_interval(rng, 600.0, 1800.0) for _ in range(50)}
    assert len(values) > 40


def test_interval_with_equal_bounds_is_exact() -> None:
    assert next_interval(random.Random(1), 900.0, 900.0) == 900.0


def test_volume_always_falls_within_bounds() -> None:
    rng = random.Random(2)
    for _ in range(1000):
        assert 0.85 <= pick_volume(rng, 0.85, 1.0) <= 1.0


def test_volume_supports_gain_above_unity() -> None:
    rng = random.Random(2)
    for _ in range(100):
        assert 1.0 <= pick_volume(rng, 1.0, 2.0) <= 2.0


def test_burst_size_is_one_when_the_roll_fails() -> None:
    assert burst_size(random.Random(3), 0.0, 2, 3) == 1


def test_burst_size_is_in_range_when_the_roll_always_succeeds() -> None:
    rng = random.Random(3)
    for _ in range(200):
        assert burst_size(rng, 1.0, 2, 3) in (2, 3)


def test_burst_size_is_either_one_or_in_range() -> None:
    rng = random.Random(4)
    sizes = {burst_size(rng, 0.3, 2, 3) for _ in range(500)}
    assert sizes <= {1, 2, 3}
    assert 1 in sizes and (2 in sizes or 3 in sizes)


def test_burst_probability_is_roughly_honoured() -> None:
    rng = random.Random(5)
    bursts = sum(1 for _ in range(10000) if burst_size(rng, 0.3, 2, 3) > 1)
    assert 2700 <= bursts <= 3300


def test_burst_gap_falls_within_bounds() -> None:
    rng = random.Random(6)
    for _ in range(500):
        assert 2.0 <= burst_gap(rng, 2.0, 6.0) <= 6.0


def test_silent_night_never_fires_at_zero_probability() -> None:
    rng = random.Random(7)
    assert not any(is_silent_night(rng, 0.0) for _ in range(500))


def test_silent_night_always_fires_at_full_probability() -> None:
    rng = random.Random(7)
    assert all(is_silent_night(rng, 1.0) for _ in range(500))


def test_silent_night_probability_is_roughly_honoured() -> None:
    rng = random.Random(8)
    silent = sum(1 for _ in range(10000) if is_silent_night(rng, 0.15))
    assert 1300 <= silent <= 1700


def test_results_are_reproducible_for_a_given_seed() -> None:
    first = next_interval(random.Random(9), 600.0, 1800.0)
    second = next_interval(random.Random(9), 600.0, 1800.0)
    assert first == second
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler_random.py -v`
Expected: FAIL — `ImportError: cannot import name 'burst_gap' from 'owlhooter.scheduler'`

- [ ] **Step 3: Append the implementation to `owlhooter/scheduler.py`**

Add `import random` to the imports at the top of the file, then append:

```python
def next_interval(rng: random.Random, min_s: float, max_s: float) -> float:
    """Seconds to wait before the next hoot event."""
    return rng.uniform(min_s, max_s)


def pick_volume(rng: random.Random, min_v: float, max_v: float) -> float:
    """Digital gain for one call. Varying it varies the apparent distance."""
    return rng.uniform(min_v, max_v)


def burst_size(rng: random.Random, probability: float, min_calls: int, max_calls: int) -> int:
    """How many calls this hoot event contains: 1, or a burst of min..max."""
    if rng.random() >= probability:
        return 1
    return rng.randint(min_calls, max_calls)


def burst_gap(rng: random.Random, min_s: float, max_s: float) -> float:
    """Seconds of silence between two calls within one burst."""
    return rng.uniform(min_s, max_s)


def is_silent_night(rng: random.Random, probability: float) -> bool:
    """Should the whole night be skipped? Removes any night-to-night pattern."""
    return rng.random() < probability
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler_random.py -v`
Expected: PASS, 14 tests

- [ ] **Step 5: Commit**

```bash
git add owlhooter/scheduler.py tests/test_scheduler_random.py
git commit -m "feat: add randomised interval, volume and burst selection"
```

---

### Task 4: Scheduler — clip selection with no-repeat memory

**Files:**
- Modify: `owlhooter/scheduler.py` (append `pick_clip`)
- Test: `tests/test_scheduler_pick_clip.py`

**Interfaces:**
- Consumes: `owlhooter/scheduler.py` from Tasks 2–3
- Produces: `pick_clip(rng: random.Random, clips: Sequence[Path], recent: Sequence[Path]) -> Path`

`recent` is whatever the caller passes — the daemon passes a `collections.deque` with a `maxlen`. The awkward case is a library smaller than the memory: with three clips and a memory of five, every clip is eventually "recent" and a naive filter returns nothing. The fallback then excludes only the immediately previous clip, which preserves the one guarantee that actually matters — never the same call twice in a row.

- [ ] **Step 1: Write the failing tests**

`tests/test_scheduler_pick_clip.py`:

```python
from __future__ import annotations

import random
from collections import deque
from pathlib import Path

import pytest

from owlhooter.scheduler import pick_clip

CLIPS = [Path(f"sounds/tawny_{index}.wav") for index in range(8)]


def test_returns_a_clip_from_the_library() -> None:
    assert pick_clip(random.Random(1), CLIPS, []) in CLIPS


def test_never_returns_a_recent_clip() -> None:
    rng = random.Random(2)
    recent = deque(CLIPS[:5], maxlen=5)
    for _ in range(500):
        assert pick_clip(rng, CLIPS, recent) not in recent


def test_a_single_clip_library_returns_that_clip() -> None:
    only = [Path("sounds/only.wav")]
    assert pick_clip(random.Random(3), only, deque(only, maxlen=5)) == only[0]


def test_library_smaller_than_memory_still_avoids_immediate_repeats() -> None:
    small = CLIPS[:3]
    rng = random.Random(4)
    recent: deque[Path] = deque(maxlen=5)
    previous: Path | None = None
    for _ in range(200):
        chosen = pick_clip(rng, small, recent)
        assert chosen != previous
        recent.append(chosen)
        previous = chosen


def test_zero_length_memory_is_tolerated() -> None:
    rng = random.Random(5)
    recent: deque[Path] = deque(maxlen=0)
    for _ in range(100):
        recent.append(pick_clip(rng, CLIPS, recent))


def test_selection_spreads_across_the_library() -> None:
    rng = random.Random(6)
    recent: deque[Path] = deque(maxlen=5)
    seen = set()
    for _ in range(300):
        chosen = pick_clip(rng, CLIPS, recent)
        recent.append(chosen)
        seen.add(chosen)
    assert seen == set(CLIPS)


def test_empty_library_raises() -> None:
    with pytest.raises(ValueError, match="at least one clip"):
        pick_clip(random.Random(7), [], [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler_pick_clip.py -v`
Expected: FAIL — `ImportError: cannot import name 'pick_clip' from 'owlhooter.scheduler'`

- [ ] **Step 3: Append the implementation to `owlhooter/scheduler.py`**

Add `from pathlib import Path` and `from typing import Sequence` to the imports, then append:

```python
def pick_clip(rng: random.Random, clips: Sequence[Path], recent: Sequence[Path]) -> Path:
    """Choose a clip, avoiding anything in `recent`.

    If the library is smaller than the no-repeat memory, every clip eventually
    becomes recent. The fallback then excludes only the immediately previous
    clip, keeping the guarantee that matters: never the same call twice running.
    """
    if not clips:
        raise ValueError("pick_clip requires at least one clip")

    candidates = [clip for clip in clips if clip not in recent]
    if not candidates:
        previous = recent[-1] if recent else None
        candidates = [clip for clip in clips if clip != previous] or list(clips)
    return rng.choice(candidates)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler_pick_clip.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add owlhooter/scheduler.py tests/test_scheduler_pick_clip.py
git commit -m "feat: add clip selection with no-repeat memory"
```

---

### Task 5: Sound library discovery

**Files:**
- Create: `owlhooter/library.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `owlhooter.library.discover_clips(sounds_dir: Path) -> list[Path]`
  - `owlhooter.library.LibraryError`
  - `owlhooter.library.AUDIO_EXTENSIONS: frozenset[str]`

Discovery is **non-recursive** and this is load-bearing: `sounds/raw/` holds the unprocessed downloads that `tools/normalise.sh` consumes, and those must never be played directly.

- [ ] **Step 1: Write the failing tests**

`tests/test_library.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from owlhooter.library import LibraryError, discover_clips


def make_clip(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"not really audio")
    return path


def test_finds_audio_files(tmp_path: Path) -> None:
    make_clip(tmp_path, "tawny_a.wav")
    make_clip(tmp_path, "tawny_b.mp3")
    assert len(discover_clips(tmp_path)) == 2


def test_results_are_sorted_for_determinism(tmp_path: Path) -> None:
    make_clip(tmp_path, "c.wav")
    make_clip(tmp_path, "a.wav")
    make_clip(tmp_path, "b.wav")
    assert [p.name for p in discover_clips(tmp_path)] == ["a.wav", "b.wav", "c.wav"]


def test_ignores_non_audio_files(tmp_path: Path) -> None:
    make_clip(tmp_path, "tawny.wav")
    make_clip(tmp_path, "README.md")
    make_clip(tmp_path, ".gitkeep")
    assert [p.name for p in discover_clips(tmp_path)] == ["tawny.wav"]


def test_extension_matching_is_case_insensitive(tmp_path: Path) -> None:
    make_clip(tmp_path, "TAWNY.WAV")
    assert len(discover_clips(tmp_path)) == 1


def test_does_not_descend_into_the_raw_subdirectory(tmp_path: Path) -> None:
    make_clip(tmp_path, "processed.wav")
    make_clip(tmp_path / "raw", "original.mp3")
    assert [p.name for p in discover_clips(tmp_path)] == ["processed.wav"]


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(LibraryError, match="not found"):
        discover_clips(tmp_path / "absent")


def test_empty_directory_raises(tmp_path: Path) -> None:
    tmp_path.joinpath("empty").mkdir()
    with pytest.raises(LibraryError, match="no audio clips"):
        discover_clips(tmp_path / "empty")


def test_directory_with_only_non_audio_raises(tmp_path: Path) -> None:
    make_clip(tmp_path, "README.md")
    with pytest.raises(LibraryError, match="no audio clips"):
        discover_clips(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_library.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'owlhooter.library'`

- [ ] **Step 3: Write `owlhooter/library.py`**

```python
"""Discovery of the owl clip library on disk."""

from __future__ import annotations

from pathlib import Path

AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus"})


class LibraryError(Exception):
    """The sound library is missing or contains no usable clips."""


def discover_clips(sounds_dir: Path) -> list[Path]:
    """Return the playable clips in `sounds_dir`, sorted.

    Deliberately non-recursive: `sounds/raw/` holds unprocessed downloads for
    tools/normalise.sh and must never be played directly.
    """
    if not sounds_dir.is_dir():
        raise LibraryError(f"sounds directory not found: {sounds_dir}")

    clips = sorted(
        entry
        for entry in sounds_dir.iterdir()
        if entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not clips:
        raise LibraryError(
            f"no audio clips found in {sounds_dir}. "
            f"Add files with one of these extensions: {', '.join(sorted(AUDIO_EXTENSIONS))}"
        )
    return clips
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_library.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add owlhooter/library.py tests/test_library.py
git commit -m "feat: add sound library discovery"
```

---

### Task 6: Playback via ffmpeg

**Files:**
- Create: `owlhooter/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `owlhooter.player.build_command(clip: Path, volume: float, device: str) -> list[str]`
  - `owlhooter.player.Player(device: str, runner=subprocess.run)` with `play(clip: Path, volume: float) -> None`
  - `owlhooter.player.PlaybackError`
  - `owlhooter.player.ffmpeg_available(runner=subprocess.run) -> bool`
  - `owlhooter.player.device_available(device: str, runner=subprocess.run) -> bool`

`runner` has the signature of `subprocess.run` and must return an object with `returncode`, `stdout` and `stderr`. Injecting it is what lets every test here run without spawning a process or making a sound.

- [ ] **Step 1: Write the failing tests**

`tests/test_player.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from owlhooter.player import (
    PlaybackError,
    Player,
    build_command,
    device_available,
    ffmpeg_available,
)

APLAY_OUTPUT = """null
    Discard all samples (playback) or generate zero samples (capture)
default:CARD=Device
    USB Audio Device, USB Audio
    Default Audio Device
plughw:CARD=Device,DEV=0
    USB Audio Device, USB Audio
    Hardware device with all software conversions
"""


@dataclass
class FakeResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class FakeRunner:
    result: FakeResult = field(default_factory=FakeResult)
    raises: Exception | None = None
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if self.raises is not None:
            raise self.raises
        return self.result


def test_command_names_ffmpeg_and_the_clip() -> None:
    command = build_command(Path("sounds/tawny.wav"), 0.9, "plughw:CARD=Device")
    assert command[0] == "ffmpeg"
    assert "-i" in command
    assert command[command.index("-i") + 1] == str(Path("sounds/tawny.wav"))


def test_command_includes_the_volume_filter() -> None:
    command = build_command(Path("sounds/tawny.wav"), 0.9, "plughw:CARD=Device")
    assert command[command.index("-filter:a") + 1] == "volume=0.900"


def test_command_targets_the_alsa_device() -> None:
    command = build_command(Path("sounds/tawny.wav"), 1.0, "plughw:CARD=Device")
    assert command[command.index("-f") + 1] == "alsa"
    assert command[-1] == "plughw:CARD=Device"


def test_command_supports_gain_above_unity() -> None:
    command = build_command(Path("sounds/tawny.wav"), 1.75, "plughw:CARD=Device")
    assert command[command.index("-filter:a") + 1] == "volume=1.750"


def test_play_invokes_the_runner() -> None:
    runner = FakeRunner()
    Player("plughw:CARD=Device", runner=runner).play(Path("sounds/tawny.wav"), 0.9)
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "ffmpeg"


def test_play_raises_on_a_non_zero_exit() -> None:
    runner = FakeRunner(result=FakeResult(returncode=1, stderr="Device or resource busy"))
    with pytest.raises(PlaybackError, match="Device or resource busy"):
        Player("plughw:CARD=Device", runner=runner).play(Path("sounds/tawny.wav"), 0.9)


def test_play_raises_when_ffmpeg_is_missing() -> None:
    runner = FakeRunner(raises=FileNotFoundError("ffmpeg"))
    with pytest.raises(PlaybackError, match="ffmpeg"):
        Player("plughw:CARD=Device", runner=runner).play(Path("sounds/tawny.wav"), 0.9)


def test_ffmpeg_available_is_true_on_success() -> None:
    assert ffmpeg_available(runner=FakeRunner()) is True


def test_ffmpeg_available_is_false_when_not_installed() -> None:
    assert ffmpeg_available(runner=FakeRunner(raises=FileNotFoundError())) is False


def test_ffmpeg_available_is_false_on_a_non_zero_exit() -> None:
    assert ffmpeg_available(runner=FakeRunner(result=FakeResult(returncode=127))) is False


def test_device_available_finds_a_listed_device() -> None:
    runner = FakeRunner(result=FakeResult(stdout=APLAY_OUTPUT))
    assert device_available("plughw:CARD=Device", runner=runner) is True


def test_device_available_matches_by_prefix() -> None:
    runner = FakeRunner(result=FakeResult(stdout=APLAY_OUTPUT))
    assert device_available("default:CARD=Device", runner=runner) is True


def test_device_available_rejects_an_unlisted_device() -> None:
    runner = FakeRunner(result=FakeResult(stdout=APLAY_OUTPUT))
    assert device_available("plughw:CARD=Nonexistent", runner=runner) is False


def test_device_available_ignores_indented_description_lines() -> None:
    runner = FakeRunner(result=FakeResult(stdout=APLAY_OUTPUT))
    assert device_available("USB Audio Device", runner=runner) is False


def test_device_available_is_false_when_aplay_is_missing() -> None:
    runner = FakeRunner(raises=FileNotFoundError())
    assert device_available("plughw:CARD=Device", runner=runner) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_player.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'owlhooter.player'`

- [ ] **Step 3: Write `owlhooter/player.py`**

```python
"""Audio playback, delegated to ffmpeg.

ffmpeg is used rather than a Python audio library because it plays whatever
format lands in sounds/ without conversion, applies per-call gain as a filter
argument, and writes straight to a named ALSA device.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class PlaybackError(Exception):
    """A clip could not be played."""


def build_command(clip: Path, volume: float, device: str) -> list[str]:
    """The ffmpeg invocation that plays one clip at one gain to one device."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-i", str(clip),
        "-filter:a", f"volume={volume:.3f}",
        "-f", "alsa", device,
    ]


class Player:
    """Plays clips to a named ALSA device."""

    def __init__(self, device: str, runner=subprocess.run) -> None:
        self._device = device
        self._runner = runner

    def play(self, clip: Path, volume: float) -> None:
        """Play one clip, blocking until it finishes.

        Raises PlaybackError rather than exiting: the daemon logs a warning and
        carries on, so one corrupt file cannot take the deterrent down.
        """
        command = build_command(clip, volume, self._device)
        try:
            result = self._runner(command, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise PlaybackError(f"ffmpeg is not installed: {exc}") from exc
        if result.returncode != 0:
            raise PlaybackError(f"ffmpeg failed for {clip}: {result.stderr.strip()}")


def ffmpeg_available(runner=subprocess.run) -> bool:
    """Is ffmpeg installed and runnable? Checked once at startup."""
    try:
        result = runner(["ffmpeg", "-version"], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return result.returncode == 0


def device_available(device: str, runner=subprocess.run) -> bool:
    """Is `device` present in `aplay -L`? Checked once at startup.

    aplay lists PCM names flush to the left margin and indents their
    descriptions, so only unindented lines are candidate device names.
    """
    try:
        result = runner(["aplay", "-L"], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False

    names = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line[0].isspace()
    ]
    return any(name == device or name.startswith(device) for name in names)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_player.py -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Commit**

```bash
git add owlhooter/player.py tests/test_player.py
git commit -m "feat: add ffmpeg-based playback and startup availability checks"
```

---

### Task 7: The daemon loop

**Files:**
- Create: `owlhooter/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `owlhooter.config.Config`, all of `owlhooter.scheduler`, `owlhooter.player.PlaybackError`
- Produces:
  - `owlhooter.daemon.Daemon(config, player, clips, rng, clock, sleeper, log=None)` with `tick() -> str` and `run(stop=None) -> None`
  - `owlhooter.daemon.NightState` (dataclass: `key: date`, `events: int`, `silent: bool`)
  - `owlhooter.daemon.InterruptibleSleeper` with `__call__(seconds)`, `interrupt()`, `interrupted` property
  - `owlhooter.daemon.MAX_IDLE_SLEEP_S: float`

`tick()` performs exactly one decision and returns a label naming what it did — one of `"waiting_for_window"`, `"silent_night"`, `"cap_reached"`, `"window_closed"`, `"hooted"`. Returning a label is what makes the loop testable: a test drives ticks against a fake clock and asserts on the sequence, with no threads and no waiting.

Idle sleeps are capped at `MAX_IDLE_SLEEP_S` rather than sleeping until the window opens in one go, so that a SIGTERM is acted on within five minutes and so that a clock change (NTP correction, DST) is noticed promptly.

- [ ] **Step 1: Write the failing tests**

`tests/test_daemon.py`:

```python
from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path

from owlhooter.config import Config
from owlhooter.daemon import Daemon
from owlhooter.player import PlaybackError

CLIPS = [Path(f"sounds/tawny_{index}.wav") for index in range(8)]

BASE_CONFIG = Config(
    window_start=time(21, 0),
    window_end=time(6, 0),
    interval_min_s=600,
    interval_max_s=1800,
    max_events_per_night=25,
    silent_night_probability=0.0,
    burst_probability=0.0,
    burst_min_calls=2,
    burst_max_calls=3,
    burst_gap_min_s=2.0,
    burst_gap_max_s=6.0,
    volume_min=0.85,
    volume_max=1.0,
    alsa_device="plughw:CARD=Device",
    sounds_dir=Path("sounds"),
    no_repeat_memory=5,
)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSleeper:
    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        self._clock.advance(seconds)


class FakePlayer:
    def __init__(self, fail_on: Path | None = None) -> None:
        self.played: list[tuple[Path, float]] = []
        self._fail_on = fail_on

    def play(self, clip: Path, volume: float) -> None:
        if clip == self._fail_on:
            raise PlaybackError("simulated failure")
        self.played.append((clip, volume))


def build(config: Config, start: datetime, seed: int = 1, player: FakePlayer | None = None):
    clock = FakeClock(start)
    sleeper = FakeSleeper(clock)
    player = player or FakePlayer()
    daemon = Daemon(
        config=config,
        player=player,
        clips=CLIPS,
        rng=random.Random(seed),
        clock=clock,
        sleeper=sleeper,
    )
    return daemon, clock, sleeper, player


def test_waits_when_outside_the_window() -> None:
    daemon, _, sleeper, player = build(BASE_CONFIG, datetime(2026, 9, 20, 14, 0))
    assert daemon.tick() == "waiting_for_window"
    assert player.played == []
    assert sleeper.slept == [300.0]


def test_hoots_when_inside_the_window() -> None:
    daemon, _, _, player = build(BASE_CONFIG, datetime(2026, 9, 20, 22, 0))
    assert daemon.tick() == "hooted"
    assert len(player.played) == 1


def test_waits_a_configured_interval_before_hooting() -> None:
    daemon, _, sleeper, _ = build(BASE_CONFIG, datetime(2026, 9, 20, 22, 0))
    daemon.tick()
    assert 600.0 <= sleeper.slept[0] <= 1800.0


def test_volume_is_inside_the_configured_band() -> None:
    daemon, _, _, player = build(BASE_CONFIG, datetime(2026, 9, 20, 22, 0))
    for _ in range(10):
        daemon.tick()
    assert player.played
    assert all(0.85 <= volume <= 1.0 for _, volume in player.played)


def test_a_burst_plays_several_distinct_clips() -> None:
    config = replace(BASE_CONFIG, burst_probability=1.0, burst_min_calls=3, burst_max_calls=3)
    daemon, _, _, player = build(config, datetime(2026, 9, 20, 22, 0))
    assert daemon.tick() == "hooted"
    clips = [clip for clip, _ in player.played]
    assert len(clips) == 3
    assert len(set(clips)) == 3


def test_a_burst_counts_as_one_event_against_the_cap() -> None:
    config = replace(
        BASE_CONFIG,
        burst_probability=1.0,
        burst_min_calls=3,
        burst_max_calls=3,
        max_events_per_night=2,
    )
    daemon, _, _, player = build(config, datetime(2026, 9, 20, 21, 30))
    assert daemon.tick() == "hooted"
    assert daemon.tick() == "hooted"
    assert daemon.tick() == "cap_reached"
    assert len(player.played) == 6


def test_gaps_within_a_burst_are_configured() -> None:
    config = replace(BASE_CONFIG, burst_probability=1.0, burst_min_calls=2, burst_max_calls=2)
    daemon, _, sleeper, _ = build(config, datetime(2026, 9, 20, 22, 0))
    daemon.tick()
    assert len(sleeper.slept) == 2
    assert 2.0 <= sleeper.slept[1] <= 6.0


def test_a_silent_night_plays_nothing() -> None:
    config = replace(BASE_CONFIG, silent_night_probability=1.0)
    daemon, _, _, player = build(config, datetime(2026, 9, 20, 22, 0))
    for _ in range(20):
        assert daemon.tick() == "silent_night"
    assert player.played == []


def test_the_cap_stops_hooting_for_the_rest_of_the_night() -> None:
    config = replace(BASE_CONFIG, max_events_per_night=3)
    daemon, _, _, player = build(config, datetime(2026, 9, 20, 21, 30))
    actions = [daemon.tick() for _ in range(8)]
    assert actions[:3] == ["hooted", "hooted", "hooted"]
    assert set(actions[3:]) == {"cap_reached"}
    assert len(player.played) == 3


def test_the_cap_resets_on_the_following_night() -> None:
    config = replace(BASE_CONFIG, max_events_per_night=1)
    daemon, clock, _, player = build(config, datetime(2026, 9, 20, 21, 30))
    assert daemon.tick() == "hooted"
    assert daemon.tick() == "cap_reached"
    clock.now = datetime(2026, 9, 21, 21, 30)
    assert daemon.tick() == "hooted"
    assert len(player.played) == 2


def test_the_budget_does_not_reset_at_midnight() -> None:
    config = replace(BASE_CONFIG, max_events_per_night=1)
    daemon, clock, _, _ = build(config, datetime(2026, 9, 20, 23, 50))
    assert daemon.tick() == "hooted"
    clock.now = datetime(2026, 9, 21, 0, 30)
    assert daemon.tick() == "cap_reached"


def test_does_not_hoot_when_the_interval_runs_past_dawn() -> None:
    daemon, _, _, player = build(BASE_CONFIG, datetime(2026, 9, 21, 5, 55))
    assert daemon.tick() == "window_closed"
    assert player.played == []


def test_consecutive_hoots_never_repeat_a_clip() -> None:
    daemon, _, _, player = build(BASE_CONFIG, datetime(2026, 9, 20, 21, 5))
    for _ in range(12):
        daemon.tick()
    clips = [clip for clip, _ in player.played]
    assert all(first != second for first, second in zip(clips, clips[1:]))


def test_a_failing_clip_does_not_stop_the_loop() -> None:
    player = FakePlayer(fail_on=CLIPS[0])
    daemon, _, _, _ = build(BASE_CONFIG, datetime(2026, 9, 20, 21, 5), player=player)
    actions = [daemon.tick() for _ in range(10)]
    assert set(actions) == {"hooted"}


def test_run_stops_when_the_stop_callback_returns_true() -> None:
    daemon, _, _, player = build(BASE_CONFIG, datetime(2026, 9, 20, 22, 0))
    ticks = {"count": 0}

    def stop() -> bool:
        ticks["count"] += 1
        return ticks["count"] > 3

    daemon.run(stop=stop)
    assert len(player.played) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'owlhooter.daemon'`

- [ ] **Step 3: Write `owlhooter/daemon.py`**

```python
"""The hoot loop.

Every dependency - clock, sleeper, player, RNG - is injected, so the whole
loop can be driven through a simulated night in milliseconds.
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Sequence

from owlhooter import scheduler
from owlhooter.config import Config
from owlhooter.player import PlaybackError

# Idle sleeps are chunked so a SIGTERM is acted on promptly and a clock
# correction (NTP, DST) is noticed rather than slept through.
MAX_IDLE_SLEEP_S = 300.0


@dataclass
class NightState:
    key: date
    events: int
    silent: bool


class InterruptibleSleeper:
    """Production sleeper. A SIGTERM cuts the wait short instead of waiting it out."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def __call__(self, seconds: float) -> None:
        self._event.wait(seconds)

    def interrupt(self) -> None:
        self._event.set()

    @property
    def interrupted(self) -> bool:
        return self._event.is_set()


class Daemon:
    def __init__(
        self,
        config: Config,
        player,
        clips: Sequence[Path],
        rng: random.Random,
        clock: Callable[[], datetime],
        sleeper: Callable[[float], None],
        log: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._player = player
        self._clips = list(clips)
        self._rng = rng
        self._clock = clock
        self._sleeper = sleeper
        self._log = log or logging.getLogger("owlhooter")
        self._recent: deque[Path] = deque(maxlen=config.no_repeat_memory)
        self._night: NightState | None = None

    def tick(self) -> str:
        """Make exactly one decision. Returns a label naming what happened."""
        config = self._config
        now = self._clock()

        if not scheduler.is_active(now, config.window_start, config.window_end):
            self._night = None
            wait = scheduler.seconds_until_window_opens(now, config.window_start)
            self._sleeper(min(wait, MAX_IDLE_SLEEP_S))
            return "waiting_for_window"

        self._begin_night_if_needed(now)
        assert self._night is not None

        if self._night.silent:
            self._idle_until_window_closes(now)
            return "silent_night"

        if self._night.events >= config.max_events_per_night:
            self._idle_until_window_closes(now)
            return "cap_reached"

        self._sleeper(
            scheduler.next_interval(self._rng, config.interval_min_s, config.interval_max_s)
        )

        # The interval may have run past dawn.
        if not scheduler.is_active(self._clock(), config.window_start, config.window_end):
            return "window_closed"

        self._hoot()
        self._night.events += 1
        return "hooted"

    def run(self, stop: Callable[[], bool] | None = None) -> None:
        while stop is None or not stop():
            self.tick()

    def _begin_night_if_needed(self, now: datetime) -> None:
        config = self._config
        key = scheduler.night_key(now, config.window_start, config.window_end)
        if self._night is not None and self._night.key == key:
            return
        silent = scheduler.is_silent_night(self._rng, config.silent_night_probability)
        self._night = NightState(key=key, events=0, silent=silent)
        self._log.info("night of %s begins (silent=%s)", key, silent)

    def _idle_until_window_closes(self, now: datetime) -> None:
        remaining = scheduler.seconds_until_window_closes(now, self._config.window_end)
        self._sleeper(min(remaining, MAX_IDLE_SLEEP_S))

    def _hoot(self) -> None:
        config = self._config
        calls = scheduler.burst_size(
            self._rng, config.burst_probability, config.burst_min_calls, config.burst_max_calls
        )
        for index in range(calls):
            clip = scheduler.pick_clip(self._rng, self._clips, self._recent)
            volume = scheduler.pick_volume(self._rng, config.volume_min, config.volume_max)
            # Recorded before playing, so a broken clip is not retried immediately.
            self._recent.append(clip)
            self._log.info("call %d/%d: %s at gain %.2f", index + 1, calls, clip.name, volume)
            try:
                self._player.play(clip, volume)
            except PlaybackError as exc:
                self._log.warning("playback failed, continuing: %s", exc)
            if index < calls - 1:
                self._sleeper(
                    scheduler.burst_gap(self._rng, config.burst_gap_min_s, config.burst_gap_max_s)
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS, all tests from Tasks 1–7

- [ ] **Step 6: Commit**

```bash
git add owlhooter/daemon.py tests/test_daemon.py
git commit -m "feat: add the hoot loop with per-night budget and burst playback"
```

---

### Task 8: Entry point and CLI

**Files:**
- Create: `owlhooter/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `owlhooter.config.load_config`, `owlhooter.library.discover_clips`, `owlhooter.player.Player/ffmpeg_available/device_available`, `owlhooter.daemon.Daemon/InterruptibleSleeper`, `owlhooter.scheduler.pick_clip/pick_volume/seconds_until_window_closes`
- Produces:
  - `owlhooter.main.build_parser() -> argparse.ArgumentParser`
  - `owlhooter.main.simulate_night(config, clips, rng, start_at) -> list[tuple[datetime, Path, float]]`
  - `owlhooter.main.main(argv: list[str] | None = None) -> int`
  - Exit codes: `0` success, `2` config error, `3` ffmpeg missing, `4` library error, `5` audio device missing

CLI surface:

| Flag | Effect |
|---|---|
| `--config PATH` | Config file to read (default `config.toml`) |
| `--once` | Play a single call immediately, then exit. Commissioning check. |
| `--volume FLOAT` | Override the gain for `--once`. Ignored otherwise. |
| `--dry-run` | Print the schedule for one simulated night. Makes no sound and checks no hardware. |
| `--seed INT` | Seed the RNG, so `--dry-run` is reproducible. |

`--dry-run` deliberately skips the ffmpeg and device checks: its whole point is to let timing settings be sanity-checked on a laptop with no audio hardware.

- [ ] **Step 1: Write the failing tests**

`tests/test_main.py`:

```python
from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path

from owlhooter.config import Config
from owlhooter.main import build_parser, main, simulate_night

CLIPS = [Path(f"sounds/tawny_{index}.wav") for index in range(8)]

BASE_CONFIG = Config(
    window_start=time(21, 0),
    window_end=time(6, 0),
    interval_min_s=600,
    interval_max_s=1800,
    max_events_per_night=25,
    silent_night_probability=0.0,
    burst_probability=0.0,
    burst_min_calls=2,
    burst_max_calls=3,
    burst_gap_min_s=2.0,
    burst_gap_max_s=6.0,
    volume_min=0.85,
    volume_max=1.0,
    alsa_device="plughw:CARD=Device",
    sounds_dir=Path("sounds"),
    no_repeat_memory=5,
)

VALID_TOML = """
[schedule]
window_start = "21:00"
window_end = "06:00"
interval_min_minutes = 10
interval_max_minutes = 30
max_events_per_night = 25
silent_night_probability = 0.0

[burst]
probability = 0.0
min_calls = 2
max_calls = 3
gap_min_seconds = 2.0
gap_max_seconds = 6.0

[audio]
alsa_device = "plughw:CARD=Device"
volume_min = 0.85
volume_max = 1.0

[library]
sounds_dir = "SOUNDS_DIR"
no_repeat_memory = 5
"""


def make_project(tmp_path: Path, toml: str = VALID_TOML) -> Path:
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    for index in range(4):
        (sounds / f"tawny_{index}.wav").write_bytes(b"not really audio")
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml.replace("SOUNDS_DIR", sounds.as_posix()), encoding="utf-8")
    return config_path


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.config == Path("config.toml")
    assert args.once is False
    assert args.dry_run is False
    assert args.volume is None
    assert args.seed is None


def test_parser_accepts_all_flags() -> None:
    args = build_parser().parse_args(
        ["--config", "other.toml", "--once", "--volume", "1.5", "--seed", "7"]
    )
    assert args.config == Path("other.toml")
    assert args.once is True
    assert args.volume == 1.5
    assert args.seed == 7


def test_simulate_night_produces_events_across_the_window() -> None:
    events = simulate_night(BASE_CONFIG, CLIPS, random.Random(1), datetime(2026, 9, 20, 21, 0))
    assert len(events) > 15
    assert all(when.hour >= 21 or when.hour < 6 for when, _, _ in events)


def test_simulate_night_respects_the_cap() -> None:
    config = replace(BASE_CONFIG, max_events_per_night=5)
    events = simulate_night(config, CLIPS, random.Random(1), datetime(2026, 9, 20, 21, 0))
    assert len(events) == 5


def test_simulate_night_is_empty_on_a_silent_night() -> None:
    config = replace(BASE_CONFIG, silent_night_probability=1.0)
    events = simulate_night(config, CLIPS, random.Random(1), datetime(2026, 9, 20, 21, 0))
    assert events == []


def test_simulate_night_is_reproducible_for_a_seed() -> None:
    first = simulate_night(BASE_CONFIG, CLIPS, random.Random(42), datetime(2026, 9, 20, 21, 0))
    second = simulate_night(BASE_CONFIG, CLIPS, random.Random(42), datetime(2026, 9, 20, 21, 0))
    assert first == second


def test_dry_run_prints_a_schedule_and_exits_zero(tmp_path: Path, capsys) -> None:
    config_path = make_project(tmp_path)
    assert main(["--config", str(config_path), "--dry-run", "--seed", "1"]) == 0
    output = capsys.readouterr().out
    assert "tawny_" in output
    assert "call" in output.lower()


def test_dry_run_needs_no_audio_hardware(tmp_path: Path) -> None:
    # No ffmpeg or ALSA device is checked, so this passes on any machine.
    config_path = make_project(tmp_path)
    assert main(["--config", str(config_path), "--dry-run", "--seed", "1"]) == 0


def test_missing_config_exits_two(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(tmp_path / "absent.toml"), "--dry-run"]) == 2
    assert "config" in capsys.readouterr().err.lower()


def test_empty_sounds_directory_exits_four(tmp_path: Path, capsys) -> None:
    config_path = make_project(tmp_path)
    for clip in (tmp_path / "sounds").iterdir():
        clip.unlink()
    assert main(["--config", str(config_path), "--dry-run"]) == 4
    assert "no audio clips" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'owlhooter.main'`

- [ ] **Step 3: Write `owlhooter/main.py`**

```python
"""Command-line entry point and startup checks."""

from __future__ import annotations

import argparse
import logging
import random
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from owlhooter import scheduler
from owlhooter.config import DEFAULT_CONFIG_PATH, Config, ConfigError, load_config
from owlhooter.daemon import Daemon, InterruptibleSleeper
from owlhooter.library import LibraryError, discover_clips
from owlhooter.player import Player, device_available, ffmpeg_available

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_NO_FFMPEG = 3
EXIT_LIBRARY_ERROR = 4
EXIT_NO_DEVICE = 5

log = logging.getLogger("owlhooter")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="owlhooter",
        description="Play owl calls at random intervals to deter mice.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="config file (default: config.toml)",
    )
    parser.add_argument(
        "--once", action="store_true", help="play one call immediately and exit"
    )
    parser.add_argument("--volume", type=float, default=None, help="gain override for --once")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print one simulated night's schedule, make no sound",
    )
    parser.add_argument("--seed", type=int, default=None, help="seed the RNG for reproducibility")
    return parser


class _SimClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _SimSleeper:
    def __init__(self, clock: _SimClock) -> None:
        self._clock = clock

    def __call__(self, seconds: float) -> None:
        self._clock.advance(seconds)


class _RecordingPlayer:
    def __init__(self, clock: _SimClock, events: list) -> None:
        self._clock = clock
        self._events = events

    def play(self, clip: Path, volume: float) -> None:
        self._events.append((self._clock(), clip, volume))


def simulate_night(
    config: Config, clips: Sequence[Path], rng: random.Random, start_at: datetime
) -> list[tuple[datetime, Path, float]]:
    """Run one night at simulated speed and return every call it would play."""
    clock = _SimClock(start_at)
    sleeper = _SimSleeper(clock)
    events: list[tuple[datetime, Path, float]] = []
    daemon = Daemon(
        config=config,
        player=_RecordingPlayer(clock, events),
        clips=clips,
        rng=rng,
        clock=clock,
        sleeper=sleeper,
        log=logging.getLogger("owlhooter.dryrun"),
    )
    deadline = start_at + timedelta(
        seconds=scheduler.seconds_until_window_closes(start_at, config.window_end)
    )
    while clock() < deadline:
        if daemon.tick() in {"window_closed", "waiting_for_window"}:
            break
    return events


def _run_dry_run(config: Config, clips: list[Path], seed: int | None) -> int:
    rng = random.Random(seed)
    tonight = datetime.combine(datetime.now().date(), config.window_start)
    events = simulate_night(config, clips, rng, tonight)

    if not events:
        print("Silent night - no calls scheduled.")
        return EXIT_OK

    print(f"{len(events)} call(s) across the night of {tonight.date()}:")
    for when, clip, volume in events:
        print(f"  {when:%H:%M:%S}  {clip.name:<32} gain {volume:.2f}")
    return EXIT_OK


def _run_once(config: Config, clips: list[Path], seed: int | None, volume: float | None) -> int:
    rng = random.Random(seed)
    clip = scheduler.pick_clip(rng, clips, [])
    gain = (
        volume
        if volume is not None
        else scheduler.pick_volume(rng, config.volume_min, config.volume_max)
    )
    log.info("playing %s at gain %.2f on %s", clip.name, gain, config.alsa_device)
    Player(config.alsa_device).play(clip, gain)
    return EXIT_OK


def _run_daemon(config: Config, clips: list[Path], seed: int | None) -> int:
    sleeper = InterruptibleSleeper()

    def handle_signal(signum, _frame) -> None:
        log.info("signal %d received, shutting down", signum)
        sleeper.interrupt()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    daemon = Daemon(
        config=config,
        player=Player(config.alsa_device),
        clips=clips,
        rng=random.Random(seed),
        clock=datetime.now,
        sleeper=sleeper,
        log=log,
    )
    log.info(
        "started: %d clip(s), window %s-%s, device %s",
        len(clips),
        config.window_start.strftime("%H:%M"),
        config.window_end.strftime("%H:%M"),
        config.alsa_device,
    )
    daemon.run(stop=lambda: sleeper.interrupted)
    log.info("stopped")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    try:
        clips = discover_clips(config.sounds_dir)
    except LibraryError as exc:
        print(f"library error: {exc}", file=sys.stderr)
        return EXIT_LIBRARY_ERROR

    if args.dry_run:
        # No audio is produced, so no hardware is checked.
        return _run_dry_run(config, clips, args.seed)

    if not ffmpeg_available():
        print("ffmpeg is not installed. Run: sudo apt install ffmpeg", file=sys.stderr)
        return EXIT_NO_FFMPEG

    if not device_available(config.alsa_device):
        print(
            f"audio device {config.alsa_device!r} not found. "
            "List available devices with: aplay -L",
            file=sys.stderr,
        )
        return EXIT_NO_DEVICE

    if args.once:
        return _run_once(config, clips, args.seed, args.volume)
    return _run_daemon(config, clips, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS, all tests

- [ ] **Step 6: Verify the dry run works end to end**

Create a few dummy clips and run it for real:

```bash
mkdir -p sounds && touch sounds/tawny_a.wav sounds/tawny_b.wav sounds/tawny_c.wav
python -m owlhooter.main --dry-run --seed 1
```

Expected: a printed list of times, clip names and gains spanning 21:00 to about 06:00, or `Silent night - no calls scheduled.`

Then remove the dummy files: `rm sounds/tawny_*.wav`

- [ ] **Step 7: Commit**

```bash
git add owlhooter/main.py tests/test_main.py
git commit -m "feat: add CLI entry point with --once and --dry-run"
```

---

### Task 9: Deployment, ingest tooling and documentation

**Files:**
- Create: `deploy/owlhooter.service`
- Create: `tools/normalise.sh`
- Create: `sounds/.gitkeep`
- Create: `sounds/raw/.gitkeep`
- Create: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `python -m owlhooter.main` from Task 8
- Produces: no code interfaces — deployment artefacts and documentation

- [ ] **Step 1: Update `.gitignore` and add the keep files**

Replace `.gitignore` with:

```
sounds/*
!sounds/.gitkeep
!sounds/raw/
sounds/raw/*
!sounds/raw/.gitkeep
__pycache__/
*.pyc
.venv/
.pytest_cache/
```

Then: `mkdir -p sounds/raw && touch sounds/.gitkeep sounds/raw/.gitkeep`

- [ ] **Step 2: Write `tools/normalise.sh`**

```bash
#!/usr/bin/env bash
# Normalise downloaded owl recordings into playable clips.
#
# Drop whatever you downloaded into sounds/raw/ in any format, then run this.
# Output is mono 44.1 kHz WAV at a consistent loudness, written to sounds/.
# Consistent loudness matters because the daemon applies a random gain on top:
# without it, a quiet recording and a loud one behave completely differently.

set -euo pipefail

RAW_DIR="${1:-sounds/raw}"
OUT_DIR="${2:-sounds}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is not installed. Run: sudo apt install ffmpeg" >&2
  exit 1
fi

if [ ! -d "$RAW_DIR" ]; then
  echo "No raw directory at $RAW_DIR" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

shopt -s nullglob nocaseglob
count=0
for source in "$RAW_DIR"/*.{wav,mp3,ogg,flac,m4a,aac,opus}; do
  name="$(basename "${source%.*}")"
  target="$OUT_DIR/${name}.wav"
  echo "normalising $(basename "$source") -> $(basename "$target")"
  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "$source" \
    -filter:a "loudnorm=I=-16:TP=-1.5:LRA=11" \
    -ar 44100 -ac 1 \
    "$target"
  count=$((count + 1))
done
shopt -u nullglob nocaseglob

if [ "$count" -eq 0 ]; then
  echo "No audio files found in $RAW_DIR" >&2
  exit 1
fi

echo "normalised $count clip(s) into $OUT_DIR"
```

Then: `chmod +x tools/normalise.sh`

- [ ] **Step 3: Write `deploy/owlhooter.service`**

```ini
[Unit]
Description=OwlHooter mouse deterrent
After=sound.target network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/OwlHooter
ExecStart=/usr/bin/python3 -m owlhooter.main --config /home/pi/OwlHooter/config.toml
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Write `README.md`**

````markdown
# OwlHooter

A Raspberry Pi mouse deterrent. It plays owl calls through a speaker at unpredictable
intervals overnight, exploiting the fear response mice have to their main natural predator.

Mice habituate to predictable noise within days, so nothing here is predictable: the
interval, the clip, the volume, the number of calls in a burst and whether a given night
happens at all are all randomised.

This is one layer of control. It works alongside sealing entry points, not instead of it.

## Hardware

- A Raspberry Pi running Pi OS Bookworm or later (Python 3.11+).
- A USB speaker or USB sound card. Nothing else is needed.

## Where to put the speaker

The mice are above a plasterboard ceiling and the speaker is below it, so most of the
useful gain is physical rather than digital:

- **Height beats volume.** On top of a cupboard or a shelf, as close to the ceiling as
  possible. Halving the distance is worth more than any software setting.
- **Find the gaps.** A loft hatch, downlighter cut-out or pipe penetration passes sound far
  better than sealed plasterboard. Aim at one if there is one.
- **Low frequencies get through; high ones do not.** See the next section.

## Getting owl sounds

Download from [xeno-canto.org](https://xeno-canto.org) — thousands of Creative Commons
recordings, filterable by species and quality grade. Grab a couple of dozen; variety is what
keeps the deterrent working.

**Favour tawny and long-eared owl over barn owl.** This is acoustics, not preference: a tawny
owl's low hoot (roughly 500-900 Hz) passes through a ceiling, while a barn owl's high screech
is largely reflected by it.

Then normalise them:

```bash
# put the downloads in sounds/raw/ first
./tools/normalise.sh
```

This converts everything to consistent-loudness mono WAV in `sounds/`. The daemon reads
`sounds/` only, never `sounds/raw/`.

## Install

```bash
sudo apt update
sudo apt install -y ffmpeg
git clone <your-repo-url> /home/pi/OwlHooter
cd /home/pi/OwlHooter
```

Find your audio device and put it in `config.toml`:

```bash
aplay -L | grep plughw
```

Turn the output up — the digital gain in `config.toml` is unity at `1.0`, so the real
loudness comes from here and from the speaker's own control:

```bash
alsamixer    # F6 to pick the USB card, arrow up, Esc
sudo alsactl store
```

Check it works before installing the service:

```bash
python3 -m owlhooter.main --once
```

Then install the service:

```bash
sudo cp deploy/owlhooter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now owlhooter
```

## Operating it

```bash
systemctl status owlhooter          # is it running
journalctl -u owlhooter -f          # watch it live
journalctl -u owlhooter --since yesterday | grep call    # what it played overnight
sudo systemctl restart owlhooter    # after editing config.toml
```

Two flags help without waiting for nightfall:

```bash
python3 -m owlhooter.main --once              # play one clip now
python3 -m owlhooter.main --once --volume 1.0 # ...at a specific gain
python3 -m owlhooter.main --dry-run           # print tonight's schedule, make no sound
```

## Configuration

Everything lives in `config.toml`, which is commented. The settings you are most likely to
change:

| Setting | Default | Notes |
|---|---|---|
| `window_start` / `window_end` | 21:00 / 06:00 | May cross midnight |
| `interval_min_minutes` / `interval_max_minutes` | 10 / 30 | Gap between hoot events |
| `max_events_per_night` | 25 | Safety valve, not the main control — widen the interval instead if it is too frequent |
| `volume_min` / `volume_max` | 0.85 / 1.0 | ffmpeg gain; 1.0 is unity. No cap, but above 1.0 clips and distorts |
| `silent_night_probability` | 0.15 | Chance of skipping a whole night |
| `probability` (burst) | 0.30 | Chance an event is 2-3 calls rather than one |

## Troubleshooting

| Symptom | Cause |
|---|---|
| Exits with code 2 | Config file missing or invalid — the message says which setting |
| Exits with code 3 | ffmpeg not installed: `sudo apt install ffmpeg` |
| Exits with code 4 | No clips in `sounds/` — download some and run `tools/normalise.sh` |
| Exits with code 5 | `alsa_device` does not match anything in `aplay -L` |
| Runs but is silent | Check the window in `config.toml`, then `alsamixer` levels, then `--once` |
| Too quiet through the ceiling | Raise the speaker; use tawny not barn owl clips; raise `alsamixer`, not `volume_max` |
| Played the same clip twice running | Only possible with fewer than two clips in `sounds/` |

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

The whole test suite runs on any machine — no Pi, no speaker, no waiting. Every clock,
sleeper, subprocess runner and player is injected. Tests never sleep and never make a sound.

- `owlhooter/scheduler.py` — pure timing and selection logic; where the interesting tests are
- `owlhooter/library.py` — clip discovery
- `owlhooter/player.py` — ffmpeg invocation
- `owlhooter/daemon.py` — the loop
- `owlhooter/main.py` — CLI and startup checks

Design notes are in `docs/superpowers/specs/2026-09-20-owlhooter-design.md`.
````

- [ ] **Step 5: Verify the shell script is syntactically valid**

Run: `bash -n tools/normalise.sh`
Expected: no output, exit 0

- [ ] **Step 6: Run the whole suite one final time**

Run: `python -m pytest -v`
Expected: PASS, all tests

- [ ] **Step 7: Commit**

```bash
git add .gitignore README.md deploy/ tools/ sounds/.gitkeep sounds/raw/.gitkeep
git commit -m "feat: add systemd unit, ingest tooling and documentation"
```

---

## Deviations from the spec

Two structural changes, both made to give a unit its own test cycle:

1. **`config.py` is a separate module.** The spec put config loading in `main.py`. Validation has enough distinct failure modes to deserve its own tests, and keeping it out of `main.py` means those tests need no CLI.
2. **`daemon.py` is a separate module from `main.py`.** The spec described one `main.py` holding both the loop and the entry point. Splitting them lets the loop be tested with injected fakes while `main.py` keeps the argument parsing, logging setup and signal handling that tests should not have to construct.

Everything else follows the spec as written.
