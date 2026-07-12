# Bulk-uploading a photo folder (macOS)

`scripts/upload_from_mac.sh` walks a folder and uploads every photo/video to
the server. The server de-duplicates by content (SHA-256), so a file it already
has is reported as "already there" and skipped -- the script is safe to
interrupt and re-run.

## Export from Photos.app first

Do NOT point the script at the `.photoslibrary` bundle. Export the originals:

    Photos.app > select photos > File > Export > Export Unmodified Original...

"Export Unmodified Original" keeps the EXIF (GPS + capture date). The plain
"Export" re-encodes and can strip or rewrite that metadata, which Malmberg uses
for the place and time search, and for the by-year / by-month / by-place stats.

Photos with no EXIF date or GPS (scans, old cameras) can still be tagged by
hand afterwards from the dashboard (per photo, or in bulk from the select bar).

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
