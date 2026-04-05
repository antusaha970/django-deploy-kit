"""Auto-detection logic for Django project configuration."""

import grp
import logging
import os
import pwd
import re
import socket
import subprocess
import sys

import psutil

from .utils import sanitize_project_name

logger = logging.getLogger(__name__)

# Well-known virtualenv directory names to search for
_VENV_DIR_NAMES = [".venv", "venv", "env", ".env"]

# Maximum depth for downward directory search to avoid deep recursion
_MAX_DOWNWARD_DEPTH = 3


class ProjectDetector:
    """Detects Django project configuration values automatically.

    For every item, if detection fails or is ambiguous, the value is stored
    as None so the validator can prompt the user. Never crashes silently.
    """

    def __init__(self, project_path=None):
        self._project_path = project_path
        self._manage_py_path = None
        self._settings_module = None
        self._detected_python_path = None

    def detect_all(self):
        """Run all detection methods and return a dict of results.

        Returns:
            dict with keys: project_name, project_path, wsgi_module, user,
                group, python_path, server_ip, workers, static_root,
                media_root. Values are None when detection fails.
        """
        result = {}
        detection_methods = [
            ("project_path", self.detect_project_path),
            ("project_name", self.detect_project_name),
            ("wsgi_module", self.detect_wsgi_module),
            ("user", self.detect_user),
            ("group", self.detect_group),
            ("python_path", self.detect_python_path),
            ("server_ip", self.detect_server_ip),
            ("workers", self.detect_workers),
            ("static_root", self.detect_static_root),
            ("media_root", self.detect_media_root),
        ]

        for key, method in detection_methods:
            try:
                result[key] = method()
            except Exception:
                result[key] = None

        return result

    def detect_project_name(self):
        """Detect project name from the current working directory.

        Uses the basename of the project path. Sanitizes special characters.

        Returns:
            str or None
        """
        path = self._project_path or os.getcwd()
        basename = os.path.basename(os.path.abspath(path))
        if not basename:
            return None
        return sanitize_project_name(basename)

    def detect_project_path(self):
        """Detect and validate the Django project path.

        Checks current directory, one level up, and one level down for
        manage.py to confirm it is a Django project.

        Returns:
            str (absolute path) or None
        """
        start_path = self._project_path or os.getcwd()
        start_path = os.path.abspath(start_path)

        # Check current directory
        manage_py = os.path.join(start_path, "manage.py")
        if os.path.isfile(manage_py):
            self._manage_py_path = manage_py
            self._project_path = start_path
            return start_path

        # Check one level up
        parent = os.path.dirname(start_path)
        manage_py = os.path.join(parent, "manage.py")
        if os.path.isfile(manage_py):
            self._manage_py_path = manage_py
            self._project_path = parent
            return parent

        # Check one level down
        try:
            for entry in os.scandir(start_path):
                if entry.is_dir(follow_symlinks=False):
                    manage_py = os.path.join(entry.path, "manage.py")
                    if os.path.isfile(manage_py):
                        self._manage_py_path = manage_py
                        self._project_path = entry.path
                        return entry.path
        except PermissionError:
            pass

        return None

    def _find_settings_module(self):
        """Parse manage.py to find the DJANGO_SETTINGS_MODULE value."""
        if self._settings_module:
            return self._settings_module

        manage_py = self._manage_py_path
        if not manage_py or not os.path.isfile(manage_py):
            return None

        try:
            with open(manage_py, "r") as f:
                content = f.read()
        except (IOError, OSError):
            return None

        # Look for: os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myapp.settings')
        patterns = [
            r"""os\.environ\.setdefault\(\s*['"]DJANGO_SETTINGS_MODULE['"]\s*,\s*['"]([^'"]+)['"]\s*\)""",
            r"""os\.environ\[['"]DJANGO_SETTINGS_MODULE['"]\]\s*=\s*['"]([^'"]+)['"]""",
            r"""DJANGO_SETTINGS_MODULE['"]\s*,\s*['"]([^'"]+)['"]""",
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                self._settings_module = match.group(1)
                return self._settings_module

        return None

    def detect_wsgi_module(self):
        """Detect the WSGI module path.

        First tries to parse manage.py for DJANGO_SETTINGS_MODULE.
        Falls back to scanning for wsgi.py files.

        Returns:
            str (e.g. 'myapp.wsgi:application') or None
        """
        # Method 1: From settings module
        settings_module = self._find_settings_module()
        if settings_module:
            # settings_module is like 'myapp.settings'
            # wsgi module is 'myapp.wsgi'
            parts = settings_module.rsplit(".", 1)
            if len(parts) >= 2:
                wsgi_module = f"{parts[0]}.wsgi:application"
                return wsgi_module

        # Method 2: Scan for wsgi.py
        project_path = self._project_path or os.getcwd()
        for root, _dirs, files in os.walk(project_path):
            if "wsgi.py" in files:
                # Convert file path to module path
                rel_path = os.path.relpath(
                    os.path.join(root, "wsgi.py"), project_path
                )
                # e.g. 'myapp/wsgi.py' -> 'myapp.wsgi'
                module_path = rel_path.replace(os.sep, ".").replace(".py", "")
                return f"{module_path}:application"

        return None

    def detect_user(self):
        """Detect the current OS user.

        Returns:
            str or None
        """
        user = os.getenv("USER") or os.getenv("LOGNAME")
        if user:
            return user
        try:
            return pwd.getpwuid(os.getuid()).pw_name
        except (KeyError, OSError):
            return None

    def detect_group(self):
        """Detect the current user's primary group.

        Returns:
            str or None
        """
        try:
            pw = pwd.getpwuid(os.getuid())
            return grp.getgrgid(pw.pw_gid).gr_name
        except (KeyError, OSError):
            return None

    @staticmethod
    def _is_valid_executable(path):
        """Check if a path points to a valid, executable file.

        Args:
            path: Filesystem path to check.

        Returns:
            bool: True if path exists, is a file, and is executable.
        """
        resolved = os.path.realpath(path)
        return (
            os.path.isfile(resolved) and os.access(resolved, os.X_OK)
        )

    @staticmethod
    def _is_valid_virtualenv(venv_dir):
        """Validate that a directory is a genuine virtualenv.

        A valid virtualenv MUST contain:
          - pyvenv.cfg at the root
          - bin/python as an executable file

        Args:
            venv_dir: Path to the candidate virtualenv directory.

        Returns:
            str or None: The venv python executable path if valid,
                         None otherwise.
        """
        venv_dir = os.path.abspath(venv_dir)
        pyvenv_cfg = os.path.join(venv_dir, "pyvenv.cfg")
        python_bin = os.path.join(venv_dir, "bin", "python")

        if not os.path.isfile(pyvenv_cfg):
            return None
        if not ProjectDetector._is_valid_executable(python_bin):
            return None

        # Return the venv path, NOT os.path.realpath().
        # realpath resolves symlinks to the system Python binary
        # (e.g. /usr/bin/python3.12), which bypasses the venv's
        # site-packages entirely.
        return python_bin

    def _search_upward_for_venv(self, start_path):
        """Search upward from start_path to root for a virtualenv directory.

        At each level, checks for well-known virtualenv directory names
        (.venv, venv, env, .env) and validates them.

        The first valid virtualenv found (closest to project) wins.

        Args:
            start_path: Absolute path to start searching from.

        Returns:
            str or None: Resolved python executable path, or None.
        """
        current = os.path.realpath(start_path)
        visited = set()

        while current and current not in visited:
            visited.add(current)
            for name in _VENV_DIR_NAMES:
                candidate = os.path.join(current, name)
                if os.path.isdir(candidate):
                    python_path = self._is_valid_virtualenv(candidate)
                    if python_path:
                        logger.debug(
                            "Upward search: found virtualenv at %s",
                            candidate,
                        )
                        return python_path

            parent = os.path.dirname(current)
            if parent == current:
                break  # Reached filesystem root
            current = parent

        return None

    def _search_downward_for_venv(self, start_path, max_depth=None):
        """Walk project directory downward looking for a virtualenv.

        Limits depth to avoid deep recursive scans. Returns the
        shallowest (nearest) valid virtualenv found.

        Args:
            start_path: Absolute path to start searching from.
            max_depth: Maximum directory depth to search (default:
                       _MAX_DOWNWARD_DEPTH).

        Returns:
            str or None: Resolved python executable path, or None.
        """
        if max_depth is None:
            max_depth = _MAX_DOWNWARD_DEPTH

        start_path = os.path.realpath(start_path)
        best_python = None
        best_depth = max_depth + 1  # Sentinel: higher than any valid depth

        for dirpath, dirnames, _files in os.walk(start_path):
            # Calculate current depth relative to start
            rel = os.path.relpath(dirpath, start_path)
            depth = 0 if rel == "." else rel.count(os.sep) + 1

            if depth >= max_depth:
                dirnames.clear()  # Prune further descent
                continue

            for name in _VENV_DIR_NAMES:
                if name in dirnames:
                    candidate = os.path.join(dirpath, name)
                    python_path = self._is_valid_virtualenv(candidate)
                    if python_path:
                        candidate_depth = depth + 1
                        if candidate_depth < best_depth:
                            best_depth = candidate_depth
                            best_python = python_path
                            logger.debug(
                                "Downward search: found virtualenv at %s "
                                "(depth %d)",
                                candidate,
                                candidate_depth,
                            )

        return best_python

    def detect_python_path(self):
        """Detect the active Python interpreter path.

        Uses a strict priority-based strategy:

        1. **Interpreter state** — if the current process is running
           inside a virtualenv (sys.prefix != sys.base_prefix), return
           sys.executable directly (highest confidence).

        2. **VIRTUAL_ENV environment variable** — resolve the env var
           to ``<VIRTUAL_ENV>/bin/python`` and validate.

        3. **Upward filesystem search** — traverse from project_path
           toward the root, checking for well-known virtualenv directory
           names (.venv, venv, env, .env) and validating each with
           ``pyvenv.cfg`` + executable presence.

        4. **Downward filesystem search** — walk project directory with
           a controlled depth limit, looking for virtualenv directories.

        Returns:
            str (resolved python executable path) or None
        """
        project_path = os.path.abspath(
            self._project_path or os.getcwd()
        )

        # --- Strategy 1: Interpreter state (highest confidence) ---
        # If the current process IS running inside a venv, trust it.
        if sys.prefix != sys.base_prefix:
            exe = sys.executable
            if exe and self._is_valid_executable(exe):
                # Use abspath (NOT realpath!) — realpath follows symlinks
                # to the system Python, which would bypass the venv.
                result = os.path.abspath(exe)
                logger.debug(
                    "Strategy 1 (interpreter state): running inside "
                    "virtualenv, using sys.executable = %s",
                    result,
                )
                return result

        # --- Strategy 2: VIRTUAL_ENV environment variable ---
        virtual_env = os.environ.get("VIRTUAL_ENV")
        if virtual_env:
            candidate = os.path.join(virtual_env, "bin", "python")
            if self._is_valid_executable(candidate):
                result = os.path.abspath(candidate)
                logger.debug(
                    "Strategy 2 (VIRTUAL_ENV env var): found python "
                    "at %s",
                    result,
                )
                return result
            else:
                logger.debug(
                    "Strategy 2 (VIRTUAL_ENV env var): VIRTUAL_ENV=%s "
                    "set but %s is not a valid executable, skipping",
                    virtual_env,
                    candidate,
                )

        # --- Strategy 3: Upward filesystem search (primary) ---
        upward_result = self._search_upward_for_venv(project_path)
        if upward_result:
            logger.debug(
                "Strategy 3 (upward search): resolved python = %s",
                upward_result,
            )
            return upward_result

        # --- Strategy 4: Downward filesystem search (secondary) ---
        downward_result = self._search_downward_for_venv(project_path)
        if downward_result:
            logger.debug(
                "Strategy 4 (downward search): resolved python = %s",
                downward_result,
            )
            return downward_result

        # --- No virtualenv found ---
        logger.debug(
            "No virtualenv detected for project at %s. "
            "You do not have any venv — please create one.",
            project_path,
        )
        return None

    def is_virtualenv(self):
        """Check if we're running inside a virtual environment."""
        return sys.prefix != sys.base_prefix

    def detect_server_ip(self):
        """Detect the server's IP address.

        Tries in order:
        1. Parse /etc/hosts for a non-loopback entry
        2. socket.gethostbyname(socket.gethostname())
        3. UDP socket trick to 8.8.8.8

        Falls back to '_' (Nginx catch-all) if all fail.

        Returns:
            str
        """
        # Method 1: Parse /etc/hosts
        try:
            with open("/etc/hosts", "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[0]
                        if ip not in ("127.0.0.1", "::1", "127.0.1.1"):
                            return ip
        except (IOError, OSError):
            pass

        # Method 2: gethostbyname
        try:
            ip = socket.gethostbyname(socket.gethostname())
            if ip and not ip.startswith("127."):
                return ip
        except socket.error:
            pass

        # Method 3: UDP socket trick
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            sock.close()
            if ip and not ip.startswith("127."):
                return ip
        except (socket.error, OSError):
            pass

        # Fallback
        return "_"

    def detect_workers(self):
        """Detect the recommended Gunicorn worker count.

        Formula: (2 × cpu_count) + 1, capped at 9.

        Returns:
            int
        """
        try:
            cpu_count = psutil.cpu_count(logical=True)
            if cpu_count is None:
                return 3
            workers = (2 * cpu_count) + 1
            return min(workers, 9)
        except Exception:
            return 3

    def _get_django_setting(self, setting_name):
        """Get a Django setting value by running manage.py diffsettings.

        Args:
            setting_name: The Django setting to look for (e.g. 'STATIC_ROOT').

        Returns:
            str or None
        """
        project_path = self._project_path or os.getcwd()
        manage_py = self._manage_py_path or os.path.join(project_path, "manage.py")

        if not os.path.isfile(manage_py):
            return None

        # Use cached result if available to avoid re-detection
        if self._detected_python_path is not None:
            python_path = self._detected_python_path
        else:
            python_path = self.detect_python_path()
            self._detected_python_path = python_path

        if not python_path:
            python_path = sys.executable
            logger.debug(
                "_get_django_setting: no venv python found, "
                "falling back to sys.executable=%s",
                python_path,
            )

        try:
            result = subprocess.run(
                [python_path, manage_py, "diffsettings"],
                capture_output=True,
                text=True,
                cwd=project_path,
                timeout=15,
            )

            if result.returncode != 0:
                return None

            # Parse output for the setting
            for line in result.stdout.splitlines():
                # Match: STATIC_ROOT = '/path/to/static'
                # or:    STATIC_ROOT = "/path/to/static"
                pattern = rf"""^{setting_name}\s*=\s*['"]([^'"]+)['"]"""
                match = re.match(pattern, line.strip())
                if match:
                    return match.group(1)

                # Match: STATIC_ROOT = PosixPath('/path/to/static')
                pattern_posix = rf"""^{setting_name}\s*=\s*PosixPath\(['"]([^'"]+)['"]\)"""
                match = re.match(pattern_posix, line.strip())
                if match:
                    return match.group(1)
            logger.debug("---- DJANGO SETTING DEBUG START ----")
            logger.debug("manage.py path: %s", manage_py)
            logger.debug("project_path: %s", project_path)
            logger.debug("python_path used: %s", python_path)
            logger.debug("VIRTUAL_ENV: %s", os.environ.get("VIRTUAL_ENV"))
            logger.debug("sys.executable: %s", sys.executable)
            logger.debug("---- DJANGO SETTING DEBUG END ----")

        except (subprocess.SubprocessError, OSError):
            logger.debug("in except block")

        return None

    def detect_static_root(self):
        """Detect STATIC_ROOT from Django settings.

        Returns:
            str (absolute path) or None
        """
        return self._get_django_setting("STATIC_ROOT")

    def detect_media_root(self):
        """Detect MEDIA_ROOT from Django settings.

        Returns:
            str (absolute path) or None
        """
        return self._get_django_setting("MEDIA_ROOT")
