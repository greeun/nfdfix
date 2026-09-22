"""Builds the human-readable output."""

import os
from typing import Sequence

from .models import (
    CONFLICT,
    DIR,
    ERROR,
    FILE,
    MISSING,
    PERMISSION_DENIED,
    RENAMED,
    SKIPPED_STATUSES,
    SYMLINK,
    VOLUME_REJECTED,
    WOULD_RENAME,
    RenameResult,
)

KIND_LABELS = {FILE: "file", DIR: "dir", SYMLINK: "link"}

STATUS_LABELS = {
    CONFLICT: "conflict",
    PERMISSION_DENIED: "denied",
    VOLUME_REJECTED: "rejected",
    MISSING: "missing",
    ERROR: "error",
}


def describe(result: RenameResult, base: str) -> str:
    """Render one result as a single line.

    An NFD name and its NFC form look identical on screen, so the new name is
    not printed next to the old one; only the affected entry is shown.
    """
    item = result.item
    try:
        relative = os.path.relpath(item.old_path, base)
    except ValueError:
        relative = item.old_path
    if relative == os.curdir:
        relative = item.old_name
    if result.status in (WOULD_RENAME, RENAMED):
        label = KIND_LABELS.get(item.kind, item.kind)
        return "  [{0}] {1}".format(label, relative)
    label = STATUS_LABELS.get(result.status, result.status)
    return "  [{0}] {1} ({2})".format(label, relative, result.detail)


def format_header(results: Sequence[RenameResult], applied: bool) -> str:
    """Build the first line of the output."""
    if not results:
        return "Nothing to normalize."
    if applied:
        return "Processed {0} item(s).".format(len(results))
    return "{0} item(s) to normalize. Re-run with --apply to rename them.".format(len(results))


def format_summary(results: Sequence[RenameResult], applied: bool) -> str:
    """Build the one-line tally grouped by status."""
    changed = sum(1 for result in results if result.status in (RENAMED, WOULD_RENAME))
    conflicts = sum(1 for result in results if result.status == CONFLICT)
    skipped = sum(1 for result in results if result.status in SKIPPED_STATUSES)
    head = "renamed" if applied else "to rename"
    return "{0}: {1}, conflicts: {2}, skipped: {3}".format(head, changed, conflicts, skipped)
