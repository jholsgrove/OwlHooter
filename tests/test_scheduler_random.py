from __future__ import annotations

import random

from owlhooter.scheduler import (
    burst_gap,
    burst_size,
    is_silent_night,
    next_interval,
    pick_volume,
)


def test_interval_always_falls_within_bounds() -> None:
    rng = random.Random(1)
    for _ in range(1000):
        assert 600.0 <= next_interval(rng, 600.0, 1800.0) <= 1800.0


def test_interval_varies_between_calls() -> None:
    rng = random.Random(1)
    values = {next_interval(rng, 600.0, 1800.0) for _ in range(50)}
    assert len(values) > 40


def test_interval_with_equal_bounds_is_exact() -> None:
    assert next_interval(random.Random(1), 900.0, 900.0) == 900.0


def test_volume_always_falls_within_bounds() -> None:
    rng = random.Random(2)
    for _ in range(1000):
        assert 0.85 <= pick_volume(rng, 0.85, 1.0) <= 1.0


def test_volume_supports_gain_above_unity() -> None:
    rng = random.Random(2)
    for _ in range(100):
        assert 1.0 <= pick_volume(rng, 1.0, 2.0) <= 2.0


def test_burst_size_is_one_when_the_roll_fails() -> None:
    assert burst_size(random.Random(3), 0.0, 2, 3) == 1


def test_burst_size_is_in_range_when_the_roll_always_succeeds() -> None:
    rng = random.Random(3)
    for _ in range(200):
        assert burst_size(rng, 1.0, 2, 3) in (2, 3)


def test_burst_size_is_either_one_or_in_range() -> None:
    rng = random.Random(4)
    sizes = {burst_size(rng, 0.3, 2, 3) for _ in range(500)}
    assert sizes <= {1, 2, 3}
    assert 1 in sizes and (2 in sizes or 3 in sizes)


def test_burst_probability_is_roughly_honoured() -> None:
    rng = random.Random(5)
    bursts = sum(1 for _ in range(10000) if burst_size(rng, 0.3, 2, 3) > 1)
    assert 2700 <= bursts <= 3300


def test_burst_gap_falls_within_bounds() -> None:
    rng = random.Random(6)
    for _ in range(500):
        assert 2.0 <= burst_gap(rng, 2.0, 6.0) <= 6.0


def test_silent_night_never_fires_at_zero_probability() -> None:
    rng = random.Random(7)
    assert not any(is_silent_night(rng, 0.0) for _ in range(500))


def test_silent_night_always_fires_at_full_probability() -> None:
    rng = random.Random(7)
    assert all(is_silent_night(rng, 1.0) for _ in range(500))


def test_silent_night_probability_is_roughly_honoured() -> None:
    rng = random.Random(8)
    silent = sum(1 for _ in range(10000) if is_silent_night(rng, 0.15))
    assert 1300 <= silent <= 1700


def test_results_are_reproducible_for_a_given_seed() -> None:
    first = next_interval(random.Random(9), 600.0, 1800.0)
    second = next_interval(random.Random(9), 600.0, 1800.0)
    assert first == second
