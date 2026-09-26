# nfdfix

A command line tool that normalizes filenames stored in Unicode NFD (decomposed form) to NFC.

macOS often stores filenames in NFD. When such a name travels through Windows, Linux, an archive or a web upload, Korean text like "한글" shows up as "ㅎㅏㄴㄱㅡㄹ", with the jamo split apart. This tool renames the entries and never touches file contents.

## Install

### Requirements

- Python 3.9 or later. The `python3` that ships with macOS is enough for the command line tool.
- One of [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/), which install the command into its own environment and put it on your `PATH`. On macOS either can be installed with Homebrew:

  ```
  brew install uv
  # or
  brew install pipx
  ```

The package is not published on PyPI, so it is installed from a copy of the source:

```
git clone https://github.com/greeun/nfdfix.git
cd nfdfix
```

### Install the command

From the source directory:

```
uv tool install .
# or
pipx install .
```

To include the interactive interface, install the `tui` extra instead. It pulls in Textual, which may need a newer Python than 3.9.

```
uv tool install ".[tui]"
# or
pipx install ".[tui]"
```

The installed executable is named `nfdfix`, the same as the package. The project was previously called `nfd2nfc`; it was renamed because Homebrew and PyPI already ship unrelated tools under that name. If an older copy was installed under that name, remove it first so the two do not both claim the `nfdfix` executable:

```
uv tool uninstall nfd2nfc
# or
pipx uninstall nfd2nfc
```

If the shell reports `command not found` after installing, the tool directory is not on your `PATH` yet. Run `uv tool update-shell` or `pipx ensurepath`, then open a new terminal.

Check the installation:

```
nfdfix --version
```

### Upgrade

After pulling new changes into the source directory, install again over the existing copy:

```
git pull
uv tool install --reinstall .
# or
pipx install --force .
```

Add `".[tui]"` in place of `.` when the interactive interface is installed.

### Uninstall

```
uv tool uninstall nfdfix
# or
pipx uninstall nfdfix
```

Journals written by earlier runs stay in `~/.local/state/nfdfix/`; delete that directory as well if you no longer need to undo those renames.

### Run without installing

You can also run it straight from the source tree:

```
PYTHONPATH=src python3 -m nfdfix ~/Documents
```

## Usage

A preview is the default, and it never touches the filesystem.

```
nfdfix ~/Documents
```

Perform the renames:

```
nfdfix ~/Documents --apply
```

Undo them, using the journal path printed by the run that applied them:

```
nfdfix --undo ~/.local/state/nfdfix/journal-20260920-215700.jsonl --apply
```

## Options

| Option | Description |
|---|---|
| `--apply` | Perform the renames. Without it the run is a preview. |
| `--exclude PATTERN` | Add a name pattern to exclude. May be given more than once. |
| `--no-default-excludes` | Do not use the built-in exclude list. |
| `--include-hidden` | Also process entries whose name starts with a dot. |
| `--log PATH` | Where to write the rename journal. |
| `--undo LOGPATH` | Restore the previous names from a journal. |
| `--quiet` | Print the summary only. |
| `--tui` | Open the interactive interface. Takes at most one path. |

The built-in exclude list is `.git`, `node_modules`, `.venv`, `venv` and `__pycache__`.

## Interactive mode

Install the `tui` extra to get a terminal interface built on Textual:

```
uv tool install ".[tui]"
```

Then open it at a directory, or at the current directory when no path is given:

```
nfdfix --tui ~/Documents
```

The left pane is a directory tree. Pick a directory and press enter to scan it; the right pane lists the entries that need renaming, all selected. The chosen directory itself is listed too when its own name needs normalizing, unlike the command line run, which leaves the name of a directory argument alone. Deselect the ones to leave alone, then press `r` and confirm. Nothing changes on disk until you confirm.

| Key | Action |
|---|---|
| `enter` | Scan the highlighted directory |
| `backspace` | Show the parent directory in the tree |
| `space` | Toggle the highlighted entry |
| `a` / `n` | Select all / none |
| `r` | Rename the selected entries (asks first) |
| `u` | Choose a journal and restore the names it records (asks first) |
| `tab` | Switch between the tree and the list |
| `q` | Quit |

`--exclude`, `--no-default-excludes`, `--include-hidden` and `--log` apply to the interactive mode as well. `--tui` cannot be combined with `--apply`, `--undo` or `--quiet`.

## How it works

- Children are renamed before their parents, so renaming a directory never invalidates the paths below it.
- Characters that macOS never decomposes are kept as they are: U+2000–U+2FFF, U+F900–U+FAFF and U+2F800–U+2FAFF. A CJK compatibility ideograph such as U+F914 is therefore not rewritten into its unified form U+6A02.
- `--exclude` patterns match a name whichever normalization form it is stored in.
- When a different entry already uses the target name, that one entry is skipped and the rest continue. APFS ignores normalization differences when comparing names, so the device and inode numbers are compared to tell a real conflict from the entry itself.
- After each rename the stored name is read back and verified, through `fcntl(F_GETPATH)` on macOS and by listing the directory elsewhere or when the entry cannot be opened. If it did not take effect, the rename is retried by way of a temporary name; if that still fails, the volume is reported as one that refuses the target form. A retry that fails halfway puts the entry back under its original name.
- The journal is opened before the first rename. If it cannot be written, nothing is renamed; if a record cannot be written midway, the run stops there.
- Symbolic links are renamed as links. The target is never followed.
- A path typed on the keyboard is NFC, and APFS still finds an entry stored as NFD with it. Each path argument is therefore first spelled with the names the filesystem actually stores, so a typed name is still recognized as needing normalization.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Nothing to do, or everything was processed. |
| `1` | Some entries were skipped because of a conflict or a permission problem. |
| `2` | The run itself failed, for example because a path does not exist or the journal cannot be written. |

## Development

```
python3 -m pytest
```

`NFDFIX_HFS_TEST=1 python3 -m pytest tests/test_volume.py` also checks a real HFS+ disk image, which takes a few seconds.
