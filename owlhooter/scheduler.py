"""Pure scheduling logic.

Every function here takes its clock and its randomness as arguments and
performs no I/O, which is what makes the timing behaviour testable without a
Pi, a speaker, or any waiting around.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Sequence


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
    if candidate < now:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()


def seconds_until_window_opens(now: datetime, start: time) -> float:
    """Seconds until the window opens; returns 0.0 if `now` equals `start`."""
    return _seconds_until(now, start)


def seconds_until_window_closes(now: datetime, end: time) -> float:
    """Seconds until the window closes; returns 0.0 if `now` equals `end`."""
    return _seconds_until(now, end)


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
