# Agent Prompt: Build `django-deploy-kit` Python Package

---

## 🎯 Mission

Build a production-grade Python package called **`django-deploy-kit`** that automatically generates and installs Gunicorn socket files, systemd service files, and Nginx configuration files for Django projects on Ubuntu/Debian Linux servers. The package must auto-detect all required values, handle every edge case gracefully, and be publishable to PyPI as open-source software.

---

## 📁 Phase 1 — Project Scaffolding

Set up the complete project structure exactly as follows:

```
django-deploy-kit/
├── django_deploy_kit/
│   ├── __init__.py
│   ├── cli.py                  # Entry point (Click-based CLI)
│   ├── detector.py             # Auto-detection logic
│   ├── validators.py           # Input validation & edge case handling
│   ├── generators/
│   │   ├── __init__.py
│   │   ├── socket.py           # .socket file generator
│   │   ├── service.py          # .service file generator
│   │   └── nginx.py            # nginx .conf generator
│   ├── installer.py            # Installer / setup engine
│   ├── rollback.py             # Rollback & cleanup on failure
│   ├── reporter.py             # Summary report & colored output
│   └── utils.py                # Shared utilities
├── tests/
│   ├── test_detector.py
│   ├── test_generators.py
│   ├── test_installer.py
│   └── test_validators.py
├── pyproject.toml
├── setup.cfg
├── README.md
├── LICENSE                     # MIT license
├── CHANGELOG.md
└── .github/
    └── workflows/
        └── publish.yml         # Auto-publish to PyPI on tag push
```

---

## 📦 Phase 2 — Dependencies & Packaging Config

Use `pyproject.toml` with `setuptools`. Required dependencies:

- `click` — CLI framework
- `rich` — colored terminal output and summary tables
- `jinja2` — template rendering for config files
- `psutil` — CPU core detection

Dev/test dependencies: `pytest`, `pytest-mock`, `coverage`.

Set the CLI entry point in `pyproject.toml`:

```toml
[project.scripts]
django-deploy = "django_deploy_kit.cli:main"
```

Minimum Python version: `3.8`. Target platforms: Linux only. Enforce this at runtime — raise a clear `SystemExit` with a message if run on Windows or macOS.

---

## 🔍 Phase 3 — Auto-Detector (`detector.py`)

This is the core intelligence of the package. Build a `ProjectDetector` class with methods to auto-detect each of the following. For every item, if detection fails or is ambiguous, store `None` and let the validator prompt the user. Never crash silently.

### Items to detect:

**1. Project name**
Use the basename of the current working directory. If the directory name contains spaces or special characters, sanitize it (replace with underscores, lowercase).

**2. Project path**
Resolve `os.getcwd()` to an absolute path. Check it exists and contains a `manage.py` file to confirm it is a Django project. If `manage.py` is not found, search one level up and one level down before giving up.

**3. WSGI module path**
Search `manage.py` for the `DJANGO_SETTINGS_MODULE` env var to find the settings module. From that, derive the wsgi path as `<settings_module_parent>.wsgi:application`. If not found, scan for any file named `wsgi.py` under the project directory and infer from its path.

**4. Current OS user**
`os.getenv('USER') or os.getenv('LOGNAME') or pwd.getpwuid(os.getuid()).pw_name`. Also detect the user's primary group with `grp.getgrgid(pwd.getpwuid(os.getuid()).pw_gid).gr_name`.

**5. Active Python interpreter path**
Use `sys.executable`. Verify it resolves to a real file. If inside a virtual environment (`sys.prefix != sys.base_prefix`), note this and use the venv Python path.

**6. Server IP address**
Try in order:
- (a) Parse `/etc/hosts` for a non-loopback entry
- (b) Use `socket.gethostbyname(socket.gethostname())`
- (c) Connect a UDP socket to `8.8.8.8:80` and read the local address with `sock.getsockname()[0]`

Fall back to `"_"` (Nginx catch-all) if all methods fail.

**7. CPU worker count**
`workers = (2 × cpu_count) + 1` using `psutil.cpu_count(logical=True)`. Cap at a maximum of 9. If `psutil` fails, default to 3.

**8. Static root**
Use `subprocess.run` to call `python manage.py diffsettings` and parse the output for `STATIC_ROOT`. Alternatively, use `importlib` to import the settings module directly and read `settings.STATIC_ROOT`. Handle `ImproperlyConfigured` exceptions. If `STATIC_ROOT` is not set, skip it in the Nginx config but warn the user.

**9. Media root**
Same approach as static root, using `MEDIA_ROOT`.

---

## ✅ Phase 4 — Validators & Interactive Prompting (`validators.py`)

Build a `ConfigValidator` class that takes the detected values and:

1. For each `None` or invalid value, prompts the user interactively using `click.prompt()` with a sensible default where possible.
2. Validates all values after input:
   - Project path must exist and be readable.
   - WSGI string must match the pattern `module.path:callable`.
   - Username must exist on the system (`pwd.getpwnam`).
   - Group must exist on the system (`grp.getgrnam`).
   - Python path must be executable (`os.access(path, os.X_OK)`).
   - IP must be a valid IPv4/IPv6 address or `"_"`.
   - Worker count must be an integer between 1 and 17.
   - Static/media root paths, if provided, must be absolute paths (they don't have to exist yet).
3. Display a confirmation table using `rich` showing all final values before proceeding. Ask the user `"Proceed with these settings? [Y/n]"`. If no, re-run the prompting flow.

---

## 📝 Phase 5 — Config Generators (`generators/`)

Use Jinja2 templates embedded as Python strings (not external files) for portability.

### `socket.py` — generate `/etc/systemd/system/<project_name>.socket`

```ini
[Unit]
Description=gunicorn socket for {{ project_name }}

[Socket]
ListenStream=/run/{{ project_name }}.sock

[Install]
WantedBy=sockets.target
```

### `service.py` — generate `/etc/systemd/system/<project_name>.service`

```ini
[Unit]
Description=gunicorn daemon for {{ project_name }}
Requires={{ project_name }}.socket
After=network.target

[Service]
User={{ user }}
Group={{ group }}
WorkingDirectory={{ project_path }}
ExecStart={{ python_path }} -m gunicorn \
          --access-logfile - \
          --workers {{ workers }} \
          --bind unix:/run/{{ project_name }}.sock \
          {{ wsgi_module }}

[Install]
WantedBy=multi-user.target
```

### `nginx.py` — generate `/etc/nginx/sites-available/<project_name>`

```nginx
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
```

> **Note:** `static_root_parent` is the parent directory of `STATIC_ROOT`. For example, if `STATIC_ROOT = /home/user/project/staticfiles`, then use `root /home/user/project;` so Nginx serves `/static/` correctly.

Each generator class must have a `generate() -> str` method and a `write(path: str)` method. The `write` method should raise `PermissionError` with a helpful message if writing fails due to permissions.

---

## ⚙️ Phase 6 — Installer (`installer.py`)

Build an `Installer` class that accepts a `dry_run=False` flag. In dry-run mode, print every command that would be run but do not execute anything.

Execute the following steps in order, wrapping each in a try/except that logs the error and triggers rollback:

1. Write the `.socket` file to `/etc/systemd/system/<project_name>.socket`
2. Write the `.service` file to `/etc/systemd/system/<project_name>.service`
3. Write the nginx config to `/etc/nginx/sites-available/<project_name>`
4. **Remove the default Nginx config** — if `/etc/nginx/sites-enabled/default` exists, delete or unlink it. If `/etc/nginx/sites-available/default` exists, also remove it. Before doing so, warn the user: `"The default Nginx config will be removed to prevent it from conflicting with your project. Press Ctrl+C to cancel."` Then pause for 3 seconds. In dry-run mode, only print that these files would be removed.
5. Create symlink: `/etc/nginx/sites-enabled/<project_name>` → `/etc/nginx/sites-available/<project_name>` (skip if already exists and points to the right target)
6. Run `systemctl daemon-reload`
7. Run `systemctl enable <project_name>.socket`
8. Run `systemctl start <project_name>.socket`
9. Run `systemctl enable <project_name>.service`
10. Run `nginx -t` to test the Nginx config — if this fails, abort and rollback
11. Run `systemctl reload nginx`

For each `subprocess.run` call, use `check=True` and capture both `stdout` and `stderr`. On failure, include the stderr output in the exception message.

Detect if the script is running as root using `os.geteuid() == 0`. If not root, prefix each system command with `sudo`. Before running any `sudo` command, check if `sudo` is available (`shutil.which('sudo')`). If not, raise a `RuntimeError` with a clear message.

---

## 🔄 Phase 7 — Rollback (`rollback.py`)

Build a `RollbackManager` class that maintains a list of "undo actions" as the installer proceeds. Register undo actions before executing each step. If any step fails, execute all registered undo actions in reverse order.

Undo actions to implement:
- Delete a file if it was created by this run
- Remove a symlink if it was created by this run
- **Restore the default Nginx config** if it was removed by this run — keep a backup copy in a temp directory before deleting, and restore it during rollback
- Run `systemctl stop` and `systemctl disable` for services/sockets that were started
- Run `systemctl daemon-reload` after undoing service files
- Run `nginx -t && systemctl reload nginx` after removing nginx config

Wrap all rollback actions in individual try/except blocks so one failing rollback step does not prevent the others from running.

---

## 📊 Phase 8 — Reporter (`reporter.py`)

Use `rich` to produce:

1. A pre-run **settings table** with two columns: "Setting" and "Detected Value". Color-code rows: green for auto-detected, yellow for user-provided, red for missing/default fallback.
2. A post-run **results table** showing each step (file written, command run) with a status column: ✓ success, ✗ failed, ⚠ skipped.
3. On success, print a final green panel:
   > `"✓ Deployment config for <project_name> is ready. Your Django project should now be served by Gunicorn + Nginx."`

   Include instructions for verifying with `systemctl status <project_name>`.
4. On failure, print a red panel with the error, the step that failed, and the rollback status.

---

## 🖥️ Phase 9 — CLI (`cli.py`)

Build the CLI using Click with the following commands:

```
django-deploy setup              # Full interactive setup (default command)
django-deploy setup --dry-run    # Show what would be done without doing it
django-deploy detect             # Just run detection and print results, no install
django-deploy generate           # Generate files to current directory without installing
django-deploy rollback           # Rollback the last install for a given project
```

Global options:
- `--project-path PATH` — override the detected project path
- `--project-name NAME` — override the detected project name
- `--no-confirm` — skip the confirmation prompt (for use in scripts/CI)
- `--verbose / --no-verbose` — show or hide detailed output

---

## 🧪 Phase 10 — Tests

Write `pytest` tests covering:

**`test_detector.py`**
Mock the filesystem and `subprocess`. Test each detection method individually. Test that `None` is returned cleanly when detection fails (no exceptions).

**`test_generators.py`**
For each generator, call `generate()` with known inputs and assert the output string contains the expected values. Test with and without static/media root. Test that the Nginx template omits static/media blocks when those values are not provided.

**`test_installer.py`**
Use `mock.patch` on `subprocess.run` and file I/O. Test that dry-run mode never calls `subprocess.run`. Test that rollback is triggered on step failure. Test that the default Nginx config removal step warns the user and pauses. Test that the backup-and-restore of the default Nginx config works correctly during rollback.

**`test_validators.py`**
Test that invalid inputs are rejected, valid inputs pass, and that `None` values trigger prompts.

Aim for at least 80% code coverage.

---

## 📖 Phase 11 — Documentation

Write a complete `README.md` with these sections:

1. **What it does** — one paragraph overview
2. **Requirements** — Ubuntu/Debian, Python 3.8+, Django project with `manage.py`, Gunicorn installed in the project's virtualenv
3. **Installation** — `pip install django-deploy-kit`
4. **Quick start** — `cd /path/to/django/project && django-deploy setup`
5. **What gets auto-detected** — a table of every detected value with the method used
6. **Dry-run mode** — example output
7. **Manual overrides** — all CLI flags
8. **Generated file examples** — show sample `.socket`, `.service`, and `.conf` outputs
9. **Default Nginx config removal** — explain why the default config is removed and how the backup/rollback works
10. **Rollback** — how it works
11. **Contributing** — how to clone, install dev deps, run tests
12. **License** — MIT

---

## 🚀 Phase 12 — PyPI Publishing Setup

1. Configure `pyproject.toml` with all required metadata: `name`, `version`, `description`, `author`, `license = "MIT"`, `classifiers` (including `"Operating System :: POSIX :: Linux"`, `"Environment :: Console"`, `"Framework :: Django"`), `keywords`, `project URLs` for homepage and issues.

2. Create `.github/workflows/publish.yml` that triggers on `push` to tags matching `v*`, builds the package with `python -m build`, and publishes to PyPI using `twine` with a secret `PYPI_API_TOKEN`.

3. Create a `CHANGELOG.md` starting with `## [0.1.0] - Initial release`.

4. Add a `Makefile` with targets: `install-dev`, `test`, `coverage`, `build`, `publish-test` (to TestPyPI), `publish`.

---

## 🛡️ Edge Cases to Handle Explicitly

Ensure the code handles all of the following without crashing, instead giving a clear, actionable error message:

- Running outside a Django project directory
- `manage.py` present but Django not installed
- Multiple virtual environments detected
- `STATIC_ROOT` / `MEDIA_ROOT` not configured in settings
- Nginx not installed on the system
- Systemd not available (e.g., running inside Docker — detect via `os.path.exists('/run/systemd/system')` and warn)
- Files already exist at the target paths — ask the user whether to overwrite
- Symlink at `/etc/nginx/sites-enabled/<name>` already exists but points elsewhere
- `/etc/nginx/sites-enabled/default` does not exist — skip the removal step silently without error
- `/etc/nginx/sites-available/default` does not exist — skip silently
- Default Nginx config removal fails due to permissions — catch the error and advise the user to remove it manually with the exact command to run
- Running as a non-sudo, non-root user — detect early and warn before attempting writes
- Project name contains characters invalid in filenames or systemd unit names
- Python path points to system Python instead of a virtualenv — warn the user
- CPU count returns `None` — fall back to 3 workers
- `gunicorn` not found in the detected Python environment — warn but continue

---

## ✅ Definition of Done

The package is complete when:

- `pip install django-deploy-kit` works from TestPyPI
- Running `django-deploy setup` in a real Django project directory on Ubuntu correctly generates all three config files, removes the default Nginx config, installs and symlinks the generated configs, and starts the services
- `django-deploy setup --dry-run` prints every action without making any changes
- All tests pass with `pytest` and coverage is above 80%
- `README.md` is complete and accurate
- The GitHub Actions workflow successfully publishes to PyPI on a version tag push
