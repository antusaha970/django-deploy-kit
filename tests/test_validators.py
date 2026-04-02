"""Tests for the ConfigValidator class."""

import os
import ipaddress
from unittest import mock

import pytest

from django_deploy_kit.validators import ConfigValidator


@pytest.fixture
def valid_config():
    """A fully valid configuration dict."""
    return {
        "project_name": "testproject",
        "project_path": os.getcwd(),  # Use a real path that exists
        "wsgi_module": "testproject.wsgi:application",
        "user": os.getenv("USER", "root"),
        "group": os.getenv("USER", "root"),
        "python_path": os.path.realpath(__import__("sys").executable),
        "server_ip": "_",
        "workers": 3,
        "static_root": None,
        "media_root": None,
    }


@pytest.fixture
def partial_config():
    """A config with some None values."""
    return {
        "project_name": None,
        "project_path": os.getcwd(),
        "wsgi_module": None,
        "user": os.getenv("USER", "root"),
        "group": os.getenv("USER", "root"),
        "python_path": os.path.realpath(__import__("sys").executable),
        "server_ip": "_",
        "workers": 3,
        "static_root": None,
        "media_root": None,
    }


class TestValidIpCheck:
    """Tests for the IP validation logic."""

    def test_valid_ipv4(self):
        assert ConfigValidator._is_valid_ip("192.168.1.1") is True

    def test_valid_ipv6(self):
        assert ConfigValidator._is_valid_ip("::1") is True

    def test_catch_all(self):
        assert ConfigValidator._is_valid_ip("_") is True

    def test_domain_name(self):
        assert ConfigValidator._is_valid_ip("example.com") is True

    def test_invalid(self):
        assert ConfigValidator._is_valid_ip("not an ip!!!") is False

    def test_empty(self):
        assert ConfigValidator._is_valid_ip("") is False


class TestUserExists:
    """Tests for user existence check."""

    def test_existing_user(self):
        # Current user should exist
        current_user = os.getenv("USER", "root")
        assert ConfigValidator._user_exists(current_user) is True

    def test_nonexistent_user(self):
        assert ConfigValidator._user_exists("nonexistent_user_xyz_99") is False


class TestGroupExists:
    """Tests for group existence check."""

    def test_existing_group(self):
        current_user = os.getenv("USER", "root")
        assert ConfigValidator._group_exists(current_user) is True

    def test_nonexistent_group(self):
        assert ConfigValidator._group_exists("nonexistent_group_xyz_99") is False


class TestValidConfigPassthrough:
    """Tests that valid configs pass without prompting."""

    def test_valid_config_no_prompts(self, valid_config):
        """A fully valid config should not trigger any prompts."""
        validator = ConfigValidator(valid_config, no_confirm=True)

        # Patch click.prompt to verify it's never called
        with mock.patch("click.prompt") as mock_prompt:
            result = validator.validate_and_prompt()
            mock_prompt.assert_not_called()

        assert result["project_name"] == "testproject"
        assert result["workers"] == 3

    def test_sources_all_auto(self, valid_config):
        """All non-None values should be marked as 'auto'."""
        validator = ConfigValidator(valid_config, no_confirm=True)
        validator.validate_and_prompt()
        sources = validator.get_sources()
        for key in ["project_name", "project_path", "user", "group", "python_path"]:
            assert sources[key] == "auto"


class TestNoneValuesPrompt:
    """Tests that None values trigger prompts."""

    def test_none_project_name_triggers_prompt(self, partial_config):
        """A None project_name should trigger a prompt."""
        validator = ConfigValidator(partial_config, no_confirm=True)

        def prompt_side_effect(text, **kwargs):
            if "Project name" in text:
                return "myproject"
            if "WSGI" in text:
                return "myapp.wsgi:application"
            return kwargs.get("default", "test")

        with mock.patch("click.prompt", side_effect=prompt_side_effect) as mock_prompt:
            result = validator.validate_and_prompt()

        # click.prompt should have been called (at least for project_name and wsgi)
        assert mock_prompt.called
        assert result["project_name"] == "myproject"

    def test_none_wsgi_triggers_prompt(self, partial_config):
        """A None wsgi_module should trigger a prompt."""
        validator = ConfigValidator(partial_config, no_confirm=True)

        def prompt_side_effect(text, **kwargs):
            if "WSGI" in text:
                return "myapp.wsgi:application"
            if "Project name" in text:
                return "myproject"
            return kwargs.get("default", "test")

        with mock.patch("click.prompt", side_effect=prompt_side_effect):
            result = validator.validate_and_prompt()

        assert result["wsgi_module"] == "myapp.wsgi:application"


class TestInvalidValuesRejected:
    """Tests that invalid values are rejected."""

    def test_invalid_wsgi_format(self):
        """WSGI module must match module.path:callable pattern."""
        config = {
            "project_name": "testproject",
            "project_path": os.getcwd(),
            "wsgi_module": "not-valid-wsgi",  # Invalid
            "user": os.getenv("USER", "root"),
            "group": os.getenv("USER", "root"),
            "python_path": os.path.realpath(__import__("sys").executable),
            "server_ip": "_",
            "workers": 3,
            "static_root": None,
            "media_root": None,
        }

        validator = ConfigValidator(config, no_confirm=True)

        call_count = 0

        def prompt_side_effect(text, **kwargs):
            nonlocal call_count
            if "WSGI" in text:
                call_count += 1
                if call_count == 1:
                    return "still-invalid"
                return "myapp.wsgi:application"
            return kwargs.get("default", "test")

        with mock.patch("click.prompt", side_effect=prompt_side_effect):
            result = validator.validate_and_prompt()

        assert result["wsgi_module"] == "myapp.wsgi:application"

    def test_invalid_workers_out_of_range(self):
        """Workers outside 1-17 should be rejected."""
        config = {
            "project_name": "testproject",
            "project_path": os.getcwd(),
            "wsgi_module": "myapp.wsgi:application",
            "user": os.getenv("USER", "root"),
            "group": os.getenv("USER", "root"),
            "python_path": os.path.realpath(__import__("sys").executable),
            "server_ip": "_",
            "workers": 99,  # Out of range
            "static_root": None,
            "media_root": None,
        }

        validator = ConfigValidator(config, no_confirm=True)

        with mock.patch("click.prompt", return_value=5):
            result = validator.validate_and_prompt()

        assert result["workers"] == 5

    def test_static_root_must_be_absolute(self):
        """Static root must be an absolute path if provided."""
        config = {
            "project_name": "testproject",
            "project_path": os.getcwd(),
            "wsgi_module": "myapp.wsgi:application",
            "user": os.getenv("USER", "root"),
            "group": os.getenv("USER", "root"),
            "python_path": os.path.realpath(__import__("sys").executable),
            "server_ip": "_",
            "workers": 3,
            "static_root": "relative/path",  # Not absolute
            "media_root": None,
        }

        validator = ConfigValidator(config, no_confirm=True)

        with mock.patch("click.prompt", return_value="/absolute/path"):
            result = validator.validate_and_prompt()

        assert result["static_root"] == "/absolute/path"


class TestDisplaySummary:
    """Tests for the summary display."""

    def test_display_does_not_crash(self, valid_config):
        """Displaying the summary should not raise any exceptions."""
        validator = ConfigValidator(valid_config, no_confirm=True)
        validator.validate_and_prompt()
        # If we got here without an exception, the display worked
