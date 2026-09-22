import os
import sys
import unicodedata

import pytest

from nfdfix.cli import main

NFD_FILE = unicodedata.normalize("NFD", "한글문서.txt")
NFC_FILE = unicodedata.normalize("NFC", "한글문서.txt")
NFD_DIR = unicodedata.normalize("NFD", "여행사진")
NFC_DIR = unicodedata.normalize("NFC", "여행사진")


def typed(path):
    """The NFC form a keyboard produces; APFS still finds the NFD entry with it."""
    text = unicodedata.normalize("NFC", str(path))
    if not os.path.lexists(text):
        pytest.skip("this filesystem tells normalization forms apart")
    return text


def listing(path):
    return sorted(name.encode("utf-8") for name in os.listdir(str(path)))


def test_preview_does_not_change_the_filesystem(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    before = listing(tmp_path)
    assert main([str(tmp_path)]) == 0
    assert listing(tmp_path) == before


def test_apply_renames_a_nested_tree(tmp_path):
    directory = tmp_path / NFD_DIR
    directory.mkdir()
    (directory / NFD_FILE).write_text("내용", encoding="utf-8")
    log = tmp_path / "journal.jsonl"

    assert main([str(tmp_path), "--apply", "--log", str(log)]) == 0

    assert listing(tmp_path) == sorted([NFC_DIR.encode("utf-8"), b"journal.jsonl"])
    assert listing(tmp_path / NFC_DIR) == [NFC_FILE.encode("utf-8")]
    assert (tmp_path / NFC_DIR / NFC_FILE).read_text(encoding="utf-8") == "내용"


def test_undo_restores_the_original_names(tmp_path):
    directory = tmp_path / NFD_DIR
    directory.mkdir()
    (directory / NFD_FILE).write_text("내용", encoding="utf-8")
    log = tmp_path / "journal.jsonl"

    assert main([str(tmp_path), "--apply", "--log", str(log)]) == 0
    assert main(["--undo", str(log), "--apply"]) == 0

    assert listing(tmp_path) == sorted([NFD_DIR.encode("utf-8"), b"journal.jsonl"])
    assert listing(tmp_path / NFD_DIR) == [NFD_FILE.encode("utf-8")]
    assert (tmp_path / NFD_DIR / NFD_FILE).read_text(encoding="utf-8") == "내용"


def test_undo_preview_does_not_change_the_filesystem(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    log = tmp_path / "journal.jsonl"
    assert main([str(tmp_path), "--apply", "--log", str(log)]) == 0
    before = listing(tmp_path)
    assert main(["--undo", str(log)]) == 0
    assert listing(tmp_path) == before


def test_excluded_directory_is_untouched(tmp_path):
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    (excluded / NFD_FILE).write_text("내용", encoding="utf-8")
    assert main([str(tmp_path), "--apply"]) == 0
    assert listing(excluded) == [NFD_FILE.encode("utf-8")]


def test_custom_exclude_pattern_is_applied(tmp_path):
    skipped = tmp_path / "보관함"
    skipped.mkdir()
    (skipped / NFD_FILE).write_text("내용", encoding="utf-8")
    assert main([str(tmp_path), "--apply", "--exclude", "보관함"]) == 0
    assert listing(skipped) == [NFD_FILE.encode("utf-8")]


def test_missing_path_returns_exit_code_two(tmp_path):
    assert main([str(tmp_path / "없는경로")]) == 2


def test_undo_with_path_argument_returns_exit_code_two(tmp_path):
    log = tmp_path / "journal.jsonl"
    log.write_text("", encoding="utf-8")
    assert main([str(tmp_path), "--undo", str(log)]) == 2


def test_tui_rejects_apply(tmp_path, capsys):
    assert main([str(tmp_path), "--tui", "--apply"]) == 2
    assert "--tui" in capsys.readouterr().err


def test_tui_rejects_undo(tmp_path, capsys):
    log = tmp_path / "journal.jsonl"
    log.write_text("", encoding="utf-8")
    assert main(["--tui", "--undo", str(log)]) == 2
    assert "--tui" in capsys.readouterr().err


def test_tui_rejects_quiet(tmp_path, capsys):
    assert main([str(tmp_path), "--tui", "--quiet"]) == 2
    assert "--tui" in capsys.readouterr().err


def test_tui_rejects_two_paths(tmp_path, capsys):
    assert main([str(tmp_path), str(tmp_path), "--tui"]) == 2
    assert "one path" in capsys.readouterr().err


def test_tui_reports_missing_textual(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "nfdfix.tui", None)
    assert main([str(tmp_path), "--tui"]) == 2
    assert '".[tui]"' in capsys.readouterr().err


def test_tui_delegates_with_the_scan_options(tmp_path, monkeypatch):
    tui = pytest.importorskip("nfdfix.tui")
    calls = []

    def fake_run_tui(start, excludes, include_hidden, log):
        calls.append((start, list(excludes), include_hidden, log))
        return 0

    monkeypatch.setattr(tui, "run_tui", fake_run_tui)
    assert main([str(tmp_path), "--tui", "--exclude", "보관함", "--include-hidden"]) == 0
    start, excludes, include_hidden, log = calls[0]
    assert start == str(tmp_path)
    assert "보관함" in excludes and ".git" in excludes
    assert include_hidden is True
    assert log is None


def test_tui_starts_at_the_parent_of_a_file(tmp_path, monkeypatch):
    tui = pytest.importorskip("nfdfix.tui")
    target = tmp_path / "파일.txt"
    target.write_text("내용", encoding="utf-8")
    calls = []
    monkeypatch.setattr(tui, "run_tui", lambda start, *rest: calls.append(start) or 0)
    assert main([str(target), "--tui"]) == 0
    assert calls == [str(tmp_path)]


def test_apply_renames_a_file_whose_path_was_typed_in_nfc(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    log = tmp_path / "journal.jsonl"
    assert main([typed(tmp_path / NFD_FILE), "--apply", "--log", str(log)]) == 0
    assert listing(tmp_path) == sorted([NFC_FILE.encode("utf-8"), b"journal.jsonl"])


def test_tui_starts_at_the_stored_name_of_a_typed_path(tmp_path, monkeypatch):
    tui = pytest.importorskip("nfdfix.tui")
    (tmp_path / NFD_DIR).mkdir()
    calls = []
    monkeypatch.setattr(tui, "run_tui", lambda start, *rest: calls.append(start) or 0)
    assert main([typed(tmp_path / NFD_DIR), "--tui"]) == 0
    assert calls == [str(tmp_path / NFD_DIR)]


def test_unwritable_journal_stops_before_renaming(tmp_path, capsys):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    before = listing(tmp_path)
    assert main([str(tmp_path), "--apply", "--log", str(blocker / "journal.jsonl")]) == 2
    assert listing(tmp_path) == before
    assert "cannot write the journal" in capsys.readouterr().err


def test_journal_failure_midway_reports_and_exits_with_two(tmp_path, monkeypatch, capsys):
    from nfdfix.journal import JournalWriter

    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")

    def broken(self, item):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(JournalWriter, "record", broken)
    assert main([str(tmp_path), "--apply", "--log", str(tmp_path / "journal.jsonl")]) == 2
    captured = capsys.readouterr()
    assert "renamed but not recorded" in captured.err
    assert "Processed 1 item(s)." in captured.out


def test_apply_leaves_no_journal_when_nothing_was_renamed(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("running as root bypasses the permission restriction")
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / NFD_FILE).write_text("내용", encoding="utf-8")
    os.chmod(str(protected), 0o500)
    log = tmp_path / "journal.jsonl"
    try:
        assert main([str(protected), "--apply", "--log", str(log)]) == 1
    finally:
        os.chmod(str(protected), 0o700)
    assert log.exists() is False
