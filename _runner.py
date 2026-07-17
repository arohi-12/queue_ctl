"""Standalone worker runner script.

This module is executed as a subprocess by the CLI worker start command.
It isolates the worker process so it can run independently with its own
event loop and signal handling.
"""
import sys
import os

# Add the parent directory to path so we can import queuectl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from queuectl.worker import run_worker_process


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python -m queuectl._runner <worker_id> <db_path> <config_path>")
        sys.exit(1)

    worker_id = int(sys.argv[1])
    db_path = sys.argv[2]
    config_path = sys.argv[3]

    try:
        run_worker_process(worker_id, db_path, config_path)
    except KeyboardInterrupt:
        pass