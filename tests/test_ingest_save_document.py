"""_save_document(): the new/updated/duplicate decision that every ingest
run makes for every fetched document, and that source_stats["new"]/
["updated"] (surfaced to the user after every pipeline run) are built
from. Previously untested despite being the most stateful, branchy piece
of ingest.py - this pins its current behaviour with real Document/
RawDocument objects (no real DB - session.add()/flush()/query() are
faked, same style as test_export_cleanup.py's FakeSession).
"""
from __future__ import annotations

from datetime import date

import pytest

from legal_monitor.models import Document, RawDocument
from legal_monitor.utils import content_hash
from legal_monitor.pipeline.ingest import _save_document


class _FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def filter_by(self, **kwargs):
        matches = [
            d for d in self._docs
            if all(getattr(d, key, None) == value for key, value in kwargs.items())
        ]
        return _FakeQuery(matches)

    def one_or_none(self):
        assert len(self._docs) <= 1, "fixture bug: filter matched more than one document"
        return self._docs[0] if self._docs else None


class _FakeSession:
    def __init__(self, existing=None):
        self.docs = list(existing or [])
        self.added = []
        self.flushed = False

    def query(self, _model):
        return _FakeQuery(self.docs)

    def add(self, doc):
        self.added.append(doc)
        self.docs.append(doc)

    def flush(self):
        self.flushed = True


class _Settings:
    """_save_document only touches settings when raw.file_urls is set -
    none of these tests exercise that path, so an empty stand-in suffices.
    """


def _raw(**overrides):
    defaults = dict(
        source="pravo",
        external_id="A1",
        title="Исходное название документа",
        doc_type="НПА",
        register_date=None,
        stage="Опубликован",
        url="http://example.test/a1",
        initiator="Правительство",
        text="Текст документа о внесении изменений в некоторый закон.",
    )
    defaults.update(overrides)
    return RawDocument(**defaults)


def test_new_document_is_added_and_flushed():
    session = _FakeSession(existing=[])
    raw = _raw()

    result = _save_document(session, _Settings(), raw)

    assert result == "new"
    assert len(session.added) == 1
    doc = session.added[0]
    assert doc.source == "pravo"
    assert doc.external_id == "A1"
    assert doc.title == raw.title
    assert doc.content_hash is not None
    assert session.flushed is True


def test_existing_document_with_changed_text_is_fully_updated():
    existing = Document(
        source="pravo",
        external_id="A1",
        title="Старое короткое название",
        doc_type="НПА",
        register_date=None,
        stage="Внесён",
        url="http://example.test/old",
        initiator="Старый инициатор",
        text="Старый текст документа.",
        content_hash="old-hash-marker",
    )
    session = _FakeSession(existing=[existing])
    raw = _raw(
        title="Новое, изменённое название документа",
        stage="Опубликован",
        text="Совсем другой, изменившийся текст документа с новыми деталями.",
    )

    result = _save_document(session, _Settings(), raw)

    assert result == "updated"
    assert existing.title == raw.title
    assert existing.stage == "Опубликован"
    assert existing.text == raw.text
    assert existing.content_hash != "old-hash-marker"
    assert session.added == [], "an existing document must be mutated in place, not re-added"


def test_existing_document_with_identical_content_is_a_duplicate():
    text = "Текст документа, который не менялся между прогонами."
    existing = Document(
        source="pravo",
        external_id="A1",
        title="Название документа подлиннее для сравнения длины",
        doc_type="НПА",
        register_date=None,
        stage="Опубликован",
        url="http://example.test/a1",
        initiator="Правительство",
        text=text,
    )
    existing.content_hash = content_hash(text)

    session = _FakeSession(existing=[existing])
    # Same title/stage/initiator/text as `existing` - nothing should change.
    raw = _raw(
        title=existing.title,
        stage=existing.stage,
        initiator=existing.initiator,
        text=text,
    )

    result = _save_document(session, _Settings(), raw)

    assert result == "duplicate"


def test_existing_document_gains_a_register_date_is_updated():
    """Same content hash (so the "full update" branch is skipped), but the
    new fetch has a register_date the stored document never had - this
    must still count as an update, not a duplicate.
    """
    text = "Текст без изменений между прогонами."
    existing = Document(
        source="pravo",
        external_id="A1",
        title="Название документа",
        doc_type="НПА",
        register_date=None,
        stage="Опубликован",
        url="http://example.test/a1",
        initiator="Правительство",
        text=text,
    )
    existing.content_hash = content_hash(text)

    session = _FakeSession(existing=[existing])
    raw = _raw(title=existing.title, text=text, register_date=date(2026, 9, 5))

    result = _save_document(session, _Settings(), raw)

    assert result == "updated"
    assert existing.register_date == date(2026, 9, 5)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
