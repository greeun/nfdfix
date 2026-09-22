from nfdfix.models import (
    CONFLICT,
    DIR,
    FILE,
    PERMISSION_DENIED,
    RENAMED,
    WOULD_RENAME,
    RenameItem,
    RenameResult,
)
from nfdfix.report import describe, format_header, format_summary


def result(status, old_name="원본.txt", new_name="변경.txt", kind=FILE, detail=""):
    item = RenameItem(parent="/base/하위", old_name=old_name, new_name=new_name, kind=kind)
    return RenameResult(item=item, status=status, detail=detail)


def test_describe_shows_relative_path_with_kind_label():
    line = describe(result(WOULD_RENAME), base="/base")
    assert "하위/원본.txt" in line
    assert "[file]" in line


def test_describe_omits_the_new_name_because_it_looks_identical():
    line = describe(result(WOULD_RENAME), base="/base")
    assert "변경.txt" not in line


def test_describe_shows_directory_label():
    line = describe(result(RENAMED, kind=DIR), base="/base")
    assert "[dir]" in line


def test_describe_shows_the_name_of_the_base_directory_itself():
    item = RenameItem(parent="/base", old_name="하위", new_name="하위", kind=DIR)
    line = describe(RenameResult(item=item, status=WOULD_RENAME), base="/base/하위")
    assert line.strip() == "[dir] 하위"


def test_describe_shows_detail_for_conflict():
    line = describe(result(CONFLICT, detail="a different entry already uses this name"), base="/base")
    assert "[conflict]" in line
    assert "a different entry already uses this name" in line


def test_summary_counts_each_status():
    results = [
        result(WOULD_RENAME),
        result(WOULD_RENAME),
        result(CONFLICT),
        result(PERMISSION_DENIED),
    ]
    summary = format_summary(results, applied=False)
    assert "to rename: 2" in summary
    assert "conflicts: 1" in summary
    assert "skipped: 1" in summary


def test_summary_uses_applied_wording():
    summary = format_summary([result(RENAMED)], applied=True)
    assert "renamed: 1" in summary


def test_header_mentions_apply_option_in_preview():
    header = format_header([result(WOULD_RENAME)], applied=False)
    assert "--apply" in header


def test_header_reports_nothing_to_do():
    assert "Nothing to normalize" in format_header([], applied=False)
