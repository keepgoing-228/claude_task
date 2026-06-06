"""Tests for the watcher's due-job query (app.scheduler.find_due_jobs)."""

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Job, _utcnow
from app.scheduler import find_due_jobs, get_time_bucket


def make_session() -> Session:
    """Fresh in-memory SQLite session, isolated per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def add_job(db: Session, *, scheduled_at, status: str = "pending") -> Job:
    job = Job(
        description=f"job @ {scheduled_at}",
        scheduled_at=scheduled_at,
        time_bucket=get_time_bucket(scheduled_at),
        status=status,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_includes_overdue_job_from_an_earlier_bucket():
    """A due, pending job whose hour-bucket is in the past must still be found.

    Reproduces Bug 1: the watcher only matched the *current* hour bucket, so
    any job left over from an earlier hour (process was offline, scheduled in
    the past, or caught on an hour-boundary race) was never picked up.
    """
    db = make_session()
    now = _utcnow()
    overdue = add_job(db, scheduled_at=now - timedelta(hours=2))

    due = find_due_jobs(now, db)

    assert overdue in due


def test_includes_due_job_in_current_bucket():
    """Control: a due job in the current hour is still returned."""
    db = make_session()
    now = _utcnow()
    current = add_job(db, scheduled_at=now - timedelta(minutes=1))

    assert current in find_due_jobs(now, db)


def test_excludes_future_job_in_a_later_bucket():
    """Guard: `<=` must not fire a job whose time has not yet arrived."""
    db = make_session()
    now = _utcnow()
    future = add_job(db, scheduled_at=now + timedelta(hours=2))

    assert future not in find_due_jobs(now, db)


def test_excludes_non_pending_jobs():
    """Guard: only `pending` jobs are due; queued/completed/cancelled are not."""
    db = make_session()
    now = _utcnow()
    past = now - timedelta(hours=2)
    for status in ("queued", "running", "completed", "failed", "cancelled"):
        add_job(db, scheduled_at=past, status=status)

    assert find_due_jobs(now, db) == []
