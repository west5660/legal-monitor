from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    register_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    stage: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    initiator: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    files_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    profiles: Mapped[list["DocumentProfile"]] = relationship(back_populates="document")
    memos: Mapped[list["Memo"]] = relationship(back_populates="document")


class DocumentProfile(Base):
    __tablename__ = "document_profiles"
    __table_args__ = (UniqueConstraint("document_id", "profile_id", name="uq_doc_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    profile_id: Mapped[str] = mapped_column(String(50), index=True)
    profile_name: Mapped[str] = mapped_column(String(255))
    relevance_score: Mapped[float] = mapped_column(Float)
    matched_by: Mapped[str] = mapped_column(String(50))
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped[Document] = relationship(back_populates="profiles")


class Memo(Base):
    __tablename__ = "memos"
    __table_args__ = (UniqueConstraint("document_id", "profile_id", name="uq_memo_doc_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    profile_id: Mapped[str] = mapped_column(String(50))
    profile_name: Mapped[str] = mapped_column(String(255))
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_changes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    legal_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    memo_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    analyzed_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped[Document] = relationship(back_populates="memos")


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fetched_count: Mapped[int] = mapped_column(default=0)
    new_count: Mapped[int] = mapped_column(default=0)
    updated_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


@dataclass
class RawDocument:
    source: str
    external_id: str
    title: str
    doc_type: str = ""
    register_date: Optional[date] = None
    stage: str = ""
    url: str = ""
    initiator: str = ""
    text: str = ""
    file_urls: list[str] = field(default_factory=list)


def get_engine(db_path: str):
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    return engine


def _try_enable_wal(engine) -> None:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    except Exception:
        pass


def ensure_schema(engine) -> None:
    _try_enable_wal(engine)
    Base.metadata.create_all(engine, checkfirst=True)
    _migrate_schema(engine)


def init_db(db_path: str):
    engine = get_engine(db_path)
    ensure_schema(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _migrate_schema(engine) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "memos" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("memos")}
    migrations = {
        "analyzed_hash": "ALTER TABLE memos ADD COLUMN analyzed_hash VARCHAR(64)",
        "legal_analysis": "ALTER TABLE memos ADD COLUMN legal_analysis TEXT",
    }
    with engine.begin() as conn:
        for col, sql in migrations.items():
            if col not in columns:
                conn.execute(text(sql))
