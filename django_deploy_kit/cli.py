"""Click-based CLI for django-deploy-kit."""

import logging
import os
import sys

import click
from rich.console import Console

from . import __version__
from .detector import ProjectDetector
from .generators.nginx import NginxGenerator
from .generators.service import ServiceGenerator
from .generators.socket import SocketGenerator
from .installer import Installer
from .reporter import Reporter
from .rollback import RollbackManager
from .utils import (
    check_gunicorn_installed,
    check_nginx_installed,
    check_platform,
    check_systemd_available,
)
from .validators import ConfigValidator

console = Console()


def _configure_logging(verbose):
    """Set up logging level based on the verbose flag."""
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    logging.getLogger("django_deploy_kit").setLevel(log_level)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="django-deploy-kit")
@click.option(
    "--project-path",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Override the detected project path.",
)
@click.option(
    "--project-name",
    type=str,
    default=None,
    help="Override the detected project name.",
)
@click.option(
    "--no-confirm",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt.",
)
@click.option(
    "--verbose/--no-verbose",
    default=False,
    help="Show or hide detailed output.",
)
@click.pass_context
def main(ctx, project_path, project_name, no_confirm, verbose):
    """django-deploy-kit: Auto-generate Gunicorn & Nginx configs for Django projects."""
    _configure_logging(verbose)
    check_platform()

    ctx.ensure_object(dict)
    ctx.obj["project_path"] = project_path
    ctx.obj["project_name"] = project_name
    ctx.obj["no_confirm"] = no_confirm
    ctx.obj["verbose"] = verbose

    # If no subcommand, show help
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without actually doing it.",
)
@click.option(
    "--verbose/--no-verbose",
    default=False,
    help="Show or hide detailed output.",
)
@click.pass_context
def setup(ctx, dry_run, verbose):
    """Full interactive setup: detect, validate, generate, and install."""
    verbose = verbose or ctx.obj.get("verbose", False)
    _configure_logging(verbose)
    project_path = ctx.obj["project_path"]
    project_name = ctx.obj["project_name"]
    no_confirm = ctx.obj["no_confirm"]

    console.print(
        "\n[bold cyan]🚀 django-deploy-kit — Setup[/bold cyan]\n"
    )

    # --- Pre-flight checks ---
    warnings = []

    if not check_systemd_available():
        warnings.append(
            "Systemd not available. Are you running inside Docker? "
            "The setup may not work correctly."
        )

    if not check_nginx_installed():
        warnings.append(
            "Nginx is not installed. Install it with: sudo apt install nginx"
        )

    for warning in warnings:
        console.print(f"[yellow]⚠ {warning}[/yellow]")

    if warnings and not dry_run:
        if not no_confirm and not click.confirm(
            "\nWarnings detected. Continue anyway?", default=True
        ):
            raise SystemExit("Setup cancelled.")

    # --- Detection ---
    console.print("[bold]Detecting project configuration...[/bold]\n")
    detector = ProjectDetector(project_path=project_path)
    config = detector.detect_all()

    # Apply overrides
    if project_name:
        config["project_name"] = project_name
    if project_path:
        config["project_path"] = os.path.abspath(project_path)

    # --- Warnings about detected values ---
    if config.get("python_path"):
        if not detector.is_virtualenv():
            console.print(
                "[yellow]⚠ Python path points to system Python, not a virtualenv. "
                "Consider activating your project's virtual environment.[/yellow]\n"
            )

        if not check_gunicorn_installed(config["python_path"]):
            console.print(
                "[yellow]⚠ Gunicorn not found in the detected Python environment. "
                "Install it with: pip install gunicorn[/yellow]\n"
            )

    # --- Validation ---
    validator = ConfigValidator(config, no_confirm=no_confirm)
    config = validator.validate_and_prompt()
    sources = validator.get_sources()

    # --- Report ---
    reporter = Reporter(config, sources)

    if dry_run:
        reporter.print_dry_run_header()

    reporter.print_settings_table()

    # --- Installation ---
    installer = Installer(config, dry_run=dry_run, overwrite=False)
    results = installer.install()

    reporter.print_results_table(results)

    # Check if any step failed
    failed = [r for r in results if r[1] == "failed"]
    if failed:
        failed_step = failed[0][0]
        error = failed[0][2]
        reporter.print_failure(error, failed_step)
        raise SystemExit(1)
    else:
        if not dry_run:
            reporter.print_success()
        else:
            console.print(
                "[bold yellow]Dry run complete. "
                "No changes were made.[/bold yellow]\n"
            )


@main.command()
@click.option(
    "--verbose/--no-verbose",
    default=False,
    help="Show or hide detailed output.",
)
@click.pass_context
def detect(ctx, verbose):
    """Run detection only and print results without installing."""
    verbose = verbose or ctx.obj.get("verbose", False)
    _configure_logging(verbose)
    project_path = ctx.obj["project_path"]

    console.print(
        "\n[bold cyan]🔍 django-deploy-kit — Detection[/bold cyan]\n"
    )

    detector = ProjectDetector(project_path=project_path)
    config = detector.detect_all()

    # Build sources
    sources = {}
    for key, value in config.items():
        sources[key] = "auto" if value is not None else "missing"

    reporter = Reporter(config, sources)
    reporter.print_detection_results()


@main.command()
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    default=".",
    help="Directory to write generated files to.",
)
@click.option(
    "--verbose/--no-verbose",
    default=False,
    help="Show or hide detailed output.",
)
@click.pass_context
def generate(ctx, output_dir, verbose):
    """Generate config files to the current directory without installing."""
    verbose = verbose or ctx.obj.get("verbose", False)
    _configure_logging(verbose)
    project_path = ctx.obj["project_path"]
    project_name = ctx.obj["project_name"]
    no_confirm = ctx.obj["no_confirm"]

    console.print(
        "\n[bold cyan]📝 django-deploy-kit — Generate[/bold cyan]\n"
    )

    # --- Detection ---
    detector = ProjectDetector(project_path=project_path)
    config = detector.detect_all()

    if project_name:
        config["project_name"] = project_name
    if project_path:
        config["project_path"] = os.path.abspath(project_path)

    # --- Validation ---
    validator = ConfigValidator(config, no_confirm=no_confirm)
    config = validator.validate_and_prompt()

    # --- Generate files ---
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    pname = config["project_name"]

    socket_path = os.path.join(output_dir, f"{pname}.socket")
    service_path = os.path.join(output_dir, f"{pname}.service")
    nginx_path = os.path.join(output_dir, f"{pname}.nginx.conf")

    SocketGenerator(config).write(socket_path)
    console.print(f"[green]✓ Written:[/green] {socket_path}")

    ServiceGenerator(config).write(service_path)
    console.print(f"[green]✓ Written:[/green] {service_path}")

    NginxGenerator(config).write(nginx_path)
    console.print(f"[green]✓ Written:[/green] {nginx_path}")

    console.print(
        f"\n[bold green]Files generated in {output_dir}[/bold green]\n"
    )


@main.command()
@click.option(
    "--name",
    type=str,
    required=True,
    help="Project name to rollback.",
)
@click.pass_context
def rollback(ctx, name):
    """Rollback the last install for a given project.

    Removes the generated config files and disables the services.
    """
    no_confirm = ctx.obj["no_confirm"]

    console.print(
        f"\n[bold red]🔄 django-deploy-kit — Rollback for '{name}'[/bold red]\n"
    )

    socket_path = f"/etc/systemd/system/{name}.socket"
    service_path = f"/etc/systemd/system/{name}.service"
    nginx_available = f"/etc/nginx/sites-available/{name}"
    nginx_enabled = f"/etc/nginx/sites-enabled/{name}"

    files_to_check = [
        ("Socket file", socket_path),
        ("Service file", service_path),
        ("Nginx config", nginx_available),
        ("Nginx symlink", nginx_enabled),
    ]

    found = []
    for label, path in files_to_check:
        if os.path.exists(path) or os.path.islink(path):
            found.append((label, path))
            console.print(f"  Found: {label} at {path}")

    if not found:
        console.print(
            f"[yellow]No deployment files found for project '{name}'.[/yellow]\n"
        )
        return

    if not no_confirm:
        if not click.confirm(
            "\nRemove these files and disable services?", default=False
        ):
            console.print("[dim]Rollback cancelled.[/dim]")
            return

    from .utils import is_root, run_system_command

    use_sudo = not is_root()

    # Stop and disable services
    for unit in [f"{name}.service", f"{name}.socket"]:
        try:
            run_system_command(
                ["systemctl", "stop", unit],
                use_sudo=use_sudo,
            )
            console.print(f"  [green]Stopped:[/green] {unit}")
        except RuntimeError:
            pass

        try:
            run_system_command(
                ["systemctl", "disable", unit],
                use_sudo=use_sudo,
            )
            console.print(f"  [green]Disabled:[/green] {unit}")
        except RuntimeError:
            pass

    # Remove files
    for label, path in found:
        try:
            if use_sudo:
                run_system_command(["rm", "-f", path], use_sudo=True)
            else:
                if os.path.islink(path):
                    os.unlink(path)
                else:
                    os.remove(path)
            console.print(f"  [green]Removed:[/green] {path}")
        except (OSError, RuntimeError) as e:
            console.print(f"  [red]Failed to remove {path}: {e}[/red]")

    # Reload
    try:
        run_system_command(
            ["systemctl", "daemon-reload"],
            use_sudo=use_sudo,
        )
        console.print("  [green]Reloaded systemd daemon[/green]")
    except RuntimeError:
        pass

    try:
        run_system_command(["nginx", "-t"], use_sudo=use_sudo)
        run_system_command(
            ["systemctl", "reload", "nginx"],
            use_sudo=use_sudo,
        )
        console.print("  [green]Reloaded Nginx[/green]")
    except RuntimeError:
        pass

    console.print(
        f"\n[bold green]Rollback for '{name}' complete.[/bold green]\n"
    )


if __name__ == "__main__":
    main()
