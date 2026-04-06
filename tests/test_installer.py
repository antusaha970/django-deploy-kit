"""Tests for the Installer class."""

import os
from unittest import mock

import pytest

from django_deploy_toolkit.installer import Installer


@pytest.fixture
def config():
    """A test configuration dict."""
    return {
        "project_name": "testproject",
        "project_path": "/home/deploy/testproject",
        "wsgi_module": "testproject.wsgi:application",
        "user": "deploy",
        "group": "deploy",
        "python_path": "/home/deploy/testproject/venv/bin/python",
        "server_ip": "192.168.1.1",
        "workers": 3,
        "static_root": "/home/deploy/testproject/staticfiles",
        "media_root": None,
    }


class TestDryRun:
    """Tests for dry-run mode."""

    @mock.patch("django_deploy_toolkit.installer.is_root", return_value=True)
    def test_dry_run_never_calls_subprocess(self, mock_root, config):
        """In dry-run mode, subprocess.run should never be called."""
        with mock.patch("django_deploy_toolkit.installer.run_system_command") as mock_cmd:
            with mock.patch("django_deploy_toolkit.installer.write_file_safe") as mock_write:
                # Also mock os.path.exists to say files don't exist
                with mock.patch("os.path.exists", return_value=False):
                    with mock.patch("os.path.islink", return_value=False):
                        installer = Installer(config, dry_run=True)
                        results = installer.install()

                # In dry-run mode, write_file_safe should not be called
                mock_write.assert_not_called()
                # run_system_command is called but with dry_run=True
                for call in mock_cmd.call_args_list:
                    assert call.kwargs.get("dry_run") is True or call[1].get("dry_run") is True

    @mock.patch("django_deploy_toolkit.installer.is_root", return_value=True)
    def test_dry_run_returns_results(self, mock_root, config):
        """Dry-run should return results for all steps."""
        with mock.patch("django_deploy_toolkit.installer.run_system_command"):
            with mock.patch("os.path.exists", return_value=False):
                with mock.patch("os.path.islink", return_value=False):
                    installer = Installer(config, dry_run=True)
                    results = installer.install()

        assert len(results) > 0
        # No step should have failed
        failed = [r for r in results if r[1] == "failed"]
        assert len(failed) == 0


class TestRollbackOnFailure:
    """Tests for rollback triggering on step failure."""

    @mock.patch("django_deploy_toolkit.installer.is_root", return_value=True)
    def test_rollback_triggered_on_failure(self, mock_root, config):
        """When a step fails, rollback should be called."""
        with mock.patch("django_deploy_toolkit.installer.write_file_safe") as mock_write:
            with mock.patch("os.path.exists", return_value=False):
                with mock.patch("os.path.islink", return_value=False):
                    # Make the first write fail
                    mock_write.side_effect = PermissionError("Test error")

                    installer = Installer(config, dry_run=False)
                    with mock.patch.object(
                        installer.rollback, "rollback"
                    ) as mock_rollback:
                        results = installer.install()

                    # Rollback should have been called
                    mock_rollback.assert_called_once()

                    # Should have a failed result
                    failed = [r for r in results if r[1] == "failed"]
                    assert len(failed) > 0


class TestDefaultNginxRemoval:
    """Tests for default Nginx config removal."""

    @mock.patch("django_deploy_toolkit.installer.is_root", return_value=True)
    @mock.patch("time.sleep")  # Don't actually sleep in tests
    def test_warns_and_pauses(self, mock_sleep, mock_root, config):
        """The removal step should warn and pause for 3 seconds."""
        with mock.patch("django_deploy_toolkit.installer.write_file_safe"):
            with mock.patch("django_deploy_toolkit.installer.run_system_command"):
                with mock.patch("os.path.exists") as mock_exists:
                    with mock.patch("os.path.islink", return_value=False):
                        with mock.patch("os.unlink"):
                            with mock.patch("os.symlink"):
                                with mock.patch("click.confirm", return_value=True):
                                    # Make default nginx exist
                                    def exists_side_effect(path):
                                        if "default" in path:
                                            return True
                                        return False

                                    mock_exists.side_effect = exists_side_effect

                                    installer = Installer(config, dry_run=False)
                                    # Mock rollback methods
                                    installer.rollback.backup_file = mock.MagicMock(return_value="/tmp/backup")
                                    installer.install()

                    # time.sleep should have been called with 3
                    mock_sleep.assert_called_with(3)

    @mock.patch("django_deploy_toolkit.installer.is_root", return_value=True)
    def test_dry_run_does_not_remove(self, mock_root, config):
        """In dry-run mode, should not actually remove files."""
        with mock.patch("django_deploy_toolkit.installer.run_system_command"):
            with mock.patch("os.path.exists") as mock_exists:
                with mock.patch("os.path.islink", return_value=False):
                    mock_exists.return_value = True

                    installer = Installer(config, dry_run=True)
                    results = installer.install()

        # Should have completed without errors
        failed = [r for r in results if r[1] == "failed"]
        assert len(failed) == 0

    @mock.patch("django_deploy_toolkit.installer.is_root", return_value=True)
    def test_skip_when_default_not_exists(self, mock_root, config):
        """Should skip silently when default nginx config doesn't exist."""
        with mock.patch("django_deploy_toolkit.installer.write_file_safe"):
            with mock.patch("django_deploy_toolkit.installer.run_system_command"):
                with mock.patch("os.path.exists", return_value=False):
                    with mock.patch("os.path.islink", return_value=False):
                        with mock.patch("os.symlink"):
                            installer = Installer(config, dry_run=False)
                            results = installer.install()

        # The "Remove default Nginx config" step should be skipped
        remove_step = [r for r in results if "default" in r[0].lower()]
        if remove_step:
            assert remove_step[0][1] == "skipped"


class TestBackupAndRestore:
    """Tests for backup/restore of default Nginx config during rollback."""

    @mock.patch("django_deploy_toolkit.installer.is_root", return_value=True)
    @mock.patch("time.sleep")
    def test_backup_created_before_removal(self, mock_sleep, mock_root, config):
        """A backup should be created before removing the default config."""
        with mock.patch("django_deploy_toolkit.installer.write_file_safe"):
            with mock.patch("django_deploy_toolkit.installer.run_system_command"):
                with mock.patch("os.path.exists") as mock_exists:
                    with mock.patch("os.path.islink", return_value=False):
                        with mock.patch("os.unlink"):
                            with mock.patch("os.symlink"):
                                with mock.patch("click.confirm", return_value=True):
                                    def exists_side_effect(path):
                                        if "default" in path:
                                            return True
                                        return False

                                    mock_exists.side_effect = exists_side_effect

                                    installer = Installer(config, dry_run=False)
                                    mock_backup = mock.MagicMock(return_value="/tmp/backup")
                                    installer.rollback.backup_file = mock_backup
                                    installer.install()

                                    # backup_file should be called for default configs
                                    assert mock_backup.call_count >= 1


class TestInstallPaths:
    """Tests for correct file paths."""

    def test_socket_path(self, config):
        installer = Installer(config)
        assert installer.socket_path == "/etc/systemd/system/testproject.socket"

    def test_service_path(self, config):
        installer = Installer(config)
        assert installer.service_path == "/etc/systemd/system/testproject.service"

    def test_nginx_available_path(self, config):
        installer = Installer(config)
        assert installer.nginx_available == "/etc/nginx/sites-available/testproject"

    def test_nginx_enabled_path(self, config):
        installer = Installer(config)
        assert installer.nginx_enabled == "/etc/nginx/sites-enabled/testproject"
