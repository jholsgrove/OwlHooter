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
