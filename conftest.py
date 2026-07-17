"""Shared test fixtures for queuectl."""
import os
import tempfile
import pytest

from queuectl.store import JobStore
from queuectl.config import Config
from queuectl.models import Job


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def store(tmp_dir):
    """Create a JobStore with a temporary database."""
    db_path = os.path.join(tmp_dir, "test.db")
    return JobStore(db_path)


@pytest.fixture
def config(tmp_dir):
    """Create a Config with a temporary config file."""
    config_path = os.path.join(tmp_dir, "config.json")
    return Config(config_path)


@pytest.fixture
def sample_job():
    """Create a sample job for testing."""
    return Job(id="test-1", command="echo hello", max_retries=3)