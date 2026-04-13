"""Tests for Celery worker and Celery Beat generators."""

import pytest

from django_deploy_toolkit.generators.celery_worker import (
    CeleryWorkerGenerator,
)
from django_deploy_toolkit.generators.celery_beat import (
    CeleryBeatGenerator,
)


@pytest.fixture
def base_config():
    """Return a minimal valid config dict for Celery generators."""
    return {
        "project_name": "myproject",
        "user": "deploy",
        "group": "deploy",
        "project_path": "/home/deploy/myproject",
        "python_path": "/home/deploy/myproject/venv/bin/python",
        "celery_app_module": "myproject.celery",
    }


# ---------------------------------------------------------------
# CeleryWorkerGenerator
# ---------------------------------------------------------------

class TestCeleryWorkerGenerator:
    def test_generate_default_concurrency(self, base_config):
        """Default concurrency should be 1."""
        gen = CeleryWorkerGenerator(base_config)
        content = gen.generate()

        assert "--concurrency=1" in content
        assert "Celery Worker for myproject" in content
        assert "User=deploy" in content
        assert "Group=deploy" in content
        assert "WorkingDirectory=/home/deploy/myproject" in content
        assert "-A myproject.celery worker" in content
        assert "Type=simple" in content
        assert "WantedBy=multi-user.target" in content

    def test_generate_custom_concurrency(self, base_config):
        """Concurrency should be configurable."""
        base_config["concurrency"] = 4
        gen = CeleryWorkerGenerator(base_config)
        content = gen.generate()

        assert "--concurrency=4" in content

    def test_generate_log_path(self, base_config):
        gen = CeleryWorkerGenerator(base_config)
        content = gen.generate()

        assert "--logfile=/var/log/celery/myproject-worker.log" in content

    def test_generate_runtime_directory(self, base_config):
        gen = CeleryWorkerGenerator(base_config)
        content = gen.generate()

        assert "RuntimeDirectory=celery" in content

    def test_generate_restart_always(self, base_config):
        gen = CeleryWorkerGenerator(base_config)
        content = gen.generate()

        assert "Restart=always" in content

    def test_write(self, base_config, tmp_path):
        """write() should produce a valid file on disk."""
        gen = CeleryWorkerGenerator(base_config)
        path = tmp_path / "celery.service"
        gen.write(str(path))

        assert path.exists()
        content = path.read_text()
        assert "Celery Worker for myproject" in content

    def test_write_permission_error(self, base_config):
        """write() should raise PermissionError with helpful message."""
        gen = CeleryWorkerGenerator(base_config)
        with pytest.raises(PermissionError, match="sudo"):
            gen.write("/etc/systemd/system/test.service")


# ---------------------------------------------------------------
# CeleryBeatGenerator
# ---------------------------------------------------------------

class TestCeleryBeatGenerator:
    def test_generate_without_django_celery_beat(self, base_config):
        """Without django_celery_beat, no --scheduler flag."""
        base_config["use_django_celery_beat"] = False
        gen = CeleryBeatGenerator(base_config)
        content = gen.generate()

        assert "Celery Beat Scheduler for myproject" in content
        assert "-A myproject.celery beat" in content
        assert "--scheduler" not in content
        assert "Type=simple" in content
        assert "Restart=always" in content

    def test_generate_with_django_celery_beat(self, base_config):
        """With django_celery_beat, --scheduler flag included."""
        base_config["use_django_celery_beat"] = True
        gen = CeleryBeatGenerator(base_config)
        content = gen.generate()

        assert (
            "--scheduler django_celery_beat.schedulers:DatabaseScheduler"
            in content
        )

    def test_generate_log_path(self, base_config):
        gen = CeleryBeatGenerator(base_config)
        content = gen.generate()

        assert "--logfile=/var/log/celery/myproject-beat.log" in content

    def test_generate_runtime_directory(self, base_config):
        gen = CeleryBeatGenerator(base_config)
        content = gen.generate()

        assert "RuntimeDirectory=celery" in content

    def test_generate_user_group(self, base_config):
        gen = CeleryBeatGenerator(base_config)
        content = gen.generate()

        assert "User=deploy" in content
        assert "Group=deploy" in content

    def test_write(self, base_config, tmp_path):
        gen = CeleryBeatGenerator(base_config)
        path = tmp_path / "celerybeat.service"
        gen.write(str(path))

        assert path.exists()
        content = path.read_text()
        assert "Celery Beat Scheduler for myproject" in content

    def test_write_permission_error(self, base_config):
        gen = CeleryBeatGenerator(base_config)
        with pytest.raises(PermissionError, match="sudo"):
            gen.write("/etc/systemd/system/test-beat.service")

    def test_default_use_django_celery_beat_is_false(self, base_config):
        """When use_django_celery_beat key is absent, default to False."""
        # Don't set use_django_celery_beat at all
        gen = CeleryBeatGenerator(base_config)
        content = gen.generate()
        assert "--scheduler" not in content


# ---------------------------------------------------------------
# Different config values
# ---------------------------------------------------------------

class TestVariousConfigs:
    def test_worker_with_different_project(self):
        config = {
            "project_name": "shopapi",
            "user": "ubuntu",
            "group": "www-data",
            "project_path": "/opt/shopapi",
            "python_path": "/opt/shopapi/.venv/bin/python",
            "celery_app_module": "shopapi.celery",
            "concurrency": 8,
        }
        gen = CeleryWorkerGenerator(config)
        content = gen.generate()

        assert "Celery Worker for shopapi" in content
        assert "User=ubuntu" in content
        assert "Group=www-data" in content
        assert "WorkingDirectory=/opt/shopapi" in content
        assert "-A shopapi.celery worker" in content
        assert "--concurrency=8" in content
        assert "/opt/shopapi/.venv/bin/python" in content

    def test_beat_with_different_project(self):
        config = {
            "project_name": "shopapi",
            "user": "ubuntu",
            "group": "www-data",
            "project_path": "/opt/shopapi",
            "python_path": "/opt/shopapi/.venv/bin/python",
            "celery_app_module": "shopapi.celery",
            "use_django_celery_beat": True,
        }
        gen = CeleryBeatGenerator(config)
        content = gen.generate()

        assert "Celery Beat Scheduler for shopapi" in content
        assert "User=ubuntu" in content
        assert "-A shopapi.celery beat" in content
        assert "--scheduler django_celery_beat.schedulers:DatabaseScheduler" in content
