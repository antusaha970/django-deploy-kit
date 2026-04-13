"""Tests for celery_detector module."""

import os
import subprocess
from unittest.mock import MagicMock, mock_open, patch

import pytest

from django_deploy_toolkit.celery_detector import CeleryDetector


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal Django project structure."""
    manage_py = tmp_path / "manage.py"
    manage_py.write_text(
        "#!/usr/bin/env python\n"
        "import os, sys\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myapp.settings')\n"
    )
    # Create a package with celery.py
    pkg = tmp_path / "myapp"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "settings.py").write_text("")
    return tmp_path


@pytest.fixture
def detector(tmp_project):
    """Return a CeleryDetector pointed at the tmp project."""
    return CeleryDetector(
        project_path=str(tmp_project),
        python_path="/usr/bin/python3",
    )


# ---------------------------------------------------------------
# detect_celery_installed
# ---------------------------------------------------------------

class TestDetectCeleryInstalled:
    def test_celery_installed(self, detector):
        """Return True when 'import celery' succeeds."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            assert detector.detect_celery_installed() is True

    def test_celery_not_installed(self, detector):
        """Return False when 'import celery' fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert detector.detect_celery_installed() is False

    def test_subprocess_error(self, detector):
        """Return False on subprocess exceptions."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.SubprocessError("boom"),
        ):
            assert detector.detect_celery_installed() is False

    def test_file_not_found(self, detector):
        """Return False when python binary doesn't exist."""
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("no python"),
        ):
            assert detector.detect_celery_installed() is False


# ---------------------------------------------------------------
# detect_celery_app_module
# ---------------------------------------------------------------

class TestDetectCeleryAppModule:
    def test_finds_celery_py(self, tmp_project):
        """Find celery.py in a top-level package."""
        pkg = tmp_project / "myapp"
        (pkg / "celery.py").write_text("from celery import Celery\n")

        det = CeleryDetector(str(tmp_project), "/usr/bin/python3")
        result = det.detect_celery_app_module()
        assert result == "myapp.celery"

    def test_no_celery_py(self, tmp_path):
        """Return None when there is no celery.py."""
        (tmp_path / "manage.py").write_text("")
        pkg = tmp_path / "myapp"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        # No celery.py

        det = CeleryDetector(str(tmp_path), "/usr/bin/python3")
        result = det.detect_celery_app_module()
        assert result is None

    def test_finds_celery_instantiation(self, tmp_path):
        """Fallback: find Celery() in a .py file."""
        (tmp_path / "manage.py").write_text("")
        pkg = tmp_path / "core"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "tasks_setup.py").write_text(
            "from celery import Celery\n"
            "app = Celery('core')\n"
        )

        det = CeleryDetector(str(tmp_path), "/usr/bin/python3")
        result = det.detect_celery_app_module()
        assert result == "core.tasks_setup"

    def test_skips_venv_directory(self, tmp_path):
        """Should not scan inside venv directories."""
        (tmp_path / "manage.py").write_text("")
        venv = tmp_path / "venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "celery.py").write_text("from celery import Celery\n")

        det = CeleryDetector(str(tmp_path), "/usr/bin/python3")
        result = det.detect_celery_app_module()
        assert result is None

    def test_skips_dotdirs(self, tmp_path):
        """Should not scan hidden directories."""
        (tmp_path / "manage.py").write_text("")
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "__init__.py").write_text("")
        (hidden / "celery.py").write_text("from celery import Celery\n")

        det = CeleryDetector(str(tmp_path), "/usr/bin/python3")
        result = det.detect_celery_app_module()
        assert result is None


# ---------------------------------------------------------------
# detect_celery_beat
# ---------------------------------------------------------------

class TestDetectCeleryBeat:
    def test_beat_schedule_in_settings(self, detector):
        """Detect CELERY_BEAT_SCHEDULE in diffsettings output."""
        fake_output = (
            "DEBUG = True\n"
            "CELERY_BEAT_SCHEDULE = {'task': ...}\n"
        )
        with patch.object(
            detector, "_get_diffsettings", return_value=fake_output
        ):
            assert detector.detect_celery_beat() is True

    def test_django_celery_beat_in_apps(self, detector):
        """Detect django_celery_beat in INSTALLED_APPS."""
        fake_output = (
            "INSTALLED_APPS = ['django.contrib.admin', "
            "'django_celery_beat']\n"
        )
        with patch.object(
            detector, "_get_diffsettings", return_value=fake_output
        ):
            assert detector.detect_celery_beat() is True

    def test_no_beat(self, detector):
        """Return False when no beat config found."""
        fake_output = "DEBUG = True\nSECRET_KEY = 'abc'\n"
        with patch.object(
            detector, "_get_diffsettings", return_value=fake_output
        ):
            with patch.object(
                detector, "_is_package_importable", return_value=False
            ):
                assert detector.detect_celery_beat() is False

    def test_beat_importable_fallback(self, detector):
        """Detect beat via importability when diffsettings fails."""
        with patch.object(
            detector, "_get_diffsettings", return_value=None
        ):
            with patch.object(
                detector, "_is_package_importable", return_value=True
            ):
                assert detector.detect_celery_beat() is True


# ---------------------------------------------------------------
# detect_django_celery_beat
# ---------------------------------------------------------------

class TestDetectDjangoCeleryBeat:
    def test_found_in_settings(self, detector):
        fake_output = "INSTALLED_APPS = ['django_celery_beat']\n"
        with patch.object(
            detector, "_get_diffsettings", return_value=fake_output
        ):
            assert detector.detect_django_celery_beat() is True

    def test_importable(self, detector):
        with patch.object(
            detector, "_get_diffsettings", return_value=""
        ):
            with patch.object(
                detector, "_is_package_importable", return_value=True
            ):
                assert detector.detect_django_celery_beat() is True

    def test_not_found(self, detector):
        with patch.object(
            detector, "_get_diffsettings", return_value=""
        ):
            with patch.object(
                detector, "_is_package_importable", return_value=False
            ):
                assert detector.detect_django_celery_beat() is False


# ---------------------------------------------------------------
# detect_broker_url
# ---------------------------------------------------------------

class TestDetectBrokerUrl:
    def test_celery_broker_url(self, detector):
        fake_output = (
            "CELERY_BROKER_URL = 'redis://localhost:6379/0'\n"
        )
        with patch.object(
            detector, "_get_diffsettings", return_value=fake_output
        ):
            result = detector.detect_broker_url()
            assert result == "redis://localhost:6379/0"

    def test_legacy_broker_url(self, detector):
        fake_output = "BROKER_URL = 'amqp://guest:guest@localhost//'\n"
        with patch.object(
            detector, "_get_diffsettings", return_value=fake_output
        ):
            result = detector.detect_broker_url()
            assert result == "amqp://guest:guest@localhost//"

    def test_no_broker(self, detector):
        fake_output = "DEBUG = True\n"
        with patch.object(
            detector, "_get_diffsettings", return_value=fake_output
        ):
            result = detector.detect_broker_url()
            assert result is None

    def test_diffsettings_fails(self, detector):
        with patch.object(
            detector, "_get_diffsettings", return_value=None
        ):
            assert detector.detect_broker_url() is None


# ---------------------------------------------------------------
# _is_redis_broker (static)
# ---------------------------------------------------------------

class TestIsRedisBroker:
    def test_redis_url(self):
        assert CeleryDetector._is_redis_broker("redis://localhost:6379/0")

    def test_rediss_url(self):
        assert CeleryDetector._is_redis_broker("rediss://localhost:6379/0")

    def test_amqp_url(self):
        assert not CeleryDetector._is_redis_broker("amqp://guest@localhost//")

    def test_none(self):
        assert not CeleryDetector._is_redis_broker(None)

    def test_empty(self):
        assert not CeleryDetector._is_redis_broker("")


# ---------------------------------------------------------------
# detect_redis_installed
# ---------------------------------------------------------------

class TestDetectRedisInstalled:
    def test_redis_server_found(self, detector):
        with patch("shutil.which", side_effect=lambda x: "/usr/bin/redis-server" if x == "redis-server" else None):
            assert detector.detect_redis_installed() is True

    def test_redis_cli_found(self, detector):
        with patch("shutil.which", side_effect=lambda x: "/usr/bin/redis-cli" if x == "redis-cli" else None):
            assert detector.detect_redis_installed() is True

    def test_no_redis(self, detector):
        with patch("shutil.which", return_value=None):
            assert detector.detect_redis_installed() is False


# ---------------------------------------------------------------
# detect_all
# ---------------------------------------------------------------

class TestDetectAll:
    def test_returns_all_keys(self, detector):
        """detect_all should return a dict with all expected keys."""
        with patch.object(detector, "detect_celery_installed", return_value=True), \
             patch.object(detector, "detect_celery_app_module", return_value="myapp.celery"), \
             patch.object(detector, "detect_celery_beat", return_value=False), \
             patch.object(detector, "detect_broker_url", return_value=None), \
             patch.object(detector, "detect_redis_installed", return_value=False), \
             patch.object(detector, "detect_django_celery_beat", return_value=False):
            result = detector.detect_all()

        expected_keys = {
            "celery_installed",
            "celery_app_module",
            "celery_beat_enabled",
            "broker_url",
            "broker_is_redis",
            "redis_installed",
            "django_celery_beat_installed",
        }
        assert set(result.keys()) == expected_keys
        assert result["celery_installed"] is True
        assert result["celery_app_module"] == "myapp.celery"
        assert result["celery_beat_enabled"] is False
        assert result["broker_is_redis"] is False


# ---------------------------------------------------------------
# _get_diffsettings (caching)
# ---------------------------------------------------------------

class TestGetDiffsettings:
    def test_caches_result(self, detector):
        """Should only call subprocess once, then return cached."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "SOME_SETTING = 'value'\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            first = detector._get_diffsettings()
            second = detector._get_diffsettings()

        assert first == second
        assert mock_run.call_count == 1

    def test_returns_none_on_failure(self, detector):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert detector._get_diffsettings() is None

    def test_returns_none_no_manage_py(self, tmp_path):
        """Should return None if manage.py doesn't exist."""
        det = CeleryDetector(str(tmp_path), "/usr/bin/python3")
        assert det._get_diffsettings() is None


# ---------------------------------------------------------------
# _is_package_importable
# ---------------------------------------------------------------

class TestIsPackageImportable:
    def test_importable(self, detector):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            assert detector._is_package_importable("celery") is True

    def test_not_importable(self, detector):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert detector._is_package_importable("nonexistent") is False

    def test_subprocess_error(self, detector):
        with patch(
            "subprocess.run",
            side_effect=subprocess.SubprocessError("boom"),
        ):
            assert detector._is_package_importable("celery") is False
