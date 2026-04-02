# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-02

### Added

- Initial release
- Auto-detection of Django project configuration:
  - Project name and path
  - WSGI module path
  - OS user and group
  - Python interpreter path (virtualenv-aware)
  - Server IP address
  - CPU-based Gunicorn worker count
  - STATIC_ROOT and MEDIA_ROOT from Django settings
- Jinja2-based config generators:
  - Gunicorn systemd socket file
  - Gunicorn systemd service file
  - Nginx server block configuration
- Interactive validation with sensible defaults
- Full installer with:
  - Automatic file placement in system directories
  - Default Nginx config removal with backup
  - Service enabling and starting
  - Nginx config testing before reload
- Rollback support on installation failure
- Dry-run mode to preview all actions
- `detect` command for read-only detection
- `generate` command for local file generation
- `rollback` command for manual cleanup
- Rich colored terminal output with summary tables
- Comprehensive edge case handling
