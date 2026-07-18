from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from kavach_saathi.config import get_settings


class Base(DeclarativeBase):
    pass


def _create_database_engine(url: str, *, pool_size: int) -> Engine:
    settings = get_settings()
    connect_args = {}
    if url.startswith("postgresql"):
        connect_args = {
            "connect_timeout": settings.database_connect_timeout_seconds,
            "application_name": settings.database_application_name,
        }
        if settings.database_ssl_mode:
            connect_args["sslmode"] = settings.database_ssl_mode
        if settings.database_statement_timeout_ms:
            connect_args["options"] = f"-c statement_timeout={settings.database_statement_timeout_ms}"
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_use_lifo=True,
        connect_args=connect_args,
        future=True,
    )


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return _create_database_engine(settings.database_url, pool_size=settings.database_pool_size)


@lru_cache
def get_read_engine() -> Engine:
    settings = get_settings()
    if not settings.database_read_url or settings.database_read_url == settings.database_url:
        return get_engine()
    return _create_database_engine(settings.database_read_url, pool_size=settings.database_read_pool_size)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


@lru_cache
def _read_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_read_engine(), autoflush=False, expire_on_commit=False, future=True)


def SessionLocal() -> Session:
    return _session_factory()()


def ReadSessionLocal() -> Session:
    """Read-only-by-convention session for replica-safe catalogue/reporting queries."""
    return _read_session_factory()()


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@event.listens_for(Session, "before_flush")
def _mark_catalogue_changes(session: Session, _flush_context, _instances) -> None:
    # Import lazily to keep the declarative model module's Base import acyclic.
    from kavach_saathi.db.models import Product, ProductImage, ProductSpecification, ProductVariant, Review

    catalogue_types = (Product, ProductImage, ProductSpecification, ProductVariant, Review)
    if any(isinstance(row, catalogue_types) for row in (*session.new, *session.dirty, *session.deleted)):
        session.info["catalogue_changed"] = True


@event.listens_for(Session, "after_commit")
def _invalidate_catalogue_after_commit(session: Session) -> None:
    if session.info.pop("catalogue_changed", False):
        from kavach_saathi.catalog_cache import invalidate_catalogue_cache

        invalidate_catalogue_cache()


@event.listens_for(Session, "after_rollback")
def _clear_catalogue_change_marker(session: Session) -> None:
    session.info.pop("catalogue_changed", None)
