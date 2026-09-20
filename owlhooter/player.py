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
