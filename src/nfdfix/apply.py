"""Performs the renames and verifies what the filesystem actually stored."""

import os
import stat
from typing import Callable, List, Optional, Sequence, Tuple
from uuid import uuid4

try:
    import fcntl
except ImportError:  # not a POSIX system
    fcntl = None

from .journal import JournalWriter
from .models import (
    CONFLICT,
    ERROR,
    MISSING,
    PERMISSION_DENIED,
    RENAMED,
    VOLUME_REJECTED,
    RenameItem,
    RenameResult,
)
from .plan import Identity, check_conflict, identify_path

# Opens a symbolic link itself. Older Pythons lack the name; this is its value
# on macOS, the only system that also has F_GETPATH.
O_SYMLINK = getattr(os, "O_SYMLINK", 0x200000)

# MAXPATHLEN on macOS, which is also the largest buffer fcntl accepts.
PATH_BUFFER = 1024

# st_flags bit of a cloud placeholder whose content is not on disk (macOS).
SF_DATALESS = 0x40000000


def is_dataless(path: str) -> bool:
    """Report whether the entry is a placeholder that opening would download."""
    try:
        return bool(getattr(os.lstat(path), "st_flags", 0) & SF_DATALESS)
    except OSError:
        return False


def stored_name_by_handle(path: str) -> Optional[str]:
    """Return the name the filesystem stores for the entry, or None.

    fcntl(F_GETPATH) reports the stored form without listing the directory,
    even when the entry was reached through a path in another normalization
    form. The entry is opened without following a symbolic link and without
    blocking on a FIFO. None means the handle cannot answer: the system has no
    F_GETPATH, the entry is a dataless placeholder, it cannot be opened, or it
    is a file with several hard links, whose reported path may belong to
    another link.
    """
    getpath = getattr(fcntl, "F_GETPATH", None)
    if fcntl is None or getpath is None or is_dataless(path):
        return None
    try:
        descriptor = os.open(path, os.O_RDONLY | O_SYMLINK | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) and info.st_nlink > 1:
            return None
        buffer = fcntl.fcntl(descriptor, getpath, bytes(PATH_BUFFER))
    except OSError:
        return None
    finally:
        os.close(descriptor)
    return os.path.basename(os.fsdecode(buffer.split(b"\0", 1)[0]))


def stored_names(parent: str) -> List[bytes]:
    """Return the names a directory actually stores, as UTF-8 bytes."""
    try:
        return sorted(name.encode("utf-8") for name in os.listdir(parent))
    except OSError:
        return []


def is_stored_as(parent: str, name: str) -> bool:
    """Report whether the directory stores the name in exactly this form.

    The file handle answers directly; listing the directory is the fallback.
    """
    stored = stored_name_by_handle(os.path.join(parent, name))
    if stored is not None:
        return stored == name
    return name.encode("utf-8") in stored_names(parent)


def _restore_from_temporary(item: RenameItem, temporary: str, error: OSError) -> RenameResult:
    """Put the entry back under its original name after a failed retry."""
    try:
        os.rename(temporary, item.old_path)
    except OSError:
        return RenameResult(
            item=item,
            status=ERROR,
            detail="{0}; the entry was left at {1}".format(error, temporary),
        )
    return RenameResult(
        item=item,
        status=ERROR,
        detail="{0}; the original name was restored".format(error),
    )


def _retry_through_temporary(item: RenameItem) -> RenameResult:
    """Retry the rename by way of a temporary name.

    On a filesystem that ignores normalization, a single rename may leave the
    stored name untouched. The entry then still carries its original name.
    When the second step fails, the entry is moved back so it never stays
    under the hidden temporary name.
    """
    temporary = os.path.join(item.parent, ".nfdfix-tmp-" + uuid4().hex)
    try:
        os.rename(item.old_path, temporary)
    except OSError as error:
        return RenameResult(item=item, status=ERROR, detail=str(error))
    try:
        os.rename(temporary, item.new_path)
    except OSError as error:
        return _restore_from_temporary(item, temporary, error)
    if is_stored_as(item.parent, item.new_name):
        return RenameResult(item=item, status=RENAMED)
    return RenameResult(
        item=item,
        status=VOLUME_REJECTED,
        detail="this volume does not store the name in that form",
    )


def apply_item(
    item: RenameItem,
    identify: Callable[[str], Identity] = identify_path,
) -> RenameResult:
    """Rename a single entry and verify the result."""
    if identify(item.old_path) is None:
        return RenameResult(item=item, status=MISSING, detail="the source entry is gone")
    if check_conflict(item, identify=identify):
        return RenameResult(
            item=item,
            status=CONFLICT,
            detail="a different entry already uses this name",
        )
    try:
        os.rename(item.old_path, item.new_path)
    except PermissionError as error:
        return RenameResult(item=item, status=PERMISSION_DENIED, detail=str(error))
    except FileNotFoundError as error:
        return RenameResult(item=item, status=MISSING, detail=str(error))
    except OSError as error:
        return RenameResult(item=item, status=ERROR, detail=str(error))
    if is_stored_as(item.parent, item.new_name):
        return RenameResult(item=item, status=RENAMED)
    return _retry_through_temporary(item)


def apply_items(
    items: Sequence[RenameItem],
    journal_path: Optional[str] = None,
) -> Tuple[List[RenameResult], Optional[str]]:
    """Rename the items in order, recording each success in a journal.

    The journal is opened before the first rename, so a path that cannot be
    written leaves everything untouched. A record that cannot be written stops
    the run, because the renames after it could no longer be undone. The
    second value describes either failure, and is None otherwise.
    """
    if journal_path is None or not items:
        return [apply_item(item) for item in items], None
    results: List[RenameResult] = []
    with JournalWriter(journal_path) as journal:
        try:
            journal.open()
        except OSError as error:
            return results, "cannot write the journal: {0}".format(error)
        for item in items:
            result = apply_item(item)
            results.append(result)
            if result.status != RENAMED:
                continue
            try:
                journal.record(item)
            except OSError as error:
                return results, (
                    "cannot write the journal: {0}; {1} was renamed but not "
                    "recorded, so the run stopped".format(error, item.new_path)
                )
    return results, None
