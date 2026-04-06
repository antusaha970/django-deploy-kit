"""Gunicorn socket file generator."""

from jinja2 import Template


SOCKET_TEMPLATE = """\
[Unit]
Description=gunicorn socket for {{ project_name }}

[Socket]
ListenStream=/run/{{ project_name }}.sock

[Install]
WantedBy=sockets.target
"""


class SocketGenerator:
    """Generates a systemd socket unit file for Gunicorn."""

    def __init__(self, config):
        """
        Args:
            config: Dict with at least 'project_name'.
        """
        self.config = config

    def generate(self):
        """Generate the socket file content.

        Returns:
            str: The rendered socket unit file content.
        """
        template = Template(SOCKET_TEMPLATE)
        return template.render(project_name=self.config["project_name"])

    def write(self, path):
        """Write the generated socket file to disk.

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
                f"Permission denied writing socket file to {path}. "
                f"Try running with sudo: sudo django-deploy setup"
            ) from e
