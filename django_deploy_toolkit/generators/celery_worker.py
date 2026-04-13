"""Celery worker systemd service file generator."""

from jinja2 import Template


CELERY_WORKER_TEMPLATE = """\
[Unit]
Description=Celery Worker for {{ project_name }}
After=network.target

[Service]
Type=simple
User={{ user }}
Group={{ group }}
WorkingDirectory={{ project_path }}
ExecStart={{ python_path }} -m celery -A {{ celery_app_module }} worker \\
          --loglevel=info \\
          --concurrency={{ concurrency }} \\
          --logfile=/var/log/celery/{{ project_name }}-worker.log
RuntimeDirectory=celery
Restart=always

[Install]
WantedBy=multi-user.target
"""


class CeleryWorkerGenerator:
    """Generates a systemd service unit file for a Celery worker."""

    def __init__(self, config):
        """
        Args:
            config: Dict with keys: project_name, user, group,
                project_path, python_path, celery_app_module.
                Optional: concurrency (default 1).
        """
        self.config = config

    def generate(self):
        """Generate the Celery worker service file content.

        Returns:
            str: The rendered systemd unit file content.
        """
        template = Template(CELERY_WORKER_TEMPLATE)
        return template.render(
            project_name=self.config["project_name"],
            user=self.config["user"],
            group=self.config["group"],
            project_path=self.config["project_path"],
            python_path=self.config["python_path"],
            celery_app_module=self.config["celery_app_module"],
            concurrency=self.config.get("concurrency", 1),
        )

    def write(self, path):
        """Write the generated service file to disk.

        Args:
            path: Absolute path to write the file.

        Raises:
            PermissionError: If writing fails due to permissions.
        """
        content = self.generate()
        try:
            with open(path, "w") as f:
                f.write(content)
        except PermissionError as e:
            raise PermissionError(
                f"Permission denied writing Celery worker service to {path}. "
                f"Try running with sudo: sudo django-deploy celery-setup"
            ) from e
