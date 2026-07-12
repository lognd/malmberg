#!/usr/bin/env bash
#
# Bulk-upload every photo/video in a folder to a Malmberg server.
#
# The server de-duplicates by file content (SHA-256), so a file it already has
# is reported as "already there" and skipped.  That makes this script safe to
# re-run: interrupt it, run it again, and it picks up where it left off.
#
# Usage:
#   ./upload_from_mac.sh [options] DIRECTORY
#
# Options:
#   -s URL   Server base URL (default: $MALMBERG_SERVER or http://192.168.69.69:8444)
#   -j N     Upload N files in parallel (default: 3)
#   -n       Dry run: list what would be uploaded, upload nothing
#   -h       Show this help
#
# macOS note: if your photos live in Photos.app, do NOT point this at the
# .photoslibrary bundle.  Export them first with
#   File > Export > Export Unmodified Original
# so the originals keep their EXIF (GPS + capture date).  A plain "Export"
# re-encodes and can strip that metadata, which Malmberg uses for the
# place/time search.

set -u

SERVER="${MALMBERG_SERVER:-http://192.168.69.69:8444}"
JOBS=3
DRY_RUN=0

usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while getopts ":s:j:nh" opt; do
  case "$opt" in
    s) SERVER="$OPTARG" ;;
    j) JOBS="$OPTARG" ;;
    n) DRY_RUN=1 ;;
    h) usage 0 ;;
    *) echo "Unknown option: -$OPTARG" >&2; usage 1 ;;
  esac
done
shift $((OPTIND - 1))

DIR="${1:-}"
if [ -z "$DIR" ] || [ ! -d "$DIR" ]; then
  echo "error: give a directory to upload from" >&2
  usage 1
fi

SERVER="${SERVER%/}"

# Fail fast if the server is not reachable, rather than 500 curl errors.
if ! curl -fsS -m 10 -o /dev/null "$SERVER/status"; then
  echo "error: cannot reach Malmberg server at $SERVER" >&2
  echo "       (set -s URL or MALMBERG_SERVER)" >&2
  exit 1
fi
echo "Server:  $SERVER"
echo "Folder:  $DIR"

# Extensions Malmberg ingests. -iname so .JPG and .jpg both match.
EXTS="jpg jpeg png heic heif avif tif tiff webp gif bmp mp4 mov m4v avi mkv webm"
FIND_ARGS=()
first=1
for e in $EXTS; do
  if [ $first -eq 1 ]; then first=0; else FIND_ARGS+=(-o); fi
  FIND_ARGS+=(-iname "*.${e}")
done

# NUL-delimited so spaces/newlines in filenames are safe.
LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT
find "$DIR" -type f \( "${FIND_ARGS[@]}" \) -print0 > "$LIST"

TOTAL=$(tr -d -c '\0' < "$LIST" | wc -c | tr -d ' ')
echo "Found:   $TOTAL media file(s)"
[ "$TOTAL" -eq 0 ] && exit 0

if [ "$DRY_RUN" -eq 1 ]; then
  echo "--- dry run: would upload ---"
  tr '\0' '\n' < "$LIST"
  exit 0
fi

RESULTS="$(mktemp)"
trap 'rm -f "$LIST" "$RESULTS"' EXIT

# One upload. Prints a single status word so the parent can tally results.
upload_one() {
  file="$1"; server="$2"; results="$3"
  code=$(curl -sS -o /dev/null -w '%{http_code}' -m 300 \
           -F "file=@${file}" "${server}/upload" 2>/dev/null)
  case "$code" in
    200) echo "ok"        >> "$results"; printf '  uploaded  %s\n' "$file" ;;
    409) echo "dup"       >> "$results"; printf '  already   %s\n' "$file" ;;
    413) echo "toobig"    >> "$results"; printf '  TOO BIG   %s\n' "$file" ;;
    *)   echo "fail"      >> "$results"; printf '  FAILED(%s) %s\n' "$code" "$file" ;;
  esac
}
export -f upload_one

echo "Uploading with $JOBS parallel job(s)..."
# xargs -0 keeps NUL-delimited paths intact; -P runs JOBS at a time.
xargs -0 -P "$JOBS" -I {} bash -c 'upload_one "$@"' _ {} "$SERVER" "$RESULTS" < "$LIST"

ok=$(grep -c '^ok$'     "$RESULTS" 2>/dev/null || true)
dup=$(grep -c '^dup$'    "$RESULTS" 2>/dev/null || true)
big=$(grep -c '^toobig$' "$RESULTS" 2>/dev/null || true)
bad=$(grep -c '^fail$'   "$RESULTS" 2>/dev/null || true)

echo
echo "Done."
echo "  uploaded:     ${ok:-0}"
echo "  already there:${dup:-0}"
echo "  too big:      ${big:-0}"
echo "  failed:       ${bad:-0}"
[ "${bad:-0}" -gt 0 ] && exit 1
exit 0
