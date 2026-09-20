"""Discovery of the owl clip library on disk."""

from __future__ import annotations

from pathlib import Path

AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus"})


class LibraryError(Exception):
    """The sound library is missing or contains no usable clips."""


def discover_clips(sounds_dir: Path) -> list[Path]:
    """Return the playable clips in `sounds_dir`, sorted.

    Deliberately non-recursive: `sounds/raw/` holds unprocessed downloads for
    tools/normalise.sh and must never be played directly.
    """
    if not sounds_dir.is_dir():
        raise LibraryError(f"sounds directory not found: {sounds_dir}")

    clips = sorted(
        entry
        for entry in sounds_dir.iterdir()
        if entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not clips:
        raise LibraryError(
            f"no audio clips found in {sounds_dir}. "
            f"Add files with one of these extensions: {', '.join(sorted(AUDIO_EXTENSIONS))}"
        )
    return clips
