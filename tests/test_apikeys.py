import os
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.env_file import parse_env_file, serialize_env_value, validate_env_value, write_env_file


def test_serialize_env_value_quotes_spaces_quotes_and_backslashes():
    assert serialize_env_value("abc123") == "'abc123'"
    assert serialize_env_value("value with spaces") == "'value with spaces'"
    assert serialize_env_value("quote'value") == "'quote\\'value'"
    assert serialize_env_value("path\\value") == "'path\\\\value'"


@pytest.mark.parametrize("value", ["line\nbreak", "line\rbreak", "null\x00byte", "tab\tvalue"])
def test_validate_env_value_rejects_newlines_and_control_characters(value):
    with pytest.raises(ValueError, match="control characters"):
        validate_env_value(value)


def test_write_env_file_quotes_values_and_sets_restrictive_permissions(tmp_path):
    env_path = tmp_path / ".env"

    assert write_env_file(env_path, [
        ("NORMAL_KEY", "abc123"),
        ("SPACED_KEY", "value with spaces"),
        ("QUOTE_KEY", "quote'value")
    ])

    raw_env = env_path.read_text()
    assert "NORMAL_KEY='abc123'\n" in raw_env
    assert "SPACED_KEY='value with spaces'\n" in raw_env
    assert "QUOTE_KEY='quote\\'value'\n" in raw_env
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600

    parsed = dict(parse_env_file(env_path))
    assert parsed["NORMAL_KEY"] == "abc123"
    assert parsed["SPACED_KEY"] == "value with spaces"
    assert parsed["QUOTE_KEY"] == "quote'value"


def test_write_env_file_tightens_existing_permissions(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OLD='value'\n")
    os.chmod(env_path, 0o644)

    assert write_env_file(env_path, [("NEW_KEY", "value")])

    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert dict(parse_env_file(env_path)) == {"NEW_KEY": "value"}


def test_write_env_file_rejects_control_characters_directly(tmp_path):
    env_path = tmp_path / ".env"

    with pytest.raises(ValueError, match="control characters"):
        write_env_file(env_path, [("BAD_SECRET", "first\nSECOND=injected")])

    assert not env_path.exists()


def test_write_env_file_rejects_invalid_keys_directly(tmp_path):
    env_path = tmp_path / ".env"

    with pytest.raises(ValueError, match="Invalid key format"):
        write_env_file(env_path, [("BAD-SECRET", "value")])

    assert not env_path.exists()


def create_app(tmp_path):
    flask = pytest.importorskip("flask")
    from blueprints import apikeys as apikeys_module

    Flask = flask.Flask
    app = Flask(__name__)
    app.secret_key = "test"
    app.config["DEVICE_CONFIG"] = MagicMock()
    app.config["REFRESH_TASK"] = MagicMock()
    app.register_blueprint(apikeys_module.apikeys_bp)
    apikeys_module.get_env_path = lambda: str(tmp_path / ".env")
    return app


def test_save_apikeys_preserves_keep_existing_value(monkeypatch, tmp_path):
    app = create_app(tmp_path)
    env_path = tmp_path / ".env"
    write_env_file(env_path, [("OPEN_WEATHER_MAP_SECRET", "existing secret")])

    response = app.test_client().post("/api-keys/save", json={
        "entries": [
            {"key": "OPEN_WEATHER_MAP_SECRET", "keepExisting": True},
            {"key": "NEW_SECRET", "value": "new value"}
        ]
    })

    assert response.status_code == 200
    parsed = dict(parse_env_file(env_path))
    assert parsed["OPEN_WEATHER_MAP_SECRET"] == "existing secret"
    assert parsed["NEW_SECRET"] == "new value"


def test_save_apikeys_rejects_newline_value(tmp_path):
    app = create_app(tmp_path)

    response = app.test_client().post("/api-keys/save", json={
        "entries": [
            {"key": "BAD_SECRET", "value": "first\nSECOND=injected"}
        ]
    })

    assert response.status_code == 400
    assert "control characters" in response.get_json()["error"]


def test_save_apikeys_rejects_keep_existing_newline_value(tmp_path):
    app = create_app(tmp_path)
    env_path = tmp_path / ".env"
    original_env = "BAD_SECRET='first\nSECOND=injected'\n"
    env_path.write_text(original_env)

    response = app.test_client().post("/api-keys/save", json={
        "entries": [
            {"key": "BAD_SECRET", "keepExisting": True}
        ]
    })

    assert response.status_code == 400
    assert "control characters" in response.get_json()["error"]
    assert env_path.read_text() == original_env
