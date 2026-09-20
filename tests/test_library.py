from __future__ import annotations

from pathlib import Path

import pytest

from owlhooter.library import LibraryError, discover_clips


def make_clip(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"not really audio")
    return path


def test_finds_audio_files(tmp_path: Path) -> None:
    make_clip(tmp_path, "tawny_a.wav")
    make_clip(tmp_path, "tawny_b.mp3")
    assert len(discover_clips(tmp_path)) == 2


def test_results_are_sorted_for_determinism(tmp_path: Path) -> None:
    make_clip(tmp_path, "c.wav")
    make_clip(tmp_path, "a.wav")
    make_clip(tmp_path, "b.wav")
    assert [p.name for p in discover_clips(tmp_path)] == ["a.wav", "b.wav", "c.wav"]


def test_ignores_non_audio_files(tmp_path: Path) -> None:
    make_clip(tmp_path, "tawny.wav")
    make_clip(tmp_path, "README.md")
    make_clip(tmp_path, ".gitkeep")
    assert [p.name for p in discover_clips(tmp_path)] == ["tawny.wav"]


def test_extension_matching_is_case_insensitive(tmp_path: Path) -> None:
    make_clip(tmp_path, "TAWNY.WAV")
    assert len(discover_clips(tmp_path)) == 1


def test_does_not_descend_into_the_raw_subdirectory(tmp_path: Path) -> None:
    make_clip(tmp_path, "processed.wav")
    make_clip(tmp_path / "raw", "original.mp3")
    assert [p.name for p in discover_clips(tmp_path)] == ["processed.wav"]


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(LibraryError, match="not found"):
        discover_clips(tmp_path / "absent")


def test_empty_directory_raises(tmp_path: Path) -> None:
    tmp_path.joinpath("empty").mkdir()
    with pytest.raises(LibraryError, match="no audio clips"):
        discover_clips(tmp_path / "empty")


def test_directory_with_only_non_audio_raises(tmp_path: Path) -> None:
    make_clip(tmp_path, "README.md")
    with pytest.raises(LibraryError, match="no audio clips"):
        discover_clips(tmp_path)
