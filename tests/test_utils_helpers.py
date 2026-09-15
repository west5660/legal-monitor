"""content_hash() and safe_filename(): small pure functions with no
existing coverage that ingest.py's dedup logic (_save_document) and file
download path (_download_files) both depend on directly.
"""
from __future__ import annotations

import pytest

from legal_monitor.utils import content_hash, safe_filename


def test_content_hash_is_stable_for_identical_text():
    text = "Текст документа о внесении изменений."
    assert content_hash(text) == content_hash(text)


def test_content_hash_ignores_whitespace_and_case_differences():
    """_save_document relies on this to avoid flagging a document as
    "changed" (and re-writing every field) just because the source added
    an extra space or line break between ingest runs.
    """
    a = "Текст  документа\nо внесении   изменений."
    b = "текст документа о внесении изменений."
    assert content_hash(a) == content_hash(b)


def test_content_hash_differs_for_different_text():
    assert content_hash("Текст А") != content_hash("Текст Б")


def test_content_hash_handles_empty_and_none():
    # Must not raise - _save_document calls this with `text` that can be "".
    assert content_hash("") == content_hash("")
    assert content_hash(None) == content_hash("")  # type: ignore[arg-type]


def test_safe_filename_replaces_unsafe_characters():
    assert safe_filename("111111-8") == "111111-8"
    assert safe_filename("some/bad:name?.txt") == "some_bad_name_.txt"


def test_safe_filename_truncates_to_max_len():
    long_value = "a" * 200
    result = safe_filename(long_value, max_len=80)
    assert len(result) == 80


def test_safe_filename_falls_back_to_document_when_empty_after_cleaning():
    # Every character gets replaced with "_"... but "_" itself is allowed
    # by the regex (\w includes it), so an all-"_"-producing input still
    # yields a non-empty string. The real empty case is an empty string in.
    assert safe_filename("") == "document"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
