"""Tests for the Reporter class."""

from unittest import mock

from rich.console import Console

from django_deploy_kit.reporter import Reporter


def _make_config():
    return {
        "project_name": "testproject",
        "project_path": "/home/deploy/testproject",
        "wsgi_module": "testproject.wsgi:application",
        "user": "deploy",
        "group": "deploy",
        "python_path": "/home/deploy/testproject/venv/bin/python",
        "server_ip": "192.168.1.1",
        "workers": 3,
        "static_root": "/home/deploy/testproject/staticfiles",
        "media_root": None,
    }


def _make_sources():
    return {
        "project_name": "auto",
        "project_path": "auto",
        "wsgi_module": "auto",
        "user": "auto",
        "group": "auto",
        "python_path": "auto",
        "server_ip": "auto",
        "workers": "auto",
        "static_root": "auto",
        "media_root": "missing",
    }


class TestReporterSettingsTable:
    """Tests for the settings table display."""

    def test_print_settings_table_no_crash(self):
        reporter = Reporter(_make_config(), _make_sources())
        reporter.print_settings_table()

    def test_print_settings_with_user_sources(self):
        sources = _make_sources()
        sources["server_ip"] = "user"
        reporter = Reporter(_make_config(), sources)
        reporter.print_settings_table()

    def test_print_settings_with_missing_sources(self):
        sources = _make_sources()
        sources["static_root"] = "missing"
        config = _make_config()
        config["static_root"] = None
        reporter = Reporter(config, sources)
        reporter.print_settings_table()

    def test_print_settings_with_no_sources(self):
        reporter = Reporter(_make_config())
        reporter.print_settings_table()


class TestReporterResultsTable:
    """Tests for the results table display."""

    def test_print_results_no_crash(self):
        reporter = Reporter(_make_config())
        results = [
            ("Write socket file", "success", "Written to /etc/systemd/system/test.socket"),
            ("Write service file", "success", "Written"),
            ("Test Nginx", "failed", "Config error"),
            ("Create symlink", "skipped", "Already exists"),
        ]
        reporter.print_results_table(results)

    def test_empty_results(self):
        reporter = Reporter(_make_config())
        reporter.print_results_table([])


class TestReporterPanels:
    """Tests for success and failure panels."""

    def test_print_success_no_crash(self):
        reporter = Reporter(_make_config())
        reporter.print_success()

    def test_print_failure_no_crash(self):
        reporter = Reporter(_make_config())
        reporter.print_failure(
            error="Permission denied",
            failed_step="Write socket file",
            rollback_performed=True,
        )

    def test_print_failure_no_rollback(self):
        reporter = Reporter(_make_config())
        reporter.print_failure(
            error="Permission denied",
            failed_step="Write socket file",
            rollback_performed=False,
        )

    def test_print_dry_run_header_no_crash(self):
        reporter = Reporter(_make_config())
        reporter.print_dry_run_header()


class TestReporterDetection:
    """Tests for detection results display."""

    @mock.patch("django_deploy_kit.utils.check_gunicorn_installed", return_value=True)
    @mock.patch("django_deploy_kit.utils.check_nginx_installed", return_value=True)
    @mock.patch("django_deploy_kit.utils.check_systemd_available", return_value=True)
    def test_print_detection_results_all_good(self, mock_sd, mock_nginx, mock_gunicorn):
        reporter = Reporter(_make_config(), _make_sources())
        reporter.print_detection_results()

    @mock.patch("django_deploy_kit.utils.check_gunicorn_installed", return_value=False)
    @mock.patch("django_deploy_kit.utils.check_nginx_installed", return_value=False)
    @mock.patch("django_deploy_kit.utils.check_systemd_available", return_value=False)
    def test_print_detection_results_all_missing(self, mock_sd, mock_nginx, mock_gunicorn):
        reporter = Reporter(_make_config(), _make_sources())
        reporter.print_detection_results()
