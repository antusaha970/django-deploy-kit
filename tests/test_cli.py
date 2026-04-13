"""Tests for the CLI module."""

from unittest import mock

from click.testing import CliRunner

from django_deploy_toolkit.cli import main


class TestCLIHelp:
    """Tests for CLI help and version."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "django-deploy-toolkit" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output

    def test_no_subcommand_shows_help(self):
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert "django-deploy-toolkit" in result.output


class TestDetectCommand:
    """Tests for the detect command."""

    @mock.patch("django_deploy_toolkit.cli.check_platform")
    @mock.patch("django_deploy_toolkit.cli.Reporter")
    @mock.patch("django_deploy_toolkit.cli.ProjectDetector")
    def test_detect_runs(self, mock_detector_cls, mock_reporter_cls, mock_platform):
        mock_detector = mock.MagicMock()
        mock_detector.detect_all.return_value = {
            "project_name": "test",
            "project_path": "/tmp/test",
            "wsgi_module": "test.wsgi:application",
            "user": "deploy",
            "group": "deploy",
            "python_path": "/usr/bin/python3",
            "server_ip": "_",
            "workers": 3,
            "static_root": None,
            "media_root": None,
        }
        mock_detector_cls.return_value = mock_detector

        mock_reporter = mock.MagicMock()
        mock_reporter_cls.return_value = mock_reporter

        runner = CliRunner()
        result = runner.invoke(main, ["detect"])
        assert result.exit_code == 0
        mock_reporter.print_detection_results.assert_called_once()


class TestGenerateCommand:
    """Tests for the generate command."""

    @mock.patch("django_deploy_toolkit.cli.check_platform")
    @mock.patch("django_deploy_toolkit.cli.ConfigValidator")
    @mock.patch("django_deploy_toolkit.cli.ProjectDetector")
    def test_generate_creates_files(self, mock_detector_cls, mock_validator_cls, mock_platform, tmp_path):
        config = {
            "project_name": "test",
            "project_path": "/tmp/test",
            "wsgi_module": "test.wsgi:application",
            "user": "deploy",
            "group": "deploy",
            "python_path": "/usr/bin/python3",
            "server_ip": "_",
            "workers": 3,
            "static_root": None,
            "media_root": None,
        }

        mock_detector = mock.MagicMock()
        mock_detector.detect_all.return_value = config
        mock_detector_cls.return_value = mock_detector

        mock_validator = mock.MagicMock()
        mock_validator.validate_and_prompt.return_value = config
        mock_validator_cls.return_value = mock_validator

        runner = CliRunner()
        result = runner.invoke(main, ["generate", "--output-dir", str(tmp_path)])
        assert result.exit_code == 0

        import os
        files = os.listdir(str(tmp_path))
        assert "test.socket" in files
        assert "test.service" in files
        assert "test.nginx.conf" in files


class TestSetupCommand:
    """Tests for the setup command."""

    @mock.patch("django_deploy_toolkit.cli.check_platform")
    @mock.patch("django_deploy_toolkit.cli.Installer")
    @mock.patch("django_deploy_toolkit.cli.ConfigValidator")
    @mock.patch("django_deploy_toolkit.cli.ProjectDetector")
    @mock.patch("django_deploy_toolkit.cli.check_systemd_available", return_value=True)
    @mock.patch("django_deploy_toolkit.cli.check_nginx_installed", return_value=True)
    @mock.patch("django_deploy_toolkit.cli.check_gunicorn_installed", return_value=True)
    def test_setup_dry_run(
        self, mock_gunicorn, mock_nginx, mock_systemd,
        mock_detector_cls, mock_validator_cls, mock_installer_cls, mock_platform
    ):
        config = {
            "project_name": "test",
            "project_path": "/tmp/test",
            "wsgi_module": "test.wsgi:application",
            "user": "deploy",
            "group": "deploy",
            "python_path": "/usr/bin/python3",
            "server_ip": "_",
            "workers": 3,
            "static_root": None,
            "media_root": None,
        }

        mock_detector = mock.MagicMock()
        mock_detector.detect_all.return_value = config
        mock_detector.is_virtualenv.return_value = True
        mock_detector_cls.return_value = mock_detector

        mock_validator = mock.MagicMock()
        mock_validator.validate_and_prompt.return_value = config
        mock_validator.get_sources.return_value = {k: "auto" for k in config}
        mock_validator_cls.return_value = mock_validator

        mock_installer = mock.MagicMock()
        mock_installer.install.return_value = [
            ("Write socket file", "success", "Dry run"),
        ]
        mock_installer_cls.return_value = mock_installer

        runner = CliRunner()
        result = runner.invoke(main, ["--no-confirm", "setup", "--dry-run"])
        assert result.exit_code == 0

    @mock.patch("django_deploy_toolkit.cli.check_platform")
    @mock.patch("django_deploy_toolkit.cli.Installer")
    @mock.patch("django_deploy_toolkit.cli.ConfigValidator")
    @mock.patch("django_deploy_toolkit.cli.ProjectDetector")
    @mock.patch("django_deploy_toolkit.cli.check_systemd_available", return_value=False)
    @mock.patch("django_deploy_toolkit.cli.check_nginx_installed", return_value=False)
    @mock.patch("django_deploy_toolkit.cli.check_gunicorn_installed", return_value=True)
    def test_setup_with_warnings(
        self, mock_gunicorn, mock_nginx, mock_systemd,
        mock_detector_cls, mock_validator_cls, mock_installer_cls, mock_platform
    ):
        config = {
            "project_name": "test",
            "project_path": "/tmp/test",
            "wsgi_module": "test.wsgi:application",
            "user": "deploy",
            "group": "deploy",
            "python_path": "/usr/bin/python3",
            "server_ip": "_",
            "workers": 3,
            "static_root": None,
            "media_root": None,
        }

        mock_detector = mock.MagicMock()
        mock_detector.detect_all.return_value = config
        mock_detector.is_virtualenv.return_value = True
        mock_detector_cls.return_value = mock_detector

        mock_validator = mock.MagicMock()
        mock_validator.validate_and_prompt.return_value = config
        mock_validator.get_sources.return_value = {k: "auto" for k in config}
        mock_validator_cls.return_value = mock_validator

        mock_installer = mock.MagicMock()
        mock_installer.install.return_value = [
            ("Write socket file", "success", "Done"),
        ]
        mock_installer_cls.return_value = mock_installer

        runner = CliRunner()
        result = runner.invoke(main, ["--no-confirm", "setup", "--dry-run"])
        assert result.exit_code == 0


class TestRollbackCommand:
    """Tests for the rollback command."""

    @mock.patch("django_deploy_toolkit.cli.check_platform")
    @mock.patch("os.path.exists", return_value=False)
    @mock.patch("os.path.islink", return_value=False)
    def test_rollback_no_files(self, mock_islink, mock_exists, mock_platform):
        runner = CliRunner()
        result = runner.invoke(main, ["rollback", "--name", "nonexistent"])
        assert result.exit_code == 0
        assert "No deployment files found" in result.output
