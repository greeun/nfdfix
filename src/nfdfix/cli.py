"""Command line interface."""

import argparse
import os
import sys
from importlib import import_module
from typing import List, Optional, Sequence, Tuple

from . import __version__
from .apply import apply_item, apply_items
from .journal import default_journal_path, read_records, undo_items
from .models import (
    CONFLICT,
    RENAMED,
    SKIPPED_STATUSES,
    WOULD_RENAME,
    RenameItem,
    RenameResult,
)
from .plan import check_conflict
from .report import describe, format_header, format_summary
from .scanner import DEFAULT_EXCLUDES, scan, stored_path

# Name of the installed executable.
COMMAND_NAME = "nfdfix"

TUI_INSTALL_HINT = 'the interactive interface needs Textual; install with: uv tool install ".[tui]"'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND_NAME,
        description="{0} {1}: Normalize filenames that macOS stores in decomposed form "
        "(NFD) to NFC.".format(COMMAND_NAME, __version__),
    )
    parser.add_argument("paths", nargs="*", help="files or directories to normalize")
    parser.add_argument("--apply", action="store_true", help="perform the renames")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="add a name pattern to exclude; may be given more than once",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="do not use the built-in exclude list",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="also process entries whose name starts with a dot",
    )
    parser.add_argument("--log", metavar="PATH", help="where to write the rename journal")
    parser.add_argument("--undo", metavar="LOGPATH", help="restore names from a journal")
    parser.add_argument("--quiet", action="store_true", help="print the summary only")
    parser.add_argument(
        "--tui",
        action="store_true",
        help="open the interactive interface; takes at most one path",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=COMMAND_NAME + " " + __version__,
    )
    return parser


def exit_code(results: Sequence[RenameResult]) -> int:
    for result in results:
        if result.status == CONFLICT or result.status in SKIPPED_STATUSES:
            return 1
    return 0


def _process(
    items: Sequence[RenameItem], apply: bool, journal_path: str
) -> Tuple[List[RenameResult], Optional[str]]:
    if apply:
        return apply_items(items, journal_path)
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
    return results, None


def _emit(results: Sequence[RenameResult], base: str, applied: bool, quiet: bool) -> None:
    print(format_header(results, applied))
    if not quiet:
        for result in results:
            print(describe(result, base))
    if results:
        print()
        print(format_summary(results, applied))


def _run_normalize(args: argparse.Namespace) -> int:
    if not args.paths:
        print("give at least one path to normalize", file=sys.stderr)
        return 2
    for path in args.paths:
        if not os.path.lexists(path):
            print("path not found: {0}".format(path), file=sys.stderr)
            return 2

    excludes = [] if args.no_default_excludes else list(DEFAULT_EXCLUDES)
    excludes.extend(args.exclude)

    # A path typed on the keyboard is NFC even when the entry is stored as NFD.
    paths = [stored_path(path) for path in args.paths]
    items = scan(paths, excludes=excludes, include_hidden=args.include_hidden)
    journal_path = args.log or default_journal_path()
    results, problem = _process(items, apply=args.apply, journal_path=journal_path)
    if problem and not results:
        print(problem, file=sys.stderr)
        return 2

    base = paths[0]
    if not os.path.isdir(base):
        base = os.path.dirname(base)
    _emit(results, base, applied=args.apply, quiet=args.quiet)

    if args.apply and any(result.status == RENAMED for result in results):
        print("journal: {0}".format(journal_path))
    if problem:
        print(problem, file=sys.stderr)
        return 2
    return exit_code(results)


def _run_undo(args: argparse.Namespace) -> int:
    if args.paths:
        print("--undo cannot be combined with path arguments", file=sys.stderr)
        return 2
    if not os.path.isfile(args.undo):
        print("journal not found: {0}".format(args.undo), file=sys.stderr)
        return 2

    try:
        records = read_records(args.undo)
    except (OSError, ValueError) as error:
        print("cannot read the journal: {0}".format(error), file=sys.stderr)
        return 2

    items = undo_items(records)
    results: List[RenameResult] = []
    if args.apply:
        for item in items:
            results.append(apply_item(item))
    else:
        for item in items:
            results.append(RenameResult(item=item, status=WOULD_RENAME))

    base = os.path.commonpath([item.parent for item in items]) if items else os.getcwd()
    _emit(results, base, applied=args.apply, quiet=args.quiet)
    return exit_code(results)


def _run_tui(args: argparse.Namespace) -> int:
    for flag, given in (("--apply", args.apply), ("--undo", args.undo), ("--quiet", args.quiet)):
        if given:
            print("--tui cannot be combined with {0}".format(flag), file=sys.stderr)
            return 2
    if len(args.paths) > 1:
        print("--tui takes at most one path", file=sys.stderr)
        return 2

    start = stored_path(args.paths[0] if args.paths else os.getcwd())
    if not os.path.lexists(start):
        print("path not found: {0}".format(start), file=sys.stderr)
        return 2
    if not os.path.isdir(start):
        start = os.path.dirname(start)

    excludes = [] if args.no_default_excludes else list(DEFAULT_EXCLUDES)
    excludes.extend(args.exclude)

    try:
        tui = import_module(__package__ + ".tui")
    except ImportError:
        print(TUI_INSTALL_HINT, file=sys.stderr)
        return 2
    return tui.run_tui(start, excludes, args.include_hidden, args.log)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.tui:
        return _run_tui(args)
    if args.undo:
        return _run_undo(args)
    return _run_normalize(args)


def run() -> None:
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    run()
