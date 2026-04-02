"""Rollback and cleanup logic for django-deploy-kit."""

import os
import shutil
import tempfile

from rich.console import Console

from .utils import run_system_command, is_root

console = Console()


class RollbackManager:
    """Manages undo actions for the installer.

    Maintains a stack of undo actions. If any installation step fails,
    executes all registered undo actions in reverse order.
    """

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self._undo_actions = []
        self._backup_dir = tempfile.mkdtemp(prefix="django_deploy_kit_backup_")
        self._backups = {}

    def register_file_creation(self, path):
        """Register that a file was created and should be deleted on rollback."""
        self._undo_actions.append(("delete_file", path))

    def register_symlink_creation(self, path):
        """Register that a symlink was created and should be removed on rollback."""
        self._undo_actions.append(("delete_symlink", path))

    def register_service_start(self, service_name):
        """Register that a service was started and should be stopped on rollback."""
        self._undo_actions.append(("stop_service", service_name))

    def register_service_enable(self, service_name):
        """Register that a service was enabled and should be disabled on rollback."""
        self._undo_actions.append(("disable_service", service_name))

    def backup_file(self, path):
        """Create a backup of a file before it's deleted.

        Args:
            path: Absolute path to the file to back up.

        Returns:
            str: Path to the backup copy, or None if backup failed.
        """
        if not os.path.exists(path):
            return None

        try:
            backup_name = os.path.basename(path) + ".bak"
            backup_path = os.path.join(self._backup_dir, backup_name)
            shutil.copy2(path, backup_path)
            self._backups[path] = backup_path
            self._undo_actions.append(("restore_file", path))
            return backup_path
        except (IOError, OSError) as e:
            console.print(f"[yellow]Warning: Could not backup {path}: {e}[/yellow]")
            return None

    def register_daemon_reload(self):
        """Register that a daemon-reload should be run on rollback."""
        self._undo_actions.append(("daemon_reload",))

    def register_nginx_reload(self):
        """Register that nginx should be tested and reloaded on rollback."""
        self._undo_actions.append(("nginx_reload",))

    def rollback(self):
        """Execute all registered undo actions in reverse order.

        Each action is wrapped in its own try/except so one failure
        doesn't prevent the others from running.
        """
        if not self._undo_actions:
            console.print("[dim]No actions to rollback.[/dim]")
            return

        console.print("\n[bold red]Rolling back changes...[/bold red]")
        use_sudo = not is_root()

        # Execute in reverse order
        for action in reversed(self._undo_actions):
            try:
                action_type = action[0]

                if action_type == "delete_file":
                    path = action[1]
                    self._rollback_delete_file(path, use_sudo)

                elif action_type == "delete_symlink":
                    path = action[1]
                    self._rollback_delete_symlink(path, use_sudo)

                elif action_type == "stop_service":
                    service = action[1]
                    self._rollback_stop_service(service, use_sudo)

                elif action_type == "disable_service":
                    service = action[1]
                    self._rollback_disable_service(service, use_sudo)

                elif action_type == "restore_file":
                    path = action[1]
                    self._rollback_restore_file(path, use_sudo)

                elif action_type == "daemon_reload":
                    self._rollback_daemon_reload(use_sudo)

                elif action_type == "nginx_reload":
                    self._rollback_nginx_reload(use_sudo)

            except Exception as e:
                console.print(
                    f"[red]Rollback step failed ({action_type}): {e}[/red]"
                )

        console.print("[yellow]Rollback complete.[/yellow]")

        # Cleanup backup directory
        self._cleanup_backups()

    def _rollback_delete_file(self, path, use_sudo):
        """Delete a file that was created during installation."""
        if self.dry_run:
            console.print(f"  [DRY RUN] Would delete: {path}")
            return

        if os.path.exists(path):
            try:
                if use_sudo:
                    run_system_command(["rm", "-f", path], use_sudo=True)
                else:
                    os.remove(path)
                console.print(f"  [green]Deleted:[/green] {path}")
            except (OSError, RuntimeError) as e:
                console.print(f"  [red]Failed to delete {path}: {e}[/red]")

    def _rollback_delete_symlink(self, path, use_sudo):
        """Remove a symlink that was created during installation."""
        if self.dry_run:
            console.print(f"  [DRY RUN] Would remove symlink: {path}")
            return

        if os.path.islink(path):
            try:
                if use_sudo:
                    run_system_command(["rm", "-f", path], use_sudo=True)
                else:
                    os.unlink(path)
                console.print(f"  [green]Removed symlink:[/green] {path}")
            except (OSError, RuntimeError) as e:
                console.print(f"  [red]Failed to remove symlink {path}: {e}[/red]")

    def _rollback_stop_service(self, service, use_sudo):
        """Stop a service that was started during installation."""
        if self.dry_run:
            console.print(f"  [DRY RUN] Would stop: {service}")
            return

        try:
            run_system_command(
                ["systemctl", "stop", service],
                use_sudo=use_sudo,
                description=f"Stop {service}",
            )
            console.print(f"  [green]Stopped:[/green] {service}")
        except RuntimeError as e:
            console.print(f"  [red]Failed to stop {service}: {e}[/red]")

    def _rollback_disable_service(self, service, use_sudo):
        """Disable a service that was enabled during installation."""
        if self.dry_run:
            console.print(f"  [DRY RUN] Would disable: {service}")
            return

        try:
            run_system_command(
                ["systemctl", "disable", service],
                use_sudo=use_sudo,
                description=f"Disable {service}",
            )
            console.print(f"  [green]Disabled:[/green] {service}")
        except RuntimeError as e:
            console.print(f"  [red]Failed to disable {service}: {e}[/red]")

    def _rollback_restore_file(self, original_path, use_sudo):
        """Restore a file from backup."""
        backup_path = self._backups.get(original_path)
        if not backup_path or not os.path.exists(backup_path):
            console.print(
                f"  [yellow]No backup found for {original_path}[/yellow]"
            )
            return

        if self.dry_run:
            console.print(
                f"  [DRY RUN] Would restore: {original_path} from {backup_path}"
            )
            return

        try:
            if use_sudo:
                run_system_command(
                    ["cp", backup_path, original_path],
                    use_sudo=True,
                    description=f"Restore {original_path}",
                )
            else:
                shutil.copy2(backup_path, original_path)
            console.print(f"  [green]Restored:[/green] {original_path}")
        except (OSError, RuntimeError) as e:
            console.print(
                f"  [red]Failed to restore {original_path}: {e}[/red]"
            )

    def _rollback_daemon_reload(self, use_sudo):
        """Run systemctl daemon-reload."""
        if self.dry_run:
            console.print("  [DRY RUN] Would run: systemctl daemon-reload")
            return

        try:
            run_system_command(
                ["systemctl", "daemon-reload"],
                use_sudo=use_sudo,
                description="Reload systemd daemon",
            )
            console.print("  [green]Reloaded systemd daemon[/green]")
        except RuntimeError as e:
            console.print(f"  [red]Failed to reload daemon: {e}[/red]")

    def _rollback_nginx_reload(self, use_sudo):
        """Test and reload nginx."""
        if self.dry_run:
            console.print(
                "  [DRY RUN] Would run: nginx -t && systemctl reload nginx"
            )
            return

        try:
            run_system_command(
                ["nginx", "-t"],
                use_sudo=use_sudo,
                description="Test Nginx config",
            )
            run_system_command(
                ["systemctl", "reload", "nginx"],
                use_sudo=use_sudo,
                description="Reload Nginx",
            )
            console.print("  [green]Reloaded Nginx[/green]")
        except RuntimeError as e:
            console.print(f"  [red]Failed to reload Nginx: {e}[/red]")

    def _cleanup_backups(self):
        """Remove the temporary backup directory."""
        try:
            if os.path.isdir(self._backup_dir):
                shutil.rmtree(self._backup_dir)
        except OSError:
            pass
