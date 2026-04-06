"""Summary report and colored output for django-deploy-toolkit."""

import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


class Reporter:
    """Produces rich terminal output for django-deploy-toolkit operations."""

    def __init__(self, config, sources=None):
        """
        Args:
            config: The validated configuration dict.
            sources: Dict mapping config keys to source type
                ('auto', 'user', 'missing').
        """
        self.config = config
        self.sources = sources or {}

    def print_settings_table(self):
        """Print the pre-run settings table.

        Color-codes rows:
        - Green for auto-detected values
        - Yellow for user-provided values
        - Red for missing/default fallback values
        """
        table = Table(
            title="🔍 Detected Configuration",
            show_lines=True,
            title_style="bold cyan",
        )
        table.add_column("Setting", style="bold", min_width=16)
        table.add_column("Value", min_width=30)

        display_items = [
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

        for key, label in display_items:
            value = self.config.get(key)
            source = self.sources.get(key, "missing")

            if value is None:
                style = "red"
                value_str = "Not set"
            elif source == "auto":
                style = "green"
                value_str = str(value)
            elif source == "user":
                style = "yellow"
                value_str = str(value)
            else:
                style = "red"
                value_str = str(value) if value else "Not set"

            table.add_row(f"[{style}]{label}[/{style}]", f"[{style}]{value_str}[/{style}]")

        console.print()
        console.print(table)
        console.print()

    def print_results_table(self, results):
        """Print the post-run results table.

        Args:
            results: List of (step_name, status, detail) tuples.
                status: 'success', 'failed', or 'skipped'.
        """
        table = Table(
            title="📋 Installation Results",
            show_lines=True,
            title_style="bold cyan",
        )
        table.add_column("Step", style="bold", min_width=28)
        table.add_column("Status", min_width=10, justify="center")
        table.add_column("Detail", min_width=30)

        status_icons = {
            "success": "[green]✓ Success[/green]",
            "failed": "[red]✗ Failed[/red]",
            "skipped": "[yellow]⚠ Skipped[/yellow]",
        }

        for step_name, status, detail in results:
            icon = status_icons.get(status, status)
            detail_style = "green" if status == "success" else (
                "red" if status == "failed" else "yellow"
            )
            table.add_row(step_name, icon, f"[{detail_style}]{detail}[/{detail_style}]")

        console.print()
        console.print(table)
        console.print()

    def print_success(self):
        """Print the success panel with verification instructions."""
        project_name = self.config["project_name"]
        message = (
            f"[bold green]✓ Deployment config for {project_name} is ready.[/bold green]\n\n"
            f"Your Django project should now be served by Gunicorn + Nginx.\n\n"
            f"[bold]Verify with:[/bold]\n"
            f"  systemctl status {project_name}.socket\n"
            f"  systemctl status {project_name}.service\n"
            f"  sudo nginx -t\n"
            f"  curl --unix-socket /run/{project_name}.sock http://localhost/\n"
        )

        panel = Panel(
            message,
            title="🎉 Deployment Complete",
            border_style="green",
            padding=(1, 2),
        )
        console.print(panel)

    def print_failure(self, error, failed_step, rollback_performed=True):
        """Print the failure panel with error details.

        Args:
            error: The error message string.
            failed_step: Name of the step that failed.
            rollback_performed: Whether rollback was executed.
        """
        rollback_status = (
            "[yellow]Rollback was performed. Changes have been undone.[/yellow]"
            if rollback_performed
            else "[red]Rollback was NOT performed.[/red]"
        )

        message = (
            f"[bold red]✗ Installation failed at step: {failed_step}[/bold red]\n\n"
            f"[red]Error:[/red] {error}\n\n"
            f"{rollback_status}\n\n"
            f"[dim]Check the error details above and try again. "
            f"Use --dry-run to preview actions without making changes.[/dim]"
        )

        panel = Panel(
            message,
            title="❌ Installation Failed",
            border_style="red",
            padding=(1, 2),
        )
        console.print(panel)

    def print_dry_run_header(self):
        """Print a header indicating dry-run mode."""
        panel = Panel(
            "[bold yellow]DRY RUN MODE[/bold yellow]\n"
            "No changes will be made. The following actions would be performed:",
            border_style="yellow",
            padding=(0, 2),
        )
        console.print()
        console.print(panel)
        console.print()

    def print_detection_results(self):
        """Print detection results (for the 'detect' command)."""
        self.print_settings_table()

        # Print additional info
        import sys
        is_venv = sys.prefix != sys.base_prefix
        if is_venv:
            console.print(
                "[green]✓ Running inside a virtual environment[/green]"
            )
        else:
            console.print(
                "[yellow]⚠ Not running inside a virtual environment. "
                "Consider activating your project's venv.[/yellow]"
            )

        from .utils import check_gunicorn_installed
        python_path = self.config.get("python_path", sys.executable)
        if check_gunicorn_installed(python_path):
            console.print("[green]✓ Gunicorn is installed[/green]")
        else:
            console.print(
                "[yellow]⚠ Gunicorn not found in the detected Python environment. "
                "Install it with: pip install gunicorn[/yellow]"
            )

        from .utils import check_nginx_installed, check_systemd_available
        if check_nginx_installed():
            console.print("[green]✓ Nginx is installed[/green]")
        else:
            console.print(
                "[red]✗ Nginx is not installed. "
                "Install it with: sudo apt install nginx[/red]"
            )

        if check_systemd_available():
            console.print("[green]✓ Systemd is available[/green]")
        else:
            console.print(
                "[red]✗ Systemd not available. Are you running inside Docker?[/red]"
            )
        console.print()
