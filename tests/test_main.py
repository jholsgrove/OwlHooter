from __future__ import annotations

import random
import re
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
    # The table itself, not just any line mentioning a clip: a simulated
    # HH:MM:SS timestamp, a clip name, and a gain reading.
    assert re.search(r"\d{2}:\d{2}:\d{2}\s+tawny_\d+\.wav\s+gain \d\.\d{2}", output)
    # No log line - of any level - may leak into a dry-run's stdout: that
    # would be a real wall-clock timestamp sitting above a simulated one.
    assert "INFO" not in output


def test_dry_run_needs_no_audio_hardware(tmp_path: Path, monkeypatch) -> None:
    config_path = make_project(tmp_path)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("hardware check should not be called during --dry-run")

    monkeypatch.setattr("owlhooter.main.ffmpeg_available", _must_not_be_called)
    monkeypatch.setattr("owlhooter.main.device_available", _must_not_be_called)
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


def test_missing_ffmpeg_exits_three(tmp_path: Path, capsys, monkeypatch) -> None:
    config_path = make_project(tmp_path)
    monkeypatch.setattr("owlhooter.main.ffmpeg_available", lambda: False)
    monkeypatch.setattr("owlhooter.main.device_available", lambda device: True)
    assert main(["--config", str(config_path)]) == 3
    assert "apt install ffmpeg" in capsys.readouterr().err.lower()


def test_missing_audio_device_exits_five(tmp_path: Path, capsys, monkeypatch) -> None:
    config_path = make_project(tmp_path)
    monkeypatch.setattr("owlhooter.main.ffmpeg_available", lambda: True)
    monkeypatch.setattr("owlhooter.main.device_available", lambda device: False)
    assert main(["--config", str(config_path)]) == 5
    assert "aplay -l" in capsys.readouterr().err.lower()


class _RecordingPlayer:
    """Fake Player used by the --once success-path tests below.

    Records the device its constructor received (class-level, since main()
    constructs it) and every (clip, volume) passed to play().
    """

    last_device: str | None = None
    plays: list[tuple[Path, float]] = []

    def __init__(self, device: str) -> None:
        type(self).last_device = device
        type(self).plays = []

    def play(self, clip: Path, volume: float) -> None:
        type(self).plays.append((clip, volume))


def test_once_success_path_plays_a_clip_through_the_configured_device(
    tmp_path: Path, monkeypatch
) -> None:
    # Important 1 hid exactly here: nothing exercised the path that
    # constructs a real Player before this test (Minor 7, partial).
    config_path = make_project(tmp_path)
    monkeypatch.setattr("owlhooter.main.ffmpeg_available", lambda: True)
    monkeypatch.setattr("owlhooter.main.device_available", lambda device: True)
    monkeypatch.setattr("owlhooter.main.Player", _RecordingPlayer)

    assert main(["--config", str(config_path), "--once", "--seed", "1"]) == 0

    assert _RecordingPlayer.last_device == "plughw:CARD=Device"
    assert len(_RecordingPlayer.plays) == 1
    clip, gain = _RecordingPlayer.plays[0]
    assert clip.name.startswith("tawny_")
    assert 0.85 <= gain <= 1.0


def test_once_volume_flag_overrides_the_configured_gain_exactly(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = make_project(tmp_path)
    monkeypatch.setattr("owlhooter.main.ffmpeg_available", lambda: True)
    monkeypatch.setattr("owlhooter.main.device_available", lambda device: True)
    monkeypatch.setattr("owlhooter.main.Player", _RecordingPlayer)

    assert main(["--config", str(config_path), "--once", "--volume", "1.5"]) == 0

    assert _RecordingPlayer.plays == [(_RecordingPlayer.plays[0][0], 1.5)]


def test_once_playback_failure_exits_five(tmp_path: Path, capsys, monkeypatch) -> None:
    from owlhooter.player import PlaybackError

    config_path = make_project(tmp_path)
    monkeypatch.setattr("owlhooter.main.ffmpeg_available", lambda: True)
    monkeypatch.setattr("owlhooter.main.device_available", lambda device: True)

    class _FailingPlayer:
        def __init__(self, device: str) -> None:
            pass

        def play(self, clip, volume) -> None:
            raise PlaybackError("device busy")

    monkeypatch.setattr("owlhooter.main.Player", _FailingPlayer)
    assert main(["--config", str(config_path), "--once"]) == 5
    err = capsys.readouterr().err.lower()
    assert "device busy" in err
    assert "tawny_" in err
