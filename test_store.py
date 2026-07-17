"""Tests for the JobStore module."""
import pytest
from datetime import datetime, timezone

from queuectl.models import Job
from queuectl.store import JobStore


class TestJobStoreEnqueue:
    def test_enqueue_job(self, store):
        job = Job(id="j1", command="echo hello")
        result = store.enqueue(job)
        assert result.id == "j1"
        assert result.state == "pending"

    def test_enqueue_duplicate_id_fails(self, store):
        job = Job(id="j1", command="echo hello")
        store.enqueue(job)
        with pytest.raises(ValueError, match="already exists"):
            store.enqueue(Job(id="j1", command="echo world"))

    def test_get_job(self, store):
        job = Job(id="j1", command="echo hello")
        store.enqueue(job)
        retrieved = store.get_job("j1")
        assert retrieved is not None
        assert retrieved.id == "j1"
        assert retrieved.command == "echo hello"

    def test_get_nonexistent_job(self, store):
        assert store.get_job("nonexistent") is None


class TestJobStoreClaim:
    def test_claim_pending_job(self, store):
        store.enqueue(Job(id="j1", command="echo hello"))
        job = store.claim_job("worker-1")
        assert job is not None
        assert job.id == "j1"
        assert job.state == "processing"

    def test_claim_returns_none_when_empty(self, store):
        assert store.claim_job("worker-1") is None

    def test_claim_prevents_duplicate_processing(self, store):
        store.enqueue(Job(id="j1", command="echo hello"))
        first = store.claim_job("worker-1")
        assert first is not None
        second = store.claim_job("worker-2")
        assert second is None

    def test_claim_respects_priority(self, store):
        store.enqueue(Job(id="low", command="echo low", priority=1))
        store.enqueue(Job(id="high", command="echo high", priority=10))
        job = store.claim_job("worker-1")
        assert job.id == "high"

    def test_claim_failed_job_ready_for_retry(self, store):
        job = Job(id="j1", command="echo hello", state="failed", attempts=1,
                  next_retry_at=datetime.now(timezone.utc).isoformat())
        store.enqueue(job)
        claimed = store.claim_job("worker-1")
        assert claimed is not None
        assert claimed.id == "j1"
        assert claimed.state == "processing"


class TestJobStoreList:
    def test_list_all_jobs(self, store):
        store.enqueue(Job(id="j1", command="echo 1"))
        store.enqueue(Job(id="j2", command="echo 2"))
        jobs = store.list_jobs()
        assert len(jobs) == 2

    def test_list_by_state(self, store):
        store.enqueue(Job(id="j1", command="echo 1"))
        store.enqueue(Job(id="j2", command="echo 2"))
        # Claim one to make it processing
        store.claim_job("worker-1")
        pending = store.list_jobs(state="pending")
        assert len(pending) == 1

    def test_list_empty(self, store):
        jobs = store.list_jobs()
        assert len(jobs) == 0


class TestJobStoreStatus:
    def test_status_counts(self, store):
        store.enqueue(Job(id="j1", command="echo 1"))
        store.enqueue(Job(id="j2", command="echo 2"))
        store.enqueue(Job(id="j3", command="echo 3"))
        store.claim_job("worker-1")  # one goes to processing
        status = store.get_status()
        assert status["total"] == 3
        assert status["pending"] == 2
        assert status["processing"] == 1

    def test_status_empty(self, store):
        status = store.get_status()
        assert status["total"] == 0
        assert status["pending"] == 0


class TestJobStoreDLQ:
    def test_dlq_list(self, store):
        job = Job(id="j1", command="bad_cmd", state="dead", attempts=4)
        store.enqueue(job)
        dlq = store.get_dlq_jobs()
        assert len(dlq) == 1
        assert dlq[0].state == "dead"

    def test_retry_dlq_job(self, store):
        job = Job(id="j1", command="bad_cmd", state="dead", attempts=4,
                  error="failed", exit_code=1)
        store.enqueue(job)
        result = store.retry_dlq_job("j1")
        assert result is True
        updated = store.get_job("j1")
        assert updated.state == "pending"
        assert updated.attempts == 0
        assert updated.error is None

    def test_retry_non_dlq_job_fails(self, store):
        job = Job(id="j1", command="echo hi", state="pending")
        store.enqueue(job)
        result = store.retry_dlq_job("j1")
        assert result is False

    def test_purge_dlq(self, store):
        job = Job(id="j1", command="bad_cmd", state="dead", attempts=4)
        store.enqueue(job)
        count = store.purge_dlq()
        assert count == 1
        assert store.get_job("j1") is None


class TestJobStorePersistence:
    def test_data_survives_reopen(self, tmp_dir):
        import os
        db_path = os.path.join(tmp_dir, "persist.db")
        store1 = JobStore(db_path)
        store1.enqueue(Job(id="j1", command="echo persist"))
        store1.claim_job("worker-1")

        # Open a new connection
        store2 = JobStore(db_path)
        job = store2.get_job("j1")
        assert job is not None
        assert job.state == "processing"
        assert job.command == "echo persist"