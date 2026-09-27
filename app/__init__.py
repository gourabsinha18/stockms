from flask import Flask
from config import Config
from app.extensions import db, login_manager, csrf, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from app.blueprints.auth.routes import bp as auth_bp
    from app.blueprints.main.routes import bp as main_bp
    from app.blueprints.locations.routes import bp as locations_bp
    from app.blueprints.catalog.routes import bp as catalog_bp
    from app.blueprints.stock.routes import bp as stock_bp
    from app.blueprints.transfers.routes import bp as transfers_bp
    from app.blueprints.adjustments.routes import bp as adjustments_bp
    from app.blueprints.returns.routes import bp as returns_bp
    from app.blueprints.users.routes import bp as users_bp
    from app.blueprints.reports.routes import bp as reports_bp
    from app.blueprints.notifications.routes import bp as notifications_bp
    from app.blueprints.audit.routes import bp as audit_bp
    from app.blueprints.approvals.routes import bp as approvals_bp
    from app.blueprints.bad_products.routes import bp as bad_products_bp
    from app.blueprints.employee_stock.routes import bp as employee_stock_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(locations_bp, url_prefix="/locations")
    app.register_blueprint(catalog_bp, url_prefix="/catalog")
    app.register_blueprint(stock_bp, url_prefix="/stock")
    app.register_blueprint(transfers_bp, url_prefix="/transfers")
    app.register_blueprint(adjustments_bp, url_prefix="/adjustments")
    app.register_blueprint(returns_bp, url_prefix="/returns")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(notifications_bp, url_prefix="/notifications")
    app.register_blueprint(audit_bp, url_prefix="/audit")
    app.register_blueprint(approvals_bp, url_prefix="/approvals")
    app.register_blueprint(bad_products_bp, url_prefix="/bad-products")
    app.register_blueprint(employee_stock_bp, url_prefix="/employee-stock")

    # Context processor: unread notification count in sidebar for every template
    from app.models import Notification
    from flask_login import current_user

    @app.context_processor
    def inject_notification_count():
        if current_user.is_authenticated:
            count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            return {"unread_notification_count": count}
        return {"unread_notification_count": 0}

    # Basic security headers
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Error handlers
    from flask import render_template as _render_template

    @app.errorhandler(403)
    def forbidden(e):
        return _render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return _render_template("errors/404.html"), 404

    return app
