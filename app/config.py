import os


def _bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///fitness.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Public base URL, e.g. https://fit.example.com — used to build OAuth redirect URIs.
    # If unset, redirect URIs are derived from the incoming request.
    BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_HTTPONLY = True

    # Google OAuth (https://console.cloud.google.com/apis/credentials)
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    # Sign in with Apple (https://developer.apple.com/account/resources/identifiers)
    APPLE_CLIENT_ID = os.environ.get("APPLE_CLIENT_ID", "")  # the Services ID
    APPLE_TEAM_ID = os.environ.get("APPLE_TEAM_ID", "")
    APPLE_KEY_ID = os.environ.get("APPLE_KEY_ID", "")
    # Contents of the .p8 key, or a path to it via APPLE_PRIVATE_KEY_PATH
    APPLE_PRIVATE_KEY = os.environ.get("APPLE_PRIVATE_KEY", "")
    APPLE_PRIVATE_KEY_PATH = os.environ.get("APPLE_PRIVATE_KEY_PATH", "")

    # Create tables + seed exercises when the app starts (the Docker image runs
    # `flask init-db` once instead, so gunicorn workers don't race).
    AUTO_INIT_DB = _bool("AUTO_INIT_DB", True)

    # Number of reverse proxies in front of the app (for X-Forwarded-* headers)
    PROXY_COUNT = int(os.environ.get("PROXY_COUNT", "1"))
