"""Error variants for the backup subsystem."""

from __future__ import annotations

from typani.error_set import ErrorSet


class BackupError(ErrorSet):
    """Errors that can occur during ZFS snapshot management."""

    CommandFailed = "The zfs/zpool command returned a non-zero exit code"
    ParseError = "Could not parse the output of a zfs command"
    NotFound = "The requested snapshot or dataset does not exist"
    IOError = "An I/O error occurred while writing the audit log"
