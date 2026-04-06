"""Nginx configuration file generator."""

import os

from jinja2 import Template


NGINX_TEMPLATE = """\
server {
    listen 80;
    server_name {{ server_ip }};

{% if static_root %}
    location /static/ {
        root {{ static_root_parent }};
    }

{% endif %}
{% if media_root %}
    location /media/ {
        root {{ media_root_parent }};
    }

{% endif %}
    location / {
        include proxy_params;
        proxy_pass http://unix:/run/{{ project_name }}.sock;
    }
}
"""


class NginxGenerator:
    """Generates an Nginx server block configuration for a Django project."""

    def __init__(self, config):
        """
        Args:
            config: Dict with keys: project_name, server_ip.
                Optional: static_root, media_root.
        """
        self.config = config

    def generate(self):
        """Generate the Nginx config content.

        Returns:
            str: The rendered Nginx configuration.
        """
        static_root = self.config.get("static_root")
        media_root = self.config.get("media_root")

        # Compute parent directories for Nginx root directive
        static_root_parent = None
        if static_root:
            static_root_parent = os.path.dirname(static_root.rstrip(os.sep))

        media_root_parent = None
        if media_root:
            media_root_parent = os.path.dirname(media_root.rstrip(os.sep))

        template = Template(NGINX_TEMPLATE)
        return template.render(
            project_name=self.config["project_name"],
            server_ip=self.config["server_ip"],
            static_root=static_root,
            static_root_parent=static_root_parent,
            media_root=media_root,
            media_root_parent=media_root_parent,
        )

    def write(self, path):
        """Write the generated Nginx config to disk.

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
                f"Permission denied writing Nginx config to {path}. "
                f"Try running with sudo: sudo django-deploy setup"
            ) from e
