"""Tests for the utils module."""

import os
import platform
import subprocess
from unittest import mock

import pytest

from django_deploy_toolkit.utils import (
    check_platform,
    check_systemd_available,
    check_nginx_installed,
    check_gunicorn_installed,
    check_sudo_available,
    is_root,
    run_system_command,
    sanitize_project_name,
    write_file_safe,
)


class TestCheckPlatform:
    """Tests for platform checking."""

    @mock.patch("django_deploy_toolkit.utils.platform.system", return_value="Linux")
    def test_linux_passes(self, mock_sys):
        check_platform()  # Should not raise

    @mock.patch("django_deploy_toolkit.utils.platform.system", return_value="Windows")
    def test_windows_fails(self, mock_sys):
        with pytest.raises(SystemExit, match="only supports Linux"):
            check_platform()

    @mock.patch("django_deploy_toolkit.utils.platform.system", return_value="Darwin")
    def test_macos_fails(self, mock_sys):
        with pytest.raises(SystemExit, match="only supports Linux"):
            check_platform()


class TestCheckSystemdAvailable:
    """Tests for systemd availability check."""

    @mock.patch("os.path.exists", return_value=True)
    def test_available(self, mock_exists):
        assert check_systemd_available() is True

    @mock.patch("os.path.exists", return_value=False)
    def test_not_available(self, mock_exists):
        assert check_systemd_available() is False


class TestCheckNginxInstalled:
    """Tests for nginx installation check."""

    @mock.patch("shutil.which", return_value="/usr/sbin/nginx")
    def test_installed(self, mock_which):
        assert check_nginx_installed() is True

    @mock.patch("shutil.which", return_value=None)
    def test_not_installed(self, mock_which):
        assert check_nginx_installed() is False


class TestCheckGunicornInstalled:
    """Tests for gunicorn installation check."""

    @mock.patch("subprocess.run")
    def test_installed(self, mock_run):
        mock_run.return_value = mock.MagicMock(returncode=0)
        assert check_gunicorn_installed("/usr/bin/python3") is True

    @mock.patch("subprocess.run")
    def test_not_installed(self, mock_run):
        mock_run.return_value = mock.MagicMock(returncode=1)
        assert check_gunicorn_installed("/usr/bin/python3") is False

    @mock.patch("subprocess.run", side_effect=FileNotFoundError)
    def test_python_not_found(self, mock_run):
        assert check_gunicorn_installed("/nonexistent/python") is False


class TestIsRoot:
    """Tests for root detection."""

    @mock.patch("os.geteuid", return_value=0)
    def test_is_root(self, mock_euid):
        assert is_root() is True

    @mock.patch("os.geteuid", return_value=1000)
    def test_not_root(self, mock_euid):
        assert is_root() is False


class TestRunSystemCommand:
    """Tests for system command execution."""

    def test_dry_run(self):
        result = run_system_command(["echo", "test"], dry_run=True)
        assert result is None

    @mock.patch("subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = mock.MagicMock(returncode=0)
        result = run_system_command(["echo", "test"])
        assert result is not None

    @mock.patch("subprocess.run", side_effect=subprocess.CalledProcessError(
        1, "cmd", stderr="error output"
    ))
    def test_failure_raises_runtime_error(self, mock_run):
        with pytest.raises(RuntimeError, match="Command failed"):
            run_system_command(["false"])

    @mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
        "cmd", 60
    ))
    def test_timeout_raises(self, mock_run):
        with pytest.raises(RuntimeError, match="timed out"):
            run_system_command(["sleep", "999"])

    @mock.patch("django_deploy_toolkit.utils.is_root", return_value=False)
    @mock.patch("django_deploy_toolkit.utils.check_sudo_available", return_value=True)
    @mock.patch("subprocess.run")
    def test_sudo_prepended(self, mock_run, mock_sudo, mock_root):
        mock_run.return_value = mock.MagicMock(returncode=0)
        run_system_command(["systemctl", "start", "test"], use_sudo=True)
        # Check that sudo was prepended
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "sudo"

    @mock.patch("django_deploy_toolkit.utils.is_root", return_value=False)
    @mock.patch("django_deploy_toolkit.utils.check_sudo_available", return_value=False)
    def test_no_sudo_raises(self, mock_sudo, mock_root):
        with pytest.raises(RuntimeError, match="sudo is not available"):
            run_system_command(["test"], use_sudo=True)

    def test_dry_run_with_description(self, capsys):
        run_system_command(["echo", "test"], dry_run=True, description="Test echo")
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out


class TestSanitizeProjectName:
    """Tests for project name sanitization."""

    def test_simple_name(self):
        assert sanitize_project_name("myproject") == "myproject"

    def test_uppercase(self):
        assert sanitize_project_name("MyProject") == "myproject"

    def test_spaces(self):
        assert sanitize_project_name("my project") == "my_project"

    def test_special_chars(self):
        assert sanitize_project_name("my@project!") == "my_project"

    def test_leading_number(self):
        result = sanitize_project_name("123abc")
        assert result[0].isalpha()

    def test_empty_string(self):
        assert sanitize_project_name("") == "django_project"

    def test_all_special_chars(self):
        assert sanitize_project_name("@#$%") == "django_project"

    def test_multiple_underscores_collapsed(self):
        assert sanitize_project_name("my___project") == "my_project"

    def test_hyphens_normalized(self):
        # Hyphens are treated as separators (like underscores)
        assert sanitize_project_name("my-project") == "my_project"


class TestWriteFileSafe:
    """Tests for safe file writing."""

    def test_write_new_file(self, tmp_path):
        path = str(tmp_path / "test.txt")
        write_file_safe(path, "hello world")
        with open(path) as f:
            assert f.read() == "hello world"

    def test_dry_run_does_not_write(self, tmp_path):
        path = str(tmp_path / "test.txt")
        write_file_safe(path, "hello", dry_run=True)
        assert not os.path.exists(path)

    def test_existing_file_no_overwrite(self, tmp_path):
        path = str(tmp_path / "test.txt")
        with open(path, "w") as f:
            f.write("existing")
        with pytest.raises(FileExistsError):
            write_file_safe(path, "new content", overwrite=False)

    def test_existing_file_with_overwrite(self, tmp_path):
        path = str(tmp_path / "test.txt")
        with open(path, "w") as f:
            f.write("existing")
        write_file_safe(path, "new content", overwrite=True)
        with open(path) as f:
            assert f.read() == "new content"

    def test_creates_parent_directories(self, tmp_path):
        path = str(tmp_path / "sub" / "dir" / "test.txt")
        write_file_safe(path, "hello")
        assert os.path.exists(path)

    @mock.patch("django_deploy_toolkit.utils.is_root", return_value=False)
    @mock.patch("django_deploy_toolkit.utils.check_sudo_available", return_value=False)
    def test_sudo_no_sudo_available(self, mock_sudo, mock_root, tmp_path):
        path = str(tmp_path / "test.txt")
        with pytest.raises(RuntimeError, match="sudo is not available"):
            write_file_safe(path, "hello", use_sudo=True)
