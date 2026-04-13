"""Tests for celery_installer module."""

import os
from unittest.mock import MagicMock, patch, call

import pytest

from django_deploy_toolkit.celery_installer import CeleryInstaller


@pytest.fixture
def base_config():
    """Return a minimal valid config for CeleryInstaller."""
    return {
        "project_name": "myproject",
        "user": "deploy",
        "group": "deploy",
        "project_path": "/home/deploy/myproject",
        "python_path": "/home/deploy/myproject/venv/bin/python",
        "celery_app_module": "myproject.celery",
        "concurrency": 1,
        "use_django_celery_beat": False,
    }


# ---------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------

class TestDryRun:
    def test_dry_run_worker_only(self, base_config):
        """Dry-run should succeed without any real side effects."""
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=True
        )
        results = installer.install()

        assert len(results) > 0
        for step, status, detail in results:
            assert status in ("success", "skipped"), (
                f"Unexpected status for {step}: {status} — {detail}"
            )

    def test_dry_run_with_beat(self, base_config):
        """Dry-run with beat should include beat steps."""
        installer = CeleryInstaller(
            base_config, install_beat=True, dry_run=True
        )
        results = installer.install()

        step_names = [r[0] for r in results]
        assert "Write Celery Beat service" in step_names
        assert "Enable Celery Beat" in step_names
        assert "Start Celery Beat" in step_names

    def test_dry_run_no_beat_steps(self, base_config):
        """Without beat, beat steps should not appear."""
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=True
        )
        results = installer.install()

        step_names = [r[0] for r in results]
        assert "Write Celery Beat service" not in step_names
        assert "Enable Celery Beat" not in step_names
        assert "Start Celery Beat" not in step_names


# ---------------------------------------------------------------
# Step ordering
# ---------------------------------------------------------------

class TestStepOrdering:
    def test_worker_only_steps(self, base_config):
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=True
        )
        results = installer.install()
        step_names = [r[0] for r in results]

        expected = [
            "Create log directory",
            "Write Celery worker service",
            "Reload systemd daemon",
            "Enable Celery worker",
            "Start Celery worker",
        ]
        assert step_names == expected

    def test_worker_and_beat_steps(self, base_config):
        installer = CeleryInstaller(
            base_config, install_beat=True, dry_run=True
        )
        results = installer.install()
        step_names = [r[0] for r in results]

        expected = [
            "Create log directory",
            "Write Celery worker service",
            "Write Celery Beat service",
            "Reload systemd daemon",
            "Enable Celery worker",
            "Start Celery worker",
            "Enable Celery Beat",
            "Start Celery Beat",
        ]
        assert step_names == expected


# ---------------------------------------------------------------
# File paths
# ---------------------------------------------------------------

class TestFilePaths:
    def test_worker_path(self, base_config):
        installer = CeleryInstaller(base_config, install_beat=False)
        assert installer.worker_path == (
            "/etc/systemd/system/myproject-celery.service"
        )

    def test_beat_path(self, base_config):
        installer = CeleryInstaller(base_config, install_beat=True)
        assert installer.beat_path == (
            "/etc/systemd/system/myproject-celerybeat.service"
        )


# ---------------------------------------------------------------
# Log directory creation
# ---------------------------------------------------------------

class TestCreateLogDir:
    def test_log_dir_exists(self, base_config):
        """Skip if /var/log/celery already exists."""
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=False
        )
        with patch("os.path.isdir", return_value=True):
            result = installer._create_log_dir()

        assert result.startswith("SKIP")

    def test_log_dir_created(self, base_config):
        """Create the directory and chown it."""
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=False
        )
        with patch("os.path.isdir", return_value=False), \
             patch(
                 "django_deploy_toolkit.celery_installer.run_system_command"
             ) as mock_cmd:
            result = installer._create_log_dir()

        assert "Created" in result
        assert mock_cmd.call_count == 2  # mkdir + chown


# ---------------------------------------------------------------
# Rollback on failure
# ---------------------------------------------------------------

class TestRollback:
    def test_rollback_called_on_failure(self, base_config):
        """If a step fails, rollback.rollback() is called."""
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=False
        )
        installer.rollback = MagicMock()

        # Make _create_log_dir raise
        with patch.object(
            installer, "_create_log_dir",
            side_effect=RuntimeError("disk full")
        ):
            results = installer.install()

        installer.rollback.rollback.assert_called_once()
        assert results[-1][1] == "failed"
        assert "disk full" in results[-1][2]

    def test_no_rollback_on_dry_run_failure(self, base_config):
        """In dry-run, rollback should NOT be called even on failure."""
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=True
        )
        installer.rollback = MagicMock()

        with patch.object(
            installer, "_create_log_dir",
            side_effect=RuntimeError("simulated")
        ):
            results = installer.install()

        installer.rollback.rollback.assert_not_called()
        assert results[-1][1] == "failed"


# ---------------------------------------------------------------
# Service writing (mocked filesystem)
# ---------------------------------------------------------------

class TestWriteServices:
    def test_write_worker_service(self, base_config, tmp_path):
        """Worker service file is written with correct content."""
        worker_path = str(tmp_path / "myproject-celery.service")
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=False
        )
        installer.worker_path = worker_path
        installer.use_sudo = False

        with patch("os.path.exists", return_value=False), \
             patch(
                 "django_deploy_toolkit.celery_installer.write_file_safe"
             ) as mock_write:
            result = installer._write_worker_service()

        mock_write.assert_called_once()
        written_content = mock_write.call_args[0][1]
        assert "Celery Worker for myproject" in written_content
        assert "--concurrency=1" in written_content

    def test_write_beat_service(self, base_config, tmp_path):
        """Beat service file is written with DatabaseScheduler if configured."""
        base_config["use_django_celery_beat"] = True
        beat_path = str(tmp_path / "myproject-celerybeat.service")
        installer = CeleryInstaller(
            base_config, install_beat=True, dry_run=False
        )
        installer.beat_path = beat_path
        installer.use_sudo = False

        with patch("os.path.exists", return_value=False), \
             patch(
                 "django_deploy_toolkit.celery_installer.write_file_safe"
             ) as mock_write:
            result = installer._write_beat_service()

        mock_write.assert_called_once()
        written_content = mock_write.call_args[0][1]
        assert "Celery Beat Scheduler for myproject" in written_content
        assert "DatabaseScheduler" in written_content

    def test_skip_existing_worker(self, base_config):
        """If file exists and user declines overwrite, skip."""
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=False
        )
        with patch("os.path.exists", return_value=True), \
             patch("click.confirm", return_value=False):
            result = installer._write_worker_service()

        assert result.startswith("SKIP")


# ---------------------------------------------------------------
# Systemd operations
# ---------------------------------------------------------------

class TestSystemdOps:
    def test_daemon_reload_dry_run(self, base_config):
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=True
        )
        result = installer._daemon_reload()
        assert result == "Dry run"

    def test_enable_worker(self, base_config):
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=True
        )
        result = installer._enable_worker()
        assert result == "Dry run"

    def test_start_worker(self, base_config):
        installer = CeleryInstaller(
            base_config, install_beat=False, dry_run=True
        )
        result = installer._start_worker()
        assert result == "Dry run"

    def test_enable_beat(self, base_config):
        installer = CeleryInstaller(
            base_config, install_beat=True, dry_run=True
        )
        result = installer._enable_beat()
        assert result == "Dry run"

    def test_start_beat(self, base_config):
        installer = CeleryInstaller(
            base_config, install_beat=True, dry_run=True
        )
        result = installer._start_beat()
        assert result == "Dry run"
