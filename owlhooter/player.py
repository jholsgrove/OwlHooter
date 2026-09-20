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


# A wedged USB PCM can block subprocess.run() forever. Every call site below
# bounds its wait so a sick device costs one hoot (or one startup check),
# never the whole night: unlike every other failure mode in this system,
# a hang does not self-heal - the process stays "active (running)" under
# systemd with nothing to trigger a restart.
PLAY_TIMEOUT_S = 60
CHECK_TIMEOUT_S = 10


class Player:
    """Plays clips to a named ALSA device."""

    def __init__(self, device: str, runner=subprocess.run) -> None:
        self._device = device
        self._runner = runner

    def play(self, clip: Path, volume: float) -> None:
        """Play one clip, blocking until it finishes (or PLAY_TIMEOUT_S elapses).

        Raises PlaybackError rather than exiting: the daemon logs a warning and
        carries on, so one corrupt file - or one wedged device - cannot take
        the deterrent down.

        Trade-off: a recording longer than PLAY_TIMEOUT_S (60s) - e.g. one a
        user dropped into sounds/ without running tools/normalise.sh - is cut
        off rather than played to the end.
        """
        command = build_command(clip, volume, self._device)
        try:
            result = self._runner(command, capture_output=True, text=True, timeout=PLAY_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise PlaybackError(
                f"ffmpeg timed out after {PLAY_TIMEOUT_S}s playing {clip}"
            ) from exc
        except OSError as exc:
            raise PlaybackError(f"ffmpeg is not installed: {clip}: {exc}") from exc
        if result.returncode != 0:
            raise PlaybackError(f"ffmpeg failed for {clip}: {result.stderr.strip()}")


def ffmpeg_available(runner=subprocess.run) -> bool:
    """Is ffmpeg installed and runnable? Checked once at startup.

    Bounded to CHECK_TIMEOUT_S: this should return in milliseconds, and must
    not be able to hang the daemon before it ever reaches the loop.
    """
    try:
        result = runner(["ffmpeg", "-version"], capture_output=True, text=True, timeout=CHECK_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def device_available(device: str, runner=subprocess.run) -> bool:
    """Is `device` present in `aplay -L`? Checked once at startup.

    aplay lists PCM names flush to the left margin and indents their
    descriptions, so only unindented lines are candidate device names.

    Bounded to CHECK_TIMEOUT_S: aplay -L can itself block on a sick USB card,
    which would hang the daemon before it ever reaches the loop.
    """
    if not device.strip():
        return False

    try:
        result = runner(["aplay", "-L"], capture_output=True, text=True, timeout=CHECK_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False

    names = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line[0].isspace()
    ]
    return any(
        name == device or (name.startswith(device) and len(name) > len(device) and name[len(device)] == ",")
        for name in names
    )
