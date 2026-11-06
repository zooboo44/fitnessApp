import os
import time

import click
from flask import Flask, redirect, request, url_for
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
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
        raise RuntimeError(
            "SECRET_KEY is missing or still the placeholder. Put a long random value in .env, e.g. the "
            "output of: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )

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
    @click.option("--wait", default=30, show_default=True, help="Seconds to wait for the database.")
    def init_db_command(wait):
        """Create tables and seed the built-in exercise library."""
        deadline = time.monotonic() + wait
        while True:
            try:
                init_db()
                break
            except OperationalError as exc:
                # Only connection problems are worth retrying (e.g. Postgres still starting).
                if time.monotonic() >= deadline:
                    raise click.ClickException(f"Database not reachable: {exc.orig}") from exc
                click.echo("Database not ready yet, retrying in 3s...", err=True)
                db.session.rollback()
                time.sleep(3)
            except SchemaOutdated as exc:
                raise click.ClickException(str(exc)) from exc
        click.echo("Database initialised.")

    if app.config["AUTO_INIT_DB"]:
        with app.app_context():
            init_db()

    return app


class SchemaOutdated(RuntimeError):
    pass


def check_schema():
    """create_all() adds missing tables but never changes existing ones. Spot tables
    created by an older version of the app and explain how to fix it, instead of
    failing later with confusing 'column does not exist' errors."""
    inspector = inspect(db.engine)
    missing = []
    for table in db.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        missing += [f"{table.name}.{c.name}" for c in table.columns if c.name not in existing]
    if missing:
        raise SchemaOutdated(
            "The database was created by an older version of the app and is missing: "
            + ", ".join(missing)
            + ".\nIf it only holds test data, reset it: `docker compose down -v` then "
            "`docker compose up --build` (this deletes all data in the database)."
        )


def init_db():
    from .seed import seed_exercises

    db.create_all()
    check_schema()
    seed_exercises()
