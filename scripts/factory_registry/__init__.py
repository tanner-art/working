"""Provider- and backend-neutral Threadline Factory registry boundary."""

from .models import (
    DispatchSnapshot,
    Evidence,
    FailureCode,
    Feature,
    Lane,
    Lease,
    PackageKind,
    TaskStatus,
    Worker,
    WorkPackage,
)
from .repository import Registry, RegistryConflict, RegistryError, RegistryNotFound
from .sqlite_registry import SQLiteRegistry

__all__ = [
    "Evidence",
    "DispatchSnapshot",
    "FailureCode",
    "Feature",
    "Lane",
    "Lease",
    "PackageKind",
    "Registry",
    "RegistryConflict",
    "RegistryError",
    "RegistryNotFound",
    "SQLiteRegistry",
    "TaskStatus",
    "Worker",
    "WorkPackage",
]
