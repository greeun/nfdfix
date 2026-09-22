import os
import unicodedata

import pytest

from nfdfix.models import DIR, SYMLINK
from nfdfix.scanner import DEFAULT_EXCLUDES, is_excluded, is_hidden, scan, stored_path

NFD_FILE = unicodedata.normalize("NFD", "한글문서.txt")
NFD_DIR = unicodedata.normalize("NFD", "여행사진")


def typed(path):
    """The NFC form a keyboard produces; APFS still finds the NFD entry with it."""
    text = unicodedata.normalize("NFC", str(path))
    if not os.path.lexists(text):
        pytest.skip("this filesystem tells normalization forms apart")
    return text


def run_scan(root, include_hidden=False):
    return scan([str(root)], excludes=DEFAULT_EXCLUDES, include_hidden=include_hidden)


def test_is_hidden_detects_leading_dot():
    assert is_hidden(".config") is True
    assert is_hidden("config") is False


def test_is_excluded_matches_exact_name():
    assert is_excluded(".git", DEFAULT_EXCLUDES) is True


def test_is_excluded_matches_glob_pattern():
    assert is_excluded("build-2026", ["build-*"]) is True


def test_is_excluded_rejects_unrelated_name():
    assert is_excluded("문서", DEFAULT_EXCLUDES) is False


def test_scan_finds_nfd_file(tmp_path):
    (tmp_path / NFD_FILE).write_text("x", encoding="utf-8")
    assert [item.old_name for item in run_scan(tmp_path)] == [NFD_FILE]


def test_scan_ignores_already_normalized_name(tmp_path):
    (tmp_path / unicodedata.normalize("NFC", "정상문서.txt")).write_text("x", encoding="utf-8")
    assert run_scan(tmp_path) == []


def test_scan_returns_children_before_their_parent(tmp_path):
    parent = tmp_path / NFD_DIR
    parent.mkdir()
    (parent / NFD_FILE).write_text("x", encoding="utf-8")
    names = [item.old_name for item in run_scan(tmp_path)]
    assert names.index(NFD_FILE) < names.index(NFD_DIR)


def test_scan_marks_directory_kind(tmp_path):
    (tmp_path / NFD_DIR).mkdir()
    assert [item.kind for item in run_scan(tmp_path)] == [DIR]


def test_scan_skips_excluded_directory(tmp_path):
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    (excluded / NFD_FILE).write_text("x", encoding="utf-8")
    assert run_scan(tmp_path) == []


def test_scan_skips_hidden_entries_by_default(tmp_path):
    (tmp_path / ("." + NFD_FILE)).write_text("x", encoding="utf-8")
    assert run_scan(tmp_path) == []


def test_scan_includes_hidden_entries_when_requested(tmp_path):
    (tmp_path / ("." + NFD_FILE)).write_text("x", encoding="utf-8")
    names = [item.old_name for item in run_scan(tmp_path, include_hidden=True)]
    assert names == ["." + NFD_FILE]


def test_scan_accepts_a_single_file_path(tmp_path):
    target = tmp_path / NFD_FILE
    target.write_text("x", encoding="utf-8")
    items = scan([str(target)], excludes=DEFAULT_EXCLUDES, include_hidden=False)
    assert [item.old_name for item in items] == [NFD_FILE]


def test_scan_does_not_rename_the_root_directory_itself(tmp_path):
    root = tmp_path / NFD_DIR
    root.mkdir()
    assert run_scan(root) == []


def test_scan_includes_the_root_directory_when_requested(tmp_path):
    root = tmp_path / NFD_DIR
    root.mkdir()
    (root / NFD_FILE).write_text("x", encoding="utf-8")
    items = scan([str(root)], excludes=DEFAULT_EXCLUDES, include_hidden=False, include_root_dirs=True)
    assert [item.old_name for item in items] == [NFD_FILE, NFD_DIR]
    assert items[-1].kind == DIR


def test_scan_leaves_a_hidden_root_directory_alone_even_when_requested(tmp_path):
    root = tmp_path / ("." + NFD_DIR)
    root.mkdir()
    items = scan([str(root)], excludes=DEFAULT_EXCLUDES, include_hidden=False, include_root_dirs=True)
    assert items == []


def test_scan_marks_symlink_kind(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    os.symlink(str(target), str(tmp_path / NFD_FILE))
    items = run_scan(tmp_path)
    assert [item.kind for item in items] == [SYMLINK]


def test_stored_path_returns_the_names_the_filesystem_stores(tmp_path):
    directory = tmp_path / NFD_DIR
    directory.mkdir()
    (directory / NFD_FILE).write_text("x", encoding="utf-8")
    assert stored_path(typed(directory / NFD_FILE)) == str(directory / NFD_FILE)


def test_stored_path_keeps_names_stored_as_given(tmp_path):
    target = tmp_path / unicodedata.normalize("NFC", "정상문서.txt")
    target.write_text("x", encoding="utf-8")
    assert stored_path(str(target)) == str(target)


def test_stored_path_keeps_a_missing_path_as_given(tmp_path):
    missing = str(tmp_path / unicodedata.normalize("NFC", "없음") / NFD_FILE)
    assert stored_path(missing) == missing


def test_is_excluded_matches_an_nfd_name_with_an_nfc_pattern():
    name = unicodedata.normalize("NFD", "사진")
    assert is_excluded(name, [unicodedata.normalize("NFC", "사진")]) is True


def test_is_excluded_matches_an_nfc_name_with_an_nfd_pattern():
    pattern = unicodedata.normalize("NFD", "사진*")
    assert is_excluded(unicodedata.normalize("NFC", "사진첩"), [pattern]) is True


def test_scan_skips_an_nfd_directory_excluded_by_an_nfc_pattern(tmp_path):
    excluded = tmp_path / NFD_DIR
    excluded.mkdir()
    (excluded / NFD_FILE).write_text("내용", encoding="utf-8")
    pattern = unicodedata.normalize("NFC", NFD_DIR)
    assert scan([str(tmp_path)], excludes=[pattern], include_hidden=False) == []
