"""Shared utilities for django-deploy-kit."""

import os
import platform
import re
import shutil
import subprocess
import sys


def check_platform():
    """Ensure we're running on Linux. Raise SystemExit otherwise."""
    current = platform.system().lower()
    if current != "linux":
        raise SystemExit(
            f"django-deploy-kit only supports Linux (Ubuntu/Debian). "
            f"Detected OS: {platform.system()}. Exiting."
        )


def check_systemd_available():
    """Check if systemd is available on the system."""
    return os.path.exists("/run/systemd/system")


def check_nginx_installed():
    """Check if nginx is installed."""
    return shutil.which("nginx") is not None


def check_gunicorn_installed(python_path):
    """Check if gunicorn is installed in the given Python environment."""
    try:
        result = subprocess.run(
            [python_path, "-c", "import gunicorn"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def is_root():
    """Check if the current process is running as root."""
    return os.geteuid() == 0


def check_sudo_available():
    """Check if sudo is available on the system."""
    return shutil.which("sudo") is not None


def run_system_command(cmd, dry_run=False, use_sudo=False, description=None):
    """Run a system command, optionally with sudo.

    Args:
        cmd: Command as a list of strings.
        dry_run: If True, only print what would be run.
        use_sudo: If True, prefix with sudo.
        description: Human-readable description of the command.

    Returns:
        subprocess.CompletedProcess or None (in dry-run mode).

    Raises:
        RuntimeError: If the command fails.
    """
    if use_sudo and not is_root():
        if not check_sudo_available():
            raise RuntimeError(
                "sudo is not available on this system. "
                "Please run this command as root or install sudo."
            )
        cmd = ["sudo"] + cmd

    cmd_str = " ".join(cmd)

    if dry_run:
        label = f" ({description})" if description else ""
        print(f"  [DRY RUN] Would run: {cmd_str}{label}")
        return None

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else "No error output"
        raise RuntimeError(
            f"Command failed: {cmd_str}\n"
            f"Exit code: {e.returncode}\n"
            f"Error: {stderr}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command timed out: {cmd_str}") from e


def sanitize_project_name(name):
    """Sanitize a project name for use in filenames and systemd unit names.

    - Lowercase
    - Replace spaces and special characters with underscores
    - Remove leading/trailing underscores
    - Ensure it starts with a letter
    """
    name = name.lower().strip()
    # Replace any non-alphanumeric character (except underscore and hyphen) with underscore
    name = re.sub(r"[^a-z0-9_-]", "_", name)
    # Collapse multiple underscores/hyphens
    name = re.sub(r"[_-]+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    # Ensure it starts with a letter
    if name and not name[0].isalpha():
        name = "project_" + name
    # Fallback
    if not name:
        name = "django_project"
    return name


def write_file_safe(path, content, dry_run=False, use_sudo=False, overwrite=False):
    """Write content to a file, handling permissions and existing files.

    Args:
        path: Absolute path to write to.
        content: String content to write.
        dry_run: If True, only print what would be written.
        use_sudo: If True, use sudo tee to write.
        overwrite: If True, overwrite existing files.

    Raises:
        FileExistsError: If file exists and overwrite is False.
        PermissionError: If writing fails due to permissions.
    """
    if dry_run:
        print(f"  [DRY RUN] Would write file: {path}")
        return

    if os.path.exists(path) and not overwrite:
        raise FileExistsError(
            f"File already exists: {path}. "
            f"Use --overwrite or delete it manually."
        )

    if use_sudo and not is_root():
        if not check_sudo_available():
            raise RuntimeError(
                "sudo is not available. Please run as root or install sudo."
            )
        try:
            process = subprocess.run(
                ["sudo", "tee", path],
                input=content,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        except subprocess.CalledProcessError as e:
            raise PermissionError(
                f"Failed to write {path} with sudo: {e.stderr}"
            ) from e
    else:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
        except PermissionError as e:
            raise PermissionError(
                f"Permission denied writing to {path}. "
                f"Try running with sudo: sudo django-deploy setup"
            ) from e
