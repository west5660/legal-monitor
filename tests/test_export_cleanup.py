"""run_cleanup(): before this session's fix, a single document whose files
could not be deleted (e.g. a locked/open file, common on Windows) raised
out of the per-document loop entirely - aborting the WHOLE cleanup batch
via `finally: session.close()` with no commit. That silently discarded the
pending `session.delete()` calls already queued for every document
processed earlier in the same batch, even though their files were already
removed from disk - leaving orphaned DB rows pointing at now-missing
folders.

These tests exercise the real `run_cleanup()` against a fake SQLAlchemy
session/query chain (no real DB needed - same style as the connector
MockTransport tests), with `doc.files_path` pointed at real temp
directories so filesystem failures are genuine, not simulated.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from legal_monitor.pipeline import export as export_module


class _FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._docs)


class _FakeSession:
    def __init__(self, docs):
        self._docs = docs
        self.deleted = []
        self.committed = False
        self.closed = False

    def query(self, _model):
        return _FakeQuery(self._docs)

    def delete(self, doc):
        self.deleted.append(doc)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _settings(monkeypatch, session):
    """Patch init_db so run_cleanup() gets our fake session, and build a
    minimal Settings-like object with just the two attributes it reads.
    """
    monkeypatch.setattr(export_module, "init_db", lambda _db_path: lambda: session)
    return SimpleNamespace(db_path="unused.db", retention_days=30, cleanup_batch_days=365)


def _doc(doc_id, files_path=None):
    return SimpleNamespace(id=doc_id, files_path=str(files_path) if files_path else None)


def test_all_documents_removed_when_nothing_fails(tmp_path, monkeypatch):
    folder1 = tmp_path / "doc1"
    folder1.mkdir()
    (folder1 / "a.pdf").write_text("x")
    folder2 = tmp_path / "doc2"
    folder2.mkdir()

    docs = [_doc(1, folder1), _doc(2, folder2), _doc(3)]  # doc 3 has no files_path
    session = _FakeSession(docs)
    settings = _settings(monkeypatch, session)

    stats = export_module.run_cleanup(settings)

    assert stats == {"deleted_docs": 3, "deleted_files": 2, "failed": 0}
    assert session.deleted == docs
    assert session.committed is True
    assert not folder1.exists()
    assert not folder2.exists()


def test_one_document_failing_does_not_abort_the_whole_batch(tmp_path, monkeypatch):
    """The regression this fix targets: a folder that can't be removed
    (simulated here by a stray un-listable path, not a permissions trick,
    to stay portable) must not cancel deletion of the OTHER documents in
    the batch, and must not have its own DB row deleted either.
    """
    good_folder = tmp_path / "good"
    good_folder.mkdir()

    # A "files_path" whose deletion genuinely fails: it contains a nested
    # subdirectory, and the cleanup code only calls unlink() on entries
    # (never rmtree()) - unlink() on a directory raises IsADirectoryError,
    # a portable, permission-free way to trigger a real OSError.
    bad_folder = tmp_path / "bad_folder"
    bad_folder.mkdir()
    (bad_folder / "nested_subdir").mkdir()

    good_doc = _doc(1, good_folder)
    bad_doc = _doc(2, bad_folder)
    trailing_doc = _doc(3, tmp_path / "also_good")
    (tmp_path / "also_good").mkdir()

    docs = [good_doc, bad_doc, trailing_doc]
    session = _FakeSession(docs)
    settings = _settings(monkeypatch, session)

    stats = export_module.run_cleanup(settings)

    assert stats["failed"] == 1, "the bad document must be counted as failed, not silently dropped"
    assert stats["deleted_docs"] == 2, "the two good documents must still be processed"
    assert bad_doc not in session.deleted, (
        "a document whose files could not be removed must NOT have its DB row "
        "deleted - otherwise the DB would reference a folder that still exists"
    )
    assert good_doc in session.deleted
    assert trailing_doc in session.deleted, (
        "a document AFTER the failing one in the batch must still be processed - "
        "this is the actual regression: one bad folder used to abort everything "
        "queued after it too"
    )
    assert session.committed is True, "the batch must still commit the documents that did succeed"
    assert not good_folder.exists()
    assert bad_folder.exists(), "the undeletable folder must be left alone, not partially removed"


def test_no_documents_in_window_is_a_noop(monkeypatch):
    session = _FakeSession([])
    settings = _settings(monkeypatch, session)

    stats = export_module.run_cleanup(settings)

    assert stats == {"deleted_docs": 0, "deleted_files": 0, "failed": 0}
    assert session.committed is True
    assert session.closed is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
