"""Database engine / session management.

PostgreSQL is the authoritative store for production use (Docker Compose).
SQLite is supported for isolated unit tests and zero-dependency local runs;
it is never used to validate production concurrency behaviour.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from nirikshan.core.config import Settings, get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(settings: Settings) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if settings.is_sqlite:
        # Allow cross-thread use (FastAPI threadpool) and share one in-memory db.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in settings.database_url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_recycle"] = 1800

    engine = create_engine(settings.database_url, **kwargs)

    if settings.is_sqlite:

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def init_engine(settings: Settings | None = None) -> Engine:
    global _engine, _SessionLocal
    settings = settings or get_settings()
    _engine = _make_engine(settings)
    _SessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
    )
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def reset_engine() -> None:
    """Dispose the engine (used by tests to rebuild against a fresh database)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Caller controls commit via service layer / session_scope."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def create_all() -> None:
    """Create every table from the ORM metadata (dev / test bootstrap)."""
    from nirikshan.models import Base  # local import to avoid cycles

    Base.metadata.create_all(bind=get_engine())


def drop_all() -> None:
    from nirikshan.models import Base

    Base.metadata.drop_all(bind=get_engine())
