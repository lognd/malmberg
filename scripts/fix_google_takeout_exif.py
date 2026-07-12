#!/usr/bin/env python3
"""Bake Google Takeout sidecar metadata back into the photos' EXIF.

Google Takeout does NOT put your location in the exported image files.  It
strips GPS out and writes the real metadata into a per-photo JSON sidecar
(``IMG_1234.jpg.json``, and in newer exports
``IMG_1234.jpg.supplemental-metadata.json``).  Upload the photos as-is and
they arrive with no place and often no capture date, so they never show up in
the place search, the time filters, or the by-year / by-month / by-place stats.

This script matches each photo to its sidecar and writes the two things
Malmberg actually indexes back into the file itself:

  photoTakenTime -> DateTimeOriginal
  geoData        -> GPSLatitude / GPSLongitude (+ refs, altitude)

Run this on the unzipped Takeout folder BEFORE uploading, then upload with
scripts/upload_from_mac.sh.

Requires exiftool:   brew install exiftool

Usage:
    python3 fix_google_takeout_exif.py [-n] TAKEOUT_DIR

    -n, --dry-run   report what would be written; change nothing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".avif", ".tif", ".tiff",
    ".webp", ".gif", ".bmp", ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
}


def find_sidecar(media: Path) -> Path | None:
    """Return the Takeout JSON describing *media*, or None.

    Takeout's naming is inconsistent across exports and it truncates long
    names, so try the known shapes rather than assuming one.
    """
    candidates = [
        media.with_name(media.name + ".json"),
        media.with_name(media.name + ".supplemental-metadata.json"),
        media.with_suffix(".json"),
    ]
    # Duplicates land as "IMG_1234(1).jpg" whose sidecar is "IMG_1234.jpg(1).json".
    stem, ext = media.stem, media.suffix
    if stem.endswith(")") and "(" in stem:
        base, _, dup = stem.rpartition("(")
        candidates.append(media.with_name(f"{base}{ext}({dup}.json"))
    # Takeout truncates very long filenames; fall back to a prefix match.
    for cand in candidates:
        if cand.is_file():
            return cand
    matches = sorted(media.parent.glob(media.name[:40] + "*.json"))
    return matches[0] if matches else None


def read_sidecar(path: Path) -> dict:
    """Pull the capture time and coordinates out of a Takeout sidecar."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    out: dict = {}
    # photoTakenTime is the real capture time; creationTime is the upload time.
    ts = (data.get("photoTakenTime") or {}).get("timestamp")
    if ts:
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            out["taken"] = dt.strftime("%Y:%m:%d %H:%M:%S")
        except (ValueError, OSError):
            pass

    geo = data.get("geoData") or data.get("geoDataExif") or {}
    lat, lon = geo.get("latitude"), geo.get("longitude")
    # Takeout writes 0.0/0.0 for "no location"; that is the Gulf of Guinea, not
    # a real place, so treat it as absent.
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        if lat != 0.0 or lon != 0.0:
            out["lat"] = float(lat)
            out["lon"] = float(lon)
            alt = geo.get("altitude")
            if isinstance(alt, (int, float)) and alt != 0.0:
                out["alt"] = float(alt)
    return out


def build_args(media: Path, meta: dict) -> list[str]:
    """Build the exiftool argument block that writes *meta* into *media*."""
    args: list[str] = []
    if "taken" in meta:
        args += [
            f"-DateTimeOriginal={meta['taken']}",
            f"-CreateDate={meta['taken']}",
        ]
        if media.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            args.append(f"-QuickTime:CreateDate={meta['taken']}")
    if "lat" in meta:
        lat, lon = meta["lat"], meta["lon"]
        args += [
            f"-GPSLatitude={abs(lat)}",
            f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
            f"-GPSLongitude={abs(lon)}",
            f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
        ]
        if "alt" in meta:
            args += [
                f"-GPSAltitude={abs(meta['alt'])}",
                f"-GPSAltitudeRef={'0' if meta['alt'] >= 0 else '1'}",
            ]
    if not args:
        return []
    # Keep the file's own mtime out of it; overwrite in place.
    args += ["-overwrite_original", "-api", "QuickTimeUTC=1", str(media), "-execute"]
    return args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("takeout_dir", type=Path)
    ap.add_argument("-n", "--dry-run", action="store_true")
    ns = ap.parse_args()

    root: Path = ns.takeout_dir
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 1

    media_files = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS
    ]
    print(f"Found {len(media_files)} media file(s) under {root}")
    if not media_files:
        return 0

    blocks: list[str] = []
    with_date = with_gps = no_sidecar = nothing = 0

    for media in media_files:
        sidecar = find_sidecar(media)
        if sidecar is None:
            no_sidecar += 1
            continue
        meta = read_sidecar(sidecar)
        args = build_args(media, meta)
        if not args:
            nothing += 1
            continue
        if "taken" in meta:
            with_date += 1
        if "lat" in meta:
            with_gps += 1
        blocks.extend(args)

    print(f"  will set capture date on: {with_date}")
    print(f"  will set GPS on:          {with_gps}")
    print(f"  no sidecar found:         {no_sidecar}")
    print(f"  sidecar had nothing:      {nothing}")

    if ns.dry_run:
        print("\ndry run: nothing written")
        return 0
    if not blocks:
        print("\nnothing to write")
        return 0

    if not shutil_which("exiftool"):
        print(
            "\nerror: exiftool not found. Install it with:  brew install exiftool",
            file=sys.stderr,
        )
        return 1

    # One exiftool invocation for the whole library: per-file calls would take
    # hours on a big Takeout.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".args", delete=False, encoding="utf-8"
    ) as f:
        f.write("\n".join(blocks) + "\n")
        argfile = f.name

    print("\nWriting EXIF with exiftool (this can take a while)...")
    proc = subprocess.run(
        ["exiftool", "-@", argfile, "-common_args", "-charset", "filename=utf8"],
        check=False,
    )
    Path(argfile).unlink(missing_ok=True)
    if proc.returncode != 0:
        print("exiftool reported errors (see above).", file=sys.stderr)
        return proc.returncode
    print("\nDone. Now upload:  ./scripts/upload_from_mac.sh " + str(root))
    return 0


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


if __name__ == "__main__":
    raise SystemExit(main())
