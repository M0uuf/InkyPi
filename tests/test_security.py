import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

flask = pytest.importorskip("flask")
Flask = flask.Flask

from security import init_security


class FakeDeviceConfig:
    def __init__(self, admin_token=None):
        self.admin_token = admin_token

    def get_config(self, key=None, default=None):
        values = {"web_admin_token": self.admin_token}
        if key is None:
            return values
        return values.get(key, default)


def create_app(admin_token=None):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["DEVICE_CONFIG"] = FakeDeviceConfig(admin_token)

    @app.route("/")
    def index():
        return "index"

    @app.route("/mutate", methods=["POST"])
    def mutate():
        return {"success": True}

    init_security(app)
    return app


def test_mutating_routes_allow_without_admin_token():
    client = create_app().test_client()

    response = client.post("/mutate")

    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_protected_get_redirects_to_login_without_session():
    client = create_app("secret").test_client()

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?next=/")


def test_protected_mutation_requires_authentication():
    client = create_app("secret").test_client()

    response = client.post("/mutate")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


def test_token_header_allows_api_style_mutation_without_csrf():
    client = create_app("secret").test_client()

    response = client.post("/mutate", headers={"X-InkyPi-Admin-Token": "secret"})

    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_bearer_token_allows_api_style_mutation_without_csrf():
    client = create_app("secret").test_client()

    response = client.post("/mutate", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_session_mutation_requires_csrf_token():
    client = create_app("secret").test_client()
    login_response = client.post("/login", data={"admin_token": "secret"})
    assert login_response.status_code == 302

    response = client.post("/mutate")

    assert response.status_code == 403
    assert response.get_json()["error"] == "CSRF token missing or invalid"


def test_session_mutation_accepts_csrf_token():
    app = create_app("secret")
    client = app.test_client()
    login_response = client.post("/login", data={"admin_token": "secret"})
    assert login_response.status_code == 302

    with client.session_transaction() as session:
        csrf_token = session["inkypi_csrf_token"]

    response = client.post("/mutate", headers={"X-CSRF-Token": csrf_token})

    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_login_rejects_wrong_admin_token():
    client = create_app("secret").test_client()

    response = client.post("/login", data={"admin_token": "wrong"})

    assert response.status_code == 401
