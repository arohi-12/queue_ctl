"""Persistent job storage using SQLite for queuectl."""
import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional, List

from queuectl.models import Job


class JobStore:
    """SQLite-backed persistent job storage with atomic claim operations."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            from queuectl.utils import get_db_path
            db_path = get_db_path()
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_retry_at TEXT,
                    output TEXT,
                    error TEXT,
                    exit_code INTEGER,
                    priority INTEGER NOT NULL DEFAULT 0,
                    run_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE INDEX IF NOT EXISTS idx_jobs_next_retry ON jobs(next_retry_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_priority_created
                    ON jobs(priority DESC, created_at ASC);
            """
            )
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, job: Job) -> Job:
        """Add a new job to the queue."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO jobs (id, command, state, attempts, max_retries,
                    created_at, updated_at, next_retry_at, output, error,
                    exit_code, priority, run_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    job.id,
                    job.command,
                    job.state,
                    job.attempts,
                    job.max_retries,
                    job.created_at,
                    job.updated_at,
                    job.next_retry_at,
                    job.output,
                    job.error,
                    job.exit_code,
                    job.priority,
                    job.run_at,
                ),
            )
            conn.commit()
            return job
        except sqlite3.IntegrityError:
            raise ValueError(f"Job with id '{job.id}' already exists")
        finally:
            conn.close()

    def claim_job(self, worker_id: str = None) -> Optional[Job]:
        """Atomically claim an available job for processing.

        Uses BEGIN IMMEDIATE to prevent race conditions between workers.
        """
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc).isoformat()

            # Try pending jobs first (respecting run_at for scheduled jobs)
            row = conn.execute(
                """
                SELECT id FROM jobs
                WHERE state = 'pending'
                  AND (run_at IS NULL OR run_at <= ?)
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            """,
                (now,),
            ).fetchone()

            # If no pending jobs, try failed jobs ready for retry
            if row is None:
                row = conn.execute(
                    """
                    SELECT id FROM jobs
                    WHERE state = 'failed'
                      AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                """,
                    (now,),
                ).fetchone()

            if row is None:
                conn.rollback()
                return None

            job_id = row["id"]
            cursor = conn.execute(
                """
                UPDATE jobs SET state = 'processing', updated_at = ?
                WHERE id = ? AND state IN ('pending', 'failed')
            """,
                (now, job_id),
            )

            if cursor.rowcount == 0:
                conn.rollback()
                return None

            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            conn.commit()

            if row:
                return Job.from_dict(dict(row))
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_job(self, job: Job):
        """Update an existing job's fields."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                UPDATE jobs SET command=?, state=?, attempts=?, max_retries=?,
                    created_at=?, updated_at=?, next_retry_at=?, output=?,
                    error=?, exit_code=?, priority=?, run_at=?
                WHERE id=?
            """,
                (
                    job.command,
                    job.state,
                    job.attempts,
                    job.max_retries,
                    job.created_at,
                    job.updated_at,
                    job.next_retry_at,
                    job.output,
                    job.error,
                    job.exit_code,
                    job.priority,
                    job.run_at,
                    job.id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row:
                return Job.from_dict(dict(row))
            return None
        finally:
            conn.close()

    def list_jobs(self, state: Optional[str] = None, limit: int = 50) -> List[Job]:
        """List jobs, optionally filtered by state."""
        conn = self._get_conn()
        try:
            if state:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                    (state, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [Job.from_dict(dict(row)) for row in rows]
        finally:
            conn.close()

    def get_status(self) -> dict:
        """Get a summary of job counts by state."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT state, COUNT(*) as count FROM jobs GROUP BY state"
            ).fetchall()
            status = {row["state"]: row["count"] for row in rows}
            for state in ["pending", "processing", "completed", "failed", "dead"]:
                if state not in status:
                    status[state] = 0
            status["total"] = sum(status.values())
            return status
        finally:
            conn.close()

    def get_dlq_jobs(self) -> List[Job]:
        """Get all jobs in the Dead Letter Queue."""
        return self.list_jobs(state="dead", limit=1000)

    def retry_dlq_job(self, job_id: str) -> bool:
        """Move a job from DLQ back to pending for retry."""
        job = self.get_job(job_id)
        if job and job.state == "dead":
            job.state = "pending"
            job.attempts = 0
            job.next_retry_at = None
            job.updated_at = datetime.now(timezone.utc).isoformat()
            job.error = None
            job.exit_code = None
            job.output = None
            self.update_job(job)
            return True
        return False

    def get_stale_processing(self, timeout_seconds: int = 600) -> List[Job]:
        """Get jobs stuck in processing state for too long."""
        conn = self._get_conn()
        try:
            cutoff = datetime.now(timezone.utc)
            from datetime import timedelta
            cutoff_str = (cutoff - timedelta(seconds=timeout_seconds)).isoformat()
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE state = 'processing' AND updated_at < ?
            """,
                (cutoff_str,),
            ).fetchall()
            return [Job.from_dict(dict(row)) for row in rows]
        finally:
            conn.close()

    def recover_stale(self, timeout_seconds: int = 600) -> int:
        """Reset stale processing jobs back to pending."""
        stale = self.get_stale_processing(timeout_seconds)
        count = 0
        for job in stale:
            job.state = "pending"
            job.updated_at = datetime.now(timezone.utc).isoformat()
            self.update_job(job)
            count += 1
        return count

    def purge_completed(self) -> int:
        """Remove all completed jobs."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM jobs WHERE state = 'completed'")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def purge_dlq(self) -> int:
        """Remove all dead-letter jobs."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM jobs WHERE state = 'dead'")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()