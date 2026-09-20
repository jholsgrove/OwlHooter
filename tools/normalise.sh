#!/usr/bin/env bash
# Normalise downloaded owl recordings into playable clips.
#
# Drop whatever you downloaded into sounds/raw/ in any format, then run this.
# Output is mono 44.1 kHz WAV at a consistent loudness, written to sounds/.
# Consistent loudness matters because the daemon applies a random gain on top:
# without it, a quiet recording and a loud one behave completely differently.

set -euo pipefail

RAW_DIR="${1:-sounds/raw}"
OUT_DIR="${2:-sounds}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is not installed. Run: sudo apt install ffmpeg" >&2
  exit 1
fi

if [ ! -d "$RAW_DIR" ]; then
  echo "No raw directory at $RAW_DIR" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

shopt -s nullglob nocaseglob
count=0
for source in "$RAW_DIR"/*.{wav,mp3,ogg,flac,m4a,aac,opus}; do
  name="$(basename "${source%.*}")"
  target="$OUT_DIR/${name}.wav"
  echo "normalising $(basename "$source") -> $(basename "$target")"
  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -i "$source" \
    -filter:a "loudnorm=I=-16:TP=-1.5:LRA=11" \
    -ar 44100 -ac 1 \
    "$target"
  count=$((count + 1))
done
shopt -u nullglob nocaseglob

if [ "$count" -eq 0 ]; then
  echo "No audio files found in $RAW_DIR" >&2
  exit 1
fi

echo "normalised $count clip(s) into $OUT_DIR"
