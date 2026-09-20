from __future__ import annotations

import random
from collections import deque
from pathlib import Path

import pytest

from owlhooter.scheduler import pick_clip

CLIPS = [Path(f"sounds/tawny_{index}.wav") for index in range(8)]


def test_returns_a_clip_from_the_library() -> None:
    assert pick_clip(random.Random(1), CLIPS, []) in CLIPS


def test_never_returns_a_recent_clip() -> None:
    rng = random.Random(2)
    recent = deque(CLIPS[:5], maxlen=5)
    for _ in range(500):
        assert pick_clip(rng, CLIPS, recent) not in recent


def test_a_single_clip_library_returns_that_clip() -> None:
    only = [Path("sounds/only.wav")]
    assert pick_clip(random.Random(3), only, deque(only, maxlen=5)) == only[0]


def test_library_smaller_than_memory_still_avoids_immediate_repeats() -> None:
    small = CLIPS[:3]
    rng = random.Random(4)
    recent: deque[Path] = deque(maxlen=5)
    previous: Path | None = None
    for _ in range(200):
        chosen = pick_clip(rng, small, recent)
        assert chosen != previous
        recent.append(chosen)
        previous = chosen


def test_zero_length_memory_is_tolerated() -> None:
    rng = random.Random(5)
    recent: deque[Path] = deque(maxlen=0)
    for _ in range(100):
        recent.append(pick_clip(rng, CLIPS, recent))


def test_selection_spreads_across_the_library() -> None:
    rng = random.Random(6)
    recent: deque[Path] = deque(maxlen=5)
    seen = set()
    for _ in range(300):
        chosen = pick_clip(rng, CLIPS, recent)
        recent.append(chosen)
        seen.add(chosen)
    assert seen == set(CLIPS)


def test_empty_library_raises() -> None:
    with pytest.raises(ValueError, match="at least one clip"):
        pick_clip(random.Random(7), [], [])
