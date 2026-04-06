"""Tests for the ProjectDetector class."""

import os
import sys
from unittest import mock

import pytest

from django_deploy_toolkit.detector import ProjectDetector


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


class TestIsValidExecutable:
    """Tests for _is_valid_executable helper."""

    def test_valid_executable(self, tmp_path):
        exe = tmp_path / "python"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        assert ProjectDetector._is_valid_executable(str(exe)) is True

    def test_nonexistent_path(self):
        assert ProjectDetector._is_valid_executable("/no/such/file") is False

    def test_not_executable(self, tmp_path):
        f = tmp_path / "python"
        f.write_text("not executable")
        f.chmod(0o644)
        assert ProjectDetector._is_valid_executable(str(f)) is False

    def test_directory_not_file(self, tmp_path):
        d = tmp_path / "python"
        d.mkdir()
        assert ProjectDetector._is_valid_executable(str(d)) is False


class TestIsValidVirtualenv:
    """Tests for _is_valid_virtualenv helper."""

    def _make_venv(self, path):
        """Create a minimal valid virtualenv structure at path."""
        path.mkdir(exist_ok=True)
        (path / "pyvenv.cfg").write_text("home = /usr/bin\n")
        bin_dir = path / "bin"
        bin_dir.mkdir(exist_ok=True)
        python = bin_dir / "python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)

    def test_valid_virtualenv(self, tmp_path):
        venv = tmp_path / ".venv"
        self._make_venv(venv)
        result = ProjectDetector._is_valid_virtualenv(str(venv))
        assert result is not None
        assert result.endswith("python")

    def test_missing_pyvenv_cfg(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        python = bin_dir / "python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)
        # No pyvenv.cfg → invalid
        assert ProjectDetector._is_valid_virtualenv(str(venv)) is None

    def test_missing_python_binary(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        # No bin/python → invalid
        assert ProjectDetector._is_valid_virtualenv(str(venv)) is None

    def test_nonexecutable_python(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        python = bin_dir / "python"
        python.write_text("not executable")
        python.chmod(0o644)
        assert ProjectDetector._is_valid_virtualenv(str(venv)) is None


class TestDetectPythonPath:
    """Tests for Python path detection (multi-strategy)."""

    def _make_venv(self, path):
        """Create a minimal valid virtualenv structure at path."""
        path.mkdir(exist_ok=True)
        (path / "pyvenv.cfg").write_text("home = /usr/bin\n")
        bin_dir = path / "bin"
        bin_dir.mkdir(exist_ok=True)
        python = bin_dir / "python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)

    # --- Strategy 1: Interpreter state ---

    def test_strategy1_inside_virtualenv(self, tmp_path):
        """When running inside a virtualenv, sys.executable is returned."""
        detector = ProjectDetector(project_path=str(tmp_path))
        fake_exe = tmp_path / "fake_python"
        fake_exe.write_text("#!/bin/sh\n")
        fake_exe.chmod(0o755)
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/some/venv"
            mock_sys.base_prefix = "/usr"
            mock_sys.executable = str(fake_exe)
            result = detector.detect_python_path()
        assert result == os.path.realpath(str(fake_exe))

    def test_strategy1_not_in_virtualenv_skips(self, tmp_path):
        """When NOT inside a virtualenv, strategy 1 is skipped."""
        detector = ProjectDetector(project_path=str(tmp_path))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            mock_sys.executable = "/usr/bin/python3"
            with mock.patch.dict(os.environ, {}, clear=True):
                result = detector.detect_python_path()
        # Falls through to filesystem search, nothing in tmp_path → None
        assert result is None

    # --- Strategy 2: VIRTUAL_ENV env var ---

    def test_strategy2_virtual_env_var(self, tmp_path):
        """VIRTUAL_ENV env var points to a valid venv."""
        venv = tmp_path / "myvenv"
        self._make_venv(venv)

        detector = ProjectDetector(project_path=str(tmp_path))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(
                os.environ, {"VIRTUAL_ENV": str(venv)}, clear=False
            ):
                result = detector.detect_python_path()
        expected = os.path.realpath(str(venv / "bin" / "python"))
        assert result == expected

    def test_strategy2_invalid_virtual_env(self, tmp_path):
        """VIRTUAL_ENV set but points to broken path — falls through."""
        detector = ProjectDetector(project_path=str(tmp_path))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(
                os.environ, {"VIRTUAL_ENV": "/nonexistent/venv"}, clear=False
            ):
                result = detector.detect_python_path()
        assert result is None

    # --- Strategy 3: Upward search ---

    def test_strategy3_upward_search_project_level(self, tmp_path):
        """Venv directory at the project root level."""
        venv = tmp_path / ".venv"
        self._make_venv(venv)

        detector = ProjectDetector(project_path=str(tmp_path))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(os.environ, {}, clear=True):
                result = detector.detect_python_path()
        expected = os.path.realpath(str(venv / "bin" / "python"))
        assert result == expected

    def test_strategy3_upward_search_parent_level(self, tmp_path):
        """Venv directory one level above the project."""
        venv = tmp_path / "venv"
        self._make_venv(venv)
        sub = tmp_path / "project"
        sub.mkdir()

        detector = ProjectDetector(project_path=str(sub))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(os.environ, {}, clear=True):
                result = detector.detect_python_path()
        expected = os.path.realpath(str(venv / "bin" / "python"))
        assert result == expected

    def test_strategy3_prefers_closest_venv(self, tmp_path):
        """When multiple venvs exist, upward search returns closest."""
        # Parent venv
        parent_venv = tmp_path / ".venv"
        self._make_venv(parent_venv)
        # Project-level venv (closer)
        project = tmp_path / "project"
        project.mkdir()
        project_venv = project / ".venv"
        self._make_venv(project_venv)

        detector = ProjectDetector(project_path=str(project))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(os.environ, {}, clear=True):
                result = detector.detect_python_path()
        expected = os.path.realpath(str(project_venv / "bin" / "python"))
        assert result == expected

    # --- Strategy 4: Downward search ---

    def test_strategy4_downward_search(self, tmp_path):
        """Venv in a subdirectory found by downward search."""
        sub = tmp_path / "subdir"
        sub.mkdir()
        venv = sub / ".venv"
        self._make_venv(venv)

        # Use a project path that has NO venv at its own level or above
        project = tmp_path / "project"
        project.mkdir()
        # Place the venv inside the project subdirectory
        inner = project / "inner"
        inner.mkdir()
        inner_venv = inner / "venv"
        self._make_venv(inner_venv)

        detector = ProjectDetector(project_path=str(project))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(os.environ, {}, clear=True):
                result = detector.detect_python_path()
        expected = os.path.realpath(str(inner_venv / "bin" / "python"))
        assert result == expected

    # --- No venv found ---

    def test_no_venv_returns_none(self, tmp_path):
        """When no virtualenv exists anywhere, return None."""
        detector = ProjectDetector(project_path=str(tmp_path))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(os.environ, {}, clear=True):
                result = detector.detect_python_path()
        assert result is None

    # --- Broken venv skipped ---

    def test_broken_venv_skipped(self, tmp_path):
        """A directory named 'venv' without pyvenv.cfg is ignored."""
        broken = tmp_path / "venv"
        broken.mkdir()
        # No pyvenv.cfg, no bin/python

        detector = ProjectDetector(project_path=str(tmp_path))
        with mock.patch("django_deploy_toolkit.detector.sys") as mock_sys:
            mock_sys.prefix = "/usr"
            mock_sys.base_prefix = "/usr"
            with mock.patch.dict(os.environ, {}, clear=True):
                result = detector.detect_python_path()
        assert result is None


class TestDetectServerIp:
    """Tests for server IP detection via ipify API."""

    @mock.patch("django_deploy_toolkit.detector.urllib.request.urlopen")
    def test_returns_ip_from_ipify(self, mock_urlopen):
        """Successful ipify response returns the IP."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = b'{"ip": "203.0.113.42"}'
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        detector = ProjectDetector()
        ip = detector.detect_server_ip()
        assert ip == "203.0.113.42"

    @mock.patch(
        "django_deploy_toolkit.detector.urllib.request.urlopen",
        side_effect=OSError("no network"),
    )
    def test_fallback_to_underscore_on_error(self, mock_urlopen):
        """When ipify request fails, return '_'."""
        detector = ProjectDetector()
        ip = detector.detect_server_ip()
        assert ip == "_"

    @mock.patch("django_deploy_toolkit.detector.urllib.request.urlopen")
    def test_fallback_on_bad_json(self, mock_urlopen):
        """When ipify returns invalid JSON, return '_'."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        detector = ProjectDetector()
        ip = detector.detect_server_ip()
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
