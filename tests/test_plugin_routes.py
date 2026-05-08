import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

flask = pytest.importorskip("flask")
Flask = flask.Flask

from blueprints.playlist import playlist_bp
from blueprints.plugin import plugin_bp


class UnsupportedPluginConfig:
    def get_plugin(self, plugin_id):
        return None

    def get_playlist_manager(self):
        return MagicMock()


def create_app():
    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = UnsupportedPluginConfig()
    app.config["REFRESH_TASK"] = MagicMock(running=False)
    app.config["DISPLAY_MANAGER"] = MagicMock()
    app.register_blueprint(plugin_bp)
    app.register_blueprint(playlist_bp)
    return app


def test_add_plugin_rejects_unsupported_plugin_id():
    client = create_app().test_client()

    response = client.post("/add_plugin", data={
        "plugin_id": "clock",
        "refresh_settings": json.dumps({
            "playlist": "Default",
            "instance_name": "Clock",
            "refreshType": "interval",
            "unit": "hour",
            "interval": "1"
        })
    })

    assert response.status_code == 404
    assert response.get_json()["error"] == "Unsupported plugin 'clock'"


def test_update_now_rejects_unsupported_plugin_id():
    client = create_app().test_client()

    response = client.post("/update_now", data={"plugin_id": "clock"})

    assert response.status_code == 404
    assert response.get_json()["error"] == "Unsupported plugin 'clock'"


def test_update_plugin_instance_rejects_unsupported_plugin_id():
    client = create_app().test_client()

    response = client.put("/update_plugin_instance/Clock", data={"plugin_id": "clock"})

    assert response.status_code == 404
    assert response.get_json()["error"] == "Unsupported plugin 'clock'"


def test_display_plugin_instance_rejects_unsupported_plugin_id():
    client = create_app().test_client()

    response = client.post("/display_plugin_instance", json={
        "playlist_name": "Default",
        "plugin_id": "clock",
        "plugin_instance": "Clock"
    })

    assert response.status_code == 404
    assert response.get_json()["error"] == "Unsupported plugin 'clock'"
