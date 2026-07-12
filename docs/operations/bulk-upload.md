# Bulk-uploading a photo folder (macOS)

`scripts/upload_from_mac.sh` walks a folder and uploads every photo/video to
the server. The server de-duplicates by content (SHA-256), so a file it already
has is reported as "already there" and skipped -- the script is safe to
interrupt and re-run.

## Getting photos out of Photos.app

Never drag the `.photoslibrary` bundle onto the dashboard drop zone. It is a
package: besides the originals it holds derivatives/thumbnails and a database.
Those derivatives are different bytes, so content-dedup cannot catch them and
you would import low-quality duplicates.

### Option 1 -- Export (safest; keeps your edits)

If you use iCloud Photos, first set Photos > Settings > iCloud >
**Download Originals to this Mac** and let it finish. With "Optimize Mac
Storage" on, many originals are not actually on disk.

    Photos.app > Edit > Select All > File > Export >
      Export Unmodified Original For N Photos...
      Subfolder Format: None    File Naming: Use File Name

**Export Unmodified Original** keeps the EXIF (GPS + capture date). The plain
"Export..." re-encodes and can strip or rewrite that metadata, which Malmberg
uses for place/time search and the by-year / by-month / by-place stats.
Needs roughly as much free disk as the library.

### Option 2 -- Upload the originals in place (no export, no extra disk)

Quit Photos.app, then point the script at the library. It detects the bundle
and narrows to its `originals/` folder automatically, skipping derivatives and
the database:

    ./scripts/upload_from_mac.sh -n "$HOME/Pictures/Photos Library.photoslibrary"

Filenames there are UUIDs, which is fine -- Malmberg reads date/place from EXIF
and dedups by content. Caveat: this gives ORIGINALS ONLY (not your edits), and
Live Photos bring a paired .mov.

Photos with no EXIF date or GPS (scans, old cameras) can still be tagged by
hand afterwards from the dashboard (per photo, or in bulk from the select bar).

## Google Photos (Takeout) -- fix the EXIF first

Google Takeout is the only way to get your whole Google Photos library: the
Photos API cannot read photos the app did not upload (see cloud-sync.md).

**Takeout does not keep your location in the image files.** It strips GPS out
and writes the real metadata into a per-photo JSON sidecar
(`IMG_1234.jpg.json`, or `IMG_1234.jpg.supplemental-metadata.json` in newer
exports). Upload the photos as-is and most arrive with no place and often no
capture date, so they never appear in the place search, the time filters, or
the by-year / by-month / by-place stats.

Bake the sidecars back into the files first:

    brew install exiftool
    python3 scripts/fix_google_takeout_exif.py -n ~/Downloads/Takeout   # dry run
    python3 scripts/fix_google_takeout_exif.py    ~/Downloads/Takeout
    ./scripts/upload_from_mac.sh                  ~/Downloads/Takeout

The dry run reports how many photos will get a capture date, how many will get
GPS, and how many have no sidecar at all. It handles the sidecar naming
variants (classic, `supplemental-metadata`, and the `IMG_0003(1).jpg` ->
`IMG_0003.jpg(1).json` duplicate quirk) and ignores Takeout's `0.0, 0.0`
"no location" marker rather than geocoding those photos into the ocean.

When requesting the Takeout, choose Google Photos only, and prefer larger
archive parts (e.g. 50 GB) so you unzip fewer files.

## Run it

    ./scripts/upload_from_mac.sh ~/Desktop/exported-photos

Options:

    -s URL   server base URL (default: $MALMBERG_SERVER, else the LAN server)
    -j N     upload N files in parallel (default: 3)
    -n       dry run -- list what would be uploaded, upload nothing
    -h       help

Always start with a dry run to confirm it picked up the right files:

    ./scripts/upload_from_mac.sh -n ~/Desktop/exported-photos

## What the summary means

- `uploaded`      -- new photo, now in the library
- `already there` -- the server already has this exact file (409); nothing to do
- `too big`       -- over the server's max upload size (`max_upload_mb`)
- `failed`        -- anything else; the HTTP code is printed next to the file

Faces, reverse-geocoded places, and thumbnails are all filled in by the server
in the background after upload, so a new photo may take a little while to appear
in the People section and the place search.
