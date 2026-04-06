"""Tests for config file generators."""

import os

import pytest

from django_deploy_toolkit.generators.socket import SocketGenerator
from django_deploy_toolkit.generators.service import ServiceGenerator
from django_deploy_toolkit.generators.nginx import NginxGenerator


@pytest.fixture
def full_config():
    """A complete configuration dict for testing."""
    return {
        "project_name": "myproject",
        "project_path": "/home/deploy/myproject",
        "wsgi_module": "myproject.wsgi:application",
        "user": "deploy",
        "group": "deploy",
        "python_path": "/home/deploy/myproject/venv/bin/python",
        "server_ip": "192.168.1.100",
        "workers": 5,
        "static_root": "/home/deploy/myproject/staticfiles",
        "media_root": "/home/deploy/myproject/media",
    }


@pytest.fixture
def minimal_config():
    """A config without static/media root."""
    return {
        "project_name": "myproject",
        "project_path": "/home/deploy/myproject",
        "wsgi_module": "myproject.wsgi:application",
        "user": "deploy",
        "group": "deploy",
        "python_path": "/home/deploy/myproject/venv/bin/python",
        "server_ip": "_",
        "workers": 3,
        "static_root": None,
        "media_root": None,
    }


class TestSocketGenerator:
    """Tests for the SocketGenerator."""

    def test_generate_contains_project_name(self, full_config):
        gen = SocketGenerator(full_config)
        output = gen.generate()
        assert "myproject" in output

    def test_generate_has_required_sections(self, full_config):
        gen = SocketGenerator(full_config)
        output = gen.generate()
        assert "[Unit]" in output
        assert "[Socket]" in output
        assert "[Install]" in output

    def test_generate_listen_stream(self, full_config):
        gen = SocketGenerator(full_config)
        output = gen.generate()
        assert "ListenStream=/run/myproject.sock" in output

    def test_generate_wants(self, full_config):
        gen = SocketGenerator(full_config)
        output = gen.generate()
        assert "WantedBy=sockets.target" in output

    def test_write_creates_file(self, full_config, tmp_path):
        gen = SocketGenerator(full_config)
        path = str(tmp_path / "test.socket")
        gen.write(path)
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert "myproject" in content


class TestServiceGenerator:
    """Tests for the ServiceGenerator."""

    def test_generate_contains_all_values(self, full_config):
        gen = ServiceGenerator(full_config)
        output = gen.generate()
        assert "myproject" in output
        assert "deploy" in output
        assert "/home/deploy/myproject" in output
        assert "venv/bin/python" in output
        assert "5" in output
        assert "myproject.wsgi:application" in output

    def test_generate_has_required_sections(self, full_config):
        gen = ServiceGenerator(full_config)
        output = gen.generate()
        assert "[Unit]" in output
        assert "[Service]" in output
        assert "[Install]" in output

    def test_generate_requires_socket(self, full_config):
        gen = ServiceGenerator(full_config)
        output = gen.generate()
        assert "Requires=myproject.socket" in output

    def test_generate_exec_start(self, full_config):
        gen = ServiceGenerator(full_config)
        output = gen.generate()
        assert "-m gunicorn" in output
        assert "--bind unix:/run/myproject.sock" in output

    def test_generate_user_group(self, full_config):
        gen = ServiceGenerator(full_config)
        output = gen.generate()
        assert "User=deploy" in output
        assert "Group=deploy" in output

    def test_write_creates_file(self, full_config, tmp_path):
        gen = ServiceGenerator(full_config)
        path = str(tmp_path / "test.service")
        gen.write(path)
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert "myproject" in content


class TestNginxGenerator:
    """Tests for the NginxGenerator."""

    def test_generate_contains_server_ip(self, full_config):
        gen = NginxGenerator(full_config)
        output = gen.generate()
        assert "server_name 192.168.1.100" in output

    def test_generate_contains_proxy_pass(self, full_config):
        gen = NginxGenerator(full_config)
        output = gen.generate()
        assert "proxy_pass http://unix:/run/myproject.sock" in output

    def test_generate_with_static_root(self, full_config):
        gen = NginxGenerator(full_config)
        output = gen.generate()
        assert "location /static/" in output
        # Parent directory of /home/deploy/myproject/staticfiles is /home/deploy/myproject
        assert "root /home/deploy/myproject" in output

    def test_generate_with_media_root(self, full_config):
        gen = NginxGenerator(full_config)
        output = gen.generate()
        assert "location /media/" in output

    def test_generate_without_static_root(self, minimal_config):
        gen = NginxGenerator(minimal_config)
        output = gen.generate()
        assert "location /static/" not in output

    def test_generate_without_media_root(self, minimal_config):
        gen = NginxGenerator(minimal_config)
        output = gen.generate()
        assert "location /media/" not in output

    def test_generate_catch_all_server_name(self, minimal_config):
        gen = NginxGenerator(minimal_config)
        output = gen.generate()
        assert "server_name _" in output

    def test_generate_includes_proxy_params(self, full_config):
        gen = NginxGenerator(full_config)
        output = gen.generate()
        assert "include proxy_params" in output

    def test_write_creates_file(self, full_config, tmp_path):
        gen = NginxGenerator(full_config)
        path = str(tmp_path / "test.conf")
        gen.write(path)
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert "server" in content

    def test_static_root_parent_computation(self):
        """Test that static_root_parent strips the last dir component."""
        config = {
            "project_name": "test",
            "server_ip": "_",
            "static_root": "/home/user/project/staticfiles",
            "media_root": None,
        }
        gen = NginxGenerator(config)
        output = gen.generate()
        assert "root /home/user/project;" in output
