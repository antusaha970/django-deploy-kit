"""Installer / setup engine for django-deploy-toolkit."""

import os
import time

import click
from rich.console import Console

from .generators.socket import SocketGenerator
from .generators.service import ServiceGenerator
from .generators.nginx import NginxGenerator
from .rollback import RollbackManager
from .utils import is_root, run_system_command, write_file_safe

console = Console()


class Installer:
    """Installs generated configuration files and activates services.

    Supports dry-run mode where all commands are printed but not executed.
    Uses RollbackManager to undo changes on failure.
    """

    def __init__(self, config, dry_run=False, overwrite=False):
        """
        Args:
            config: Validated configuration dict.
            dry_run: If True, only print actions without executing.
            overwrite: If True, overwrite existing files.
        """
        self.config = config
        self.dry_run = dry_run
        self.overwrite = overwrite
        self.use_sudo = not is_root()
        self.rollback = RollbackManager(dry_run=dry_run)
        self.results = []  # List of (step_name, status, detail)

        project_name = config["project_name"]
        self.socket_path = f"/etc/systemd/system/{project_name}.socket"
        self.service_path = f"/etc/systemd/system/{project_name}.service"
        self.nginx_available = f"/etc/nginx/sites-available/{project_name}"
        self.nginx_enabled = f"/etc/nginx/sites-enabled/{project_name}"

    def install(self):
        """Run the full installation sequence.

        Returns:
            list: Results as list of (step_name, status, detail) tuples.
                  status is one of: 'success', 'failed', 'skipped'.
        """
        steps = [
            ("Write socket file", self._write_socket_file),
            ("Write service file", self._write_service_file),
            ("Write Nginx config", self._write_nginx_config),
            ("Remove default Nginx config", self._remove_default_nginx),
            ("Create Nginx symlink", self._create_nginx_symlink),
            ("Reload systemd daemon", self._daemon_reload),
            ("Enable socket", self._enable_socket),
            ("Start socket", self._start_socket),
            ("Enable service", self._enable_service),
            ("Test Nginx config", self._test_nginx),
            ("Reload Nginx", self._reload_nginx),
        ]

        for step_name, step_fn in steps:
            try:
                detail = step_fn()
                status = "success"
                if detail and detail.startswith("SKIP"):
                    status = "skipped"
                    detail = detail[5:]  # Remove "SKIP:" prefix
                self.results.append((step_name, status, detail or "Done"))
            except Exception as e:
                self.results.append((step_name, "failed", str(e)))
                console.print(
                    f"\n[bold red]Step failed: {step_name}[/bold red]"
                )
                console.print(f"[red]{e}[/red]")

                if not self.dry_run:
                    self.rollback.rollback()

                return self.results

        return self.results

    def _write_socket_file(self):
        """Write the .socket file to /etc/systemd/system/."""
        generator = SocketGenerator(self.config)
        content = generator.generate()

        if self.dry_run:
            console.print(f"  [DRY RUN] Would write: {self.socket_path}")
            return "Dry run"

        # Check if file exists
        if os.path.exists(self.socket_path) and not self.overwrite:
            if not click.confirm(
                f"File {self.socket_path} already exists. Overwrite?",
                default=False,
            ):
                return "SKIP:File exists, user chose not to overwrite"

        write_file_safe(
            self.socket_path, content,
            use_sudo=self.use_sudo, overwrite=True,
        )
        self.rollback.register_file_creation(self.socket_path)
        self.rollback.register_daemon_reload()
        return f"Written to {self.socket_path}"

    def _write_service_file(self):
        """Write the .service file to /etc/systemd/system/."""
        generator = ServiceGenerator(self.config)
        content = generator.generate()

        if self.dry_run:
            console.print(f"  [DRY RUN] Would write: {self.service_path}")
            return "Dry run"

        if os.path.exists(self.service_path) and not self.overwrite:
            if not click.confirm(
                f"File {self.service_path} already exists. Overwrite?",
                default=False,
            ):
                return "SKIP:File exists, user chose not to overwrite"

        write_file_safe(
            self.service_path, content,
            use_sudo=self.use_sudo, overwrite=True,
        )
        self.rollback.register_file_creation(self.service_path)
        return f"Written to {self.service_path}"

    def _write_nginx_config(self):
        """Write the Nginx config to /etc/nginx/sites-available/."""
        generator = NginxGenerator(self.config)
        content = generator.generate()

        if self.dry_run:
            console.print(f"  [DRY RUN] Would write: {self.nginx_available}")
            return "Dry run"

        if os.path.exists(self.nginx_available) and not self.overwrite:
            if not click.confirm(
                f"File {self.nginx_available} already exists. Overwrite?",
                default=False,
            ):
                return "SKIP:File exists, user chose not to overwrite"

        write_file_safe(
            self.nginx_available, content,
            use_sudo=self.use_sudo, overwrite=True,
        )
        self.rollback.register_file_creation(self.nginx_available)
        self.rollback.register_nginx_reload()
        return f"Written to {self.nginx_available}"

    def _remove_default_nginx(self):
        """Remove the default Nginx config to prevent conflicts."""
        sites_enabled_default = "/etc/nginx/sites-enabled/default"
        sites_available_default = "/etc/nginx/sites-available/default"

        has_enabled = os.path.exists(sites_enabled_default)
        has_available = os.path.exists(sites_available_default)

        if not has_enabled and not has_available:
            return "SKIP:Default Nginx config not found (already removed)"

        if self.dry_run:
            if has_enabled:
                console.print(
                    f"  [DRY RUN] Would remove: {sites_enabled_default}"
                )
            if has_available:
                console.print(
                    f"  [DRY RUN] Would remove: {sites_available_default}"
                )
            return "Dry run"

        console.print(
            "\n[bold yellow]⚠ The default Nginx config will be removed to "
            "prevent it from conflicting with your project. "
            "Press Ctrl+C to cancel.[/bold yellow]"
        )
        time.sleep(3)

        # Backup and remove sites-enabled/default
        if has_enabled:
            self.rollback.backup_file(sites_enabled_default)
            try:
                if self.use_sudo:
                    run_system_command(
                        ["rm", "-f", sites_enabled_default],
                        use_sudo=True,
                        description="Remove default Nginx enabled config",
                    )
                else:
                    os.unlink(sites_enabled_default)
            except (OSError, RuntimeError) as e:
                console.print(
                    f"[yellow]Could not remove {sites_enabled_default}: {e}\n"
                    f"You can remove it manually: "
                    f"sudo rm {sites_enabled_default}[/yellow]"
                )

        # Backup and remove sites-available/default
        if has_available:
            self.rollback.backup_file(sites_available_default)
            try:
                if self.use_sudo:
                    run_system_command(
                        ["rm", "-f", sites_available_default],
                        use_sudo=True,
                        description="Remove default Nginx available config",
                    )
                else:
                    os.remove(sites_available_default)
            except (OSError, RuntimeError) as e:
                console.print(
                    f"[yellow]Could not remove {sites_available_default}: {e}\n"
                    f"You can remove it manually: "
                    f"sudo rm {sites_available_default}[/yellow]"
                )

        return "Default Nginx config removed"

    def _create_nginx_symlink(self):
        """Create symlink from sites-enabled to sites-available."""
        if self.dry_run:
            console.print(
                f"  [DRY RUN] Would create symlink: "
                f"{self.nginx_enabled} -> {self.nginx_available}"
            )
            return "Dry run"

        # Check if symlink already exists
        if os.path.islink(self.nginx_enabled):
            target = os.readlink(self.nginx_enabled)
            if target == self.nginx_available:
                return "SKIP:Symlink already exists and points to correct target"
            else:
                # Points to wrong target
                if not click.confirm(
                    f"Symlink {self.nginx_enabled} exists but points to "
                    f"{target} instead of {self.nginx_available}. Replace?",
                    default=True,
                ):
                    return "SKIP:User chose not to replace existing symlink"

                if self.use_sudo:
                    run_system_command(
                        ["rm", "-f", self.nginx_enabled],
                        use_sudo=True,
                    )
                else:
                    os.unlink(self.nginx_enabled)

        # Create the symlink
        if self.use_sudo:
            run_system_command(
                ["ln", "-s", self.nginx_available, self.nginx_enabled],
                use_sudo=True,
                description="Create Nginx symlink",
            )
        else:
            os.symlink(self.nginx_available, self.nginx_enabled)

        self.rollback.register_symlink_creation(self.nginx_enabled)
        return f"Created symlink {self.nginx_enabled} -> {self.nginx_available}"

    def _daemon_reload(self):
        """Run systemctl daemon-reload."""
        project_name = self.config["project_name"]
        run_system_command(
            ["systemctl", "daemon-reload"],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description="Reload systemd daemon",
        )
        return "Daemon reloaded" if not self.dry_run else "Dry run"

    def _enable_socket(self):
        """Enable the Gunicorn socket."""
        project_name = self.config["project_name"]
        unit = f"{project_name}.socket"
        run_system_command(
            ["systemctl", "enable", unit],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description=f"Enable {unit}",
        )
        if not self.dry_run:
            self.rollback.register_service_enable(unit)
        return f"Enabled {unit}" if not self.dry_run else "Dry run"

    def _start_socket(self):
        """Start the Gunicorn socket."""
        project_name = self.config["project_name"]
        unit = f"{project_name}.socket"
        run_system_command(
            ["systemctl", "start", unit],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description=f"Start {unit}",
        )
        if not self.dry_run:
            self.rollback.register_service_start(unit)
        return f"Started {unit}" if not self.dry_run else "Dry run"

    def _enable_service(self):
        """Enable the Gunicorn service."""
        project_name = self.config["project_name"]
        unit = f"{project_name}.service"
        run_system_command(
            ["systemctl", "enable", unit],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description=f"Enable {unit}",
        )
        if not self.dry_run:
            self.rollback.register_service_enable(unit)
        return f"Enabled {unit}" if not self.dry_run else "Dry run"

    def _test_nginx(self):
        """Test the Nginx configuration."""
        run_system_command(
            ["nginx", "-t"],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description="Test Nginx configuration",
        )
        return "Nginx config test passed" if not self.dry_run else "Dry run"

    def _reload_nginx(self):
        """Reload Nginx to apply the new config."""
        run_system_command(
            ["systemctl", "reload", "nginx"],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description="Reload Nginx",
        )
        return "Nginx reloaded" if not self.dry_run else "Dry run"
