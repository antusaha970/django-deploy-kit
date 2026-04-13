"""Click-based CLI for django-deploy-toolkit."""

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
from .celery_detector import CeleryDetector
from .celery_installer import CeleryInstaller
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
    logging.getLogger("django_deploy_toolkit").setLevel(log_level)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="django-deploy-toolkit")
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
    """django-deploy-toolkit: Auto-generate Gunicorn & Nginx configs for Django projects."""
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
        "\n[bold cyan]🚀 django-deploy-toolkit — Setup[/bold cyan]\n"
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

        # Always remind the user to update server_name
        server_ip = config.get("server_ip", "_")
        nginx_path = f"/etc/nginx/sites-available/{config['project_name']}"
        console.print(
            f"[bold cyan]📌 Important:[/bold cyan] Your Nginx [bold]server_name[/bold] "
            f"is currently set to [yellow]{server_ip}[/yellow].\n"
            f"   If you have a domain name, update it in the Nginx config:\n\n"
            f"     [dim]sudo nano {nginx_path}[/dim]\n\n"
            f"   Change [yellow]server_name {server_ip};[/yellow] → "
            f"[green]server_name yourdomain.com;[/green]\n"
            f"   Then reload Nginx: [dim]sudo systemctl reload nginx[/dim]\n"
        )

        # --- Celery hint ---
        try:
            celery_det = CeleryDetector(
                project_path=config["project_path"],
                python_path=config.get("python_path"),
            )
            celery_info = celery_det.detect_all()
            has_celery = celery_info.get("celery_installed", False)
            has_beat = celery_info.get("celery_beat_enabled", False)

            if has_celery and has_beat:
                console.print(
                    "[bold magenta]📦 Celery & Celery Beat detected![/bold magenta]\n"
                    "   Generate systemd services for both with:\n\n"
                    "     [dim]django-deploy celery-setup[/dim]\n"
                )
            elif has_celery:
                console.print(
                    "[bold magenta]📦 Celery detected![/bold magenta]\n"
                    "   Generate a systemd service for Celery worker with:\n\n"
                    "     [dim]django-deploy celery-setup[/dim]\n"
                )
        except Exception:
            pass  # Don't let celery detection failure break setup


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
        "\n[bold cyan]🔍 django-deploy-toolkit — Detection[/bold cyan]\n"
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
        "\n[bold cyan]📝 django-deploy-toolkit — Generate[/bold cyan]\n"
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
        f"\n[bold red]🔄 django-deploy-toolkit — Rollback for '{name}'[/bold red]\n"
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


@main.command(name="celery-setup")
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
def celery_setup(ctx, dry_run, verbose):
    """Detect Celery/Celery Beat and generate + install systemd services."""
    verbose = verbose or ctx.obj.get("verbose", False)
    _configure_logging(verbose)
    project_path = ctx.obj["project_path"]
    project_name = ctx.obj["project_name"]
    no_confirm = ctx.obj["no_confirm"]

    console.print(
        "\n[bold cyan]🥬 django-deploy-toolkit — Celery Setup[/bold cyan]\n"
    )

    # --- Detection (reuse Django detector for project basics) ---
    console.print("[bold]Detecting project configuration...[/bold]\n")
    detector = ProjectDetector(project_path=project_path)
    config = detector.detect_all()

    if project_name:
        config["project_name"] = project_name
    if project_path:
        config["project_path"] = os.path.abspath(project_path)

    # Validate essentials
    if not config.get("project_path"):
        console.print(
            "[red]✗ Could not detect Django project path. "
            "Run this command from your Django project root "
            "(where manage.py lives).[/red]"
        )
        raise SystemExit(1)

    if not config.get("python_path"):
        console.print(
            "[red]✗ Could not detect Python interpreter. "
            "Activate your project's virtual environment and "
            "try again.[/red]"
        )
        raise SystemExit(1)

    # --- Celery detection ---
    console.print("[bold]Detecting Celery configuration...[/bold]\n")
    celery_det = CeleryDetector(
        project_path=config["project_path"],
        python_path=config.get("python_path"),
    )
    celery_info = celery_det.detect_all()

    if not celery_info["celery_installed"]:
        console.print(
            "[yellow]Celery is not installed in this environment.[/yellow]\n"
            "Install it with: [dim]pip install celery[/dim]\n"
        )
        raise SystemExit(0)

    if not celery_info["celery_app_module"]:
        console.print(
            "[yellow]⚠ Could not auto-detect Celery app module.[/yellow]"
        )
        celery_app_module = click.prompt(
            "Celery app module (e.g. myproject.celery)",
            type=str,
        )
    else:
        celery_app_module = celery_info["celery_app_module"]
        console.print(
            f"  Celery app module: [green]{celery_app_module}[/green]"
        )

    has_beat = celery_info["celery_beat_enabled"]
    has_django_beat = celery_info["django_celery_beat_installed"]
    broker_url = celery_info["broker_url"]
    broker_is_redis = celery_info["broker_is_redis"]
    redis_installed = celery_info["redis_installed"]

    # --- Print summary ---
    console.print(f"  Celery installed:   [green]Yes[/green]")
    console.print(
        f"  Celery Beat:        "
        f"{'[green]Yes[/green]' if has_beat else '[dim]No[/dim]'}"
    )
    if broker_url:
        console.print(f"  Broker URL:         [cyan]{broker_url}[/cyan]")
    if has_django_beat:
        console.print(
            f"  django_celery_beat: [green]Installed[/green] "
            f"(will use DatabaseScheduler)"
        )

    # --- Redis warning ---
    if broker_is_redis and not redis_installed:
        console.print(
            "\n[yellow]⚠ Your broker uses Redis, but redis-server was "
            "not found on this system.[/yellow]\n"
            "  If Redis is running on a remote host, you can ignore "
            "this warning.\n"
            "  Otherwise, install Redis: [dim]sudo apt install "
            "redis-server[/dim]\n"
        )

    # --- What will be generated ---
    pname = config["project_name"]
    console.print("\n[bold]The following systemd services will be created:[/bold]")
    console.print(f"  • /etc/systemd/system/{pname}-celery.service")
    if has_beat:
        console.print(
            f"  • /etc/systemd/system/{pname}-celerybeat.service"
        )
    console.print()

    if not no_confirm:
        if not click.confirm("Proceed?", default=True):
            console.print("[dim]Celery setup cancelled.[/dim]")
            raise SystemExit(0)

    # --- Build installer config ---
    install_config = {
        "project_name": config["project_name"],
        "project_path": config["project_path"],
        "python_path": config["python_path"],
        "user": config["user"],
        "group": config["group"],
        "celery_app_module": celery_app_module,
        "concurrency": 1,
        "use_django_celery_beat": has_django_beat,
    }

    # --- Install ---
    installer = CeleryInstaller(
        install_config,
        install_beat=has_beat,
        dry_run=dry_run,
        overwrite=False,
    )
    results = installer.install()

    # --- Results ---
    reporter = Reporter(config, {})
    reporter.print_results_table(results)

    failed = [r for r in results if r[1] == "failed"]
    if failed:
        failed_step = failed[0][0]
        error = failed[0][2]
        reporter.print_failure(error, failed_step)
        raise SystemExit(1)

    if dry_run:
        console.print(
            "[bold yellow]Dry run complete. "
            "No changes were made.[/bold yellow]\n"
        )
    else:
        console.print(
            f"[bold green]✓ Celery services for '{pname}' are now "
            f"active.[/bold green]\n"
        )

    # --- Post-install reminders ---
    console.print(
        "[bold cyan]📌 Important:[/bold cyan] Celery worker "
        "[bold]concurrency[/bold] is set to [yellow]1[/yellow].\n"
        "   Adjust it based on your workload:\n\n"
        f"     [dim]sudo nano /etc/systemd/system/{pname}-celery.service[/dim]\n\n"
        "   Change [yellow]--concurrency=1[/yellow] to a suitable value,\n"
        "   then reload: [dim]sudo systemctl daemon-reload && "
        f"sudo systemctl restart {pname}-celery.service[/dim]\n"
    )

    if has_beat:
        console.print(
            "[bold cyan]📌 Verify Celery Beat:[/bold cyan]\n"
            f"  systemctl status {pname}-celerybeat.service\n"
        )


if __name__ == "__main__":
    main()
