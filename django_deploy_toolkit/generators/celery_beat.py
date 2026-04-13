"""Celery Beat systemd service file generator."""

from jinja2 import Template


CELERY_BEAT_TEMPLATE = """\
[Unit]
Description=Celery Beat Scheduler for {{ project_name }}
After=network.target

[Service]
Type=simple
User={{ user }}
Group={{ group }}
WorkingDirectory={{ project_path }}
ExecStart={{ python_path }} -m celery -A {{ celery_app_module }} beat \\
          --loglevel=info \\
          --pidfile=/run/celery/{{ project_name }}-beat.pid \\
          --logfile=/var/log/celery/{{ project_name }}-beat.log{% if use_django_celery_beat %} \\
          --scheduler django_celery_beat.schedulers:DatabaseScheduler{% endif %}

ExecStop=/bin/kill -s TERM $MAINPID
RuntimeDirectory=celery
Restart=always

[Install]
WantedBy=multi-user.target
"""


class CeleryBeatGenerator:
    """Generates a systemd service unit file for Celery Beat."""

    def __init__(self, config):
        """
        Args:
            config: Dict with keys: project_name, user, group,
                project_path, python_path, celery_app_module.
                Optional: use_django_celery_beat (bool, default False).
        """
        self.config = config

    def generate(self):
        """Generate the Celery Beat service file content.

        Returns:
            str: The rendered systemd unit file content.
        """
        template = Template(CELERY_BEAT_TEMPLATE)
        return template.render(
            project_name=self.config["project_name"],
            user=self.config["user"],
            group=self.config["group"],
            project_path=self.config["project_path"],
            python_path=self.config["python_path"],
            celery_app_module=self.config["celery_app_module"],
            use_django_celery_beat=self.config.get(
                "use_django_celery_beat", False
            ),
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
                f"Permission denied writing Celery Beat service to {path}. "
                f"Try running with sudo: sudo django-deploy celery-setup"
            ) from e
