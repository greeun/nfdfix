import os
import unicodedata

import pytest

pytest.importorskip("textual")

from textual.widgets import DirectoryTree, Label, SelectionList, Static

from nfdfix import tui
from nfdfix.journal import read_records
from nfdfix.models import CONFLICT, PERMISSION_DENIED, RenameItem, RenameResult
from nfdfix.tui import NfdfixApp

NFD_FILE = unicodedata.normalize("NFD", "한글문서.txt")
NFC_FILE = unicodedata.normalize("NFC", "한글문서.txt")
NFD_DIR = unicodedata.normalize("NFD", "여행사진")
NFC_DIR = unicodedata.normalize("NFC", "여행사진")


def listing(path):
    return sorted(name.encode("utf-8") for name in os.listdir(str(path)))


def make_app(tmp_path, log=None):
    return NfdfixApp(str(tmp_path), excludes=["node_modules"], include_hidden=False, log=log)


async def settle(app, pilot):
    """Wait for the scan and apply workers; the tree keeps a loader worker alive."""
    own = [worker for worker in app.workers if worker.group in ("scan", "apply")]
    if own:
        await app.workers.wait_for_complete(own)
    await pilot.pause()


async def wait_for(pilot, condition, attempts=100):
    """Poll until the tree has caught up; it reloads in its own loader worker."""
    for _ in range(attempts):
        if condition():
            return True
        await pilot.pause(0.02)
    return condition()


def tree_children(app):
    return [child.data.path.name for child in app.query_one("#tree", DirectoryTree).root.children]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_moved_path_follows_renamed_ancestors_in_applied_order():
    nfd_sub = unicodedata.normalize("NFD", "하위")
    nfc_sub = unicodedata.normalize("NFC", "하위")
    renamed = [
        RenameItem(parent="/p/" + NFD_DIR, old_name=nfd_sub, new_name=nfc_sub, kind="dir"),
        RenameItem(parent="/p", old_name=NFD_DIR, new_name=NFC_DIR, kind="dir"),
    ]
    assert tui.moved_path("/p/{0}/{1}/x".format(NFD_DIR, nfd_sub), renamed) == "/p/{0}/{1}/x".format(
        NFC_DIR, nfc_sub
    )
    assert tui.moved_path("/p/" + NFD_DIR + "2", renamed) == "/p/" + NFD_DIR + "2"


async def test_scan_lists_the_entries_selected(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    (tmp_path / NFD_DIR).mkdir()
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        assert entries.option_count == 2
        assert sorted(item.old_name for item in entries.selected) == sorted([NFD_FILE, NFD_DIR])
        assert "2 item(s), 2 selected" in str(app.query_one("#status", Static).content)


async def test_conflict_entry_is_disabled_and_unselected(tmp_path, home, monkeypatch):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    monkeypatch.setattr(tui, "check_conflict", lambda item: True)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        assert entries.option_count == 1
        assert entries.get_option_at_index(0).disabled is True
        assert entries.selected == []
        assert app.results[0].status == CONFLICT
        assert str(entries.get_option_at_index(0).prompt) == (
            "[conflict] " + NFD_FILE + " (a different entry already uses this name)"
        )


async def test_brackets_in_names_are_shown_as_written(tmp_path, home):
    root = tmp_path / "[red]상자"
    root.mkdir()
    name = unicodedata.normalize("NFD", "[bold]굵게.txt")
    (root / name).write_text("내용", encoding="utf-8")
    log = tmp_path / "[i]journal.jsonl"
    app = make_app(root, log=str(log))
    async with app.run_test() as pilot:
        app.scan_directory(str(root))
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        status = app.query_one("#status", Static)
        assert str(entries.get_option_at_index(0).prompt) == "[file] " + name
        assert str(root) in str(status.visual)

        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)
        assert str(entries.get_option_at_index(0).prompt) == "[file] " + name
        assert str(log) in str(status.visual)

        await pilot.press("u")
        await pilot.pause()
        picker = app.screen.query_one("#journals")
        assert str(picker.get_option_at_index(0).prompt) == str(log)


async def test_scan_skips_excluded_directories(tmp_path, home):
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    (excluded / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        assert app.query_one("#entries", SelectionList).option_count == 0


async def test_select_all_and_none_skip_disabled_entries(tmp_path, home, monkeypatch):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    (tmp_path / NFD_DIR).mkdir()
    monkeypatch.setattr(tui, "check_conflict", lambda item: item.old_name == NFD_DIR)
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        await pilot.press("n")
        assert entries.selected == []
        await pilot.press("a")
        assert [item.old_name for item in entries.selected] == [NFD_FILE]


async def test_rename_applies_only_the_selected_entries(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    (tmp_path / NFD_DIR).mkdir()
    log = tmp_path / "journal.jsonl"
    app = make_app(tmp_path, log=str(log))
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        for index in range(entries.option_count):
            option = entries.get_option_at_index(index)
            if option.value.old_name == NFD_DIR:
                entries.deselect(option)
        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)

        assert listing(tmp_path) == sorted(
            [NFC_FILE.encode("utf-8"), NFD_DIR.encode("utf-8"), b"journal.jsonl"]
        )
        records = read_records(str(log))
        assert [record["from"] for record in records] == [NFD_FILE]
        assert "renamed: 1" in str(app.query_one("#status", Static).content)
        assert entries.get_option_at_index(0).disabled or entries.get_option_at_index(1).disabled


async def test_rename_includes_the_scanned_directory_itself(tmp_path, home):
    root = tmp_path / NFD_DIR
    root.mkdir()
    (root / NFD_FILE).write_text("내용", encoding="utf-8")
    renamed = tmp_path / NFC_DIR
    app = make_app(root, log=str(tmp_path / "journal.jsonl"))
    async with app.run_test() as pilot:
        app.scan_directory(str(root))
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        assert sorted(item.old_name for item in entries.selected) == sorted([NFD_FILE, NFD_DIR])
        assert str(entries.get_option_at_index(1).prompt) == "[dir] " + NFD_DIR

        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)

        assert listing(tmp_path) == sorted([NFC_DIR.encode("utf-8"), b"journal.jsonl"])
        assert listing(renamed) == [NFC_FILE.encode("utf-8")]
        assert app.base == str(renamed)
        tree = app.query_one("#tree", DirectoryTree)
        assert await wait_for(pilot, lambda: str(tree.root.data.path) == str(renamed))

        app.scan_directory(str(tree.root.data.path))
        await settle(app, pilot)
        assert entries.option_count == 0


async def test_rename_refreshes_the_tree_for_renamed_directories(tmp_path, home):
    (tmp_path / NFD_DIR).mkdir()
    app = make_app(tmp_path, log=str(tmp_path / "journal.jsonl"))
    async with app.run_test() as pilot:
        assert await wait_for(pilot, lambda: tree_children(app) == [NFD_DIR])
        app.scan_directory(str(tmp_path / NFD_DIR))
        await settle(app, pilot)
        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)

        assert listing(tmp_path) == sorted([NFC_DIR.encode("utf-8"), b"journal.jsonl"])
        assert app.base == str(tmp_path / NFC_DIR)
        assert await wait_for(pilot, lambda: tree_children(app) == [NFC_DIR])


async def test_cancelled_rename_changes_nothing(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    before = listing(tmp_path)
    app = make_app(tmp_path, log=str(tmp_path / "journal.jsonl"))
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        await pilot.press("r")
        await pilot.press("escape")
        await settle(app, pilot)
        assert listing(tmp_path) == before
        assert app.last_results is None


async def test_rename_with_nothing_selected_opens_no_dialog(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        await pilot.press("n")
        await pilot.press("r")
        await pilot.pause()
        assert len(app.screen_stack) == 1


async def test_quit_returns_one_after_a_skipped_entry(tmp_path, home):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        item = RenameItem(parent=str(tmp_path), old_name=NFD_FILE, new_name=NFC_FILE, kind="file")
        app.last_results = [RenameResult(item=item, status=PERMISSION_DENIED, detail="denied")]
        await pilot.press("q")
    assert app.return_value == 1


async def test_quit_returns_zero_without_an_apply(tmp_path, home):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("q")
    assert app.return_value == 0


async def test_undo_restores_the_original_names(tmp_path, home):
    directory = tmp_path / NFD_DIR
    directory.mkdir()
    (directory / NFD_FILE).write_text("내용", encoding="utf-8")
    log = tmp_path / "journal.jsonl"
    app = make_app(tmp_path, log=str(log))
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)
        assert listing(tmp_path) == sorted([NFC_DIR.encode("utf-8"), b"journal.jsonl"])

        await pilot.press("u")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.mode == "undo"
        assert "undo:" in str(app.query_one("#status", Static).content)
        assert app.query_one("#entries", SelectionList).option_count == 2

        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)
        await pilot.press("q")

    assert listing(tmp_path) == sorted([NFD_DIR.encode("utf-8"), b"journal.jsonl"])
    assert listing(tmp_path / NFD_DIR) == [NFD_FILE.encode("utf-8")]
    assert app.return_value == 0


async def test_undo_without_journals_opens_no_dialog(tmp_path, home):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("u")
        await pilot.pause()
        assert len(app.screen_stack) == 1


async def test_list_journals_puts_the_log_option_first(tmp_path, home):
    state = home / ".local" / "state" / "nfdfix"
    state.mkdir(parents=True)
    (state / "journal-20260101-000000.jsonl").write_text("", encoding="utf-8")
    (state / "journal-20260102-000000.jsonl").write_text("", encoding="utf-8")
    log = tmp_path / "custom.jsonl"
    log.write_text("", encoding="utf-8")
    app = make_app(tmp_path, log=str(log))
    assert app.list_journals() == [
        str(log),
        str(state / "journal-20260102-000000.jsonl"),
        str(state / "journal-20260101-000000.jsonl"),
    ]


async def test_unreadable_journal_keeps_the_dialog_open(tmp_path, home, monkeypatch):
    log = tmp_path / "broken.jsonl"
    log.write_text("{not json\n", encoding="utf-8")
    app = make_app(tmp_path, log=str(log))
    shown = []
    async with app.run_test() as pilot:
        monkeypatch.setattr(app, "notify", lambda message, **options: shown.append(options))
        await pilot.press("u")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        assert app.mode == "scan"
    assert shown and shown[0].get("markup") is False


async def test_header_shows_the_version(tmp_path, home):
    from textual.widgets._header import HeaderTitle

    from nfdfix import __version__

    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.sub_title == "v" + __version__
        rendered = str(app.query_one(HeaderTitle).render())
        assert "v" + __version__ in rendered


async def test_an_older_scan_does_not_replace_a_newer_one(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        assert entries.option_count == 1
        app.show_scan([], app.scan_generation - 1)
        await pilot.pause()
        assert entries.option_count == 1


async def test_a_pending_scan_does_not_replace_the_undo_plan(tmp_path, home):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        generation = app.scan_generation
        record = {"parent": str(tmp_path), "from": NFD_FILE, "to": NFC_FILE, "kind": "file"}
        app.show_undo_plan(str(tmp_path / "journal.jsonl"), [record])
        app.show_scan([], generation)
        await pilot.pause()
        assert app.query_one("#entries", SelectionList).option_count == 1


async def test_rename_undo_and_scan_are_refused_while_renaming(tmp_path, home, monkeypatch):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    shown = []
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        monkeypatch.setattr(app, "notify", lambda message, **options: shown.append(message))
        app.busy = True
        generation = app.scan_generation
        await pilot.press("r")
        await pilot.press("u")
        app.scan_directory(str(tmp_path))
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert app.scan_generation == generation
        assert shown == ["renaming in progress"] * 3


async def test_busy_is_cleared_after_renaming(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path, log=str(tmp_path / "journal.jsonl"))
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)
        assert app.busy is False


async def test_unwritable_journal_renames_nothing_in_the_tui(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    before = listing(tmp_path)
    app = make_app(tmp_path, log=str(blocker / "journal.jsonl"))
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)
        assert listing(tmp_path) == before
        assert "cannot write the journal" in str(app.query_one("#status", Static).content)
        assert app.busy is False


# -- appearance ---------------------------------------------------------


def span_styles(content):
    return [(span.start, span.end, str(span.style)) for span in content.spans]


def test_entry_label_colors_the_kind_and_keeps_the_text():
    item = RenameItem(parent="/p", old_name=NFD_FILE, new_name=NFC_FILE, kind="file")
    label = tui.entry_label(RenameResult(item=item, status="would_rename"), "/p")
    assert label.plain == "[file] " + NFD_FILE
    assert span_styles(label) == [(0, 6, tui.KIND_STYLES["file"])]


def test_entry_label_colors_the_status_and_dims_the_detail():
    item = RenameItem(parent="/p", old_name=NFD_FILE, new_name=NFC_FILE, kind="file")
    result = RenameResult(item=item, status=CONFLICT, detail="taken")
    label = tui.entry_label(result, "/p")
    assert label.plain == "[conflict] " + NFD_FILE + " (taken)"
    end = len(label.plain)
    assert span_styles(label) == [
        (0, 10, tui.STATUS_STYLES[CONFLICT]),
        (end - len("(taken)"), end, tui.DETAIL_STYLE),
    ]


def test_entry_label_keeps_brackets_in_names_as_text():
    name = unicodedata.normalize("NFD", "[bold]굵게.txt")
    item = RenameItem(parent="/p", old_name=name, new_name=name, kind="file")
    label = tui.entry_label(RenameResult(item=item, status="would_rename"), "/p")
    assert label.plain == "[file] " + name
    assert len(label.spans) == 1


async def test_panels_carry_titles_and_the_selection_count(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    (tmp_path / NFD_DIR).mkdir()
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        entries = app.query_one("#entries", SelectionList)
        assert app.query_one("#tree", DirectoryTree).border_title == "Folders"
        assert entries.border_title == "Entries"
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        assert entries.border_subtitle == "2 of 2 selected"
        await pilot.press("n")
        await pilot.pause()
        assert entries.border_subtitle == "0 of 2 selected"


async def test_selection_count_drops_after_renaming(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        await pilot.press("r")
        await pilot.press("y")
        await settle(app, pilot)
        entries = app.query_one("#entries", SelectionList)
        assert entries.border_subtitle == "0 of 1 selected"
        assert span_styles(entries.get_option_at_index(0).prompt)[0][2] == tui.RENAMED_STYLE


async def test_status_starts_with_the_mode_badge(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#status", Static)
        assert str(status.content).startswith(" SCAN ")
        assert span_styles(status.content)[0] == (0, 6, tui.MODE_STYLES["scan"])
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        assert str(status.content).startswith(" SCAN ")
        app.show_undo_plan(
            str(tmp_path / "journal.jsonl"),
            [{"parent": str(tmp_path), "from": NFD_FILE, "to": NFC_FILE, "kind": "file"}],
        )
        await pilot.pause()
        assert str(status.content).startswith(" UNDO ")


async def test_empty_list_shows_a_hint(tmp_path, home):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        empty = app.query_one("#empty", Static)
        assert empty.display is True
        assert "press enter to scan" in str(empty.content)
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        assert empty.display is True
        assert "Nothing to normalize" in str(empty.content)


async def test_hint_hides_when_entries_are_listed(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        assert app.query_one("#empty", Static).display is False


async def test_confirm_dialog_names_the_action_and_the_directory(tmp_path, home):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        app.scan_directory(str(tmp_path))
        await settle(app, pilot)
        await pilot.press("r")
        await pilot.pause()
        dialog = app.screen.query_one("#dialog")
        assert dialog.border_title == "Rename"
        assert str(tmp_path) in str(app.screen.query_one("#message", Label).content)
