"""Tests for the RollbackManager class."""

import os
import shutil
from unittest import mock

import pytest

from django_deploy_toolkit.rollback import RollbackManager


class TestRollbackRegistration:
    """Tests for registering undo actions."""

    def test_register_file_creation(self):
        rm = RollbackManager()
        rm.register_file_creation("/tmp/test.txt")
        assert len(rm._undo_actions) == 1
        assert rm._undo_actions[0] == ("delete_file", "/tmp/test.txt")

    def test_register_symlink_creation(self):
        rm = RollbackManager()
        rm.register_symlink_creation("/tmp/test.link")
        assert len(rm._undo_actions) == 1
        assert rm._undo_actions[0] == ("delete_symlink", "/tmp/test.link")

    def test_register_service_start(self):
        rm = RollbackManager()
        rm.register_service_start("test.socket")
        assert len(rm._undo_actions) == 1
        assert rm._undo_actions[0] == ("stop_service", "test.socket")

    def test_register_service_enable(self):
        rm = RollbackManager()
        rm.register_service_enable("test.service")
        assert len(rm._undo_actions) == 1

    def test_register_daemon_reload(self):
        rm = RollbackManager()
        rm.register_daemon_reload()
        assert len(rm._undo_actions) == 1

    def test_register_nginx_reload(self):
        rm = RollbackManager()
        rm.register_nginx_reload()
        assert len(rm._undo_actions) == 1


class TestBackupFile:
    """Tests for file backup."""

    def test_backup_existing_file(self, tmp_path):
        test_file = tmp_path / "test.conf"
        test_file.write_text("original content")

        rm = RollbackManager()
        backup_path = rm.backup_file(str(test_file))

        assert backup_path is not None
        assert os.path.exists(backup_path)
        with open(backup_path) as f:
            assert f.read() == "original content"

    def test_backup_nonexistent_file(self):
        rm = RollbackManager()
        result = rm.backup_file("/nonexistent/file.txt")
        assert result is None


class TestRollbackExecution:
    """Tests for rollback execution."""

    def test_rollback_no_actions(self):
        """Rollback with no actions should not crash."""
        rm = RollbackManager()
        rm.rollback()  # Should not raise

    def test_rollback_deletes_created_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("created during install")

        rm = RollbackManager()
        rm.register_file_creation(str(test_file))
        rm.rollback()

        assert not os.path.exists(str(test_file))

    def test_rollback_removes_created_symlink(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("target")
        link = tmp_path / "link.txt"
        os.symlink(str(target), str(link))

        rm = RollbackManager()
        rm.register_symlink_creation(str(link))
        rm.rollback()

        assert not os.path.islink(str(link))
        assert os.path.exists(str(target))  # Target should still exist

    def test_rollback_restores_backup(self, tmp_path):
        test_file = tmp_path / "nginx_default"
        test_file.write_text("original nginx config")

        rm = RollbackManager()
        rm.backup_file(str(test_file))

        # Delete the original
        os.remove(str(test_file))
        assert not os.path.exists(str(test_file))

        # Rollback should restore it
        rm.rollback()
        assert os.path.exists(str(test_file))
        with open(str(test_file)) as f:
            assert f.read() == "original nginx config"

    @mock.patch("django_deploy_toolkit.rollback.run_system_command")
    @mock.patch("django_deploy_toolkit.rollback.is_root", return_value=True)
    def test_rollback_stops_services(self, mock_root, mock_cmd):
        rm = RollbackManager()
        rm.register_service_start("test.socket")
        rm.rollback()

        # Should have called systemctl stop
        mock_cmd.assert_called()
        stop_calls = [c for c in mock_cmd.call_args_list
                      if "stop" in str(c)]
        assert len(stop_calls) > 0

    @mock.patch("django_deploy_toolkit.rollback.run_system_command")
    @mock.patch("django_deploy_toolkit.rollback.is_root", return_value=True)
    def test_rollback_disables_services(self, mock_root, mock_cmd):
        rm = RollbackManager()
        rm.register_service_enable("test.service")
        rm.rollback()

        mock_cmd.assert_called()
        disable_calls = [c for c in mock_cmd.call_args_list
                         if "disable" in str(c)]
        assert len(disable_calls) > 0

    @mock.patch("django_deploy_toolkit.rollback.run_system_command")
    @mock.patch("django_deploy_toolkit.rollback.is_root", return_value=True)
    def test_rollback_daemon_reload(self, mock_root, mock_cmd):
        rm = RollbackManager()
        rm.register_daemon_reload()
        rm.rollback()

        mock_cmd.assert_called()
        reload_calls = [c for c in mock_cmd.call_args_list
                        if "daemon-reload" in str(c)]
        assert len(reload_calls) > 0

    @mock.patch("django_deploy_toolkit.rollback.run_system_command")
    @mock.patch("django_deploy_toolkit.rollback.is_root", return_value=True)
    def test_rollback_nginx_reload(self, mock_root, mock_cmd):
        rm = RollbackManager()
        rm.register_nginx_reload()
        rm.rollback()

        mock_cmd.assert_called()

    def test_rollback_continues_on_failure(self, tmp_path):
        """A failing rollback step should not prevent others from running."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("should be deleted")

        rm = RollbackManager()
        # Register a bad action first
        rm.register_file_creation("/nonexistent/path/will/fail")
        # Register a good action second
        rm.register_file_creation(str(test_file))

        rm.rollback()

        # The good action should still have run (delete test_file)
        assert not os.path.exists(str(test_file))

    def test_dry_run_rollback(self, tmp_path):
        """Dry run rollback should not delete files."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("should NOT be deleted")

        rm = RollbackManager(dry_run=True)
        rm.register_file_creation(str(test_file))
        rm.rollback()

        # File should still exist in dry-run
        assert os.path.exists(str(test_file))

    def test_rollback_reverse_order(self):
        """Actions should be executed in reverse order."""
        rm = RollbackManager()
        order = []

        rm.register_file_creation("first")
        rm.register_file_creation("second")
        rm.register_file_creation("third")

        with mock.patch.object(rm, "_rollback_delete_file") as mock_del:
            rm.rollback()
            # Should be called in reverse: third, second, first
            calls = [c[0][0] for c in mock_del.call_args_list]
            assert calls == ["third", "second", "first"]


class TestCleanup:
    """Tests for backup directory cleanup."""

    def test_cleanup_on_rollback(self, tmp_path):
        rm = RollbackManager()
        backup_dir = rm._backup_dir
        assert os.path.isdir(backup_dir)

        # Need at least one action for rollback to proceed to cleanup
        test_file = tmp_path / "dummy.txt"
        test_file.write_text("dummy")
        rm.register_file_creation(str(test_file))
        rm.rollback()

        # Backup dir should be cleaned up
        assert not os.path.isdir(backup_dir)
