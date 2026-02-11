from __future__ import annotations

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_migrate import Migrate

# Flask extensions (initialized in app factory)
db = SQLAlchemy()
csrf = CSRFProtect()
migrate = Migrate()
login_manager = LoginManager()

# Login settings are applied in create_app()
