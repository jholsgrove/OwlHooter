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
