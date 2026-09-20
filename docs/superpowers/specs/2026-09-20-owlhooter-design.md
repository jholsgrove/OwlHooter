# OwlHooter — Design

**Date:** 2026-09-20
**Status:** Approved

## Purpose

A Raspberry Pi mouse deterrent. It plays owl calls through a speaker at unpredictable
intervals during the night, exploiting the fear response mice have to their main natural
predator.

The design's central concern is **habituation**. Rodents learn quickly that a repeating,
predictable noise never results in an actual predator, and they begin ignoring it within
days to weeks. Every randomisation decision below exists to delay that: varying the
interval, the clip, the volume, and occasionally skipping whole nights means there is no
pattern to learn. This is one layer of control and is expected to sit alongside physical
exclusion (sealing entry points), not replace it.

## Deployment context

- **Hardware:** Raspberry Pi with a USB speaker / USB sound card.
- **Location:** Inside the house. People sleep nearby.
- **Hours:** Night only — silent during the day.

The indoor siting is the key constraint. It is why volume is capped, why a nightly budget
exists at all, and why the deterrent is occasional rather than continuous.

## Architecture

A single long-running Python daemon, started and kept alive by systemd. One loop:

```
while running:
    if not inside active window:  sleep until window opens
    sleep a random interval
    pick a clip (not one of the recent ones)
    play it at a random volume
```

Alternatives considered and rejected:

- **systemd timer / cron one-shot.** No resident process, naturally crash-resilient, but a
  random 10–30 minute interval is awkward to express in a timer unit, and per-night state
  (budget consumed, recently-played clips) would need a file on disk. More moving parts for
  less control.
- **Daemon with MQTT / Home Assistant integration.** Remote control and dashboards. Real
  capability, but disproportionate machinery for a box that needs to hoot occasionally.

### Playback

Playback shells out to `ffmpeg`:

```
ffmpeg -i <clip> -filter:a volume=<gain> -f alsa <device>
```

Chosen over a Python audio library (`pygame.mixer`, `sounddevice`) because it plays any
format dropped into `sounds/` without conversion, provides per-hoot volume as a filter
argument, and addresses the ALSA device explicitly. It costs one apt package and adds no
Python dependencies that could break on an OS upgrade.

The output device is named (e.g. `plughw:CARD=Device`) rather than indexed (`card 1`), so
it survives reboots and re-plugging of the USB device.

## Components

```
owlhooter/
  scheduler.py   # pure logic: window test, interval, clip choice, volume
  player.py      # ffmpeg subprocess wrapper
  main.py        # loop, config loading, logging, CLI flags
sounds/          # clip library (gitignored)
tools/normalise.sh
deploy/owlhooter.service
tests/
config.toml
```

**`scheduler.py`** — Pure functions only. Takes an injected clock and a seeded RNG; performs
no I/O and imports nothing from the rest of the package. This is what makes the timing logic
testable instantly on a development machine with no Pi, no speaker, and no waiting.

- `is_active(now, window) -> bool`
- `next_interval(rng, min_s, max_s) -> float`
- `pick_clip(rng, clips, recent) -> Path`
- `pick_volume(rng, min_v, max_v) -> float`
- `is_silent_night(rng, probability) -> bool`

**`player.py`** — Builds and runs the ffmpeg command. Takes an injectable subprocess runner
so tests can assert on the constructed command without producing sound.

**`main.py`** — Wires the two together, loads config, sets up logging, handles the CLI flags
and shutdown signals.

## Configuration

`config.toml`, read with the standard library's `tomllib`. Pi OS Bookworm ships Python 3.11,
so this adds **no third-party Python dependencies**.

| Setting | Default | Rationale |
|---|---|---|
| Active window | 21:00–06:00 | Mouse-active hours; crosses midnight |
| Interval between hoots | random 10–30 min | The core unpredictability |
| Max hoots per night | 25 | Safety valve against a runaway loop or bad config — not the governing constraint |
| Volume | random 40–80% | Varies apparent distance; caps peak loudness indoors |
| No-repeat memory | last 5 clips | Never the same call twice in a row |
| Silent-night probability | 15% | Removes any learnable night-to-night pattern |
| ALSA device | `plughw:CARD=Device` | Named, not indexed |

### On the cap and the interval

A 21:00–06:00 window is 9 hours; a 20-minute mean interval yields roughly 27 hoots. The cap
is set to 25 so that the interval governs behaviour and hoots spread across the entire night.
A lower cap (e.g. 12) would be exhausted around 01:00 and leave the rest of the night without
cover — the cap, rather than the interval, would be shaping behaviour. If the deterrent proves
too intrusive indoors, the correct adjustment is to widen the interval, not to lower the cap.

## Sound library

The user supplies clips by dropping files into `sounds/`; the daemon discovers whatever is
present at startup. No clips are committed to the repository.

Recommended source is **xeno-canto.org**, which carries thousands of individually downloadable,
Creative Commons licensed owl recordings (tawny, barn, little, long-eared), filterable by
species and quality grade. This suits the anti-habituation design far better than compilation
videos, which provide a single long track and therefore little genuine variety.

`tools/normalise.sh` is a one-off ingest helper that levels the loudness of everything in
`sounds/`, so that a quiet recording and a loud one do not behave wildly differently once the
random volume multiplier is applied on top.

## Error handling

**Fail fast at startup** on conditions meaning it can never work, so `systemctl status` reports
the actual problem:

- `ffmpeg` not installed
- `sounds/` empty or missing
- configured ALSA device not present
- malformed config

**Fail soft at runtime.** A single clip that fails to play logs a warning and the loop
continues; one corrupt file must not take the deterrent down. `Restart=on-failure` in the
systemd unit is the backstop for anything unanticipated.

Logging goes to stdout, which systemd routes to the journal (`journalctl -u owlhooter`).

## CLI

- `--once` — play a single hoot immediately and exit. Commissioning check that the speaker,
  device name and clips all work.
- `--dry-run` — print the schedule that would be followed for one night, without playing
  anything. Lets the timing settings be sanity-checked before deployment.

## Testing

Test-driven, targeting `scheduler.py`, where all the logic that can be wrong lives. A seeded
RNG and a fake clock make assertions exact and instant:

- Window boundaries, including the midnight crossing
- Interval always falls within configured bounds
- Nightly budget exhaustion, and its reset at the start of the next night
- Clip selection never returns one of the last five played
- Clip selection behaves correctly when the library is smaller than the no-repeat memory
- Silent-night probability honoured across a seeded run

`player.py` is tested with a fake subprocess runner asserting the ffmpeg command is built
correctly, including volume and device arguments. No test sleeps, and no test produces audio.

Playback itself is verified manually on the Pi via `--once`.

## Out of scope

- **Burst calling** — real owls often call two or three times in sequence. Realistic, but not
  required for the deterrent effect.
- **Remote control** — MQTT, web UI, Home Assistant.
- **Motion/PIR triggering** — the deterrent is time-based by design.
