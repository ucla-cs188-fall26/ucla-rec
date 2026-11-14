from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Integer,
    DateTime,
    ForeignKey,
    String,
    Text,
    TypeDecorator,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


class UTCDateTime(TypeDecorator):
    """Store UTC, always hand back timezone-aware UTC (SQLite drops the zone)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: pass timezone-aware values")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(40), default="other")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Venue codes in event locations that belong to this facility, e.g. ["JWC"].
    venues: Mapped[list | None] = mapped_column(JSON, nullable=True)


class ActivitySnapshot(Base):
    """One scrape of a facility's official counts, with the raw input kept so
    records can be reprocessed when the parser improves."""

    __tablename__ = "activity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(120))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    zones: Mapped[list] = mapped_column(JSON)
    content_type: Mapped[str] = mapped_column(String(80))
    raw_content: Mapped[str] = mapped_column(Text)


class EventBatch(Base):
    """One scrape of the events grid for one source and one date. Re-scraping
    the same source and date replaces the previous batch."""

    __tablename__ = "event_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(120), index=True)
    event_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD, local
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    content_type: Mapped[str] = mapped_column(String(80))
    raw_content: Mapped[str] = mapped_column(Text)


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("event_batches.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(120))
    event_date: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    venue: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    space: Mapped[str | None] = mapped_column(String(300), nullable=True)
    facility_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)


class LoginCode(Base):
    """A one-time sign-in code. Stores hashes only, never the email or code."""

    __tablename__ = "login_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email_hash: Mapped[str] = mapped_column(String(64), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class UserSession(Base):
    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    user_hash: Mapped[str] = mapped_column(String(64))
    level: Mapped[int] = mapped_column(Integer)  # 1 quiet, 2 moderate, 3 busy
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if database_url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # one shared in-memory database
        return create_engine(database_url, **kwargs)
    return create_engine(database_url)
