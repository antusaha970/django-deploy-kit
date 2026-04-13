# django-deploy-toolkit

**Auto-generate and install Gunicorn, Nginx, Celery & Celery Beat configuration for Django projects on Ubuntu/Debian.**

`django-deploy-toolkit` detects your Django project's configuration, generates production-ready systemd service/socket files and Nginx server blocks, and installs them — all with a single command. It handles edge cases gracefully, supports dry-run mode, and includes full rollback on failure.

---

## Created By

**Antu Saha** — creator and lead maintainer of this package.

We also appreciate all the open-source contributors who help improve `django-deploy-toolkit`. Contributions of any kind are welcome — bug reports, feature requests, documentation improvements, and code contributions. See the [Contributing](#contributing) section below to get started.

---

## Requirements

- **OS:** Ubuntu / Debian Linux
- **Python:** 3.8 or higher
- **Django project** with a `manage.py` file
- **Gunicorn** installed in the project's virtual environment
- **Nginx** installed on the server (`sudo apt install nginx`)
- **systemd** available (standard on Ubuntu/Debian)

---

## Installation

```bash
pip install django-deploy-toolkit
```

Or install from source:

```bash
git clone https://github.com/antusaha970/django-deploy-toolkit.git
cd django-deploy-toolkit
pip install -e .
```

---

## Quick Start

```bash
# Navigate to your Django project root (where manage.py lives)
cd /path/to/your/django/project

# Activate your project's virtual environment
source venv/bin/activate

# Run the setup
django-deploy setup
```

That's it. The tool will:
1. Auto-detect your project configuration
2. Show you what it found and ask for confirmation
3. Generate and install the config files
4. Enable and start the services
5. Test and reload Nginx
6. **Detect Celery** — if Celery is installed, it hints you to run `django-deploy celery-setup`

---

## What Gets Auto-Detected

| Setting | Detection Method |
|---------|-----------------|
| **Project Name** | Basename of the current directory (sanitized) |
| **Project Path** | Current working directory (searches for `manage.py`) |
| **WSGI Module** | Parsed from `manage.py` → `DJANGO_SETTINGS_MODULE`, or scans for `wsgi.py` |
| **User** | `$USER` env var → `$LOGNAME` → `pwd.getpwuid()` |
| **Group** | Primary group of the detected user via `grp.getgrgid()` |
| **Python Path** | `sys.executable` (virtualenv-aware) |
| **Server IP** | `/etc/hosts` → `socket.gethostbyname()` → UDP socket trick → `_` (catch-all) |
| **Workers** | `(2 × CPU cores) + 1`, capped at 9 (via `psutil`) |
| **Static Root** | Parsed from `python manage.py diffsettings` output |
| **Media Root** | Same as Static Root |

---

## Celery & Celery Beat Support

`django-deploy-toolkit` can also generate and install systemd service files for **Celery worker** and **Celery Beat** — keeping your background task infrastructure managed by systemd alongside Gunicorn.

### What Gets Detected (Celery)

| Check | Detection Method |
|-------|-----------------|
| **Celery installed** | `python -c "import celery"` using the project's Python |
| **Celery app module** | Scans for `celery.py` in project packages, or `Celery(...)` instantiation |
| **Celery Beat enabled** | `CELERY_BEAT_SCHEDULE` in settings, or `django_celery_beat` in `INSTALLED_APPS` |
| **Broker URL** | `CELERY_BROKER_URL` / `BROKER_URL` from Django settings |
| **Redis installed** | `redis-server` or `redis-cli` on `$PATH` |

### Celery Quick Start

```bash
# After running django-deploy setup (or standalone):
django-deploy celery-setup
```

The tool will:
1. Auto-detect your Celery configuration
2. Show you a summary and ask for confirmation
3. Generate systemd service files for Celery worker (and Beat if detected)
4. Install, enable, and start the services
5. Remind you to adjust the worker concurrency (defaults to **1**)

### Celery CLI Options

```bash
django-deploy celery-setup [OPTIONS]

Options:
  --dry-run              Show what would be done without doing it
  --verbose / --no-verbose  Show or hide detailed output
  --no-confirm           Skip the confirmation prompt
  --help                 Show this message and exit
```

### Edge Cases Handled

- **Redis not installed locally** — If your broker URL uses `redis://` but `redis-server` isn't found, a warning is shown. This is non-blocking because Redis may run on a remote host.
- **Celery without Beat** — Only the worker service is generated.
- **Beat with `django_celery_beat`** — The `--scheduler django_celery_beat.schedulers:DatabaseScheduler` flag is automatically added to the Beat service.
- **No Celery found** — A helpful message is shown and the command exits cleanly.
- **Celery app module not found** — The user is prompted to enter it manually.

---

## Dry-Run Mode

Preview everything that would happen without making any changes:

```bash
django-deploy setup --dry-run
django-deploy celery-setup --dry-run
```

Example output:

```
🚀 django-deploy-toolkit — Setup

  [DRY RUN] Would write: /etc/systemd/system/myproject.socket
  [DRY RUN] Would write: /etc/systemd/system/myproject.service
  [DRY RUN] Would write: /etc/nginx/sites-available/myproject
  [DRY RUN] Would remove: /etc/nginx/sites-enabled/default
  [DRY RUN] Would remove: /etc/nginx/sites-available/default
  [DRY RUN] Would create symlink: /etc/nginx/sites-enabled/myproject -> /etc/nginx/sites-available/myproject
  [DRY RUN] Would run: systemctl daemon-reload
  [DRY RUN] Would run: systemctl enable myproject.socket
  [DRY RUN] Would run: systemctl start myproject.socket
  [DRY RUN] Would run: systemctl enable myproject.service
  [DRY RUN] Would run: nginx -t
  [DRY RUN] Would run: systemctl reload nginx
```

---

## Manual Overrides

All CLI flags:

```bash
django-deploy setup [OPTIONS]

Options:
  --dry-run              Show what would be done without doing it
  --project-path PATH    Override the detected project path
  --project-name NAME    Override the detected project name
  --no-confirm           Skip the confirmation prompt (for scripts/CI)
  --verbose / --no-verbose  Show or hide detailed output
  --version              Show version and exit
  --help                 Show this message and exit
```

Other commands:

```bash
django-deploy detect             # Just run detection, no install
django-deploy generate           # Generate files to current directory
django-deploy generate --output-dir ./configs  # Generate to a specific directory
django-deploy rollback --name myproject        # Rollback a previous install
django-deploy celery-setup       # Generate and install Celery systemd services
django-deploy celery-setup --dry-run  # Preview Celery setup
```

---

## Generated File Examples

### Gunicorn Socket (`/etc/systemd/system/myproject.socket`)

```ini
[Unit]
Description=gunicorn socket for myproject

[Socket]
ListenStream=/run/myproject.sock

[Install]
WantedBy=sockets.target
```

### Gunicorn Service (`/etc/systemd/system/myproject.service`)

```ini
[Unit]
Description=gunicorn daemon for myproject
Requires=myproject.socket
After=network.target

[Service]
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/myproject
ExecStart=/home/deploy/myproject/venv/bin/python -m gunicorn \
          --access-logfile - \
          --workers 5 \
          --bind unix:/run/myproject.sock \
          myproject.wsgi:application

[Install]
WantedBy=multi-user.target
```

### Nginx Config (`/etc/nginx/sites-available/myproject`)

```nginx
server {
    listen 80;
    server_name 192.168.1.100;

    location /static/ {
        root /home/deploy/myproject;
    }

    location /media/ {
        root /home/deploy/myproject;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/myproject.sock;
    }
}
```

### Celery Worker (`/etc/systemd/system/myproject-celery.service`)

```ini
[Unit]
Description=Celery Worker for myproject
After=network.target

[Service]
Type=forking
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/myproject
ExecStart=/home/deploy/myproject/venv/bin/python -m celery -A myproject.celery worker \
          --loglevel=info \
          --concurrency=1 \
          --pidfile=/run/celery/myproject-worker.pid \
          --logfile=/var/log/celery/myproject-worker.log
ExecStop=/bin/kill -s TERM $MAINPID
RuntimeDirectory=celery
Restart=always

[Install]
WantedBy=multi-user.target
```

### Celery Beat (`/etc/systemd/system/myproject-celerybeat.service`)

```ini
[Unit]
Description=Celery Beat Scheduler for myproject
After=network.target

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/myproject
ExecStart=/home/deploy/myproject/venv/bin/python -m celery -A myproject.celery beat \
          --loglevel=info \
          --pidfile=/run/celery/myproject-beat.pid \
          --logfile=/var/log/celery/myproject-beat.log \
          --scheduler django_celery_beat.schedulers:DatabaseScheduler
ExecStop=/bin/kill -s TERM $MAINPID
RuntimeDirectory=celery
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Default Nginx Config Removal

During installation, `django-deploy-toolkit` removes the default Nginx configuration files:

- `/etc/nginx/sites-enabled/default`
- `/etc/nginx/sites-available/default`

**Why?** The default Nginx config listens on port 80 and can conflict with your project's server block. Removing it ensures your Django project is the one handling requests.

**Safety measures:**
- Both files are backed up to a temporary directory before deletion
- The tool warns you and pauses for 3 seconds before proceeding (press Ctrl+C to cancel)
- If you skip if they don't exist — no error
- During rollback, the backed-up files are restored to their original locations

---

## Rollback

If any installation step fails, `django-deploy-toolkit` automatically rolls back all changes:

1. Files created during the run are deleted
2. Symlinks created during the run are removed
3. The default Nginx config is restored from backup (if it was removed)
4. Services that were started are stopped and disabled
5. Systemd daemon is reloaded
6. Nginx config is tested and reloaded

You can also manually rollback a previous installation:

```bash
django-deploy rollback --name myproject
```

---

## Contributing

Contributions are welcome! Whether it's a bug fix, new feature, or documentation improvement — all help is appreciated.

```bash
# Clone the repository
git clone https://github.com/antusaha970/django-deploy-toolkit.git
cd django-deploy-toolkit

# Install dev dependencies
make install-dev

# Run tests
make test

# Run tests with coverage
make coverage
```

---

## Credits

- **Antu Saha** — Creator and lead maintainer
- All open-source contributors — Thank you for helping make this project better! 🙏

---

## License

MIT — see [LICENSE](LICENSE) for details.
