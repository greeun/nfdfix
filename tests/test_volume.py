"""Checks against a real HFS+ volume, which refuses to store NFC names.

Creating and mounting a disk image takes a few seconds, so these tests run
only with NFDFIX_HFS_TEST=1 on macOS.
"""

import os
import shutil
import subprocess
import sys
import unicodedata

import pytest

from nfdfix import apply as apply_module
from nfdfix.apply import apply_item
from nfdfix.models import FILE, VOLUME_REJECTED
from nfdfix.plan import build_item

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin"
    or os.environ.get("NFDFIX_HFS_TEST") != "1"
    or shutil.which("hdiutil") is None,
    reason="set NFDFIX_HFS_TEST=1 on macOS to test against a real HFS+ volume",
)

NFD_FILE = unicodedata.normalize("NFD", "한글문서.txt")


@pytest.fixture
def hfs_volume(tmp_path):
    image = tmp_path / "volume.dmg"
    mount = tmp_path / "mount"
    mount.mkdir()
    subprocess.run(
        ["hdiutil", "create", "-size", "20m", "-fs", "HFS+", "-volname", "NFDFIX", "-quiet", str(image)],
        check=True,
    )
    subprocess.run(
        ["hdiutil", "attach", str(image), "-nobrowse", "-quiet", "-mountpoint", str(mount)],
        check=True,
    )
    try:
        yield mount
    finally:
        subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], check=False)


@pytest.mark.parametrize("handle", [True, False], ids=["handle", "listing"])
def test_hfs_volume_is_reported_as_rejecting_the_nfc_form(hfs_volume, monkeypatch, handle):
    if not handle:
        monkeypatch.setattr(apply_module, "fcntl", None)
    (hfs_volume / NFD_FILE).write_text("내용", encoding="utf-8")
    result = apply_item(build_item(str(hfs_volume), NFD_FILE, FILE))
    names = os.listdir(str(hfs_volume))
    assert result.status == VOLUME_REJECTED
    assert NFD_FILE in names
    assert not any(name.startswith(".nfdfix-tmp-") for name in names)
