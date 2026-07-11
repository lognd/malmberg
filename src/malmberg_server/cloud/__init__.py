"""Cloud pull-sync: download photos from cloud providers, verify, then delete.

Public surface of the cloud package. Providers degrade gracefully when their
optional dependency extras (cloud-icloud, cloud-googlephotos) are missing --
importing this package never raises.
"""

from __future__ import annotations

from malmberg_server.cloud.base import CloudError, CloudProvider, RemotePhoto
from malmberg_server.cloud.google_photos import GooglePhotosProvider
from malmberg_server.cloud.icloud import ICloudProvider
from malmberg_server.cloud.sync import (
    CloudStatus,
    CloudSyncAck,
    CloudSyncEngine,
    CloudSyncRecord,
    CloudSyncRequest,
    CloudSyncState,
    ProviderStatus,
    ProviderSyncMeta,
    SyncResult,
    cloud_state_path,
    run_cloud_sync_worker,
    state_key,
)
from malmberg_server.cloud.verify_and_delete import (
    CloudDeleteRequest,
    DeletableEntry,
    DeletablePage,
    DeleteReport,
    DeletionAuditRecord,
    append_audit_line,
    audit_log_path,
    delete_verified,
    dry_run_deletable,
)

__all__ = [
    "CloudError",
    "CloudProvider",
    "RemotePhoto",
    "GooglePhotosProvider",
    "ICloudProvider",
    "CloudStatus",
    "CloudSyncAck",
    "CloudSyncEngine",
    "CloudSyncRecord",
    "CloudSyncRequest",
    "CloudSyncState",
    "ProviderStatus",
    "ProviderSyncMeta",
    "SyncResult",
    "cloud_state_path",
    "run_cloud_sync_worker",
    "state_key",
    "CloudDeleteRequest",
    "DeletableEntry",
    "DeletablePage",
    "DeleteReport",
    "DeletionAuditRecord",
    "append_audit_line",
    "audit_log_path",
    "delete_verified",
    "dry_run_deletable",
]
