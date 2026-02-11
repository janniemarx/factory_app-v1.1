from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

# Global extensions
# Note: Using Flask-SQLAlchemy for simplicity in v2
# (v1 uses a plain SQLAlchemy session via models.db)
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object('v2.config.Config')

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Import models to register metadata with SQLAlchemy
    from v2.models import operator, profile, machine, pre_expansion, block, cutting  # noqa: F401

    # Register a minimal API blueprint
    from v2.api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.route('/')
    def index():
        return {
            "app": "Factory v2",
            "status": "ok",
            "message": "Welcome to the simplified API."
        }

    return app
