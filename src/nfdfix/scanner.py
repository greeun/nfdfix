"""Walks the given paths and collects the entries that need renaming."""

import os
import unicodedata
from fnmatch import fnmatch
from typing import Iterable, List, Optional, Sequence

from .models import DIR, FILE, SYMLINK, RenameItem
from .plan import build_item, identify_path

DEFAULT_EXCLUDES = (".git", "node_modules", ".venv", "venv", "__pycache__")


def is_hidden(name: str) -> bool:
    """Report whether the name is a hidden entry starting with a dot."""
    return name.startswith(".")


def is_excluded(name: str, patterns: Iterable[str]) -> bool:
    """Report whether the name matches any of the exclude patterns.

    A pattern typed on the keyboard is NFC while the stored name may be NFD,
    so both sides are compared in NFC.
    """
    composed = unicodedata.normalize("NFC", name)
    return any(fnmatch(composed, unicodedata.normalize("NFC", pattern)) for pattern in patterns)


def kind_of(path: str) -> str:
    """Classify an entry. Symbolic links are never followed."""
    if os.path.islink(path):
        return SYMLINK
    if os.path.isdir(path):
        return DIR
    return FILE


def stored_name(parent: str, name: str) -> str:
    """Return the form in which the parent directory stores the named entry.

    APFS finds an entry whatever normalization its name is written in, so a
    name typed in NFC reaches an entry stored in NFD while the string still
    says NFC. Only the directory listing tells which form is stored.
    """
    if unicodedata.normalize("NFC", name) == unicodedata.normalize("NFD", name):
        return name
    try:
        names = os.listdir(parent)
    except OSError:
        return name
    if name in names:
        return name
    wanted = identify_path(os.path.join(parent, name))
    if wanted is None:
        return name
    target = unicodedata.normalize("NFC", name)
    for candidate in names:
        if unicodedata.normalize("NFC", candidate) != target:
            continue
        if identify_path(os.path.join(parent, candidate)) == wanted:
            return candidate
    return name


def stored_path(path: str) -> str:
    """Return the absolute path spelled with the names the filesystem stores.

    A component that is stored as given, or cannot be looked up, is kept.
    """
    resolved = os.sep
    for name in os.path.abspath(path).split(os.sep):
        if name:
            resolved = os.path.join(resolved, stored_name(resolved, name))
    return resolved


def root_item(root: str, patterns: Sequence[str], include_hidden: bool) -> Optional[RenameItem]:
    """Build the item for an input path's own name, honoring the same filters."""
    parent, name = os.path.split(root)
    if not include_hidden and is_hidden(name):
        return None
    if is_excluded(name, patterns):
        return None
    return build_item(parent, name, kind_of(root))


def scan(
    roots: Sequence[str],
    excludes: Iterable[str],
    include_hidden: bool,
    include_root_dirs: bool = False,
) -> List[RenameItem]:
    """Return the entries needing a rename, deepest paths first.

    The walk runs top-down so that excluded directories can be pruned, and the
    collected entries are then sorted by descending path depth. Children must
    be renamed before their parents, otherwise renaming a directory would
    invalidate the paths of everything below it.

    A directory given as a root keeps its own name unless include_root_dirs is
    set; the interactive interface sets it so the chosen directory is renamed
    along with its contents.
    """
    patterns = tuple(excludes)
    items: List[RenameItem] = []

    for root in roots:
        root = os.path.abspath(root)
        walkable = os.path.isdir(root) and not os.path.islink(root)
        if include_root_dirs or not walkable:
            item = root_item(root, patterns, include_hidden)
            if item is not None:
                items.append(item)
        if not walkable:
            continue

        for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            kept = []
            for name in dirnames:
                if is_excluded(name, patterns):
                    continue
                if not include_hidden and is_hidden(name):
                    continue
                kept.append(name)
            dirnames[:] = kept

            for name in list(filenames) + list(kept):
                if not include_hidden and is_hidden(name):
                    continue
                if is_excluded(name, patterns):
                    continue
                item = build_item(current, name, kind_of(os.path.join(current, name)))
                if item is not None:
                    items.append(item)

    items.sort(key=lambda item: item.old_path.count(os.sep), reverse=True)
    return items
