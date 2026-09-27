import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool_env(name, default):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'stockms.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 hours

    # App-level constants
    LOW_STOCK_DEFAULT_MIN = 5

    # -----------------------------------------------------------------
    # JWT (API / PWA / mobile authentication) - completely separate from
    # the Flask-Login session system used by the browser web app above.
    # -----------------------------------------------------------------
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-change-in-production")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=_int_env("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 15))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=_int_env("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 30))

    # Access tokens: sent by the client via the `Authorization: Bearer <token>` header
    # (used for PWA fetch calls and native/mobile clients alike). Never stored in a cookie.
    #
    # Refresh tokens: stored in an HttpOnly cookie scoped to /api/auth/refresh only, so
    # JavaScript can never read it (mitigates XSS token theft). Because it's cookie-based,
    # flask-jwt-extended's double-submit CSRF protection is enabled for it - the client must
    # echo the (non-HttpOnly) CSRF cookie value back in the X-CSRF-TOKEN header when calling
    # /api/auth/refresh. This is entirely separate from the web app's own session CSRF token.
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_ACCESS_COOKIE_PATH = "/api/"          # access tokens are NOT issued via cookie; harmless default
    JWT_REFRESH_COOKIE_PATH = "/api/auth/refresh"
    JWT_COOKIE_SECURE = _bool_env("JWT_COOKIE_SECURE", False)  # set True in production (HTTPS)
    JWT_COOKIE_SAMESITE = os.environ.get("JWT_COOKIE_SAMESITE", "Strict")
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_SESSION_COOKIE = False  # refresh cookie should persist per JWT_REFRESH_TOKEN_EXPIRES, not "until browser closes"
    JWT_ERROR_MESSAGE_KEY = "message"
