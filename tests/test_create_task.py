"""Tests for the create boundary's timezone normalization.

Bug 3: handle_create_task parsed scheduled_at with no normalization, so a
tz-aware input had its offset silently dropped by the naive SQLite DateTime
column — wrong stored time and wrong hour bucket. The convention is: the
internal representation is naive UTC; tz-aware input is converted to UTC, and
naive input is assumed to already be UTC.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.mcp_server import handle_create_task
from app.models import Job, _utcnow
from app.scheduler import find_due_jobs


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def only_job(db: Session) -> Job:
    return db.query(Job).one()


def test_aware_offset_is_converted_to_utc(db):
    """10:00 at +08:00 must be stored as 02:00 UTC, bucketed in UTC."""
    handle_create_task(db, description="x", scheduled_at="2026-05-03T10:00:00+08:00")

    job = only_job(db)
    assert job.scheduled_at == datetime(2026, 5, 3, 2, 0, 0)
    assert job.time_bucket == "2026050302"


def test_z_suffix_is_converted_to_utc(db):
    handle_create_task(db, description="x", scheduled_at="2026-05-03T02:00:00Z")

    job = only_job(db)
    assert job.scheduled_at == datetime(2026, 5, 3, 2, 0, 0)
    assert job.time_bucket == "2026050302"


def test_naive_input_is_treated_as_utc(db):
    """Guard: naive input passes through unchanged (assumed UTC)."""
    handle_create_task(db, description="x", scheduled_at="2026-05-03T02:00:00")

    job = only_job(db)
    assert job.scheduled_at == datetime(2026, 5, 3, 2, 0, 0)
    assert job.time_bucket == "2026050302"


def test_aware_past_job_becomes_due(db):
    """End-to-end: an aware, just-past job is found by the UTC watcher.

    Proves the stored time and its bucket align with _utcnow()-based scanning
    after normalization (Bug 1 + Bug 3 interaction).
    """
    tz8 = timezone(timedelta(hours=8))
    past_aware = (datetime.now(UTC) - timedelta(minutes=5)).astimezone(tz8)

    handle_create_task(db, description="x", scheduled_at=past_aware.isoformat())

    due = find_due_jobs(_utcnow(), db)
    assert len(due) == 1
