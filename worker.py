"""Worker process management and job execution for queuectl."""
import subprocess
import signal
import sys
import os
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from queuectl.store import JobStore
from queuectl.config import Config
from queuectl.models import Job

# Global shutdown flag for signal handling
_shutdown = False


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    global _shutdown
    _shutdown = True


def run_worker_process(worker_id: int, db_path: str, config_path: str):
    """Main entry point for a background worker process.

    Runs continuously, polling for available jobs and executing them.
    Handles SIGTERM for graceful shutdown (finishes current job before exit).
    """
    global _shutdown

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    store = JobStore(db_path)
    config = Config(config_path)

    worker_name = f"worker-{worker_id}"

    # Write worker info file for status tracking
    from queuectl.utils import get_data_dir
    data_dir = get_data_dir()
    worker_info_file = os.path.join(data_dir, f"worker_{os.getpid()}.info")

    def _write_info(current_job=None):
        try:
            with open(worker_info_file, "w") as f:
                json.dump(
                    {
                        "pid": os.getpid(),
                        "worker_id": worker_id,
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "current_job": current_job,
                    },
                    f,
                )
        except IOError:
            pass

    _write_info()

    try:
        while not _shutdown:
            try:
                job = store.claim_job(worker_name)
                if job:
                    _write_info(current_job=job.id)
                    _execute_job(job, store, config)
                    _write_info(current_job=None)
                else:
                    time.sleep(config.get("poll_interval"))
            except Exception:
                # Keep worker alive even if individual operations fail
                time.sleep(config.get("poll_interval"))
    finally:
        # Clean up worker info file
        try:
            if os.path.exists(worker_info_file):
                os.remove(worker_info_file)
        except OSError:
            pass


def _execute_job(job: Job, store: JobStore, config: Config):
    """Execute a job's command and update its state based on the result."""
    job.attempts += 1
    job.updated_at = datetime.now(timezone.utc).isoformat()
    store.update_job(job)

    timeout = config.get("job_timeout")

    try:
        result = subprocess.run(
            job.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        job.output = result.stdout
        job.exit_code = result.returncode
        job.updated_at = datetime.now(timezone.utc).isoformat()

        if result.returncode == 0:
            job.state = "completed"
            job.error = None
            job.next_retry_at = None
        else:
            job.error = result.stderr or f"Command exited with code {result.returncode}"
            _handle_failure(job, config)

    except subprocess.TimeoutExpired:
        job.error = f"Job timed out after {timeout}s"
        job.exit_code = -1
        job.updated_at = datetime.now(timezone.utc).isoformat()
        _handle_failure(job, config)

    except Exception as e:
        job.error = f"Execution error: {str(e)}"
        job.exit_code = -1
        job.updated_at = datetime.now(timezone.utc).isoformat()
        _handle_failure(job, config)

    store.update_job(job)


def _handle_failure(job: Job, config: Config):
    """Handle a failed job - schedule retry with exponential backoff or move to DLQ.

    Exponential backoff formula: delay = base ^ attempts seconds
    Job moves to DLQ (state='dead') when attempts > max_retries.
    With max_retries=3, the job gets 1 initial attempt + 3 retries = 4 total attempts
    before moving to the Dead Letter Queue.
    """
    backoff_base = config.get("backoff_base")
    max_retries = config.get("max_retries")

    # job.attempts was already incremented before execution
    if job.attempts > max_retries:
        # Exhausted all retries — move to Dead Letter Queue
        job.state = "dead"
        job.next_retry_at = None
    else:
        # Schedule retry with exponential backoff
        delay_seconds = backoff_base ** job.attempts
        retry_time = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        job.state = "failed"
        job.next_retry_at = retry_time.isoformat()


def get_active_workers() -> list:
    """Get list of currently active worker processes."""
    from queuectl.utils import get_worker_info_files

    workers = []
    for info_file in get_worker_info_files():
        try:
            with open(info_file, "r") as f:
                info = json.load(f)
            # Check if process is still alive
            pid = info.get("pid")
            if pid and _is_process_alive(pid):
                workers.append(info)
            else:
                # Clean up stale info file
                os.remove(info_file)
        except (IOError, json.JSONDecodeError, OSError):
            # Clean up corrupt info file
            try:
                os.remove(info_file)
            except OSError:
                pass
    return workers


def stop_all_workers():
    """Send SIGTERM to all active workers for graceful shutdown."""
    workers = get_active_workers()
    for w in workers:
        pid = w.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return True
    except OSError:
        return False