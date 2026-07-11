"""Provider-neutral cloud interfaces: RemotePhoto, CloudProvider, CloudError.

Every provider is synchronous/blocking (pyicloud and google-auth are sync
libraries); CloudSyncEngine wraps calls in an executor, mirroring the
detect_faces pattern in faces/worker.py. Providers must never raise across
this boundary -- every failure is a CloudError variant in a Result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from typani.error_set import ErrorSet
from typani.result import Result


class CloudError(ErrorSet):
    """Failure modes for cloud provider calls and sync-state persistence."""

    NotConfigured = "The provider's optional dependency or credentials are missing"
    AuthError = "Authentication with the cloud provider failed or expired"
    NetworkError = "A network request to the cloud provider failed"
    NotFound = "The remote item does not exist"
    RateLimited = "The cloud provider throttled the request"
    Unsupported = "The cloud provider does not support this operation"
    StateError = "The cloud sync state file could not be read or written"
    AuditError = "The deletion audit log could not be written"


class RemotePhoto(BaseModel):
    """One item as reported by a cloud provider's listing."""

    remote_id: str
    """Provider-scoped stable identifier for this item."""
    filename: str
    sha256: Optional[str] = None
    """Content digest when the provider reports one; usually None."""
    size_bytes: Optional[int] = None
    created_at: Optional[datetime] = None
    """When the item was created/taken according to the provider."""


class CloudProvider(ABC):
    """Blocking interface a cloud photo source must implement.

    Implementations lazily import their optional dependency at module import
    time (try/except ImportError) and report is_configured() == False when it
    is absent -- constructing a provider never raises.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable machine name for state keys and API routing (e.g. 'icloud')."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """True only if the optional dependency imported and credentials exist."""
        ...

    @abstractmethod
    def list_remote(self) -> Result[list[RemotePhoto], CloudError]:
        """Enumerate every remote item this app is permitted to see."""
        ...

    @abstractmethod
    def download(self, remote_id: str) -> Result[bytes, CloudError]:
        """Fetch the original bytes of one remote item."""
        ...

    @abstractmethod
    def delete(self, remote_id: str) -> Result[None, CloudError]:
        """Remove one remote item; Err(Unsupported) if the API cannot delete."""
        ...
