"""Data structures and status values shared across modules."""

import os
from dataclasses import dataclass

FILE = "file"
DIR = "dir"
SYMLINK = "symlink"

WOULD_RENAME = "would_rename"
RENAMED = "renamed"
CONFLICT = "conflict"
PERMISSION_DENIED = "permission_denied"
VOLUME_REJECTED = "volume_rejected"
MISSING = "missing"
ERROR = "error"

SKIPPED_STATUSES = (PERMISSION_DENIED, VOLUME_REJECTED, MISSING, ERROR)


@dataclass(frozen=True)
class RenameItem:
    """A single entry whose name is to be changed."""

    parent: str
    old_name: str
    new_name: str
    kind: str

    @property
    def old_path(self) -> str:
        return os.path.join(self.parent, self.old_name)

    @property
    def new_path(self) -> str:
        return os.path.join(self.parent, self.new_name)


@dataclass(frozen=True)
class RenameResult:
    """The outcome of processing a single entry."""

    item: RenameItem
    status: str
    detail: str = ""
