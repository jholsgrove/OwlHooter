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
from owlhooter.player import Player, PlaybackError, device_available, ffmpeg_available

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

    # This logger must never print anything, in this process or any other:
    # its messages are stamped with the wall-clock time the simulation ran,
    # not the simulated time they describe, and mixing the two defeats the
    # whole point of a schedule preview. `propagate = False` plus a
    # NullHandler makes it inert regardless of how the caller (main(), a
    # test, or anything else) has configured logging elsewhere.
    dry_run_log = logging.getLogger("owlhooter.dryrun")
    dry_run_log.propagate = False
    if not dry_run_log.handlers:
        dry_run_log.addHandler(logging.NullHandler())

    daemon = Daemon(
        config=config,
        player=_RecordingPlayer(clock, events),
        clips=clips,
        rng=rng,
        clock=clock,
        sleeper=sleeper,
        log=dry_run_log,
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
    try:
        Player(config.alsa_device).play(clip, gain)
    except PlaybackError as exc:
        print(f"playback failed for {clip.name}: {exc}", file=sys.stderr)
        return EXIT_NO_DEVICE
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
        # No audio is produced, so no hardware is checked - and no logging is
        # configured either. The whole point of --dry-run is a clean table of
        # simulated times; wiring up logging here would risk exactly the
        # leaked-real-clock-log-lines bug simulate_night's own logger already
        # guards against.
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

    # Only the paths that actually run something worth logging - a single
    # commissioning call, or the daemon loop - configure logging.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    if args.once:
        return _run_once(config, clips, args.seed, args.volume)
    return _run_daemon(config, clips, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
