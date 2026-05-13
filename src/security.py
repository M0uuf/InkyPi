import hmac
import os
import secrets
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for
)


security_bp = Blueprint("security", __name__)

CSRF_SESSION_KEY = "inkypi_csrf_token"
AUTH_SESSION_KEY = "inkypi_admin_authenticated"
ADMIN_TOKEN_CONFIG_KEYS = ("web_admin_token", "admin_token")
ADMIN_TOKEN_ENV_KEYS = ("INKYPI_ADMIN_TOKEN", "INKYPI_WEB_ADMIN_TOKEN")
PROTECTED_METHODS = {"POST", "PUT", "DELETE"}
EXEMPT_ENDPOINTS = {"security.login", "static"}


def _get_admin_token():
    for env_key in ADMIN_TOKEN_ENV_KEYS:
        value = os.getenv(env_key)
        if value:
            return value

    device_config = current_app.config.get("DEVICE_CONFIG")
    if not device_config:
        return None

    for config_key in ADMIN_TOKEN_CONFIG_KEYS:
        value = device_config.get_config(config_key)
        if value:
            return value
    return None


def is_security_enabled():
    return bool(_get_admin_token())


def _constant_time_equals(left, right):
    if not left or not right:
        return False
    return hmac.compare_digest(str(left), str(right))


def _token_from_request():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.headers.get("X-InkyPi-Admin-Token")


def _has_token_auth():
    return _constant_time_equals(_token_from_request(), _get_admin_token())


def _is_session_authenticated():
    return bool(session.get(AUTH_SESSION_KEY))


def _wants_json_response():
    if request.path.startswith("/api/"):
        return True
    if request.is_json:
        return True
    return request.accept_mimetypes.best == "application/json"


def _is_safe_redirect_target(target):
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/")


def get_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _request_csrf_token():
    return (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-InkyPi-CSRF-Token")
        or request.form.get("_csrf_token")
    )


def _has_valid_csrf_token():
    return _constant_time_equals(_request_csrf_token(), session.get(CSRF_SESSION_KEY))


def _unauthorized_response(message="Authentication required"):
    if request.method in PROTECTED_METHODS or _wants_json_response():
        return jsonify({"error": message}), 401
    return redirect(url_for("security.login", next=request.full_path if request.query_string else request.path))


def _forbidden_response(message="CSRF token missing or invalid"):
    return jsonify({"error": message}), 403


def _requires_auth_for_get():
    if request.method != "GET":
        return False
    if request.endpoint in EXEMPT_ENDPOINTS:
        return False
    return True


def _protect_request():
    if not is_security_enabled():
        return None
    if request.endpoint in EXEMPT_ENDPOINTS:
        return None
    if _has_token_auth():
        return None

    if _requires_auth_for_get() and not _is_session_authenticated():
        return _unauthorized_response()

    if request.method in PROTECTED_METHODS:
        if not _is_session_authenticated():
            return _unauthorized_response()
        if not _has_valid_csrf_token():
            return _forbidden_response()
    return None


@security_bp.route("/login", methods=["GET", "POST"])
def login():
    if not is_security_enabled():
        return redirect(url_for("main.main_page"))

    if request.method == "POST":
        submitted_token = request.form.get("admin_token")
        if not submitted_token:
            submitted_json = request.get_json(silent=True, cache=False, force=False) or {}
            if isinstance(submitted_json, dict):
                submitted_token = submitted_json.get("admin_token")
        if _constant_time_equals(submitted_token, _get_admin_token()):
            session[AUTH_SESSION_KEY] = True
            get_csrf_token()
            target = request.args.get("next") or url_for("main.main_page")
            if not _is_safe_redirect_target(target):
                target = url_for("main.main_page")
            return redirect(target)
        return render_template("login.html", error="Invalid admin token"), 401

    return render_template("login.html", error=None)


@security_bp.route("/logout", methods=["POST"])
def logout():
    session.pop(AUTH_SESSION_KEY, None)
    session.pop(CSRF_SESSION_KEY, None)
    return redirect(url_for("security.login"))


def init_security(app):
    app.register_blueprint(security_bp)
    app.before_request(_protect_request)

    @app.context_processor
    def inject_security_context():
        enabled = is_security_enabled()
        return {
            "security_enabled": enabled,
            "csrf_token": get_csrf_token() if enabled else ""
        }
