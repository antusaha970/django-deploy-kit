"""Input validation and interactive prompting for django-deploy-toolkit."""

import grp
import ipaddress
import os
import pwd
import re

import click
from rich.console import Console
from rich.table import Table

console = Console()


class ConfigValidator:
    """Validates detected configuration values and prompts for missing ones.

    Takes the detected values dict from ProjectDetector, validates each,
    prompts the user for any None or invalid values, and returns a fully
    validated configuration dict.
    """

    def __init__(self, config, no_confirm=False):
        """
        Args:
            config: Dict of detected values from ProjectDetector.
            no_confirm: If True, skip the confirmation prompt.
        """
        self.config = dict(config)
        self.no_confirm = no_confirm
        self._sources = {}  # Track whether values were auto-detected or user-provided

        # Initialize sources: auto-detected if not None
        for key, value in self.config.items():
            self._sources[key] = "auto" if value is not None else "missing"

    def validate_and_prompt(self):
        """Run validation and prompting flow.

        Returns:
            dict: Fully validated configuration.
        """
        while True:
            self._validate_project_path()
            self._validate_project_name()
            self._validate_wsgi_module()
            self._validate_user()
            self._validate_group()
            self._validate_python_path()
            self._validate_server_ip()
            self._validate_workers()
            self._validate_static_root()
            self._validate_media_root()

            self._display_summary()

            if self.no_confirm:
                break

            proceed = click.confirm(
                "\nProceed with these settings?", default=True
            )
            if proceed:
                break
            else:
                console.print(
                    "\n[yellow]Re-entering configuration...[/yellow]\n"
                )
                # Reset sources to allow re-prompting
                for key in self.config:
                    self._sources[key] = "missing"

        return self.config

    def get_sources(self):
        """Return the sources dict for reporting."""
        return dict(self._sources)

    def _prompt_value(self, key, prompt_text, default=None, validator=None):
        """Prompt the user for a value and validate it.

        Args:
            key: Config key to set.
            prompt_text: Text to display in the prompt.
            default: Default value to suggest.
            validator: Optional callable(value) -> bool for validation.
        """
        while True:
            value = click.prompt(prompt_text, default=default, type=str)
            if validator and not validator(value):
                console.print("[red]Invalid value. Please try again.[/red]")
                continue
            self.config[key] = value
            self._sources[key] = "user"
            return value

    def _validate_project_path(self):
        """Validate project_path exists and is readable."""
        path = self.config.get("project_path")

        if path and os.path.isdir(path) and os.access(path, os.R_OK):
            return

        self._prompt_value(
            "project_path",
            "Django project path",
            default=os.getcwd(),
            validator=lambda v: os.path.isdir(v) and os.access(v, os.R_OK),
        )

    def _validate_project_name(self):
        """Validate project_name is set and clean."""
        name = self.config.get("project_name")

        if name and re.match(r"^[a-z][a-z0-9_-]*$", name):
            return

        default = os.path.basename(
            self.config.get("project_path", os.getcwd())
        ).lower()
        default = re.sub(r"[^a-z0-9_-]", "_", default).strip("_") or "django_project"

        self._prompt_value(
            "project_name",
            "Project name (used for systemd units and nginx config)",
            default=default,
            validator=lambda v: bool(re.match(r"^[a-z][a-z0-9_-]*$", v)),
        )

    def _validate_wsgi_module(self):
        """Validate WSGI module path matches pattern module.path:callable."""
        wsgi = self.config.get("wsgi_module")

        if wsgi and re.match(r"^[\w.]+:\w+$", wsgi):
            return

        self._prompt_value(
            "wsgi_module",
            "WSGI module path (e.g. myapp.wsgi:application)",
            default=wsgi,
            validator=lambda v: bool(re.match(r"^[\w.]+:\w+$", v)),
        )

    def _validate_user(self):
        """Validate username exists on the system."""
        user = self.config.get("user")

        if user:
            try:
                pwd.getpwnam(user)
                return
            except KeyError:
                pass

        self._prompt_value(
            "user",
            "System user to run Gunicorn as",
            default=os.getenv("USER", "www-data"),
            validator=self._user_exists,
        )

    @staticmethod
    def _user_exists(username):
        try:
            pwd.getpwnam(username)
            return True
        except KeyError:
            return False

    def _validate_group(self):
        """Validate group exists on the system."""
        group = self.config.get("group")

        if group:
            try:
                grp.getgrnam(group)
                return
            except KeyError:
                pass

        self._prompt_value(
            "group",
            "System group",
            default=self.config.get("user", "www-data"),
            validator=self._group_exists,
        )

    @staticmethod
    def _group_exists(groupname):
        try:
            grp.getgrnam(groupname)
            return True
        except KeyError:
            return False

    def _validate_python_path(self):
        """Validate Python path is executable."""
        path = self.config.get("python_path")

        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return

        import sys

        self._prompt_value(
            "python_path",
            "Python interpreter path",
            default=sys.executable,
            validator=lambda v: os.path.isfile(v) and os.access(v, os.X_OK),
        )

    def _validate_server_ip(self):
        """Validate IP is a valid IPv4/IPv6 address or '_'."""
        ip = self.config.get("server_ip")

        if ip and self._is_valid_ip(ip):
            return

        self._prompt_value(
            "server_ip",
            "Server IP address or domain (use '_' for catch-all)",
            default="_",
            validator=self._is_valid_ip,
        )

    @staticmethod
    def _is_valid_ip(value):
        if value == "_":
            return True
        # Allow domain names too
        if re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$", value):
            return True
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            pass
        return False

    def _validate_workers(self):
        """Validate worker count is between 1 and 17."""
        workers = self.config.get("workers")

        if workers is not None:
            try:
                workers = int(workers)
                if 1 <= workers <= 17:
                    self.config["workers"] = workers
                    return
            except (ValueError, TypeError):
                pass

        while True:
            value = click.prompt(
                "Number of Gunicorn workers (1-17)",
                default=3,
                type=int,
            )
            if 1 <= value <= 17:
                self.config["workers"] = value
                self._sources["workers"] = "user"
                return
            console.print("[red]Must be between 1 and 17.[/red]")

    def _validate_static_root(self):
        """Validate static_root is an absolute path if provided."""
        path = self.config.get("static_root")

        if path is None:
            # It's optional — skip without prompting
            return

        if os.path.isabs(path):
            return

        self._prompt_value(
            "static_root",
            "STATIC_ROOT absolute path (leave empty to skip)",
            default="",
            validator=lambda v: v == "" or os.path.isabs(v),
        )
        if self.config["static_root"] == "":
            self.config["static_root"] = None

    def _validate_media_root(self):
        """Validate media_root is an absolute path if provided."""
        path = self.config.get("media_root")

        if path is None:
            return

        if os.path.isabs(path):
            return

        self._prompt_value(
            "media_root",
            "MEDIA_ROOT absolute path (leave empty to skip)",
            default="",
            validator=lambda v: v == "" or os.path.isabs(v),
        )
        if self.config["media_root"] == "":
            self.config["media_root"] = None

    def _display_summary(self):
        """Display a Rich table summarizing all configuration values."""
        table = Table(title="Deployment Configuration", show_lines=True)
        table.add_column("Setting", style="bold")
        table.add_column("Value")
        table.add_column("Source")

        display_order = [
            ("project_name", "Project Name"),
            ("project_path", "Project Path"),
            ("wsgi_module", "WSGI Module"),
            ("user", "User"),
            ("group", "Group"),
            ("python_path", "Python Path"),
            ("server_ip", "Server IP"),
            ("workers", "Workers"),
            ("static_root", "Static Root"),
            ("media_root", "Media Root"),
        ]

        for key, label in display_order:
            value = self.config.get(key)
            source = self._sources.get(key, "missing")

            if value is None:
                value_str = "[dim]Not set[/dim]"
                source_style = "red"
                source_label = "⚠ Missing"
            elif source == "auto":
                value_str = str(value)
                source_style = "green"
                source_label = "✓ Auto-detected"
            elif source == "user":
                value_str = str(value)
                source_style = "yellow"
                source_label = "✎ User-provided"
            else:
                value_str = str(value)
                source_style = "red"
                source_label = "⚠ Default fallback"

            table.add_row(label, value_str, f"[{source_style}]{source_label}[/{source_style}]")

        console.print()
        console.print(table)
