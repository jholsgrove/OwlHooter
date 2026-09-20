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
