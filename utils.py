"""Utility functions for queuectl."""
import os


def get_data_dir() -> str:
    """Get the data directory for queuectl (default: .queuectl in CWD)."""
    data_dir = os.environ.get(
        "QUEUECTL_DATA_DIR", os.path.join(os.getcwd(), ".queuectl")
    )
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_db_path() -> str:
    """Get the SQLite database path."""
    return os.path.join(get_data_dir(), "queue.db")


def get_config_path() -> str:
    """Get the configuration file path."""
    return os.path.join(get_data_dir(), "config.json")


def get_pid_file() -> str:
    """Get the worker PID file path."""
    return os.path.join(get_data_dir(), "workers.json")


def get_log_dir() -> str:
    """Get the log directory for worker output."""
    log_dir = os.path.join(get_data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_worker_info_files() -> list:
    """Get list of active worker info files."""
    data_dir = get_data_dir()
    files = []
    for f in os.listdir(data_dir):
        if f.startswith("worker_") and f.endswith(".info"):
            files.append(os.path.join(data_dir, f))
    return files