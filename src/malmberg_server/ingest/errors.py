"""Error set for the server ingest pipeline."""

from __future__ import annotations

from typani.error_set import ErrorSet


class IngestError(ErrorSet):
    FileTooLarge = "File exceeds the configured maximum upload size"
    IOError = "An I/O error occurred while reading or writing the file"
    ExifError = "EXIF metadata could not be extracted from the file"
    DuplicateFile = "A file with the same SHA-256 digest already exists"
    NotFound = "The requested media item does not exist"
    StorageError = "The media store could not persist or read its index"
