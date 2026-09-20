#!/usr/bin/env python3
"""Bulk-download owl recordings from xeno-canto into sounds/raw/.

Deliberately biased towards LOW-frequency callers. The speaker sits below a
plasterboard ceiling and the mice are above it; plasterboard attenuates high
frequencies far more than low ones, so a tawny owl's hoot gets through and a
barn owl's screech largely does not.

Short recordings only - a four-minute soundscape is useless as a deterrent clip.

xeno-canto retired API v2 (it now 404s). v3 needs a free API key from your
account page: https://xeno-canto.org/account

Standard library only, matching the rest of the project.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://xeno-canto.org/api/3/recordings"
UA = "OwlHooter/1.0 (personal rodent deterrent)"

# UK predators of small rodents. Two competing pressures here:
#
#   - ACOUSTICS favour low frequencies. The speaker is below a plasterboard
#     ceiling and the mice are above it, and transmission loss rises with
#     frequency, so a tawny owl's ~600 Hz hoot gets through and a barn owl's
#     1-8 kHz screech largely does not.
#   - BIOLOGY favours the species the mice actually meet. A UK house mouse in
#     a roof space has evolved alongside barn and tawny owls; it has never
#     encountered a eagle owl.
#
# Both matter, so take both. Variety is the anti-habituation mechanism, and a
# clip that is only partly audible through the ceiling still varies the signal.
SPECIES = [
    # UK natives, nocturnal, rodent specialists - the core of the library
    ("Strix", "aluco"),        # tawny owl - low hoot, best ceiling penetration
    ("Tyto", "alba"),          # barn owl - the classic UK mouse predator
    ("Asio", "otus"),          # long-eared owl - low repeated hoot
    ("Asio", "flammeus"),      # short-eared owl - vole and mouse specialist
    ("Athene", "noctua"),      # little owl - takes small mammals and insects
    # UK natives, diurnal raptors. Major rodent predators, but a daytime
    # hunter calling at 3am is ecologically incongruous - kept because the
    # fear response to raptor calls is broad, but they are a minority.
    ("Falco", "tinnunculus"),  # kestrel
    ("Buteo", "buteo"),        # common buzzard
    # NOT UK species. Included only for their very low frequencies, which
    # carry through a ceiling better than anything native. Drop these two if
    # you would rather the library were strictly British.
    ("Bubo", "bubo"),          # eagle owl
    ("Strix", "uralensis"),    # ural owl
]


def api_request(query: str, key: str, page: int = 1) -> dict:
    params = {"query": query, "key": key, "page": str(page)}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url: str, target: Path) -> bool:
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        print("    failed: no download URL in response", file=sys.stderr)
        return False
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"    failed: {exc}", file=sys.stderr)
        return False
    if len(data) < 2048:
        print("    failed: response too small to be audio", file=sys.stderr)
        return False
    target.write_bytes(data)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, help="xeno-canto API key")
    parser.add_argument("--out", type=Path, required=True, help="raw download directory")
    parser.add_argument("--per-species", type=int, default=12, help="recordings per species")
    parser.add_argument("--max-seconds", type=int, default=20, help="longest recording to accept")
    parser.add_argument("--probe", action="store_true", help="query only, download nothing")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    attributions: list[str] = []
    total = 0

    for genus, species in SPECIES:
        # q:A     - top quality grade only
        # len:1-N - short recordings, so clips are usable without editing
        query = f"gen:{genus} sp:{species} q:A len:1-{args.max_seconds}"
        label = f"{genus} {species}"
        print(f"\n== {label} ==")
        try:
            data = api_request(query, args.key)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            print(f"  HTTP {exc.code}: {body}", file=sys.stderr)
            if exc.code in (401, 403):
                print("  -> the API key was rejected.", file=sys.stderr)
            return 2
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"  request failed: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError:
            print("  API returned something that is not JSON", file=sys.stderr)
            return 2

        recordings = data.get("recordings", [])
        print(f"  {data.get('numRecordings', '?')} matching; taking up to {args.per_species}")
        if args.probe:
            for rec in recordings[:3]:
                print(f"    e.g. XC{rec.get('id')} {rec.get('en')} "
                      f"{rec.get('length')} by {rec.get('rec')} [{rec.get('lic', '?')}]")
            continue

        for rec in recordings[: args.per_species]:
            xc_id = rec.get("id")
            stem = f"XC{xc_id}_{genus}_{species}"
            target = args.out / f"{stem}.mp3"
            if target.exists():
                print(f"  XC{xc_id} already present")
                continue
            print(f"  XC{xc_id} ({rec.get('length')}) by {rec.get('rec')}")
            if download(rec.get("file", ""), target):
                total += 1
                attributions.append(
                    f"{stem}.mp3 | XC{xc_id} | {rec.get('en')} ({label}) | "
                    f"recordist: {rec.get('rec')} | licence: {rec.get('lic')} | "
                    f"https://xeno-canto.org/{xc_id}"
                )
            time.sleep(0.4)  # be polite to a free community service

    if attributions:
        credits = args.out / "ATTRIBUTION.txt"
        header = (
            "Recordings downloaded from xeno-canto.org.\n"
            "Each is Creative Commons licensed; the specific licence is listed per file.\n"
            "Licence texts: https://creativecommons.org/licenses/\n\n"
        )
        existing = credits.read_text(encoding="utf-8") if credits.exists() else header
        credits.write_text(existing + "\n".join(attributions) + "\n", encoding="utf-8")
        print(f"\nwrote attributions to {credits}")

    print(f"\ndownloaded {total} recording(s) into {args.out}")
    if total:
        print("next: run tools/normalise.sh to level them into sounds/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
