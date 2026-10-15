"""One engine, one session factory, one transaction boundary.

Sync on purpose: a request is dominated by the LLM stream, and Qdrant,
embeddings and BM25 are all sync too -- an async driver would buy nothing and
colour every caller.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from law_agent.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # pool_pre_ping, because a pooled connection outlives a restart of the
    # Postgres container during development.
    return create_engine(settings.database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    # expire_on_commit=False: repositories read attributes off a row after the
    # commit that wrote it, and a refresh there is a pointless round trip.
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Generator[Session]:
    """A session that rolls back on an exception and always closes.

    Committing is left to the caller: ingestion writes the ``pending`` row,
    commits, and only then starts a parse that takes minutes -- holding one
    transaction across it would pin a connection for no reason.
    """
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
