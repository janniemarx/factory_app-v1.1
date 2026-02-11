# Factory App v2 (Side-by-side Rewrite)

This is a clean, simplified rewrite that lives alongside your existing app. It uses a fresh database and a minimal architecture so you can iterate without disturbing the current system.

## Goals
- Simplify schema and code paths.
- Keep the old app running while we build v2.
- Provide a safe migration path for data.

## Stack
- Flask + Flask-SQLAlchemy + Flask-Migrate
- SQLAlchemy 2.x
- Waitress for Windows-friendly serving

## Layout
```
v2/
  app.py            # Flask app factory and extensions
  config.py         # Config (uses V2_DATABASE_URL)
  wsgi_v2.py        # WSGI entrypoint
  requirements.txt  # Minimal deps for v2
  models/           # Simplified schema
  api/routes.py     # Minimal API (health + you add features)
  etl/migrate_v1_to_v2.py  # Baseline ETL script
```

## Run (Windows PowerShell)
```powershell
# Create/activate a venv if you wish
python -m venv .venv; .\.venv\Scripts\Activate.ps1

# Install v2-only deps
pip install -r v2\requirements.txt

# Set DB to a new file (optional)
$env:V2_DATABASE_URL = "sqlite:///factory_v2.db"

# Initialize tables (first run only)
python -c "from v2.app import create_app, db; app=create_app();\nimport contextlib;\nwith app.app_context(): db.create_all(); print('v2 DB initialized')"

# Serve v2 on a different port so v1 remains intact
waitress-serve --host=0.0.0.0 --port=8081 v2.wsgi_v2:app
```

## Migration plan
1. Finalize the v2 schema (start small: Operators, Profiles, Machines, PreExpansion, BlockSession, Block, WireCuttingSession).
2. Run the baseline ETL to copy Operators and Profiles:
   ```powershell
   python v2\etl\migrate_v1_to_v2.py
   ```
3. Extend ETL for other entities. Migrate in phases, validating each module.
4. Keep v1 read-only during migration windows if needed; once confident, switch production to v2.

## Coexistence
- v1 keeps using `factory.db` and its own WSGI (`wsgi.py`).
- v2 uses `factory_v2.db` by default and runs on a separate port via `v2/wsgi_v2.py`.
- You can gradually rebuild features in v2 with cleaner flows while v1 continues serving users.

## Next steps
- Add blueprints/routes for the production modules you want to simplify first.
- Implement authentication with Flask-Login (v2 has the extension configured).
- Add Alembic/Flask-Migrate commands and proper migrations once the schema stabilizes.
- Write small tests for new modules to keep v2 clean.
