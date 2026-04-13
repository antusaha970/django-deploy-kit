"""Celery and Celery Beat detection logic for django-deploy-toolkit."""

import logging
import os
import re
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


class CeleryDetector:
    """Detects Celery and Celery Beat configuration in a Django project.

    Designed to be run after ProjectDetector has already resolved the
    project path and Python interpreter.  All detection methods return
    safe defaults (False / None) on failure — never raises to the caller.
    """

    def __init__(self, project_path, python_path=None):
        """
        Args:
            project_path: Absolute path to the Django project root
                (directory containing manage.py).
            python_path: Absolute path to the Python interpreter
                inside the project's virtualenv.  Falls back to
                sys.executable when not given.
        """
        self._project_path = os.path.abspath(project_path)
        self._python_path = python_path or sys.executable
        self._manage_py = os.path.join(self._project_path, "manage.py")
        # Cache for diffsettings output (expensive subprocess call)
        self._diffsettings_cache = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_all(self):
        """Run every detection method and return a summary dict.

        Returns:
            dict with keys:
                celery_installed    (bool)
                celery_app_module   (str | None)  e.g. "myproject.celery"
                celery_beat_enabled (bool)
                broker_url          (str | None)
                broker_is_redis     (bool)
                redis_installed     (bool)
        """
        result = {}

        result["celery_installed"] = self.detect_celery_installed()
        result["celery_app_module"] = self.detect_celery_app_module()
        result["celery_beat_enabled"] = self.detect_celery_beat()
        result["broker_url"] = self.detect_broker_url()
        result["broker_is_redis"] = self._is_redis_broker(
            result["broker_url"]
        )
        result["redis_installed"] = self.detect_redis_installed()
        result["django_celery_beat_installed"] = (
            self.detect_django_celery_beat()
        )

        return result

    # ------------------------------------------------------------------
    # Individual detectors
    # ------------------------------------------------------------------

    def detect_celery_installed(self):
        """Check whether the ``celery`` package is importable.

        Returns:
            bool
        """
        try:
            proc = subprocess.run(
                [self._python_path, "-c", "import celery"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            installed = proc.returncode == 0
            logger.debug(
                "detect_celery_installed: celery importable = %s", installed
            )
            return installed
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
            logger.debug(
                "detect_celery_installed: subprocess failed (%s)", exc
            )
            return False

    def detect_celery_app_module(self):
        """Find the Celery application module path.

        Strategy:
        1. Look for a ``celery.py`` file inside any top-level Python
           package of the project (e.g. ``myproject/celery.py``).
        2. Scan Python files in the project for ``Celery(...)``
           instantiation as a fallback.

        Returns:
            str (dotted module path, e.g. ``"myproject.celery"``) or None
        """
        # Strategy 1: find celery.py in sub-packages
        try:
            for entry in os.scandir(self._project_path):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                # Skip common non-package directories
                if entry.name.startswith(".") or entry.name in (
                    "venv", ".venv", "env", ".env", "node_modules",
                    "__pycache__", "static", "media", "templates",
                    "staticfiles",
                ):
                    continue
                celery_py = os.path.join(entry.path, "celery.py")
                init_py = os.path.join(entry.path, "__init__.py")
                if os.path.isfile(celery_py) and os.path.isfile(init_py):
                    module = f"{entry.name}.celery"
                    logger.debug(
                        "detect_celery_app_module: found %s", module
                    )
                    return module
        except (PermissionError, OSError) as exc:
            logger.debug(
                "detect_celery_app_module: scandir failed (%s)", exc
            )

        # Strategy 2: grep for Celery() instantiation
        try:
            for root, _dirs, files in os.walk(self._project_path):
                # Prune uninteresting directories
                rel = os.path.relpath(root, self._project_path)
                parts = rel.split(os.sep)
                if any(
                    p.startswith(".")
                    or p in (
                        "venv", ".venv", "env", ".env",
                        "node_modules", "__pycache__",
                    )
                    for p in parts
                ):
                    continue

                for fname in files:
                    if not fname.endswith(".py"):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", errors="ignore") as fh:
                            content = fh.read()
                    except (IOError, OSError):
                        continue

                    if re.search(
                        r"""Celery\s*\(""", content
                    ):
                        rel_path = os.path.relpath(fpath, self._project_path)
                        module = (
                            rel_path
                            .replace(os.sep, ".")
                            .replace(".py", "")
                        )
                        logger.debug(
                            "detect_celery_app_module: found Celery() "
                            "in %s → %s",
                            fpath,
                            module,
                        )
                        return module
        except (PermissionError, OSError) as exc:
            logger.debug(
                "detect_celery_app_module: walk failed (%s)", exc
            )

        return None

    def detect_celery_beat(self):
        """Detect whether Celery Beat is configured.

        Checks:
        1. ``CELERY_BEAT_SCHEDULE`` defined in Django settings
           (via ``manage.py diffsettings``).
        2. ``django_celery_beat`` present in ``INSTALLED_APPS``
           (via ``manage.py diffsettings``).
        3. Presence of ``django_celery_beat`` importable in the env.

        Returns:
            bool
        """
        output = self._get_diffsettings()
        if output:
            if "CELERY_BEAT_SCHEDULE" in output:
                logger.debug(
                    "detect_celery_beat: CELERY_BEAT_SCHEDULE found in "
                    "diffsettings"
                )
                return True
            if "django_celery_beat" in output:
                logger.debug(
                    "detect_celery_beat: django_celery_beat found in "
                    "diffsettings (INSTALLED_APPS)"
                )
                return True

        # Fallback: check if django_celery_beat is importable
        if self._is_package_importable("django_celery_beat"):
            logger.debug(
                "detect_celery_beat: django_celery_beat is importable"
            )
            return True

        return False

    def detect_django_celery_beat(self):
        """Check if ``django_celery_beat`` is installed.

        Used to decide whether to add ``--scheduler
        django_celery_beat.schedulers:DatabaseScheduler`` to the Beat
        systemd unit.

        Returns:
            bool
        """
        # Check diffsettings first (most reliable: it's in INSTALLED_APPS)
        output = self._get_diffsettings()
        if output and "django_celery_beat" in output:
            return True
        return self._is_package_importable("django_celery_beat")

    def detect_broker_url(self):
        """Parse ``CELERY_BROKER_URL`` from Django settings.

        Returns:
            str (e.g. ``"redis://localhost:6379/0"``) or None
        """
        output = self._get_diffsettings()
        if not output:
            return None

        # Try both the modern and legacy setting names
        for setting in ("CELERY_BROKER_URL", "BROKER_URL"):
            for line in output.splitlines():
                pattern = rf"""^{setting}\s*=\s*['"]([^'"]+)['"]"""
                match = re.match(pattern, line.strip())
                if match:
                    url = match.group(1)
                    logger.debug(
                        "detect_broker_url: %s = %s", setting, url
                    )
                    return url
        return None

    def detect_redis_installed(self):
        """Check whether Redis server or client CLI is available.

        Returns:
            bool
        """
        has_server = shutil.which("redis-server") is not None
        has_cli = shutil.which("redis-cli") is not None
        installed = has_server or has_cli
        logger.debug(
            "detect_redis_installed: server=%s, cli=%s → %s",
            has_server,
            has_cli,
            installed,
        )
        return installed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_redis_broker(broker_url):
        """Return True if the broker URL uses the ``redis://`` scheme."""
        if not broker_url:
            return False
        return broker_url.lower().startswith(("redis://", "rediss://"))

    def _is_package_importable(self, package_name):
        """Try to import *package_name* using the project's Python."""
        try:
            proc = subprocess.run(
                [self._python_path, "-c", f"import {package_name}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return proc.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    def _get_diffsettings(self):
        """Run ``manage.py diffsettings`` and cache the output.

        Returns:
            str (stdout) or None
        """
        if self._diffsettings_cache is not None:
            return self._diffsettings_cache

        if not os.path.isfile(self._manage_py):
            return None

        try:
            proc = subprocess.run(
                [self._python_path, self._manage_py, "diffsettings"],
                capture_output=True,
                text=True,
                cwd=self._project_path,
                timeout=15,
            )
            if proc.returncode == 0:
                self._diffsettings_cache = proc.stdout
                return self._diffsettings_cache
        except (subprocess.SubprocessError, OSError) as exc:
            logger.debug("_get_diffsettings: failed (%s)", exc)

        return None
