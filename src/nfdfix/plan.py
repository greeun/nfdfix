"""Normalization and conflict decisions.

This module receives its filesystem lookup function as an argument, so the
decision logic can be unit tested without creating real files.
"""

import os
import re
import unicodedata
from typing import Callable, Optional, Tuple

from .models import RenameItem

Identity = Optional[Tuple[int, int]]

# Ranges that Apple's decomposition leaves untouched. A character from them was
# written that way on purpose, so composing it would change the name itself.
PRESERVED_RANGES = ((0x2000, 0x2FFF), (0xF900, 0xFAFF), (0x2F800, 0x2FAFF))

_PRESERVED_RUNS = re.compile(
    "(["
    + "".join("{0}-{1}".format(chr(low), chr(high)) for low, high in PRESERVED_RANGES)
    + "]+)"
)


def to_nfc(name: str) -> str:
    """Compose the name to NFC, keeping the characters macOS never decomposes.

    Splitting on the preserved runs leaves them at the odd indices; only the
    runs between them are normalized.
    """
    parts = _PRESERVED_RUNS.split(name)
    return "".join(
        part if index % 2 else unicodedata.normalize("NFC", part)
        for index, part in enumerate(parts)
    )


def needs_normalization(name: str) -> bool:
    """Report whether the name is not in NFC and therefore needs renaming."""
    return to_nfc(name) != name


def build_item(parent: str, name: str, kind: str) -> Optional[RenameItem]:
    """Build an item when renaming is needed, or return None when it is not."""
    normalized = to_nfc(name)
    if normalized == name:
        return None
    return RenameItem(parent=parent, old_name=name, new_name=normalized, kind=kind)


def identify_path(path: str) -> Identity:
    """Return the device and inode numbers of a path, or None when absent."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def check_conflict(
    item: RenameItem,
    identify: Callable[[str], Identity] = identify_path,
) -> bool:
    """Report whether a different entry already occupies the target name.

    APFS ignores normalization differences when comparing names, so the target
    path may appear to exist even when it is the entry itself. Comparing the
    device and inode numbers tells the two cases apart.
    """
    destination = identify(item.new_path)
    if destination is None:
        return False
    return destination != identify(item.old_path)
