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
