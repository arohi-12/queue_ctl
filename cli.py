"""CLI interface for queuectl using Click."""
import json
import sys
import os
import time
import signal
import subprocess  # <-- ADDED FOR WINDOWS COMPATIBILITY

import click

from queuectl.models import Job
from queuectl.store import JobStore
from queuectl.config import Config
from queuectl.worker import get_active_workers, stop_all_workers
from queuectl import __version__


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_store() -> JobStore:
    return JobStore()


def _get_config() -> Config:
    return Config()


def _print_job(job: Job, verbose: bool = False):
    """Pretty-print a single job."""
    click.secho(f"  ID:          {job.id}", fg="white")
    click.secho(f"  Command:     {job.command}", fg="white")
    click.secho(f"  State:       {job.state}", fg=_state_color(job.state))
    click.secho(f"  Attempts:    {job.attempts}/{job.max_retries}", fg="white")
    if job.priority != 0:
        click.secho(f"  Priority:    {job.priority}", fg="white")
    if job.run_at:
        click.secho(f"  Run At:      {job.run_at}", fg="white")
    if job.next_retry_at:
        click.secho(f"  Next Retry:  {job.next_retry_at}", fg="yellow")
    if verbose:
        if job.output:
            click.secho(f"  Output:      {job.output.strip()}", fg="green")
        if job.error:
            click.secho(f"  Error:       {job.error.strip()}", fg="red")
        if job.exit_code is not None:
            click.secho(f"  Exit Code:   {job.exit_code}", fg="white")
    click.secho(f"  Created:     {job.created_at}", fg="bright_black")
    click.secho(f"  Updated:     {job.updated_at}", fg="bright_black")
    click.echo()


def _state_color(state: str) -> str:
    colors = {
        "pending": "yellow",
        "processing": "blue",
        "completed": "green",
        "failed": "red",
        "dead": "bright_red",
    }
    return colors.get(state, "white")


# ── Main CLI Group ──────────────────────────────────────────────────────────


@click.group()
@click.version_option(version=__version__, prog_name="queuectl")
def cli():
    """queuectl - A CLI-based background job queue system.

    Manage background jobs with workers, retries, exponential backoff,
    and a Dead Letter Queue.
    """
    pass


# ── Enqueue Command ─────────────────────────────────────────────────────────


@cli.command()
@click.argument("json_data")
@click.option("--priority", default=0, help="Job priority (higher = processed first)")
@click.option("--run-at", default=None, help="Schedule job for later (ISO 8601 datetime)")
@click.option("--max-retries", default=None, type=int, help="Override default max retries")
def enqueue(json_data, priority, run_at, max_retries):
    """Add a new job to the queue.

    JSON_DATA should be a JSON object with at least a "command" field.

    Examples:

        queuectl enqueue '{"command": "echo Hello World"}'

        queuectl enqueue '{"id": "job1", "command": "sleep 2"}'

        queuectl enqueue '{"command": "echo urgent", "priority": 10}'
    """
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        click.secho(f"Invalid JSON: {e}", fg="red")
        sys.exit(1)

    if "command" not in data:
        click.secho("Error: 'command' field is required in job JSON", fg="red")
        sys.exit(1)

    config = _get_config()

    job = Job(
        id=data.get("id", Job.id),
        command=data["command"],
        priority=data.get("priority", priority),
        max_retries=max_retries if max_retries is not None else data.get(
            "max_retries", config.get("max_retries")
        ),
        run_at=run_at or data.get("run_at"),
    )

    store = _get_store()
    try:
        store.enqueue(job)
        click.secho(f"✓ Job enqueued successfully", fg="green")
        _print_job(job)
    except ValueError as e:
        click.secho(f"Error: {e}", fg="red")
        sys.exit(1)


# ── Worker Commands ─────────────────────────────────────────────────────────


@cli.group()
def worker():
    """Manage worker processes."""
    pass


@worker.command("start")
@click.option("--count", "-n", default=1, type=int, help="Number of workers to start")
def worker_start(count):
    """Start one or more worker processes.

    Workers run in the background, polling for and executing jobs.
    They handle SIGTERM for graceful shutdown.

    Examples:

        queuectl worker start

        queuectl worker start --count 3
    """
    if count < 1:
        click.secho("Error: count must be at least 1", fg="red")
        sys.exit(1)

    from queuectl.utils import get_db_path, get_config_path

    db_path = get_db_path()
    config_path = get_config_path()
    runner_path = os.path.join(os.path.dirname(__file__), "_runner.py")

    pids = []
    for i in range(count):
        worker_id = int(time.time() * 1000) % 100000 + i
        try:
            # --- FIXED: Use subprocess instead of os.fork for Windows compatibility ---
            process = subprocess.Popen(
                [sys.executable, runner_path, str(worker_id), db_path, config_path],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            pids.append(process.pid)
        except Exception as e:
            click.secho(f"Error starting worker {i + 1}: {e}", fg="red")

    if pids:
        click.secho(f"✓ Started {len(pids)} worker(s)", fg="green")
        click.secho(f"  PIDs: {', '.join(str(p) for p in pids)}", fg="white")
        click.secho(f"  Use 'queuectl worker stop' to stop gracefully", fg="bright_black")
    else:
        click.secho("Error: No workers started", fg="red")
        sys.exit(1)


@worker.command("stop")
def worker_stop():
    """Stop all running workers gracefully.

    Sends SIGTERM to each worker. Workers finish their current job before exiting.
    """
    workers = get_active_workers()
    if not workers:
        click.secho("No active workers found.", fg="yellow")
        return

    click.secho(f"Stopping {len(workers)} worker(s)...", fg="yellow")
    stop_all_workers()

    # Wait briefly for workers to finish
    time.sleep(2)

    remaining = get_active_workers()
    if remaining:
        click.secho(f"  {len(remaining)} worker(s) still processing jobs", fg="yellow")
        click.secho(f"  They will exit after completing current jobs", fg="bright_black")
    else:
        click.secho("✓ All workers stopped", fg="green")


@worker.command("status")
def worker_status():
    """Show active worker processes."""
    workers = get_active_workers()
    if not workers:
        click.secho("No active workers.", fg="yellow")
        return

    click.secho(f"Active Workers: {len(workers)}", fg="green")
    click.echo()
    for w in workers:
        click.secho(f"  Worker {w.get('worker_id', '?')}", fg="white")
        click.secho(f"    PID:         {w.get('pid', '?')}", fg="white")
        click.secho(f"    Started:     {w.get('started_at', '?')}", fg="bright_black")
        if w.get("current_job"):
            click.secho(f"    Current Job: {w['current_job']}", fg="blue")
        else:
            click.secho(f"    Current Job: (idle)", fg="bright_black")
        click.echo()


# ── Status Command ──────────────────────────────────────────────────────────


@cli.command()
def status():
    """Show summary of all job states and active workers.

    Displays a count of jobs in each state and lists active workers.
    """
    store = _get_store()
    job_status = store.get_status()
    workers = get_active_workers()

    click.secho("╔══════════════════════════════════════╗", fg="cyan")
    click.secho("║        QueueCTL Status               ║", fg="cyan")
    click.secho("╚══════════════════════════════════════╝", fg="cyan")
    click.echo()

    click.secho("Jobs:", fg="white", bold=True)
    click.secho(f"  Total:       {job_status.get('total', 0)}", fg="white")
    click.secho(f"  Pending:     {job_status.get('pending', 0)}", fg="yellow")
    click.secho(f"  Processing:  {job_status.get('processing', 0)}", fg="blue")
    click.secho(f"  Completed:   {job_status.get('completed', 0)}", fg="green")
    click.secho(f"  Failed:      {job_status.get('failed', 0)}", fg="red")
    click.secho(f"  Dead (DLQ):  {job_status.get('dead', 0)}", fg="bright_red")
    click.echo()

    click.secho(f"Active Workers: {len(workers)}", fg="green" if workers else "yellow")
    for w in workers:
        current = w.get("current_job", "")
        job_str = f" → {current}" if current else " (idle)"
        click.secho(f"  Worker {w.get('worker_id', '?')} (PID {w.get('pid', '?')}){job_str}", fg="white")

    # Show stale jobs warning
    stale = store.get_stale_processing()
    if stale:
        click.echo()
        click.secho(f"⚠ {len(stale)} job(s) stuck in processing state", fg="yellow")
        click.secho("  Run 'queuectl recover' to reset them", fg="bright_black")


# ── List Command ────────────────────────────────────────────────────────────


@cli.command("list")
@click.option("--state", "-s", default=None, help="Filter by state (pending/processing/completed/failed/dead)")
@click.option("--limit", "-l", default=20, type=int, help="Maximum jobs to display")
@click.option("--verbose", "-v", is_flag=True, help="Show output and error details")
def list_jobs(state, limit, verbose):
    """List jobs, optionally filtered by state.

    Examples:

        queuectl list

        queuectl list --state pending

        queuectl list --state dead --verbose
    """
    store = _get_store()

    valid_states = ["pending", "processing", "completed", "failed", "dead"]
    if state and state not in valid_states:
        click.secho(f"Invalid state '{state}'. Valid: {', '.join(valid_states)}", fg="red")
        sys.exit(1)

    jobs = store.list_jobs(state=state, limit=limit)

    if not jobs:
        filter_str = f" with state '{state}'" if state else ""
        click.secho(f"No jobs found{filter_str}.", fg="yellow")
        return

    filter_str = f" [{state}]" if state else ""
    click.secho(f"Jobs{filter_str} ({len(jobs)} shown):", fg="white", bold=True)
    click.echo()

    for job in jobs:
        _print_job(job, verbose=verbose)


# ── DLQ Commands ────────────────────────────────────────────────────────────


@cli.group()
def dlq():
    """Manage the Dead Letter Queue.

    The DLQ contains jobs that have permanently failed after
    exhausting all retry attempts.
    """
    pass


@dlq.command("list")
@click.option("--verbose", "-v", is_flag=True, help="Show error details")
def dlq_list(verbose):
    """View jobs in the Dead Letter Queue."""
    store = _get_store()
    jobs = store.get_dlq_jobs()

    if not jobs:
        click.secho("Dead Letter Queue is empty.", fg="green")
        return

    click.secho(f"Dead Letter Queue ({len(jobs)} job(s)):", fg="bright_red", bold=True)
    click.echo()

    for job in jobs:
        _print_job(job, verbose=True if verbose else False)


@dlq.command("retry")
@click.argument("job_id")
def dlq_retry(job_id):
    """Retry a job from the Dead Letter Queue.

    Moves the job back to pending state and resets its attempt count.

    Example:

        queuectl dlq retry job1
    """
    store = _get_store()

    if store.retry_dlq_job(job_id):
        click.secho(f"✓ Job '{job_id}' moved from DLQ back to pending", fg="green")
    else:
        click.secho(f"Error: Job '{job_id}' not found in DLQ", fg="red")
        sys.exit(1)


@dlq.command("purge")
@click.confirmation_option(prompt="Remove all jobs from the Dead Letter Queue?")
def dlq_purge():
    """Remove all jobs from the Dead Letter Queue."""
    store = _get_store()
    count = store.purge_dlq()
    click.secho(f"✓ Removed {count} job(s) from DLQ", fg="green")


# ── Config Commands ─────────────────────────────────────────────────────────


@cli.group()
def config():
    """Manage queuectl configuration.

    Configuration is persisted in .queuectl/config.json.
    """
    pass


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value.

    Common keys: max-retries, backoff-base, poll-interval, job-timeout

    Examples:

        queuectl config set max-retries 5

        queuectl config set backoff-base 3

        queuectl config set poll-interval 0.5
    """
    cfg = _get_config()
    try:
        cfg.set(key, value)
        # Read back to show parsed value
        actual = cfg.get(key)
        click.secho(f"✓ {key} = {actual}", fg="green")
    except Exception as e:
        click.secho(f"Error setting config: {e}", fg="red")
        sys.exit(1)


@config.command("get")
@click.argument("key")
def config_get(key):
    """Get a configuration value."""
    cfg = _get_config()
    value = cfg.get(key)
    if value is not None:
        click.secho(f"{key} = {value}", fg="white")
    else:
        click.secho(f"Key '{key}' not found in configuration", fg="yellow")


@config.command("list")
def config_list():
    """Show all configuration values."""
    cfg = _get_config()
    all_config = cfg.get_all()
    click.secho("Current Configuration:", fg="white", bold=True)
    click.echo()
    for key, value in sorted(all_config.items()):
        click.secho(f"  {key:20s} = {value}", fg="white")


@config.command("reset")
@click.confirmation_option(prompt="Reset all configuration to defaults?")
def config_reset():
    """Reset configuration to defaults."""
    cfg = _get_config()
    cfg.reset()
    click.secho("✓ Configuration reset to defaults", fg="green")


# ── Recover Command ─────────────────────────────────────────────────────────


@cli.command()
@click.option("--timeout", default=600, type=int, help="Stale threshold in seconds")
def recover(timeout):
    """Reset stale processing jobs back to pending.

    Jobs stuck in 'processing' state for longer than the timeout
    are reset to 'pending' so they can be picked up again.
    """
    store = _get_store()
    count = store.recover_stale(timeout)
    if count > 0:
        click.secho(f"✓ Recovered {count} stale job(s)", fg="green")
    else:
        click.secho("No stale jobs found.", fg="yellow")


# ── Purge Command ───────────────────────────────────────────────────────────


@cli.command()
@click.option("--completed", is_flag=True, help="Purge completed jobs")
@click.option("--dead", is_flag=True, help="Purge dead-letter jobs")
@click.confirmation_option(prompt="Purge selected jobs?")
def purge(completed, dead):
    """Remove completed and/or dead jobs from the store.

    Examples:

        queuectl purge --completed

        queuectl purge --completed --dead
    """
    store = _get_store()
    total = 0

    if completed:
        count = store.purge_completed()
        total += count
        click.secho(f"  Purged {count} completed job(s)", fg="white")

    if dead:
        count = store.purge_dlq()
        total += count
        click.secho(f"  Purged {count} dead job(s)", fg="white")

    if not completed and not dead:
        click.secho("Specify --completed and/or --dead to purge", fg="yellow")
        return

    click.secho(f"✓ Total purged: {total} job(s)", fg="green")


# ── Inspect Command (bonus: job output logging) ────────────────────────────


@cli.command()
@click.argument("job_id")
def inspect(job_id):
    """Show detailed information about a specific job.

    Example:

        queuectl inspect job1
    """
    store = _get_store()
    job = store.get_job(job_id)

    if not job:
        click.secho(f"Job '{job_id}' not found", fg="red")
        sys.exit(1)

    click.secho("╔══════════════════════════════════════╗", fg="cyan")
    click.secho(f"  Job: {job.id}", fg="cyan", bold=True)
    click.secho("╚══════════════════════════════════════╝", fg="cyan")
    click.echo()

    click.secho(f"  Command:      {job.command}", fg="white")
    click.secho(f"  State:        {job.state}", fg=_state_color(job.state))
    click.secho(f"  Attempts:     {job.attempts}/{job.max_retries}", fg="white")
    click.secho(f"  Priority:     {job.priority}", fg="white")
    click.secho(f"  Exit Code:    {job.exit_code}", fg="white")
    click.secho(f"  Created:      {job.created_at}", fg="bright_black")
    click.secho(f"  Updated:      {job.updated_at}", fg="bright_black")

    if job.run_at:
        click.secho(f"  Run At:       {job.run_at}", fg="yellow")
    if job.next_retry_at:
        click.secho(f"  Next Retry:   {job.next_retry_at}", fg="yellow")

    if job.output:
        click.echo()
        click.secho("  Output:", fg="green")
        for line in job.output.strip().split("\n"):
            click.secho(f"    {line}", fg="green")

    if job.error:
        click.echo()
        click.secho("  Error:", fg="red")
        for line in job.error.strip().split("\n"):
            click.secho(f"    {line}", fg="red")

    click.echo()
    if __name__ == '__main__':
        cli()
    