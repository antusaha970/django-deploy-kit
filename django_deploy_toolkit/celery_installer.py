"""Installer engine for Celery systemd services."""

import os

import click
from rich.console import Console

from .generators.celery_worker import CeleryWorkerGenerator
from .generators.celery_beat import CeleryBeatGenerator
from .rollback import RollbackManager
from .utils import is_root, run_system_command, write_file_safe

console = Console()


class CeleryInstaller:
    """Installs Celery worker (and optionally Beat) systemd service files.

    Mirrors the behaviour of the main ``Installer`` class — supports
    dry-run, rollback on failure, and uses sudo when not root.
    """

    def __init__(self, config, install_beat=False, dry_run=False,
                 overwrite=False):
        """
        Args:
            config: Validated configuration dict.  Must include
                project_name, user, group, project_path, python_path,
                celery_app_module.  Optionally concurrency,
                use_django_celery_beat.
            install_beat: Whether to also install the Celery Beat
                service.
            dry_run: If True, only print actions without executing.
            overwrite: If True, overwrite existing files.
        """
        self.config = config
        self.install_beat = install_beat
        self.dry_run = dry_run
        self.overwrite = overwrite
        self.use_sudo = not is_root()
        self.rollback = RollbackManager(dry_run=dry_run)
        self.results = []  # (step_name, status, detail)

        pname = config["project_name"]
        self.worker_path = f"/etc/systemd/system/{pname}-celery.service"
        self.beat_path = f"/etc/systemd/system/{pname}-celerybeat.service"

    def install(self):
        """Run the full Celery installation sequence.

        Returns:
            list of (step_name, status, detail) tuples.
        """
        steps = [
            ("Create log directory", self._create_log_dir),
            ("Write Celery worker service", self._write_worker_service),
        ]

        if self.install_beat:
            steps.append(
                ("Write Celery Beat service", self._write_beat_service)
            )

        steps.extend([
            ("Reload systemd daemon", self._daemon_reload),
            ("Enable Celery worker", self._enable_worker),
            ("Start Celery worker", self._start_worker),
        ])

        if self.install_beat:
            steps.extend([
                ("Enable Celery Beat", self._enable_beat),
                ("Start Celery Beat", self._start_beat),
            ])

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

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _create_log_dir(self):
        """Ensure /var/log/celery/ exists with correct ownership."""
        log_dir = "/var/log/celery"

        if self.dry_run:
            console.print(
                f"  [DRY RUN] Would create directory: {log_dir}"
            )
            return "Dry run"

        if os.path.isdir(log_dir):
            return "SKIP:Log directory already exists"

        user = self.config["user"]
        group = self.config["group"]

        run_system_command(
            ["mkdir", "-p", log_dir],
            use_sudo=self.use_sudo,
            description="Create Celery log directory",
        )
        run_system_command(
            ["chown", f"{user}:{group}", log_dir],
            use_sudo=self.use_sudo,
            description="Set ownership on Celery log directory",
        )
        return f"Created {log_dir}"

    def _write_worker_service(self):
        """Write the Celery worker .service file."""
        generator = CeleryWorkerGenerator(self.config)
        content = generator.generate()

        if self.dry_run:
            console.print(
                f"  [DRY RUN] Would write: {self.worker_path}"
            )
            return "Dry run"

        if os.path.exists(self.worker_path) and not self.overwrite:
            if not click.confirm(
                f"File {self.worker_path} already exists. Overwrite?",
                default=False,
            ):
                return "SKIP:File exists, user chose not to overwrite"

        write_file_safe(
            self.worker_path, content,
            use_sudo=self.use_sudo, overwrite=True,
        )
        self.rollback.register_file_creation(self.worker_path)
        self.rollback.register_daemon_reload()
        return f"Written to {self.worker_path}"

    def _write_beat_service(self):
        """Write the Celery Beat .service file."""
        generator = CeleryBeatGenerator(self.config)
        content = generator.generate()

        if self.dry_run:
            console.print(
                f"  [DRY RUN] Would write: {self.beat_path}"
            )
            return "Dry run"

        if os.path.exists(self.beat_path) and not self.overwrite:
            if not click.confirm(
                f"File {self.beat_path} already exists. Overwrite?",
                default=False,
            ):
                return "SKIP:File exists, user chose not to overwrite"

        write_file_safe(
            self.beat_path, content,
            use_sudo=self.use_sudo, overwrite=True,
        )
        self.rollback.register_file_creation(self.beat_path)
        return f"Written to {self.beat_path}"

    def _daemon_reload(self):
        """Run systemctl daemon-reload."""
        run_system_command(
            ["systemctl", "daemon-reload"],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description="Reload systemd daemon",
        )
        return "Daemon reloaded" if not self.dry_run else "Dry run"

    def _enable_worker(self):
        """Enable the Celery worker service."""
        unit = f"{self.config['project_name']}-celery.service"
        run_system_command(
            ["systemctl", "enable", unit],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description=f"Enable {unit}",
        )
        if not self.dry_run:
            self.rollback.register_service_enable(unit)
        return f"Enabled {unit}" if not self.dry_run else "Dry run"

    def _start_worker(self):
        """Start the Celery worker service."""
        unit = f"{self.config['project_name']}-celery.service"
        run_system_command(
            ["systemctl", "start", unit],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description=f"Start {unit}",
        )
        if not self.dry_run:
            self.rollback.register_service_start(unit)
        return f"Started {unit}" if not self.dry_run else "Dry run"

    def _enable_beat(self):
        """Enable the Celery Beat service."""
        unit = f"{self.config['project_name']}-celerybeat.service"
        run_system_command(
            ["systemctl", "enable", unit],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description=f"Enable {unit}",
        )
        if not self.dry_run:
            self.rollback.register_service_enable(unit)
        return f"Enabled {unit}" if not self.dry_run else "Dry run"

    def _start_beat(self):
        """Start the Celery Beat service."""
        unit = f"{self.config['project_name']}-celerybeat.service"
        run_system_command(
            ["systemctl", "start", unit],
            dry_run=self.dry_run,
            use_sudo=self.use_sudo,
            description=f"Start {unit}",
        )
        if not self.dry_run:
            self.rollback.register_service_start(unit)
        return f"Started {unit}" if not self.dry_run else "Dry run"
