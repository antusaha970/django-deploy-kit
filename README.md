# django-deploy-kit

**Auto-generate and install Gunicorn & Nginx configuration for Django projects on Ubuntu/Debian.**

`django-deploy-kit` detects your Django project's configuration, generates production-ready systemd service/socket files and Nginx server blocks, and installs them — all with a single command. It handles edge cases gracefully, supports dry-run mode, and includes full rollback on failure.

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
pip install django-deploy-kit
```

Or install from source:

```bash
git clone https://github.com/antusaha970/django-deploy-kit.git
cd django-deploy-kit
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

## Dry-Run Mode

Preview everything that would happen without making any changes:

```bash
django-deploy setup --dry-run
```

Example output:

```
🚀 django-deploy-kit — Setup

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

---

## Default Nginx Config Removal

During installation, `django-deploy-kit` removes the default Nginx configuration files:

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

If any installation step fails, `django-deploy-kit` automatically rolls back all changes:

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

```bash
# Clone the repository
git clone https://github.com/django-deploy-kit/django-deploy-kit.git
cd django-deploy-kit

# Install dev dependencies
make install-dev

# Run tests
make test

# Run tests with coverage
make coverage
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
