"""Interactive interface built on Textual.

Textual is imported only here, so the command line interface keeps working
when the optional dependency is not installed.

Textual reads a plain string as content markup, which would swallow the
"[file]" labels and any bracketed part of a name. Text built from names and
paths is therefore passed as Content, which is shown as written.
"""

import glob
import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DirectoryTree,
    Footer,
    Header,
    Label,
    OptionList,
    SelectionList,
    Static,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from . import __version__
from .apply import apply_items
from .cli import exit_code
from .journal import default_journal_path, read_records, undo_items
from .models import (
    CONFLICT,
    DIR,
    ERROR,
    FILE,
    MISSING,
    PERMISSION_DENIED,
    RENAMED,
    SYMLINK,
    VOLUME_REJECTED,
    WOULD_RENAME,
    RenameItem,
    RenameResult,
)
from .plan import check_conflict
from .report import describe, format_summary
from .scanner import is_excluded, is_hidden, scan

SCAN_MODE = "scan"
UNDO_MODE = "undo"
BUSY_MODE = "busy"

# Styles are strings resolved against the theme, so they follow light and dark.
# The $text-* variables are adjusted to stay readable on the background.
KIND_STYLES = {FILE: "bold $text-primary", DIR: "bold $text-secondary", SYMLINK: "bold $text-accent"}
RENAMED_STYLE = "bold $text-success"
STATUS_STYLES = {
    CONFLICT: "bold $text-warning",
    MISSING: "bold $text-warning",
    PERMISSION_DENIED: "bold $text-error",
    VOLUME_REJECTED: "bold $text-error",
    ERROR: "bold $text-error",
}
DETAIL_STYLE = "italic $text-muted"

MODE_LABELS = {SCAN_MODE: " SCAN ", UNDO_MODE: " UNDO ", BUSY_MODE: " RENAMING "}
MODE_STYLES = {
    SCAN_MODE: "bold $text on $primary",
    UNDO_MODE: "bold $text on $warning",
    BUSY_MODE: "bold $text on $accent",
}
MUTED_STYLE = "$text-muted"

START_HINT = "Select a directory on the left and press enter to scan it."


def entry_label(result: RenameResult, base: str) -> Content:
    """Render a result as in the command line output, with its label colored.

    The text stays exactly what describe() prints; only spans are added, and
    the name is never read as markup.
    """
    text = describe(result, base).strip()
    label = Content(text)
    end = text.index("]") + 1
    if result.status == WOULD_RENAME:
        style = KIND_STYLES.get(result.item.kind, "bold")
    elif result.status == RENAMED:
        style = RENAMED_STYLE
    else:
        style = STATUS_STYLES.get(result.status, "bold")
    label = label.stylize(style, 0, end)
    if result.detail and text.endswith(")"):
        start = len(text) - len(result.detail) - 2
        label = label.stylize(DETAIL_STYLE, start, len(text))
    return label


def preview(items: Sequence[RenameItem]) -> List[RenameResult]:
    """Turn scanned items into preview results, marking conflicts."""
    results: List[RenameResult] = []
    for item in items:
        if check_conflict(item):
            results.append(
                RenameResult(
                    item=item,
                    status=CONFLICT,
                    detail="a different entry already uses this name",
                )
            )
        else:
            results.append(RenameResult(item=item, status=WOULD_RENAME))
    return results


def moved_path(path: str, renamed: Sequence[RenameItem]) -> str:
    """Return where a path lives once the given entries have been renamed.

    Each item's paths reflect the names in place when it was applied, so the
    items are replayed in the order they were applied.
    """
    for item in renamed:
        old = item.old_path
        if path == old or path.startswith(old + os.sep):
            path = item.new_path + path[len(old):]
    return path


class FilteredDirectoryTree(DirectoryTree):
    """Shows directories only, honoring the exclude and hidden rules."""

    def __init__(self, path: str, excludes: Sequence[str], include_hidden: bool, **kwargs):
        super().__init__(path, **kwargs)
        self._excludes = tuple(excludes)
        self._include_hidden = include_hidden

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        kept = []
        for path in paths:
            if not path.is_dir() or path.is_symlink():
                continue
            if is_excluded(path.name, self._excludes):
                continue
            if not self._include_hidden and is_hidden(path.name):
                continue
            kept.append(path)
        return kept


class ConfirmScreen(ModalScreen[bool]):
    """Asks before anything is changed on disk."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; background: $background 60%; }
    #dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        border: round $warning;
        border-title-color: $warning;
        border-title-style: bold;
        background: $surface;
    }
    #message { width: 1fr; }
    #buttons { height: auto; align: right middle; margin-top: 1; }
    #buttons Button { margin-left: 2; }
    """
    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, heading: str, message: str):
        super().__init__()
        self.heading = heading
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog") as dialog:
            dialog.border_title = self.heading
            yield Label(Content(self.message), id="message")
            with Horizontal(id="buttons"):
                yield Button("Cancel (esc)", id="cancel")
                yield Button("Yes (y)", id="confirm", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


JournalChoice = Optional[Tuple[str, List[dict]]]


class JournalScreen(ModalScreen[JournalChoice]):
    """Lists journals and returns the chosen one with its records."""

    DEFAULT_CSS = """
    JournalScreen { align: center middle; background: $background 60%; }
    #journals {
        width: 80%;
        height: 60%;
        padding: 0 1;
        border: round $accent;
        border-title-color: $accent;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        background: $surface;
    }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, paths: List[str]):
        super().__init__()
        self.paths = list(paths)

    def compose(self) -> ComposeResult:
        yield OptionList(*[Option(Content(path)) for path in self.paths], id="journals")

    def on_mount(self) -> None:
        picker = self.query_one("#journals", OptionList)
        picker.border_title = "Undo from a journal"
        picker.border_subtitle = "enter choose · esc cancel"
        picker.highlighted = 0
        picker.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        path = self.paths[event.option_index]
        try:
            records = read_records(path)
        except (OSError, ValueError) as error:
            self.notify(
                "cannot read the journal: {0}".format(error), severity="error", markup=False
            )
            return
        self.dismiss((path, records))

    def action_cancel(self) -> None:
        self.dismiss(None)


class NfdfixApp(App[int]):
    """Browse, scan, select, rename, and undo."""

    TITLE = "nfdfix"
    SUB_TITLE = "v" + __version__
    CSS = """
    #main { height: 1fr; padding: 1 1 0 1; }
    #tree { width: 2fr; }
    #pane { width: 3fr; margin-left: 1; }
    #entries, #empty { height: 1fr; }
    #tree, #entries, #empty {
        border: round $panel-lighten-2;
        border-title-color: $text-muted;
        border-subtitle-color: $text-muted;
        background: $surface;
    }
    #tree:focus, #entries:focus {
        border: round $accent;
        border-title-color: $accent;
        border-title-style: bold;
    }
    #empty { content-align: center middle; text-align: center; color: $text-muted; padding: 0 2; }
    #status {
        height: 1;
        margin-top: 1;
        background: $panel;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """
    BINDINGS = [
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("r", "rename", "Rename"),
        Binding("u", "undo", "Undo"),
        Binding("backspace", "parent", "Up"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        start: str,
        excludes: Sequence[str],
        include_hidden: bool,
        log: Optional[str],
    ):
        super().__init__()
        self.start = start
        self.excludes = list(excludes)
        self.include_hidden = include_hidden
        self.log_path = log
        self.mode = SCAN_MODE
        self.base = start
        self.results: List[RenameResult] = []
        self.last_results: Optional[List[RenameResult]] = None
        self.journal_path: Optional[str] = None
        self.scan_generation = 0
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield FilteredDirectoryTree(
                self.start, self.excludes, self.include_hidden, id="tree"
            )
            with Vertical(id="pane"):
                yield SelectionList[RenameItem](id="entries")
                yield Static(Content(START_HINT), id="empty")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tree", FilteredDirectoryTree).border_title = "Folders"
        for widget in (self.entries, self.query_one("#empty", Static)):
            widget.border_title = "Entries"
        self.show_hint(START_HINT)
        self.set_status(self.start)

    # -- widgets ---------------------------------------------------------

    @property
    def entries(self) -> SelectionList:
        return self.query_one("#entries", SelectionList)

    def set_status(self, text: Union[str, Content]) -> None:
        """Show the mode badge followed by the text; a str is never read as markup."""
        mode = BUSY_MODE if self.busy else self.mode
        if isinstance(text, str):
            text = Content(text)
        badge = (MODE_LABELS[mode], MODE_STYLES[mode])
        self.query_one("#status", Static).update(Content.assemble(badge, " ", text))

    def show_hint(self, text: str) -> None:
        """Replace the empty list with a centered message."""
        empty = self.query_one("#empty", Static)
        empty.update(Content(text))
        empty.display = True
        self.entries.display = False

    def show_list(self) -> None:
        self.query_one("#empty", Static).display = False
        self.entries.display = True

    def entry_label(self, result: RenameResult) -> Content:
        return entry_label(result, self.base)

    def refuse_while_busy(self) -> bool:
        """Warn and return True while a rename is running."""
        if self.busy:
            self.notify("renaming in progress", severity="warning")
        return self.busy

    # -- scanning --------------------------------------------------------

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self.scan_directory(str(event.path))

    def scan_directory(self, path: str) -> None:
        """Scan a directory in the background and show the result."""
        if self.refuse_while_busy():
            return
        self.scan_generation += 1
        generation = self.scan_generation
        self.mode = SCAN_MODE
        self.base = path
        self.journal_path = None
        self.entries.clear_options()
        self.entries.border_subtitle = ""
        self.show_hint("Scanning {0} ...".format(path))
        self.set_status("scanning {0} ...".format(path))
        self.run_worker(
            lambda: self._scan(path, generation),
            name="scan",
            group="scan",
            exclusive=True,
            thread=True,
        )

    def _scan(self, path: str, generation: int) -> None:
        items = scan(
            [path],
            excludes=self.excludes,
            include_hidden=self.include_hidden,
            include_root_dirs=True,
        )
        results = preview(items)
        self.call_from_thread(self.show_scan, results, generation)

    def show_scan(self, results: List[RenameResult], generation: int) -> None:
        """Show a scan's results unless something newer took over the list.

        Textual cannot stop a thread worker, so a slow scan may finish after a
        newer one. The generation is compared here, on the main thread.
        """
        if generation != self.scan_generation:
            return
        self.show_results(results)

    def show_results(self, results: List[RenameResult]) -> None:
        """Fill the list from preview results."""
        self.results = list(results)
        self.entries.clear_options()
        options = []
        for result in self.results:
            pending = result.status == WOULD_RENAME
            options.append(
                Selection(
                    self.entry_label(result),
                    result.item,
                    initial_state=pending,
                    disabled=not pending,
                )
            )
        self.entries.add_options(options)
        if options:
            self.show_list()
        elif self.mode == UNDO_MODE:
            self.show_hint("The journal records no renames.")
        else:
            self.show_hint("Nothing to normalize in {0}.".format(self.base))
        self.update_status()

    def update_status(self) -> None:
        count = self.entries.option_count
        selected = len(self.entries.selected)
        self.entries.border_subtitle = "{0} of {1} selected".format(selected, count)
        tally = "{0} item(s), {1} selected".format(count, selected)
        conflicts = sum(1 for result in self.results if result.status == CONFLICT)
        if conflicts:
            # Placed before the path, which may be cut off at the right edge.
            tally = Content.assemble(
                tally,
                (" · ", MUTED_STYLE),
                ("{0} conflict(s)".format(conflicts), "bold $text-warning"),
            )
        if self.mode == UNDO_MODE:
            text = Content.assemble("undo: ", Content(self.journal_path or ""), " · ", tally)
        else:
            text = Content.assemble(tally, " · ", Content(self.base))
        self.set_status(text)

    def on_selection_list_selected_changed(self, event) -> None:
        self.update_status()

    # -- selection -------------------------------------------------------

    def action_select_all(self) -> None:
        entries = self.entries
        for index in range(entries.option_count):
            option = entries.get_option_at_index(index)
            if not option.disabled:
                entries.select(option)

    def action_select_none(self) -> None:
        self.entries.deselect_all()

    # -- renaming --------------------------------------------------------

    def action_rename(self) -> None:
        if self.refuse_while_busy():
            return
        selected = self.entries.selected
        if not selected:
            self.notify("nothing is selected", severity="warning")
            return
        verb = "Restore" if self.mode == UNDO_MODE else "Rename"
        message = "{0} {1} selected item(s) in\n{2}?".format(verb, len(selected), self.base)
        self.push_screen(ConfirmScreen(verb, message), callback=self._on_confirmed)

    def _on_confirmed(self, confirmed: Optional[bool]) -> None:
        if not confirmed:
            return
        chosen = set(self.entries.selected)
        ordered = [result.item for result in self.results if result.item in chosen]
        self.apply_selected(ordered)

    def apply_selected(self, items: List[RenameItem]) -> None:
        """Rename the given items in the background, journaling in scan mode."""
        journal_path = None
        if self.mode == SCAN_MODE:
            journal_path = self.log_path or default_journal_path()
        self.busy = True
        self.set_status("renaming {0} item(s) ...".format(len(items)))
        self.run_worker(
            lambda: self._apply(items, journal_path),
            name="apply",
            group="apply",
            exclusive=True,
            thread=True,
        )

    def _apply(self, items: List[RenameItem], journal_path: Optional[str]) -> None:
        results, problem = apply_items(items, journal_path)
        self.call_from_thread(self.show_applied, results, journal_path, problem)

    def show_applied(
        self,
        results: List[RenameResult],
        journal_path: Optional[str],
        problem: Optional[str] = None,
    ) -> None:
        """Rebuild the labels of the processed entries from their results."""
        self.busy = False
        by_item = {result.item: result for result in results}
        entries = self.entries
        with entries.prevent(SelectionList.SelectedChanged):
            for index, previous in enumerate(self.results):
                outcome = by_item.get(previous.item)
                if outcome is None:
                    continue
                self.results[index] = outcome
                option = entries.get_option_at_index(index)
                entries.deselect(option)
                entries.replace_option_prompt_at_index(index, self.entry_label(outcome))
                entries.disable_option_at_index(index)
        entries.border_subtitle = "{0} of {1} selected".format(
            len(entries.selected), entries.option_count
        )
        self.follow_renames(results)
        self.last_results = list(results)
        text = format_summary(results, applied=True)
        if journal_path and any(result.status == RENAMED for result in results):
            text = "{0} · journal: {1}".format(text, journal_path)
        if problem:
            text = "{0} · {1}".format(text, problem)
            self.notify(problem, severity="error", markup=False)
        self.set_status(text)

    def follow_renames(self, results: List[RenameResult]) -> None:
        """Point the scanned directory and the tree at the names just written.

        A tree node keeps the path it was listed with, so a renamed directory
        would otherwise be scanned again under its old name.
        """
        renamed = [result.item for result in results if result.status == RENAMED]
        self.base = moved_path(self.base, renamed)
        tree = self.query_one("#tree", FilteredDirectoryTree)
        start = str(tree.path)
        moved = moved_path(start, renamed)
        if moved != start:
            tree.path = moved
        elif any(item.kind == DIR for item in renamed):
            tree.reload()

    # -- browsing ------------------------------------------------------

    def action_parent(self) -> None:
        """Move the tree up to the parent of the directory it shows."""
        tree = self.query_one("#tree", FilteredDirectoryTree)
        current = os.path.abspath(str(tree.path))
        parent = os.path.dirname(current)
        if parent == current:
            self.notify("already at the top", severity="warning")
            return
        tree.path = parent

    # -- undo ------------------------------------------------------------

    def list_journals(self) -> List[str]:
        """Journals to offer: the --log file first, then the default directory, newest first."""
        directory = os.path.dirname(default_journal_path())
        found = sorted(glob.glob(os.path.join(directory, "journal-*.jsonl")), reverse=True)
        if self.log_path and os.path.isfile(self.log_path):
            found = [self.log_path] + [path for path in found if path != self.log_path]
        return found

    def action_undo(self) -> None:
        if self.refuse_while_busy():
            return
        paths = self.list_journals()
        if not paths:
            self.notify("no journal found", severity="warning")
            return
        self.push_screen(JournalScreen(paths), callback=self._on_journal_chosen)

    def _on_journal_chosen(self, choice: JournalChoice) -> None:
        if choice is None:
            return
        path, records = choice
        self.show_undo_plan(path, records)

    def show_undo_plan(self, path: str, records: List[dict]) -> None:
        """Switch to undo mode and list the entries the journal would restore."""
        items = undo_items(records)
        self.scan_generation += 1
        self.mode = UNDO_MODE
        self.journal_path = path
        self.base = os.path.commonpath([item.parent for item in items]) if items else os.getcwd()
        self.show_results(preview(items))

    # -- leaving ---------------------------------------------------------

    def action_quit(self) -> None:
        code = exit_code(self.last_results) if self.last_results is not None else 0
        self.exit(result=code, return_code=code)


def run_tui(
    start: str,
    excludes: Sequence[str],
    include_hidden: bool,
    log: Optional[str],
) -> int:
    """Run the interface and return the exit code."""
    result = NfdfixApp(start, excludes, include_hidden, log).run()
    return result if result is not None else 0
