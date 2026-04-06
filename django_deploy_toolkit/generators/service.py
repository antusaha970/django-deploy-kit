"""Gunicorn service file generator."""

from jinja2 import Template


SERVICE_TEMPLATE = """\
[Unit]
Description=gunicorn daemon for {{ project_name }}
Requires={{ project_name }}.socket
After=network.target

[Service]
User={{ user }}
Group={{ group }}
WorkingDirectory={{ project_path }}
ExecStart={{ python_path }} -m gunicorn \\
          --access-logfile - \\
          --workers {{ workers }} \\
          --bind unix:/run/{{ project_name }}.sock \\
          {{ wsgi_module }}

[Install]
WantedBy=multi-user.target
"""


class ServiceGenerator:
    """Generates a systemd service unit file for Gunicorn."""

    def __init__(self, config):
        """
        Args:
            config: Dict with keys: project_name, user, group,
                project_path, python_path, workers, wsgi_module.
        """
        self.config = config

    def generate(self):
        """Generate the service file content.

        Returns:
            str: The rendered service unit file content.
        """
        template = Template(SERVICE_TEMPLATE)
        return template.render(
            project_name=self.config["project_name"],
            user=self.config["user"],
            group=self.config["group"],
            project_path=self.config["project_path"],
            python_path=self.config["python_path"],
            workers=self.config["workers"],
            wsgi_module=self.config["wsgi_module"],
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
                f"Permission denied writing service file to {path}. "
                f"Try running with sudo: sudo django-deploy setup"
            ) from e
