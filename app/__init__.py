import os

from flask import Flask, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, login_manager


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    insecure_key = app.config["SECRET_KEY"] in ("", "dev-insecure-change-me", "change-me")
    if insecure_key and not (app.config.get("TESTING") or os.environ.get("FLASK_DEBUG") == "1"):
        raise RuntimeError("Set SECRET_KEY to a long random value (see .env.example).")

    if app.config["PROXY_COUNT"] > 0:
        n = app.config["PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n, x_port=n)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = None

    from .auth import bp as auth_bp, init_oauth
    from .views import bp as main_bp
    from .api import bp as api_bp
    from .models import User

    init_oauth(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return {"error": "authentication required"}, 401
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)

    from .filters import register_filters

    register_filters(app)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.cli.command("init-db")
    def init_db_command():
        """Create tables and seed the built-in exercise library."""
        init_db()
        print("Database initialised.")

    if app.config["AUTO_INIT_DB"]:
        with app.app_context():
            init_db()

    return app


def init_db():
    from .seed import seed_exercises

    db.create_all()
    seed_exercises()
