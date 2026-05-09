import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

flask = pytest.importorskip("flask")
Flask = flask.Flask

from blueprints.playlist import playlist_bp
from blueprints import plugin as plugin_module
from blueprints.plugin import plugin_bp
from refresh_task import ManualUpdateBusy


class UnsupportedPluginConfig:
    def get_plugin(self, plugin_id):
        return None

    def get_playlist_manager(self):
        return MagicMock()

class SupportedPluginConfig:
    def get_plugin(self, plugin_id):
        return {"id": plugin_id}

    def get_playlist_manager(self):
        return MagicMock()

class AsyncRefreshTask:
    running = True

    def __init__(self, busy=False):
        self.busy = busy
        self.jobs = {
            "job-1": {
                "id": "job-1",
                "state": "queued",
                "error": None,
                "plugin_id": "weather",
                "refresh_type": "Manual Update",
                "created_at": "2026-05-08T08:00:00+00:00",
                "started_at": None,
                "finished_at": None
            }
        }

    def enqueue_manual_update(self, refresh_action):
        if self.busy:
            raise ManualUpdateBusy(self.jobs["job-1"])
        return self.jobs["job-1"]

    def get_manual_update_status(self, job_id):
        return self.jobs.get(job_id)


def create_app():
    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = UnsupportedPluginConfig()
    app.config["REFRESH_TASK"] = MagicMock(running=False)
    app.config["DISPLAY_MANAGER"] = MagicMock()
    app.register_blueprint(plugin_bp)
    app.register_blueprint(playlist_bp)
    return app

def create_async_app(busy=False):
    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = SupportedPluginConfig()
    app.config["REFRESH_TASK"] = AsyncRefreshTask(busy=busy)
    app.config["DISPLAY_MANAGER"] = MagicMock()
    app.register_blueprint(plugin_bp)
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


def test_update_now_queues_manual_refresh_job():
    client = create_async_app().test_client()

    response = client.post("/update_now", data={"plugin_id": "weather"})

    assert response.status_code == 202
    data = response.get_json()
    assert data["message"] == "Display update queued"
    assert data["job"]["id"] == "job-1"
    assert data["job"]["status_url"] == "/refresh_job/job-1"


def test_update_now_returns_conflict_for_active_refresh_job():
    client = create_async_app(busy=True).test_client()

    response = client.post("/update_now", data={"plugin_id": "weather"})

    assert response.status_code == 409
    data = response.get_json()
    assert data["error"] == "A display update is already queued or running"
    assert data["job"]["id"] == "job-1"
    assert data["job"]["status_url"] == "/refresh_job/job-1"


def test_display_plugin_instance_queues_manual_refresh_job():
    client = create_async_app().test_client()

    response = client.post("/display_plugin_instance", json={
        "playlist_name": "Default",
        "plugin_id": "weather",
        "plugin_instance": "Weather"
    })

    assert response.status_code == 202
    assert response.get_json()["job"]["id"] == "job-1"


def test_refresh_job_status_returns_job_state():
    client = create_async_app().test_client()

    response = client.get("/refresh_job/job-1")

    assert response.status_code == 200
    assert response.get_json()["job"]["state"] == "queued"


def test_refresh_job_status_returns_404_for_unknown_job():
    client = create_async_app().test_client()

    response = client.get("/refresh_job/missing")

    assert response.status_code == 404
    assert response.get_json()["error"] == "Refresh job not found"


def test_plugin_image_route_caches_static_plugin_assets(monkeypatch, tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "weather"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "icon.png").write_bytes(b"fake png")

    plugin_module._plugins_dir.cache_clear()
    monkeypatch.setattr(plugin_module, "resolve_path", lambda path: str(plugins_dir))
    app = Flask(__name__)
    app.register_blueprint(plugin_bp)

    response = app.test_client().get("/images/weather/icon.png?v=123")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == (
        f"public, max-age={plugin_module.PLUGIN_ASSET_CACHE_SECONDS}, immutable"
    )
    assert response.headers["ETag"]


def test_plugin_image_route_revalidates_unversioned_assets(monkeypatch, tmp_path):
    plugins_dir = tmp_path / "plugins"
    frame_dir = plugins_dir / "base_plugin" / "frames"
    frame_dir.mkdir(parents=True)
    (frame_dir / "classic.png").write_bytes(b"fake png")

    plugin_module._plugins_dir.cache_clear()
    monkeypatch.setattr(plugin_module, "resolve_path", lambda path: str(plugins_dir))
    app = Flask(__name__)
    app.register_blueprint(plugin_bp)

    response = app.test_client().get("/images/base_plugin/frames/classic.png")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache"


def test_plugin_image_route_rejects_path_traversal(monkeypatch, tmp_path):
    plugins_dir = tmp_path / "plugins"
    (plugins_dir / "weather").mkdir(parents=True)

    plugin_module._plugins_dir.cache_clear()
    monkeypatch.setattr(plugin_module, "resolve_path", lambda path: str(plugins_dir))
    app = Flask(__name__)
    app.register_blueprint(plugin_bp)

    response = app.test_client().get("/images/weather/../calendar/icon.png")

    assert response.status_code == 403
