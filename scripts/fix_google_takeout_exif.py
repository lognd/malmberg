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


# exiftool's FileType -> the extensions that legitimately name that format.
# The first entry is the one we rename to.
_TYPE_EXTS: dict[str, tuple[str, ...]] = {
    "JPEG": (".jpg", ".jpeg"),
    "PNG": (".png",),
    "HEIC": (".heic",),
    "HEIF": (".heif",),
    "AVIF": (".avif",),
    "TIFF": (".tif", ".tiff"),
    "WEBP": (".webp",),
    "GIF": (".gif",),
    "BMP": (".bmp",),
    "MP4": (".mp4", ".m4v"),
    "MOV": (".mov",),
    "AVI": (".avi",),
    "MKV": (".mkv",),
    "WEBM": (".webm",),
}


def detect_types(media_files: list[Path]) -> dict[Path, str]:
    """Ask exiftool what each file ACTUALLY is, ignoring its name.

    One batch call: per-file invocations would take hours on a big Takeout.
    """
    with tempfile.NamedTemporaryFile(
        "w", suffix=".args", delete=False, encoding="utf-8"
    ) as f:
        f.write("-m\n-p\n$FilePath\t$FileType\n")
        f.write("\n".join(str(p) for p in media_files) + "\n")
        argfile = f.name
    try:
        proc = subprocess.run(
            ["exiftool", "-@", argfile, "-charset", "filename=utf8"],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(argfile).unlink(missing_ok=True)

    # exiftool echoes $FilePath as an absolute path regardless of how it was
    # given, so key on the resolved path or every lookup misses.
    out: dict[Path, str] = {}
    for line in proc.stdout.splitlines():
        path, _, ftype = line.partition("\t")
        if path and ftype:
            out[Path(path).resolve()] = ftype.strip().upper()
    return out


def rename_mismatched(media_files: list[Path], *, dry_run: bool) -> tuple[list[Path], int]:
    """Rename files whose extension lies about their contents.

    Google re-encodes some photos to JPEG but keeps the original ``.HEIC``
    name.  exiftool refuses to write to a file whose extension contradicts its
    contents ("Not a valid HEIC (looks more like a JPEG)") and writes NOTHING
    to it -- so those photos would keep arriving with no date and no GPS, which
    is the exact problem this script exists to solve.  No flag suppresses that;
    the name has to match the bytes.  Fixing the name also stops anything
    downstream that trusts the extension from mis-handling the file.

    Returns the (possibly renamed) file list and the number renamed.
    """
    types = detect_types(media_files)
    result: list[Path] = []
    renamed = 0
    for media in media_files:
        ftype = types.get(media.resolve())
        exts = _TYPE_EXTS.get(ftype or "")
        if exts is None or media.suffix.lower() in exts:
            result.append(media)  # unknown type, or the name already tells the truth
            continue
        target = media.with_suffix(exts[0])
        # Never clobber a real, different photo that already owns the name.
        n = 1
        while target.exists():
            target = media.with_name(f"{media.stem}-{n}{exts[0]}")
            n += 1
        print(f"  {media.name} is really {ftype} -> {target.name}")
        renamed += 1
        if dry_run:
            result.append(media)  # nothing moved; keep reporting against the old name
            continue
        media.rename(target)
        result.append(target)
    return result, renamed


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

    if not shutil_which("exiftool"):
        print(
            "\nerror: exiftool not found. Install it with:  brew install exiftool",
            file=sys.stderr,
        )
        return 1

    # Match sidecars BEFORE any rename: the sidecar is named after the file's
    # ORIGINAL name (IMG_1.HEIC.json), so renaming first would orphan it.
    pending: list[tuple[Path, dict]] = []
    no_sidecar = nothing = 0
    for media in media_files:
        sidecar = find_sidecar(media)
        if sidecar is None:
            no_sidecar += 1
            continue
        meta = read_sidecar(sidecar)
        if not build_args(media, meta):
            nothing += 1
            continue
        pending.append((media, meta))

    # Then fix any name that lies about its contents, or exiftool will refuse to
    # write to it and the photo keeps its missing date/GPS.
    paths, renamed = rename_mismatched([m for m, _ in pending], dry_run=ns.dry_run)

    blocks: list[str] = []
    with_date = with_gps = 0
    for path, (_, meta) in zip(paths, pending):
        if "taken" in meta:
            with_date += 1
        if "lat" in meta:
            with_gps += 1
        blocks.extend(build_args(path, meta))

    print(f"  will set capture date on: {with_date}")
    print(f"  will set GPS on:          {with_gps}")
    print(f"  misnamed (renamed):       {renamed}")
    print(f"  no sidecar found:         {no_sidecar}")
    print(f"  sidecar had nothing:      {nothing}")

    if ns.dry_run:
        print("\ndry run: nothing written, nothing renamed")
        return 0
    if not blocks:
        print("\nnothing to write")
        return 0

    # One exiftool invocation for the whole library: per-file calls would take
    # hours on a big Takeout.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".args", delete=False, encoding="utf-8"
    ) as f:
        f.write("\n".join(blocks) + "\n")
        argfile = f.name

    print("\nWriting EXIF with exiftool (this can take a while)...")
    # -m suppresses errors exiftool itself marks [minor], e.g. "GPS pointer
    # references previous IFD0 directory" on a slightly malformed EXIF block.
    # Without it exiftool refuses to write that file at all and the photo keeps
    # its missing date/GPS over a defect it is willing to repair.  It does NOT
    # cover the extension/content mismatch above -- that one is fatal whatever
    # flags are passed, which is why those files get renamed instead.
    #
    # It goes in -common_args because the argfile is a series of -execute
    # blocks, each its own command; a plain leading option would apply only to
    # the first block.
    proc = subprocess.run(
        ["exiftool", "-@", argfile, "-common_args", "-m", "-charset", "filename=utf8"],
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
