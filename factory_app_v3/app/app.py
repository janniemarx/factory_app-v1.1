from __future__ import annotations

from datetime import timedelta
import os
import sys

from flask import Flask, render_template
from flask_wtf.csrf import generate_csrf

from .config import Config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_object: type[Config] = Config) -> Flask:
    """Create the production-only Flask app.

    Contract:
    - Registers ONLY production + QC blueprints.
    - Does NOT import or register attendance in any way.
    """

    # Ensure legacy modules (models/, blueprints/, templates/, static/) are importable
    # when running from within the factory_app_v3 folder.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    app = Flask(__name__, template_folder="../../templates", static_folder="../../static")
    app.config.from_object(config_object)

    # Extensions
    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # User loader: we reuse the legacy Operator model for now.
    # This keeps database compatibility while we refactor structure.
    from models.operator import Operator  # legacy model

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return Operator.query.get(int(user_id))
        except Exception:
            return None

    # ---- Register blueprints (production + QC only) ----
    # Auth is still needed for login_required / sessions.
    from .domains.auth.routes import auth_bp

    from .domains.pre_expansion.routes import pre_expansion_bp
    from .domains.blocks.routes import blocks_bp
    from .domains.cutting.routes import cutting_bp
    from .domains.extrusion.routes import extrusion_bp
    from .domains.moulding.routes import moulding_bp
    from .domains.boxing.routes import boxing_bp
    from .domains.pr16.routes import pr16_bp
    from .domains.qc.routes import qc_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")

    app.register_blueprint(pre_expansion_bp, url_prefix="/pre_expansion")
    app.register_blueprint(blocks_bp, url_prefix="/blocks")
    app.register_blueprint(cutting_bp, url_prefix="/cutting")
    app.register_blueprint(extrusion_bp, url_prefix="/extrusion")
    # Legacy moulded cornice lives at /moulded_cornice and moulded boxing at /moulded_boxing
    # The wrapper blueprint preserves those prefixes.
    app.register_blueprint(moulding_bp)
    app.register_blueprint(boxing_bp, url_prefix="/boxing")
    app.register_blueprint(pr16_bp, url_prefix="/pr16")
    app.register_blueprint(qc_bp, url_prefix="/qc")

    @app.route("/")
    def index():
        # Reuse legacy landing page for now
        return render_template("index.html")

    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=generate_csrf)

    @app.context_processor
    def inject_features():
        # attendance intentionally absent
        return dict(FEATURES={"analytics": bool(app.config.get("FEATURE_ANALYTICS", False))})

    @app.template_filter("to_local")
    def to_local(dt):
        if not dt:
            return None
        try:
            s = str(app.config.get("DEVICE_TZ_OFFSET", "+02:00")).strip()
            sign = 1 if s[0] == "+" else -1
            hh, mm = s[1:].split(":")
            off = timedelta(hours=sign * int(hh), minutes=sign * int(mm))
        except Exception:
            off = timedelta(hours=2)
        return dt + off

    return app
