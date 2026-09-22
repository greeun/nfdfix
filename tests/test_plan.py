import unicodedata

from nfdfix.models import FILE
from nfdfix.plan import build_item, check_conflict, needs_normalization, to_nfc

NFD_NAME = unicodedata.normalize("NFD", "한글문서.txt")
NFC_NAME = unicodedata.normalize("NFC", "한글문서.txt")
COMPAT_RAK = "\uf914"  # CJK COMPATIBILITY IDEOGRAPH-F914, read "rak"
UNIFIED_RAK = "\u6a02"


def test_nfd_name_needs_normalization():
    assert needs_normalization(NFD_NAME) is True


def test_nfc_name_does_not_need_normalization():
    assert needs_normalization(NFC_NAME) is False


def test_ascii_name_does_not_need_normalization():
    assert needs_normalization("report.txt") is False


def test_build_item_returns_none_for_already_normalized_name():
    assert build_item("/tmp", NFC_NAME, FILE) is None


def test_build_item_returns_item_with_normalized_new_name():
    item = build_item("/tmp", NFD_NAME, FILE)
    assert item.old_name == NFD_NAME
    assert item.new_name == NFC_NAME
    assert item.kind == FILE


def test_no_conflict_when_destination_is_absent():
    item = build_item("/tmp", NFD_NAME, FILE)
    assert check_conflict(item, identify=lambda path: None) is False


def test_no_conflict_when_destination_is_the_same_entry():
    item = build_item("/tmp", NFD_NAME, FILE)
    assert check_conflict(item, identify=lambda path: (1, 42)) is False


def test_conflict_when_destination_is_a_different_entry():
    item = build_item("/tmp", NFD_NAME, FILE)
    identities = {item.old_path: (1, 42), item.new_path: (1, 99)}
    assert check_conflict(item, identify=identities.get) is True


def test_to_nfc_keeps_a_cjk_compatibility_ideograph():
    assert to_nfc(COMPAT_RAK) == COMPAT_RAK


def test_to_nfc_keeps_the_ohm_sign():
    assert to_nfc("\u2126") == "\u2126"


def test_to_nfc_keeps_a_supplementary_compatibility_ideograph():
    assert to_nfc("\U0002f800") == "\U0002f800"


def test_to_nfc_composes_hangul_next_to_a_preserved_character():
    name = unicodedata.normalize("NFD", "음") + COMPAT_RAK + ".txt"
    assert to_nfc(name) == unicodedata.normalize("NFC", "음") + COMPAT_RAK + ".txt"


def test_preserved_characters_alone_do_not_need_normalization():
    assert needs_normalization(unicodedata.normalize("NFC", "음") + COMPAT_RAK) is False


def test_build_item_keeps_the_preserved_character_in_the_new_name():
    name = unicodedata.normalize("NFD", "음") + COMPAT_RAK
    item = build_item("/tmp", name, FILE)
    assert item.new_name == unicodedata.normalize("NFC", "음") + COMPAT_RAK
    assert UNIFIED_RAK not in item.new_name
