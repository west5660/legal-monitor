from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from legal_monitor.models import ensure_schema, get_engine

logger = logging.getLogger(__name__)

DB_BUSY_MESSAGE = "База данных занята (ingest/classify). Подождите завершения задачи."


@lru_cache(maxsize=1)
def get_session_factory(db_path: str) -> sessionmaker:
    engine = get_engine(db_path)
    try:
        ensure_schema(engine)
    except OperationalError:
        logger.warning("schema init skipped (db busy)")
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def db_session(db_path: str) -> Iterator[Session]:
    try:
        SessionLocal = get_session_factory(db_path)
        session = SessionLocal()
    except OperationalError as exc:
        raise HTTPException(503, DB_BUSY_MESSAGE) from exc
    try:
        yield session
    except OperationalError as exc:
        raise HTTPException(503, DB_BUSY_MESSAGE) from exc
    finally:
        session.close()
