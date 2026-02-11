# Deployment on Windows (Production-only modules)

This guide gets the app running on another Windows PC to capture production for cornices, blocks, cutting, etc., while hiding Attendance and most Analytics.

## Prerequisites

- Windows 10/11
- Python 3.12 (same as dev PC). Install from python.org.
- Admin rights (optional) for installing Python system-wide.

## 1) Copy the project

- Option A: Zip `d:\factory_app` and copy to the target PC, then unzip to a path like `C:\factory_app`.
- Option B: Use `git clone` if you have Git set up.

## 2) Create a virtual environment

Open Windows PowerShell in the project folder and run:

```powershell
# Create and activate venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

## 3) Configure environment

Set feature flags to hide Attendance and Analytics (recommended for production-only use):

```powershell
# Hide attendance & analytics modules
$env:FEATURE_ATTENDANCE = "0"
$env:FEATURE_ANALYTICS  = "0"

# Set a strong secret key
$env:SECRET_KEY = "replace-with-a-strong-random-string"

# Optional: Device timezone offset for UI
$env:DEVICE_TZ_OFFSET = "+02:00"
```

If you want to use a different database path, edit `config.py` or set `SQLALCHEMY_DATABASE_URI` accordingly.

## 4) Initialize the database (fresh machine)

Use Alembic/Flask-Migrate to create tables:

```powershell
# Ensure venv is active
.\.venv\Scripts\Activate.ps1

# Run migrations
python -m flask --app app:create_app db upgrade
```

If you already have a `factory.db` you want to reuse, copy it into the project root and skip this step.

## 5) Run with a production server (waitress)

We included a `wsgi.py` entrypoint.

```powershell
# Start server on port 8000
python -m waitress --listen=*:8000 wsgi:app
```

Visit `http://<target-pc-ip>:8000/` from the tablet or local browser.

### Allow access from other PCs (Windows Firewall)

On the machine running the app, open an **elevated** PowerShell and allow inbound TCP 8000:

```powershell
New-NetFirewallRule -DisplayName "Factory App (TCP 8000)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000
```

If you changed the port, update `-LocalPort` accordingly.

### Helper script (optional)

You can also start the server with:

```powershell
./scripts/run_waitress.ps1 -Port 8000
```

This binds to `0.0.0.0` (all interfaces) so it’s reachable on your LAN.

### Viewing from *outside* your network (internet)

Do **not** expose the app directly to the public internet without protection.

Safer options:

- Use a VPN (recommended): Tailscale / WireGuard, then browse to `http://<vpn-ip>:8000/`.
- Use a tunnel service (e.g. Cloudflare Tunnel) and require authentication.

If you must port-forward, add HTTPS (reverse proxy) + strong auth, and restrict by IP.

## 6) Optional: Auto-start script

Create a shortcut or a scheduled task that runs the command above on login. Make sure it points to the venv `python.exe` and the working directory is the project folder.

## Notes

- Attendance and analytics sections are gated by the feature flags above. You can enable later with `$env:FEATURE_ATTENDANCE = "1"` and `$env:FEATURE_ANALYTICS = "1"`.
- For moulded sessions: once started, the batch is marked as used and won’t appear again in the start list. Active sessions also have their own page.
- For blocks: leftovers are now computed robustly and prompts are shown when finishing a session.

## Troubleshooting

- If migrations complain about the app import, use the explicit `--app` flag as shown above.
- If port 8000 is in use, change `--listen=*:9000` and browse `http://<target-pc-ip>:9000/`.
- If you see CSRF errors, ensure your browser has cookies enabled and your system time is correct.
