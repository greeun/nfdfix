import fcntl
import os
import signal
import unicodedata
from contextlib import contextmanager

import pytest

from nfdfix import apply as apply_module
from nfdfix.apply import (
    apply_item,
    apply_items,
    is_stored_as,
    stored_name_by_handle,
    stored_names,
)
from nfdfix.journal import JournalWriter, read_records
from nfdfix.models import (
    CONFLICT,
    ERROR,
    FILE,
    MISSING,
    PERMISSION_DENIED,
    RENAMED,
    RenameItem,
)
from nfdfix.plan import build_item

NFD_FILE = unicodedata.normalize("NFD", "한글문서.txt")
NFC_FILE = unicodedata.normalize("NFC", "한글문서.txt")


def listing(path):
    return sorted(name.encode("utf-8") for name in os.listdir(str(path)))


def test_stored_names_returns_utf8_bytes(tmp_path):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    assert stored_names(str(tmp_path)) == [NFD_FILE.encode("utf-8")]


def test_is_stored_as_distinguishes_nfd_from_nfc(tmp_path):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    assert is_stored_as(str(tmp_path), NFD_FILE) is True
    assert is_stored_as(str(tmp_path), NFC_FILE) is False


def test_apply_renames_nfd_file_to_nfc(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    result = apply_item(build_item(str(tmp_path), NFD_FILE, FILE))
    assert result.status == RENAMED
    assert listing(tmp_path) == [NFC_FILE.encode("utf-8")]


def test_apply_preserves_file_content(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    apply_item(build_item(str(tmp_path), NFD_FILE, FILE))
    assert (tmp_path / NFC_FILE).read_text(encoding="utf-8") == "내용"


def test_apply_reports_missing_when_source_is_gone(tmp_path):
    result = apply_item(build_item(str(tmp_path), NFD_FILE, FILE))
    assert result.status == MISSING


def test_apply_reports_conflict_when_destination_is_another_entry(tmp_path):
    item = build_item(str(tmp_path), NFD_FILE, FILE)
    identities = {item.old_path: (1, 1), item.new_path: (1, 2)}
    result = apply_item(item, identify=identities.get)
    assert result.status == CONFLICT


def test_apply_reports_permission_denied_on_a_read_only_directory(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("running as root bypasses the permission restriction")
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / NFD_FILE).write_text("내용", encoding="utf-8")
    os.chmod(str(protected), 0o500)
    try:
        result = apply_item(build_item(str(protected), NFD_FILE, FILE))
        assert result.status == PERMISSION_DENIED
        assert listing(protected) == [NFD_FILE.encode("utf-8")]
    finally:
        os.chmod(str(protected), 0o700)


def test_apply_can_restore_an_nfd_name(tmp_path):
    (tmp_path / NFC_FILE).write_text("내용", encoding="utf-8")
    item = RenameItem(parent=str(tmp_path), old_name=NFC_FILE, new_name=NFD_FILE, kind=FILE)
    result = apply_item(item)
    assert result.status == RENAMED
    assert listing(tmp_path) == [NFD_FILE.encode("utf-8")]


needs_getpath = pytest.mark.skipif(
    not hasattr(fcntl, "F_GETPATH"), reason="fcntl F_GETPATH is macOS only"
)


@contextmanager
def deadline(seconds):
    """Fail instead of hanging when a call blocks."""

    def expire(signum, frame):
        raise TimeoutError("the call blocked")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@needs_getpath
def test_handle_reports_the_stored_form_through_an_nfc_path(tmp_path):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    typed = os.path.join(str(tmp_path), NFC_FILE)
    if not os.path.lexists(typed):
        pytest.skip("this filesystem tells normalization forms apart")
    assert stored_name_by_handle(typed) == NFD_FILE


@needs_getpath
def test_handle_reports_a_symbolic_link_itself(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    os.symlink(str(target), str(tmp_path / NFD_FILE))
    assert stored_name_by_handle(str(tmp_path / NFD_FILE)) == NFD_FILE


@needs_getpath
def test_handle_does_not_block_on_a_fifo(tmp_path):
    os.mkfifo(str(tmp_path / NFD_FILE))
    with deadline(3):
        assert stored_name_by_handle(str(tmp_path / NFD_FILE)) == NFD_FILE


@needs_getpath
def test_handle_gives_up_on_a_hard_linked_file(tmp_path):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    os.link(str(tmp_path / NFD_FILE), str(tmp_path / "other.txt"))
    assert stored_name_by_handle(str(tmp_path / NFD_FILE)) is None


def test_handle_gives_up_without_f_getpath(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_module, "fcntl", None)
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    assert stored_name_by_handle(str(tmp_path / NFD_FILE)) is None


def test_handle_gives_up_on_a_missing_entry(tmp_path):
    assert stored_name_by_handle(str(tmp_path / NFD_FILE)) is None


def test_handle_does_not_open_a_dataless_file(tmp_path, monkeypatch):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    monkeypatch.setattr(apply_module, "is_dataless", lambda path: True)

    def refuse(*args):
        raise AssertionError("opened a dataless file")

    monkeypatch.setattr(apply_module.os, "open", refuse)
    assert stored_name_by_handle(str(tmp_path / NFD_FILE)) is None


def test_is_dataless_reads_the_file_flags(tmp_path):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    assert apply_module.is_dataless(str(tmp_path / NFD_FILE)) is False
    assert apply_module.is_dataless(str(tmp_path / "missing")) is False


@needs_getpath
def test_is_stored_as_does_not_list_the_directory_when_the_handle_answers(tmp_path, monkeypatch):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")

    def refuse(parent):
        raise AssertionError("listed the directory")

    monkeypatch.setattr(apply_module, "stored_names", refuse)
    assert is_stored_as(str(tmp_path), NFD_FILE) is True


def test_is_stored_as_lists_the_directory_without_the_handle(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_module, "fcntl", None)
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    assert is_stored_as(str(tmp_path), NFD_FILE) is True
    assert is_stored_as(str(tmp_path), NFC_FILE) is False


def script_renames(monkeypatch, steps):
    """Replace os.rename; each call takes the next step: skip, run or fail.

    "skip" leaves the entry as it is, which is what a volume that refuses the
    NFC form does to the first rename.
    """
    real = os.rename
    calls = []

    def scripted(source, destination):
        step = steps[len(calls)]
        calls.append((source, destination))
        if step == "fail":
            raise OSError(5, "Input/output error", source, None, destination)
        if step == "run":
            real(source, destination)

    monkeypatch.setattr(os, "rename", scripted)
    return calls


def test_retry_that_cannot_move_to_the_temporary_name_changes_nothing(tmp_path, monkeypatch):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    item = build_item(str(tmp_path), NFD_FILE, FILE)
    script_renames(monkeypatch, ["skip", "fail"])
    result = apply_item(item)
    assert result.status == ERROR
    assert listing(tmp_path) == [NFD_FILE.encode("utf-8")]


def test_retry_restores_the_original_name_when_the_final_rename_fails(tmp_path, monkeypatch):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    item = build_item(str(tmp_path), NFD_FILE, FILE)
    script_renames(monkeypatch, ["skip", "run", "fail", "run"])
    result = apply_item(item)
    assert result.status == ERROR
    assert "the original name was restored" in result.detail
    assert listing(tmp_path) == [NFD_FILE.encode("utf-8")]


def test_retry_names_the_temporary_path_when_the_rollback_fails(tmp_path, monkeypatch):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    item = build_item(str(tmp_path), NFD_FILE, FILE)
    calls = script_renames(monkeypatch, ["skip", "run", "fail", "fail"])
    result = apply_item(item)
    temporary = calls[1][1]
    assert result.status == ERROR
    assert "the entry was left at " + temporary in result.detail
    assert listing(tmp_path) == [os.path.basename(temporary).encode("utf-8")]


def test_apply_items_records_each_rename(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    log = tmp_path / "journal.jsonl"
    results, problem = apply_items([build_item(str(tmp_path), NFD_FILE, FILE)], str(log))
    assert problem is None
    assert [result.status for result in results] == [RENAMED]
    assert [record["from"] for record in read_records(str(log))] == [NFD_FILE]


def test_apply_items_renames_nothing_when_the_journal_cannot_be_opened(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    item = build_item(str(tmp_path), NFD_FILE, FILE)
    results, problem = apply_items([item], str(blocker / "journal.jsonl"))
    assert results == []
    assert problem.startswith("cannot write the journal")
    assert NFD_FILE.encode("utf-8") in listing(tmp_path)


def test_apply_items_stops_when_a_record_cannot_be_written(tmp_path, monkeypatch):
    first = unicodedata.normalize("NFD", "가.txt")
    second = unicodedata.normalize("NFD", "나.txt")
    for name in (first, second):
        (tmp_path / name).write_text("내용", encoding="utf-8")

    def broken(self, item):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(JournalWriter, "record", broken)
    items = [build_item(str(tmp_path), name, FILE) for name in (first, second)]
    results, problem = apply_items(items, str(tmp_path / "journal.jsonl"))
    assert [result.status for result in results] == [RENAMED]
    assert "renamed but not recorded" in problem
    assert items[0].new_path in problem
    assert second.encode("utf-8") in listing(tmp_path)
    assert b"journal.jsonl" not in listing(tmp_path)


def test_apply_items_without_a_journal_path_writes_nothing(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    results, problem = apply_items([build_item(str(tmp_path), NFD_FILE, FILE)])
    assert problem is None
    assert [result.status for result in results] == [RENAMED]
    assert listing(tmp_path) == [NFC_FILE.encode("utf-8")]
