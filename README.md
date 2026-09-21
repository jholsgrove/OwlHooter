<p align="center">
  <img src="logo-oh.png" alt="OwlHooter logo: an owl hooting while a mouse flees" width="260">
</p>

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

## Getting onto the Pi over SSH

The Pi runs headless — no keyboard, no monitor — so everything below happens over SSH.

**Enable SSH when you flash the card, not afterwards.** Pi OS Lite has no desktop and SSH is
off by default, so a Pi flashed without this is unreachable. In Raspberry Pi Imager, before
you click Write, open the customisation dialog (the gear icon, or `Ctrl+Shift+X`) and set:

- a hostname, e.g. `owlhooter`
- a username and password — Pi OS no longer ships a default `pi` account
- your WiFi SSID, password and country, unless you are using Ethernet
- **Services → Enable SSH**, with password authentication

Then boot the Pi and connect. Windows has an SSH client built in, so Windows Terminal or
PowerShell is enough — no PuTTY needed:

```bash
ssh <your-username>@owlhooter.local
```

If `owlhooter.local` does not resolve, mDNS is not working on your network. Find the Pi's IP
in your router's DHCP client list and use that instead.

### Getting the code onto the Pi

If you have pushed this repo to a git host, clone it on the Pi:

```bash
git clone <your-repo-url> ~/OwlHooter
```

If you have not — which is the default for a personal project — copy it from your machine
instead. `rsync` is worth it here because the `sounds/` directory is a few hundred megabytes
and rsync will resume rather than restart if the WiFi drops:

```bash
# from WSL or any Linux/macOS shell, on your machine, not the Pi
rsync -av --exclude '.git' --exclude 'sounds/raw' \
    /mnt/c/Repos/OwlHooter/ <your-username>@owlhooter.local:~/OwlHooter/
```

`sounds/raw` is excluded deliberately: those are the unprocessed downloads, and only the
normalised clips in `sounds/` are needed on the Pi. Normalising on a desktop and copying the
results across is far quicker than making a Pi 4 transcode a hundred files.

Copying from Windows loses the executable bit, so restore it on the Pi:

```bash
chmod +x ~/OwlHooter/tools/normalise.sh
```

## Install

On the Pi:

```bash
sudo apt update
sudo apt install -y ffmpeg
cd ~/OwlHooter
```

If you copied the clips across with rsync above, `sounds/` is already populated and you can
skip the next section.

## Getting owl sounds

Variety is the whole anti-habituation mechanism, so more clips is strictly better. There are
two ways to get them, and you can use both.

### Quickest: the bundled starter clips

`starter-clips/` holds eight recordings — five tawny owl, one barn owl, one little owl, one
buzzard — so the deterrent works immediately:

```bash
cd ~/OwlHooter
cp starter-clips/*.mp3 sounds/raw/
./tools/normalise.sh
```

These eight are bundled because they are CC0 or plain CC BY, with no NonCommercial,
NoDerivatives or ShareAlike conditions attached. Credits are in
[`starter-clips/ATTRIBUTION.md`](starter-clips/ATTRIBUTION.md).

Eight clips is enough to prove the system works, but it is thin for a deterrent that relies
on never sounding the same twice. Get more.

### Better: fetch a full library

`tools/fetch-xeno-canto.py` pulls 130-odd recordings across nine species of UK rodent
predator in one command. It needs a free API key from your
[xeno-canto account page](https://xeno-canto.org/account):

```bash
python3 tools/fetch-xeno-canto.py --key YOUR_KEY --out sounds/raw
./tools/normalise.sh
```

The key is passed on the command line and never stored — do not paste it into any file in
this repo.

The species list is chosen on acoustics as much as biology. Low-frequency callers come first,
because a plasterboard ceiling attenuates high frequencies far more than low ones: a tawny
owl's hoot passes through, a barn owl's screech largely does not. Barn, little and short-eared
owl are still included, because they are the predators UK house mice actually encounter, and a
partly-attenuated call still varies the signal. Edit the `SPECIES` list in the script to
change the mix.

The script also writes an `ATTRIBUTION.txt` next to the downloads recording the recordist,
licence and xeno-canto ID of every file. Most xeno-canto recordings carry NonCommercial and
ShareAlike conditions, so keep that file if you redistribute anything.

### Normalising

Either route ends the same way:

```bash
./tools/normalise.sh
```

This converts everything in `sounds/raw/` to consistent-loudness mono WAV in `sounds/`.
Consistent loudness matters because the daemon applies a random gain on top; without it, a
quiet recording and a loud one behave completely differently. The daemon reads `sounds/`
only, never `sounds/raw/`.

## Configure the audio device and go live

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

Check it works before installing the service — by now `sounds/` has clips in it, so this
has something to play:

```bash
python3 -m owlhooter.main --once
```

Then install the service. The shipped unit says `User=pi` and `/home/pi/OwlHooter`, but Pi OS
no longer creates a default `pi` account — Imager made you choose a username — and your
clone may not sit in your home directory, so rewrite both as you install it. Run this from
the root of the checkout, so `$PWD` is the directory the unit should work from:

```bash
cd ~/Repos/OwlHooter   # wherever you cloned it
sed -e "s|User=pi|User=$USER|" -e "s|/home/pi/OwlHooter|$PWD|g" \
    deploy/owlhooter.service | sudo tee /etc/systemd/system/owlhooter.service
sudo systemctl daemon-reload
sudo systemctl enable --now owlhooter
```

The `tee` prints what it wrote — check that `User=`, `WorkingDirectory=` and the `--config`
path all name your account and your checkout before you move on. Two ways this bites:

| `systemctl status` shows | Meaning |
| --- | --- |
| `status=217/USER` | `User=` is still `pi`, or another account that does not exist |
| `status=200/CHDIR` | `WorkingDirectory=` points at a directory that is not there |

Either way the unit fails immediately and retries every 30 seconds, so `Active:` reads
`activating (auto-restart)` instead of `active (running)`. Fix the installed unit at
`/etc/systemd/system/owlhooter.service` — editing the copy in `deploy/` changes nothing —
then `sudo systemctl daemon-reload && sudo systemctl restart owlhooter`.

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
python3 -m owlhooter.main --dry-run           # simulate one possible night, make no sound
python3 -m owlhooter.main --dry-run --seed 42 # ...the same one every time
```

`--dry-run` shows *a* night the current settings could produce, not the one the daemon will
actually play tonight: the schedule is re-rolled from scratch on every run, and the daemon
rolls its own. Use it to sanity-check timing after editing `config.toml`, and `journalctl`
to see what really happened.

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
