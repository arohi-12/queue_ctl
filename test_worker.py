"""Tests for the worker module."""
import pytest
from datetime import datetime, timezone, timedelta

from queuectl.models import Job
from queuectl.store import JobStore
from queuectl.config import Config
from queuectl.worker import _execute_job, _handle_failure


class TestJobExecution:
    def test_successful_job(self, store, config):
        job = Job(id="j1", command="echo hello", max_retries=3)
        store.enqueue(job)
        db_job = store.get_job("j1")
        db_job.state = "processing"
        store.update_job(db_job)

        _execute_job(db_job, store, config)

        result = store.get_job("j1")
        assert result.state == "completed"
        assert result.exit_code == 0
        assert "hello" in result.output
        assert result.attempts == 1

    def test_failed_job_retries(self, store, config):
        job = Job(id="j1", command="exit 1", max_retries=3)
        store.enqueue(job)
        db_job = store.get_job("j1")
        db_job.state = "processing"
        store.update_job(db_job)

        _execute_job(db_job, store, config)

        result = store.get_job("j1")
        assert result.state == "failed"
        assert result.attempts == 1
        assert result.next_retry_at is not None

    def test_job_moves_to_dlq_after_max_retries(self, store, config):
        job = Job(id="j1", command="exit 1", max_retries=3, attempts=4)
        store.enqueue(job)
        db_job = store.get_job("j1")
        db_job.state = "processing"
        store.update_job(db_job)

        _execute_job(db_job, store, config)

        result = store.get_job("j1")
        # attempts was 4, incremented to 5, which is > max_retries(3)
        assert result.state == "dead"

    def test_invalid_command_fails_gracefully(self, store, config):
        job = Job(id="j1", command="nonexistent_command_xyz", max_retries=3)
        store.enqueue(job)
        db_job = store.get_job("j1")
        db_job.state = "processing"
        store.update_job(db_job)

        _execute_job(db_job, store, config)

        result = store.get_job("j1")
        assert result.state == "failed"
        assert result.error is not None

    def test_job_timeout(self, store, config):
        config.set("job_timeout", 1)
        job = Job(id="j1", command="sleep 30", max_retries=3)
        store.enqueue(job)
        db_job = store.get_job("j1")
        db_job.state = "processing"
        store.update_job(db_job)

        _execute_job(db_job, store, config)

        result = store.get_job("j1")
        assert result.state == "failed"
        assert "timed out" in result.error.lower()


class TestExponentialBackoff:
    def test_backoff_calculation(self, store, config):
        config.set("backoff_base", 2)
        job = Job(id="j1", command="exit 1", max_retries=3, attempts=1)
        _handle_failure(job, config)
        assert job.state == "failed"
        # delay = 2^1 = 2 seconds
        assert job.next_retry_at is not None

    def test_backoff_increases(self, store, config):
        config.set("backoff_base", 2)

        job1 = Job(id="j1", command="exit 1", max_retries=3, attempts=1)
        _handle_failure(job1, config)
        retry1 = job1.next_retry_at

        job2 = Job(id="j2", command="exit 1", max_retries=3, attempts=2)
        _handle_failure(job2, config)
        retry2 = job2.next_retry_at

        # retry2 should be scheduled further in the future than retry1
        assert retry2 > retry1

    def test_dlq_after_exhausted_retries(self, store, config):
        config.set("max_retries", 3)
        config.set("backoff_base", 2)

        # attempts=4 means it's already been tried 4 times (1 initial + 3 retries)
        job = Job(id="j1", command="exit 1", max_retries=3, attempts=4)
        _handle_failure(job, config)
        assert job.state == "dead"
        assert job.next_retry_at is None


class TestFullRetryCycle:
    def test_complete_retry_cycle_to_dlq(self, store, config):
        """Simulate a job going through its full lifecycle to DLQ."""
        config.set("max_retries", 3)
        config.set("backoff_base", 2)

        job = Job(id="j1", command="exit 1", max_retries=3)
        store.enqueue(job)

        # Simulate 4 attempts (1 initial + 3 retries)
        for attempt_num in range(4):
            db_job = store.get_job("j1")

            if db_job.state == "failed":
                db_job.state = "processing"
                db_job.next_retry_at = None
                store.update_job(db_job)
            elif db_job.state == "pending":
                db_job.state = "processing"
                store.update_job(db_job)

            _execute_job(db_job, store, config)

        result = store.get_job("j1")
        assert result.state == "dead"
        assert result.attempts == 4