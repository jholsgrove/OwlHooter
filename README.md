# OwlHooter

A Raspberry Pi mouse deterrent. It plays owl calls through a speaker at unpredictable
intervals overnight, exploiting the fear response mice have to their main natural predator.

Mice habituate to predictable noise within days, so nothing here is predictable: the
interval, the clip, the volume, the number of calls in a burst and whether a given night
happens at all are all randomised.

This is one layer of control. It works alongside sealing entry points, not instead of it.

## Hardware

- A Raspberry Pi running Pi OS Bookworm or later (Python 3.11+).
  The build is targeted at and verified against a **Raspberry Pi 4 Model B (1GB)**.
  On a 1GB board, use **Raspberry Pi OS Lite** — there is no need for a desktop on a headless deterrent, and it leaves more memory and less SD wear.
- A USB speaker or USB sound card. Nothing else is needed.
  Although the Pi 4 has a 3.5mm analogue jack (unlike the Pi 5), **USB audio is still the right choice**: the Pi 4's analogue output is noisy and low-powered, which is the opposite of what is needed to drive sound up through a plasterboard ceiling.

## Where to put the speaker

The mice are above a plasterboard ceiling and the speaker is below it, so most of the
useful gain is physical rather than digital:

- **Height beats volume.** On top of a cupboard or a shelf, as close to the ceiling as
  possible. Halving the distance is worth more than any software setting.
- **Find the gaps.** A loft hatch, downlighter cut-out or pipe penetration passes sound far
  better than sealed plasterboard. Aim at one if there is one.
- **Low frequencies get through; high ones do not.** Favour tawny and long-eared owl over barn owl: their low hoot (roughly 500-900 Hz) passes through a ceiling, while a barn owl's high screech is largely reflected by it.

## Install

```bash
sudo apt update
sudo apt install -y ffmpeg
git clone <your-repo-url> /home/pi/OwlHooter
cd /home/pi/OwlHooter
```

Find your audio device and put it in `config.toml`:

```bash
aplay -L | grep plughw
```

Turn the output up — the digital gain in `config.toml` is unity at `1.0`, so the real
loudness comes from here and from the speaker's own control:

```bash
alsamixer    # F6 to pick the USB card, arrow up, Esc
sudo alsactl store
```

Check it works before installing the service:

```bash
python3 -m owlhooter.main --once
```

Then install the service:

```bash
sudo cp deploy/owlhooter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now owlhooter
```

## Getting owl sounds

Download from [xeno-canto.org](https://xeno-canto.org) — thousands of Creative Commons
recordings, filterable by species and quality grade. Grab a couple of dozen; variety is what
keeps the deterrent working.

Then normalise them:

```bash
cd /home/pi/OwlHooter
# put the downloads in sounds/raw/ first
./tools/normalise.sh
```

This converts everything to consistent-loudness mono WAV in `sounds/`. The daemon reads
`sounds/` only, never `sounds/raw/`.

## Operating it

```bash
systemctl status owlhooter          # is it running
journalctl -u owlhooter -f          # watch it live
journalctl -u owlhooter --since yesterday | grep call    # what it played overnight
sudo systemctl restart owlhooter    # after editing config.toml
```

Two flags help without waiting for nightfall:

```bash
python3 -m owlhooter.main --once              # play one clip now
python3 -m owlhooter.main --once --volume 1.0 # ...at a specific gain
python3 -m owlhooter.main --dry-run           # print tonight's schedule, make no sound
```

## Configuration

Everything lives in `config.toml`, which is commented. The settings you are most likely to
change:

| Setting | Default | Notes |
|---|---|---|
| `window_start` / `window_end` | 21:00 / 06:00 | May cross midnight |
| `interval_min_minutes` / `interval_max_minutes` | 10 / 30 | Gap between hoot events |
| `max_events_per_night` | 25 | Safety valve, not the main control — widen the interval instead if it is too frequent |
| `volume_min` / `volume_max` | 0.85 / 1.0 | ffmpeg gain; 1.0 is unity. No cap, but above 1.0 clips and distorts |
| `silent_night_probability` | 0.15 | Chance of skipping a whole night |
| `probability` (burst) | 0.30 | Chance an event is 2-3 calls rather than one |

## Troubleshooting

| Symptom | Cause |
|---|---|
| Exits with code 2 | Config file missing or invalid — the message says which setting |
| Exits with code 3 | ffmpeg not installed: `sudo apt install ffmpeg` |
| Exits with code 4 | No clips in `sounds/` — download some and run `tools/normalise.sh` |
| Exits with code 5 (device not found) | `alsa_device` does not match anything in `aplay -L`. Check the device string in `config.toml` against `aplay -L \| grep plughw` |
| Exits with code 5 (playback failed) | The device exists but a specific clip failed to play. Message reads `playback failed for <clip>: <reason>`. Try `python3 -m owlhooter.main --once` with a different clip, or re-run `tools/normalise.sh` on the failing clip |
| Runs but is silent | Check the window in `config.toml`, then `alsamixer` levels, then `--once` |
| Too quiet through the ceiling | Raise the speaker; use tawny not barn owl clips; raise `alsamixer`, not `volume_max` |
| Played the same clip twice running | Only possible with fewer than two clips in `sounds/` |
| Systemctl status shows repeated activating/restarting | Unit is hitting a persistent startup failure and restarting every 30 seconds. Run `journalctl -u owlhooter` to see which exit code and reason, then consult the exit-code rows above |

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

The whole test suite runs on any machine — no Pi, no speaker, no waiting. Every clock,
sleeper, subprocess runner and player is injected. Tests never sleep and never make a sound.

- `owlhooter/scheduler.py` — pure timing and selection logic; where the interesting tests are
- `owlhooter/library.py` — clip discovery
- `owlhooter/player.py` — ffmpeg invocation
- `owlhooter/daemon.py` — the loop
- `owlhooter/main.py` — CLI and startup checks

Design notes are in `docs/superpowers/specs/2026-09-20-owlhooter-design.md`.
