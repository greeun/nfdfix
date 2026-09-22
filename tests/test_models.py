import os

from nfdfix.models import FILE, RenameItem, RenameResult


def test_rename_item_builds_old_and_new_paths():
    item = RenameItem(parent="/tmp/여행", old_name="a.txt", new_name="b.txt", kind=FILE)
    assert item.old_path == os.path.join("/tmp/여행", "a.txt")
    assert item.new_path == os.path.join("/tmp/여행", "b.txt")


def test_rename_result_detail_defaults_to_empty_string():
    item = RenameItem(parent="/tmp", old_name="a", new_name="b", kind=FILE)
    assert RenameResult(item=item, status="renamed").detail == ""
