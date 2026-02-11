from flask import Flask, render_template
from config import Config
from models import db
from flask_login import LoginManager
from flask_login import login_required
from models.operator import Operator
from flask_wtf import CSRFProtect
from flask_migrate import Migrate
from flask_wtf.csrf import generate_csrf
from datetime import timedelta

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    # CSRF setup
    csrf = CSRFProtect()
    csrf.init_app(app)

    # Migrate setup
    migrate = Migrate(app, db)

    # Flask-Login setup
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return Operator.query.get(int(user_id))

    # Register all blueprints here
    from blueprints.pre_expansion.routes import pre_expansion_bp
    from blueprints.auth.routes import auth_bp
    from blueprints.blocks.routes import blocks_bp
    from blueprints.moulded_cornice.routes import moulded_cornice_bp
    from blueprints.cutting.routes import cutting_bp
    from blueprints.qc.routes import qc_bp
    from blueprints.boxing.routes import boxing_bp
    from blueprints.pr16.routes import pr16_bp
    from blueprints.analytics.eps_factory_routes import analytics_bp
    from blueprints.reports.routes import reports_bp
    from blueprints.analytics.eps_factory.routes import eps_factory_analytics_bp
    from blueprints.analytics.extrusion.routes import extrusion_analytics_bp
    from blueprints.analytics.maintenance.routes import maintenance_analytics_bp
    from blueprints.analytics.boxing.routes import boxing_analytics_bp
    from blueprints.analytics.cutting.routes import cutting_analytics_bp
    from blueprints.analytics.moulded.routes import moulded_analytics_bp
    from blueprints.moulded_boxing.routes import moulded_boxing_bp
    from blueprints.extrusion.routes import extrusion_bp
    from blueprints.maintenance.routes import maintenance_bp
    from blueprints.attendance.routes import attendance_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(pre_expansion_bp, url_prefix='/pre_expansion')
    app.register_blueprint(blocks_bp, url_prefix='/blocks')
    app.register_blueprint(moulded_cornice_bp, url_prefix='/moulded')
    app.register_blueprint(cutting_bp, url_prefix='/cutting')
    app.register_blueprint(qc_bp, url_prefix='/qc')
    app.register_blueprint(boxing_bp, url_prefix='/boxing')
    app.register_blueprint(pr16_bp, url_prefix='/pr16')
    # Register analytics/reporting only if enabled
    if app.config.get('FEATURE_ANALYTICS', False):
        app.register_blueprint(analytics_bp, url_prefix='/analytics')
        app.register_blueprint(reports_bp, url_prefix='/reports')
        app.register_blueprint(eps_factory_analytics_bp, url_prefix='/analytics/eps-factory')
        app.register_blueprint(extrusion_analytics_bp, url_prefix='/analytics/extrusion')
        app.register_blueprint(maintenance_analytics_bp, url_prefix='/analytics/maintenance')
        app.register_blueprint(boxing_analytics_bp, url_prefix='/boxing_analytics')
        app.register_blueprint(cutting_analytics_bp, url_prefix="/cutting")
        app.register_blueprint(moulded_analytics_bp, url_prefix='/analytics/moulded')
    app.register_blueprint(moulded_boxing_bp, url_prefix="/moulded_boxing")
    app.register_blueprint(extrusion_bp, url_prefix="/extrusion")
    app.register_blueprint(maintenance_bp, url_prefix="/maintenance")
    # Attendance only if enabled
    if app.config.get('FEATURE_ATTENDANCE', False):
        app.register_blueprint(attendance_bp)
    

    @app.route('/')
    @login_required
    def index():
        return render_template('index.html')

    # Expose csrf_token() helper to Jinja when not using a FlaskForm
    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=generate_csrf)

    # Feature flags to templates for conditional sections/tiles
    @app.context_processor
    def inject_features():
        return dict(FEATURES={
            'attendance': bool(app.config.get('FEATURE_ATTENDANCE', False)),
            'analytics': bool(app.config.get('FEATURE_ANALYTICS', False)),
        })

    # Jinja filter: convert stored naive UTC datetimes to local using DEVICE_TZ_OFFSET (default +02:00)
    @app.template_filter('to_local')
    def to_local(dt):
        if not dt:
            return None
        try:
            s = str(app.config.get('DEVICE_TZ_OFFSET', '+02:00')).strip()
            sign = 1 if s[0] == '+' else -1
            hh, mm = s[1:].split(':')
            off = timedelta(hours=sign*int(hh), minutes=sign*int(mm))
        except Exception:
            off = timedelta(hours=2)
        return dt + off

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
