"""Records renames as JSON Lines and builds the undo plan."""

import json
import os
from datetime import datetime
from typing import List, Optional

from . import __version__
from .models import RenameItem

HEADER_RECORD = "header"


class JournalWriter:
    """Writes one record per rename.

    Callers open the journal before the first rename, so a path that cannot
    be written stops the run before anything changes. A journal that ends up
    without records is removed again, or cut back to its previous size when
    the file already existed.
    """

    def __init__(self, path: str):
        self.path = path
        self._handle = None
        self._previous_size: Optional[int] = None
        self._records = 0

    def __enter__(self) -> "JournalWriter":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False

    def open(self) -> None:
        """Create the journal and write its header, raising OSError on failure."""
        if self._handle is not None:
            return
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        try:
            self._previous_size = os.path.getsize(self.path)
        except OSError:
            self._previous_size = None
        self._handle = open(self.path, "a", encoding="utf-8")
        try:
            self._write(
                {
                    "ts": datetime.now().astimezone().isoformat(),
                    "tool": "nfdfix",
                    "version": __version__,
                    "record": HEADER_RECORD,
                }
            )
        except OSError:
            self.close()
            raise

    def close(self) -> None:
        """Close the journal, leaving no trace when nothing was recorded."""
        if self._handle is None:
            return
        self._handle.close()
        self._handle = None
        if self._records:
            return
        try:
            if self._previous_size is None:
                os.remove(self.path)
            else:
                os.truncate(self.path, self._previous_size)
        except OSError:
            pass

    def _write(self, payload: dict) -> None:
        self._handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._handle.flush()

    def record(self, item: RenameItem) -> None:
        """Record one entry that was renamed successfully."""
        if self._handle is None:
            self.open()
        self._write(
            {
                "ts": datetime.now().astimezone().isoformat(),
                "parent": item.parent,
                "from": item.old_name,
                "to": item.new_name,
                "kind": item.kind,
            }
        )
        self._records += 1


def read_records(path: str) -> List[dict]:
    """Read the rename records from a journal, skipping its header."""
    records: List[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("record") == HEADER_RECORD:
                continue
            records.append(payload)
    return records


def undo_items(records: List[dict]) -> List[RenameItem]:
    """Reverse the records into items that restore the original names.

    A parent directory must be restored before the entries below it, so the
    records are replayed in reverse order.
    """
    items: List[RenameItem] = []
    for record in reversed(records):
        items.append(
            RenameItem(
                parent=record["parent"],
                old_name=record["to"],
                new_name=record["from"],
                kind=record["kind"],
            )
        )
    return items


def default_journal_path(now: Optional[datetime] = None) -> str:
    """Build the default journal path."""
    moment = now or datetime.now()
    base = os.path.join(os.path.expanduser("~"), ".local", "state", "nfdfix")
    return os.path.join(base, "journal-" + moment.strftime("%Y%m%d-%H%M%S") + ".jsonl")
