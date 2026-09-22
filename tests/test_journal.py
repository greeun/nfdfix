import json
from datetime import datetime

import pytest

from nfdfix.journal import (
    JournalWriter,
    default_journal_path,
    read_records,
    undo_items,
)
from nfdfix.models import DIR, FILE, RenameItem


def make_item(parent, old_name, new_name, kind=FILE):
    return RenameItem(parent=parent, old_name=old_name, new_name=new_name, kind=kind)


def test_journal_writes_header_before_records(tmp_path):
    path = tmp_path / "journal.jsonl"
    with JournalWriter(str(path)) as journal:
        journal.record(make_item("/tmp", "a", "b"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["record"] == "header"
    assert json.loads(lines[1])["from"] == "a"
    assert json.loads(lines[1])["to"] == "b"


def test_journal_is_not_created_without_records(tmp_path):
    path = tmp_path / "journal.jsonl"
    with JournalWriter(str(path)):
        pass
    assert path.exists() is False


def test_read_records_skips_the_header(tmp_path):
    path = tmp_path / "journal.jsonl"
    with JournalWriter(str(path)) as journal:
        journal.record(make_item("/tmp", "a", "b"))
        journal.record(make_item("/tmp", "c", "d"))
    records = read_records(str(path))
    assert [record["from"] for record in records] == ["a", "c"]


def test_undo_items_reverse_the_order_and_swap_names():
    records = [
        {"parent": "/tmp/상위", "from": "하위", "to": "하위NFC", "kind": FILE},
        {"parent": "/tmp", "from": "상위", "to": "상위NFC", "kind": DIR},
    ]
    items = undo_items(records)
    assert [item.old_name for item in items] == ["상위NFC", "하위NFC"]
    assert [item.new_name for item in items] == ["상위", "하위"]
    assert [item.kind for item in items] == [DIR, FILE]


def test_default_journal_path_uses_timestamp():
    path = default_journal_path(now=datetime(2026, 9, 20, 21, 57, 0))
    assert path.endswith("journal-20260920-215700.jsonl")
    assert ".local/state/nfdfix" in path


def test_open_writes_the_header_immediately(tmp_path):
    path = tmp_path / "state" / "journal.jsonl"
    journal = JournalWriter(str(path))
    journal.open()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["record"] == "header"
    journal.record(make_item("/tmp", "a", "b"))
    journal.close()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_open_raises_when_the_journal_cannot_be_written(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    with pytest.raises(OSError):
        JournalWriter(str(blocker / "journal.jsonl")).open()


def test_opened_journal_without_records_is_removed(tmp_path):
    path = tmp_path / "journal.jsonl"
    with JournalWriter(str(path)) as journal:
        journal.open()
    assert path.exists() is False


def test_existing_journal_without_new_records_keeps_its_content(tmp_path):
    path = tmp_path / "journal.jsonl"
    with JournalWriter(str(path)) as journal:
        journal.record(make_item("/tmp", "a", "b"))
    before = path.read_bytes()
    with JournalWriter(str(path)) as journal:
        journal.open()
    assert path.read_bytes() == before
