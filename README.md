# Factory App

A Flask + SQLAlchemy application for factory operations (production, attendance, analytics).

## Quick setup

- Python: 3.12 (see `requirements.txt`)
- OS: Windows supported (PowerShell examples below)

### 1) Create & activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```powershell
pip install -r requirements.txt
```

### 3) Environment (optional overrides)

Create a `.env` file in project root for secrets and overrides (the app will also read normal OS env vars).

```
# Flask
SECRET_KEY=change_me

# Attendance device (override if different)
DEVICE_IP=10.0.0.5
DEVICE_USERNAME=admin
DEVICE_PASSWORD=your_password
DEVICE_TZ_OFFSET=+02:00
DEVICE_SCHEME=http
DEVICE_PORT=
DEVICE_CONNECT_TIMEOUT=5
DEVICE_READ_TIMEOUT=30
SYNC_LOOKBACK_DAYS=30
DEVICE_HTTP_AUTH=auto
SYNC_ALL_START=

# Attendance policy
NORMAL_WEEKLY_HOURS=40
CONSECUTIVE_IN_TO_OUT_MIN_MINUTES=240
USE_NIGHT_PLAN=0
```

### 4) Initialize the database (SQLite by default)

By default the app uses `factory.db` in the repo root (ignored by Git).

```powershell
# If using Alembic migrations, initialize/upgrade as needed (optional)
# flask db upgrade
```

### 5) Run the app

```powershell
set FLASK_APP=app.py
set FLASK_ENV=development
flask run
```

Open http://127.0.0.1:5000 in your browser.

## Working across PCs (GitHub)

1. Ensure `.gitignore` is present (local DB and caches are ignored).
2. Initialize Git and push to GitHub.

```powershell
git init
git add .
git commit -m "Initial commit"
# Create a repo on GitHub, then add the remote:
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

If you previously committed `factory.db` or other files now ignored, untrack them:

```powershell
git rm --cached factory.db
# If there are other tracked artifacts now ignored
# git rm --cached -r __pycache__

git commit -m "chore: stop tracking local db and caches"
git push
```

## Troubleshooting

- If PowerShell blocks activation scripts, allow running local scripts:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

- If the device sync credentials/IP differ per site, set them via `.env` or environment variables before running.

## Notes

- Migrations live under `migrations/`; do not commit local `factory.db`.
- Static exports or temp files should go under `exports/` or `tmp/` (gitignored).

### New PC quickstart (PowerShell)

```powershell
# 1) Clone your repo (replace with your URL)
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

# 2) Create venv and install deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3) (Optional) set env vars or create .env, then run
set FLASK_APP=app.py
set FLASK_ENV=development
flask run
```
