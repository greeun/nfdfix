import os
import subprocess
import sys
import unicodedata

NFD_FILE = unicodedata.normalize("NFD", "한글문서.txt")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def run_module(module, *args):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = SRC
    return subprocess.run(
        [sys.executable, "-m", module] + list(args),
        capture_output=True,
        text=True,
        env=environment,
    )


def test_package_module_runs_and_reports_targets(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    completed = run_module("nfdfix", str(tmp_path))
    assert completed.returncode == 0
    assert "to rename:" in completed.stdout


def test_cli_module_runs_and_reports_targets(tmp_path):
    (tmp_path / NFD_FILE).write_text("내용", encoding="utf-8")
    completed = run_module("nfdfix.cli", str(tmp_path))
    assert completed.returncode == 0
    assert "to rename:" in completed.stdout


def test_module_reports_missing_path_with_exit_code_two(tmp_path):
    completed = run_module("nfdfix", str(tmp_path / "없는경로"))
    assert completed.returncode == 2
    assert "path not found" in completed.stderr


def test_help_uses_the_installed_command_name():
    completed = run_module("nfdfix", "--help")
    assert completed.returncode == 0
    assert "usage: nfdfix" in completed.stdout


def test_version_output_uses_the_installed_command_name():
    completed = run_module("nfdfix", "--version")
    assert completed.returncode == 0
    assert completed.stdout.startswith("nfdfix ")


def test_help_shows_the_version():
    from nfdfix import __version__

    completed = run_module("nfdfix", "--help")
    assert completed.returncode == 0
    assert "nfdfix {0}:".format(__version__) in completed.stdout
