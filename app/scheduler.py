import queue
import threading
import time
from datetime import datetime

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Job, _utcnow

# In-memory queue (simulates SQS for prototype)
job_queue: queue.Queue[int] = queue.Queue()


def get_time_bucket(scheduled_at: datetime) -> str:
    """Convert scheduled time to time bucket — used as DB partition key."""
    return scheduled_at.strftime("%Y%m%d%H")


def find_due_jobs(current_time: datetime, db: Session) -> list[Job]:
    """Watcher calls every interval: find all due, pending jobs.

    The hour bucket (``YYYYMMDDHH``) is fixed-width and chronologically
    sortable, so ``time_bucket <= current bucket`` prunes the scan to the
    current and all *earlier* partitions — catching jobs left over from a
    past hour (process was offline, scheduled in the past, or an
    hour-boundary race) instead of only the current hour.
    """
    bucket = get_time_bucket(current_time)
    return (
        db.query(Job)
        .filter(
            Job.time_bucket <= bucket,
            Job.scheduled_at <= current_time,
            Job.status == "pending",
        )
        .all()
    )


def watcher_loop(interval: int = 10):
    """Watcher scans DB for due jobs and pushes them to the queue."""
    while True:
        db = SessionLocal()
        try:
            now = _utcnow()
            due_jobs = find_due_jobs(now, db)
            for job in due_jobs:
                job.status = "queued"
                db.commit()
                job_queue.put(job.id)
        finally:
            db.close()
        time.sleep(interval)


def _default_executor(job: Job) -> str:
    """Run the job's work and return its result.

    Simulated for the prototype — in production this would call the LLM.
    Injectable so the execution step can be swapped or made to fail in tests.
    """
    return f"Executed: {job.description}"


def _safe_mark_failed(db: Session, job_id: int, exc: Exception) -> None:
    """Record a failure on its own clean transaction. Swallows further errors.

    Re-queries by id (rather than reusing a possibly-expired instance) after a
    rollback, and never raises — if the DB is unusable there is nothing more we
    can record, but the worker must still survive.
    """
    try:
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is not None:
            job.status = "failed"
            job.result = str(exc)
            db.commit()
    except Exception:
        pass


def process_job(job_id: int, db: Session, execute=_default_executor) -> None:
    """Execute a single job through its lifecycle. Never raises.

    pending -> running -> completed, or -> failed on any error. Self-contained
    error handling means one bad job can never escape and kill the worker
    thread (Bug 2: the old inline handler referenced an unbound `job` when the
    lookup failed and took the whole worker down).
    """
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None or job.status == "cancelled":
            return

        job.status = "running"
        db.commit()

        job.result = execute(job)
        job.status = "completed"
        db.commit()
    except Exception as exc:
        _safe_mark_failed(db, job_id, exc)


def worker_loop():
    """Worker pulls job ids off the queue and processes them, forever.

    process_job owns all per-job error handling and never raises, so the loop
    stays alive across failing jobs.
    """
    while True:
        job_id = job_queue.get()
        db = SessionLocal()
        try:
            process_job(job_id, db)
        finally:
            db.close()
            job_queue.task_done()


def start_scheduler():
    """Start watcher and worker threads."""
    watcher = threading.Thread(target=watcher_loop, daemon=True)
    worker = threading.Thread(target=worker_loop, daemon=True)
    watcher.start()
    worker.start()
