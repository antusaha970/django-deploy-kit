"""Tests for the ProjectDetector class."""

import os
import socket
import sys
from unittest import mock

import pytest

from django_deploy_kit.detector import ProjectDetector


class TestDetectProjectName:
    """Tests for project name detection."""

    def test_simple_directory_name(self, tmp_path):
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        detector = ProjectDetector(project_path=str(project_dir))
        assert detector.detect_project_name() == "myproject"

    def test_directory_with_spaces(self, tmp_path):
        project_dir = tmp_path / "my project name"
        project_dir.mkdir()
        detector = ProjectDetector(project_path=str(project_dir))
        name = detector.detect_project_name()
        assert " " not in name
        assert name == "my_project_name"

    def test_directory_with_special_chars(self, tmp_path):
        project_dir = tmp_path / "my@project!v2"
        project_dir.mkdir()
        detector = ProjectDetector(project_path=str(project_dir))
        name = detector.detect_project_name()
        assert name == "my_project_v2"

    def test_directory_starts_with_number(self, tmp_path):
        project_dir = tmp_path / "123project"
        project_dir.mkdir()
        detector = ProjectDetector(project_path=str(project_dir))
        name = detector.detect_project_name()
        assert name.startswith("project_")

    def test_uppercase_lowered(self, tmp_path):
        project_dir = tmp_path / "MyProject"
        project_dir.mkdir()
        detector = ProjectDetector(project_path=str(project_dir))
        assert detector.detect_project_name() == "myproject"


class TestDetectProjectPath:
    """Tests for project path detection."""

    def test_current_directory_with_manage_py(self, tmp_path):
        (tmp_path / "manage.py").write_text("# Django manage.py")
        detector = ProjectDetector(project_path=str(tmp_path))
        path = detector.detect_project_path()
        assert path == str(tmp_path)

    def test_subdirectory_with_manage_py(self, tmp_path):
        sub = tmp_path / "myapp"
        sub.mkdir()
        (sub / "manage.py").write_text("# Django manage.py")
        detector = ProjectDetector(project_path=str(tmp_path))
        path = detector.detect_project_path()
        assert path == str(sub)

    def test_parent_directory_with_manage_py(self, tmp_path):
        (tmp_path / "manage.py").write_text("# Django manage.py")
        sub = tmp_path / "subdir"
        sub.mkdir()
        detector = ProjectDetector(project_path=str(sub))
        path = detector.detect_project_path()
        assert path == str(tmp_path)

    def test_no_manage_py(self, tmp_path):
        detector = ProjectDetector(project_path=str(tmp_path))
        path = detector.detect_project_path()
        assert path is None


class TestDetectWsgiModule:
    """Tests for WSGI module detection."""

    def test_from_manage_py(self, tmp_path):
        manage_content = """#!/usr/bin/env python
import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myapp.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
"""
        (tmp_path / "manage.py").write_text(manage_content)

        detector = ProjectDetector(project_path=str(tmp_path))
        detector.detect_project_path()  # Sets up _manage_py_path
        wsgi = detector.detect_wsgi_module()
        assert wsgi == "myapp.wsgi:application"

    def test_from_wsgi_file_scan(self, tmp_path):
        (tmp_path / "manage.py").write_text("# no settings module here")
        wsgi_dir = tmp_path / "myapp"
        wsgi_dir.mkdir()
        (wsgi_dir / "wsgi.py").write_text("application = get_wsgi_application()")

        detector = ProjectDetector(project_path=str(tmp_path))
        detector.detect_project_path()
        wsgi = detector.detect_wsgi_module()
        assert wsgi == "myapp.wsgi:application"

    def test_no_wsgi_found(self, tmp_path):
        (tmp_path / "manage.py").write_text("# nothing useful")

        detector = ProjectDetector(project_path=str(tmp_path))
        detector.detect_project_path()
        wsgi = detector.detect_wsgi_module()
        assert wsgi is None


class TestDetectUser:
    """Tests for user detection."""

    def test_from_env(self):
        detector = ProjectDetector()
        with mock.patch.dict(os.environ, {"USER": "testuser"}):
            assert detector.detect_user() == "testuser"

    def test_from_logname(self):
        detector = ProjectDetector()
        with mock.patch.dict(os.environ, {"USER": "", "LOGNAME": "loguser"}, clear=False):
            user = detector.detect_user()
            # If USER is empty string, it's falsy, falls through to LOGNAME
            assert user is not None

    def test_fallback_to_pwd(self):
        detector = ProjectDetector()
        with mock.patch.dict(os.environ, {"USER": "", "LOGNAME": ""}, clear=False):
            user = detector.detect_user()
            assert user is not None  # Should fall back to pwd


class TestDetectGroup:
    """Tests for group detection."""

    def test_returns_group(self):
        detector = ProjectDetector()
        group = detector.detect_group()
        assert group is not None
        assert isinstance(group, str)


class TestDetectPythonPath:
    """Tests for Python path detection."""

    def test_returns_current_python(self):
        detector = ProjectDetector()
        python_path = detector.detect_python_path()
        assert python_path is not None
        assert os.path.isfile(python_path)


class TestDetectServerIp:
    """Tests for server IP detection."""

    def test_returns_string(self):
        detector = ProjectDetector()
        ip = detector.detect_server_ip()
        assert isinstance(ip, str)
        assert len(ip) > 0

    @mock.patch("django_deploy_kit.detector.socket.gethostbyname", side_effect=socket.error)
    @mock.patch("django_deploy_kit.detector.socket.gethostname", return_value="localhost")
    @mock.patch("django_deploy_kit.detector.socket.socket")
    def test_fallback_to_underscore(self, mock_socket_cls, mock_hostname, mock_gethostbyname):
        # Make /etc/hosts unreadable and UDP socket fail
        mock_sock = mock.MagicMock()
        mock_sock.getsockname.return_value = ("127.0.0.1", 0)
        mock_socket_cls.return_value = mock_sock

        detector = ProjectDetector()
        with mock.patch("builtins.open", side_effect=IOError):
            ip = detector.detect_server_ip()
        # All methods return loopback or fail, so should get "_"
        assert ip == "_"


class TestDetectWorkers:
    """Tests for worker count detection."""

    def test_returns_int(self):
        detector = ProjectDetector()
        workers = detector.detect_workers()
        assert isinstance(workers, int)
        assert 1 <= workers <= 9

    @mock.patch("psutil.cpu_count", return_value=None)
    def test_fallback_when_cpu_none(self, mock_cpu):
        detector = ProjectDetector()
        workers = detector.detect_workers()
        assert workers == 3

    @mock.patch("psutil.cpu_count", return_value=2)
    def test_formula(self, mock_cpu):
        detector = ProjectDetector()
        workers = detector.detect_workers()
        assert workers == 5  # (2*2) + 1

    @mock.patch("psutil.cpu_count", return_value=16)
    def test_capped_at_nine(self, mock_cpu):
        detector = ProjectDetector()
        workers = detector.detect_workers()
        assert workers == 9

    @mock.patch("psutil.cpu_count", side_effect=Exception("failed"))
    def test_fallback_on_exception(self, mock_cpu):
        detector = ProjectDetector()
        workers = detector.detect_workers()
        assert workers == 3


class TestDetectAll:
    """Tests for the detect_all method."""

    def test_returns_all_keys(self, tmp_path):
        manage_content = """#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myapp.settings')
"""
        (tmp_path / "manage.py").write_text(manage_content)

        detector = ProjectDetector(project_path=str(tmp_path))
        result = detector.detect_all()

        expected_keys = {
            "project_name", "project_path", "wsgi_module",
            "user", "group", "python_path", "server_ip",
            "workers", "static_root", "media_root",
        }
        assert set(result.keys()) == expected_keys

    def test_no_crash_on_missing_manage_py(self, tmp_path):
        """Detection should return Nones gracefully, not crash."""
        detector = ProjectDetector(project_path=str(tmp_path))
        result = detector.detect_all()
        assert result["project_path"] is None
        # Other keys should still be present
        assert "project_name" in result

    def test_none_on_detection_failure(self, tmp_path):
        """When detection fails, values should be None, not exceptions."""
        detector = ProjectDetector(project_path=str(tmp_path))
        result = detector.detect_all()
        # All values should be some type (None or actual value), no exception
        for key, value in result.items():
            assert isinstance(value, (str, int, type(None)))
