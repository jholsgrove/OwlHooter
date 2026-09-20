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


def test_seconds_until_window_opens_exactly_at_start() -> None:
    now = datetime(2026, 9, 20, 21, 0)
    assert seconds_until_window_opens(now, NIGHT_START) == 0.0


def test_seconds_until_window_closes_exactly_at_end() -> None:
    now = datetime(2026, 9, 21, 6, 0)
    assert seconds_until_window_closes(now, NIGHT_END) == 0.0
