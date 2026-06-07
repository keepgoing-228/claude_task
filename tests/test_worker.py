"""Tests for the worker's per-job processing (app.scheduler.process_job).

Bug 2: the old worker_loop ran job execution inline and its `except` block
referenced `job` unconditionally. If the DB lookup raised, `job` was unbound,
the handler itself raised UnboundLocalError, that escaped `while True`, and the
worker thread died silently — the queue then filled with nothing consuming it.

process_job isolates one job's lifecycle, owns its error handling, and must
never raise, so a single bad job can never take down the worker.
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Job, _utcnow
from app.scheduler import get_time_bucket, process_job


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def add_job(db: Session, *, status: str = "pending") -> Job:
    scheduled_at = _utcnow() - timedelta(minutes=1)
    job = Job(
        description="do the thing",
        scheduled_at=scheduled_at,
        time_bucket=get_time_bucket(scheduled_at),
        status=status,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def boom(job: Job) -> str:
    raise RuntimeError("executor failed")


def test_completes_a_pending_job(db):
    job = add_job(db)

    process_job(job.id, db)

    db.refresh(job)
    assert job.status == "completed"
    assert job.result == "Executed: do the thing"


def test_marks_job_failed_when_execution_raises(db):
    job = add_job(db)

    # Must not raise — the worker has to survive a failing job.
    process_job(job.id, db, execute=boom)

    db.refresh(job)
    assert job.status == "failed"
    assert "executor failed" in job.result


def test_does_not_raise_when_job_lookup_fails(db):
    """Reproduces the Bug 2 crash: a broken DB lookup must not propagate.

    With the table dropped, the very first query raises — the path that used to
    leave `job` unbound and kill the worker thread.
    """
    job = add_job(db)
    Base.metadata.drop_all(db.get_bind())  # now any query raises

    # The assertion is simply that this call returns instead of raising.
    process_job(job.id, db)


def test_skips_cancelled_job_without_executing(db):
    job = add_job(db, status="cancelled")
    calls = []

    process_job(job.id, db, execute=lambda j: calls.append(j) or "ran")

    db.refresh(job)
    assert job.status == "cancelled"
    assert calls == []  # executor never ran


def test_missing_job_is_a_noop(db):
    process_job(9999, db)  # no such id — must not raise
