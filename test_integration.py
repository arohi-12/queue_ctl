"""Integration tests for queuectl CLI."""
import pytest
import json
import os
import tempfile
from click.testing import CliRunner

from queuectl.cli import cli
from queuectl.store import JobStore
from queuectl.config import Config
from queuectl.models import Job


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def isolated_env():
    """Run in an isolated temporary directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        old_cwd = os.getcwd()
        os.chdir(tmp_dir)
        os.environ["QUEUECTL_DATA_DIR"] = os.path.join(tmp_dir, ".queuectl")
        try:
            yield tmp_dir
        finally:
            os.chdir(old_cwd)
            if "QUEUECTL_DATA_DIR" in os.environ:
                del os.environ["QUEUECTL_DATA_DIR"]


class TestCLIEnqueue:
    def test_enqueue_basic(self, runner, isolated_env):
        result = runner.invoke(cli, [
            "enqueue", '{"command": "echo hello"}'
        ])
        assert result.exit_code == 0
        assert "enqueued" in result.output.lower()

    def test_enqueue_with_id(self, runner, isolated_env):
        result = runner.invoke(cli, [
            "enqueue", '{"id": "job1", "command": "echo hello"}'
        ])
        assert result.exit_code == 0
        assert "job1" in result.output

    def test_enqueue_invalid_json(self, runner, isolated_env):
        result = runner.invoke(cli, [
            "enqueue", "not json"
        ])
        assert result.exit_code != 0

    def test_enqueue_missing_command(self, runner, isolated_env):
        result = runner.invoke(cli, [
            "enqueue", '{"id": "job1"}'
        ])
        assert result.exit_code != 0

    def test_enqueue_with_priority(self, runner, isolated_env):
        result = runner.invoke(cli, [
            "enqueue", '{"command": "echo urgent", "priority": 10}'
        ])
        assert result.exit_code == 0
        assert "10" in result.output


class TestCLIStatus:
    def test_status_empty(self, runner, isolated_env):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0

    def test_status_with_jobs(self, runner, isolated_env):
        runner.invoke(cli, ["enqueue", '{"id": "j1", "command": "echo 1"}'])
        runner.invoke(cli, ["enqueue", '{"id": "j2", "command": "echo 2"}'])
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "2" in result.output


class TestCLIList:
    def test_list_all(self, runner, isolated_env):
        runner.invoke(cli, ["enqueue", '{"id": "j1", "command": "echo 1"}'])
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "j1" in result.output

    def test_list_by_state(self, runner, isolated_env):
        runner.invoke(cli, ["enqueue", '{"id": "j1", "command": "echo 1"}'])
        result = runner.invoke(cli, ["list", "--state", "pending"])
        assert result.exit_code == 0
        assert "j1" in result.output

    def test_list_empty_state(self, runner, isolated_env):
        result = runner.invoke(cli, ["list", "--state", "dead"])
        assert result.exit_code == 0
        assert "no jobs" in result.output.lower()


class TestCLIConfig:
    def test_config_set_and_get(self, runner, isolated_env):
        result = runner.invoke(cli, ["config", "set", "max-retries", "5"])
        assert result.exit_code == 0
        assert "5" in result.output

        result = runner.invoke(cli, ["config", "get", "max-retries"])
        assert result.exit_code == 0
        assert "5" in result.output

    def test_config_list(self, runner, isolated_env):
        result = runner.invoke(cli, ["config", "list"])
        assert result.exit_code == 0
        assert "max-retries" in result.output
        assert "backoff-base" in result.output

    def test_config_backoff_base(self, runner, isolated_env):
        result = runner.invoke(cli, ["config", "set", "backoff-base", "3"])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["config", "get", "backoff-base"])
        assert "3" in result.output


class TestCLIDLQ:
    def test_dlq_list_empty(self, runner, isolated_env):
        result = runner.invoke(cli, ["dlq", "list"])
        assert result.exit_code == 0

    def test_dlq_retry_nonexistent(self, runner, isolated_env):
        result = runner.invoke(cli, ["dlq", "retry", "nonexistent"])
        assert result.exit_code != 0


class TestCLIPersistence:
    def test_jobs_persist_across_commands(self, isolated_env):
        """Test that jobs survive across CLI invocations."""
        runner = CliRunner()
        runner.invoke(cli, ["enqueue", '{"id": "persist-test", "command": "echo persist"}'])

        # Second invocation should see the job
        result = runner.invoke(cli, ["list"])
        assert "persist-test" in result.output

    def test_config_persists(self, isolated_env):
        """Test that config survives across CLI invocations."""
        runner = CliRunner()
        runner.invoke(cli, ["config", "set", "max-retries", "7"])

        result = runner.invoke(cli, ["config", "get", "max-retries"])
        assert "7" in result.output


class TestCLIInspect:
    def test_inspect_existing_job(self, runner, isolated_env):
        runner.invoke(cli, ["enqueue", '{"id": "j1", "command": "echo inspect me"}'])
        result = runner.invoke(cli, ["inspect", "j1"])
        assert result.exit_code == 0
        assert "echo inspect me" in result.output

    def test_inspect_nonexistent_job(self, runner, isolated_env):
        result = runner.invoke(cli, ["inspect", "nonexistent"])
        assert result.exit_code != 0