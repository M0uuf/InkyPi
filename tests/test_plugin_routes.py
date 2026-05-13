import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

flask = pytest.importorskip("flask")
Flask = flask.Flask

from blueprints.playlist import playlist_bp
from blueprints import playlist as playlist_module
from blueprints import plugin as plugin_module
from blueprints.plugin import plugin_bp
from model import Playlist
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


class DirectRefreshTask:
    running = False


class DirectPlugin:
    config = {"image_settings": []}

    def generate_image(self, settings, device_config):
        return Image.new("RGB", (16, 16), "white")


class MissingPlaylistManager:
    def get_playlist(self, playlist_name):
        return None

    def find_plugin(self, plugin_id, instance_name):
        return None


class MissingPlaylistConfig:
    def get_plugin(self, plugin_id):
        return {"id": plugin_id}

    def get_playlist_manager(self):
        return MissingPlaylistManager()


class WritablePlaylistManager:
    def __init__(self, plugins=None):
        self.playlist = Playlist("Default", "00:00", "24:00", plugins or [])
        self.playlists = [self.playlist]

    def get_playlist(self, playlist_name):
        if self.playlist and playlist_name == self.playlist.name:
            return self.playlist
        return None

    def find_plugin(self, plugin_id, instance_name):
        if not self.playlist:
            return None
        return self.playlist.find_plugin(plugin_id, instance_name)

    def add_plugin_to_playlist(self, playlist_name, plugin_dict):
        return self.playlist.add_plugin(plugin_dict)

    def delete_playlist(self, playlist_name):
        self.playlists = [playlist for playlist in self.playlists if playlist.name != playlist_name]
        if self.playlist.name == playlist_name:
            self.playlist = None


class FailingWriteConfig:
    def __init__(self, plugins=None):
        self.playlist_manager = WritablePlaylistManager(plugins=plugins)
        self.plugin_image_dir = "/tmp"

    def get_plugin(self, plugin_id):
        return {"id": plugin_id}

    def get_playlist_manager(self):
        return self.playlist_manager

    def write_config(self):
        raise RuntimeError("write failed")


class SuccessfulWriteConfig(FailingWriteConfig):
    def write_config(self):
        return None


class PluginWithCleanup:
    def cleanup(self, settings):
        return None


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


def test_add_plugin_rejects_missing_playlist_before_saving_upload(monkeypatch, tmp_path):
    upload_dir = tmp_path / "src" / "static" / "images" / "saved"

    def fail_if_called(request_files):
        raise AssertionError("uploads should not be saved before playlist validation")

    monkeypatch.setattr(playlist_module, "handle_request_files", fail_if_called)

    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = MissingPlaylistConfig()
    app.config["REFRESH_TASK"] = MagicMock(running=False)
    app.register_blueprint(playlist_bp)

    response = app.test_client().post("/add_plugin", data={
        "plugin_id": "weather",
        "refresh_settings": json.dumps({
            "playlist": "Missing",
            "instance_name": "Weather",
            "refreshType": "interval",
            "unit": "hour",
            "interval": "1"
        }),
        "backgroundImageFile": (io.BytesIO(b"image"), "image.png")
    })

    assert response.status_code == 400
    assert response.get_json()["error"] == "Playlist 'Missing' does not exist"
    assert not upload_dir.exists()


def test_add_plugin_cleans_upload_and_rolls_back_when_config_write_fails(monkeypatch, tmp_path):
    upload_dir = tmp_path / "src" / "static" / "images" / "saved"
    upload_dir.mkdir(parents=True)
    upload_path = upload_dir / "manual.png"
    upload_path.write_bytes(b"manual")
    config = FailingWriteConfig()

    monkeypatch.setattr(playlist_module, "handle_request_files", lambda request_files: {
        "backgroundImageFile": str(upload_path)
    })
    from utils import app_utils
    monkeypatch.setattr(app_utils, "resolve_path", lambda path: str(tmp_path / "src" / path))

    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = config
    app.config["REFRESH_TASK"] = MagicMock(running=False)
    app.register_blueprint(playlist_bp)

    response = app.test_client().post("/add_plugin", data={
        "plugin_id": "weather",
        "refresh_settings": json.dumps({
            "playlist": "Default",
            "instance_name": "Weather",
            "refreshType": "interval",
            "unit": "hour",
            "interval": "1"
        })
    })

    assert response.status_code == 500
    assert not upload_path.exists()
    assert config.playlist_manager.playlist.plugins == []


def test_delete_plugin_instance_write_failure_keeps_saved_upload(monkeypatch, tmp_path):
    upload_dir = tmp_path / "src" / "static" / "images" / "saved"
    upload_dir.mkdir(parents=True)
    upload_path = upload_dir / "existing.png"
    upload_path.write_bytes(b"existing")
    config = FailingWriteConfig(plugins=[{
        "plugin_id": "weather",
        "name": "Weather",
        "plugin_settings": {"backgroundImageFile": str(upload_path)},
        "refresh": {"interval": 3600}
    }])

    from utils import app_utils
    monkeypatch.setattr(app_utils, "resolve_path", lambda path: str(tmp_path / "src" / path))
    monkeypatch.setattr(plugin_module, "get_plugin_instance", lambda plugin_config: PluginWithCleanup())

    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = config
    app.register_blueprint(plugin_bp)

    response = app.test_client().post("/delete_plugin_instance", json={
        "playlist_name": "Default",
        "plugin_id": "weather",
        "plugin_instance": "Weather"
    })

    assert response.status_code == 500
    assert upload_path.exists()
    assert config.playlist_manager.playlist.find_plugin("weather", "Weather") is not None


def test_delete_plugin_instance_success_cleans_saved_upload_after_write(monkeypatch, tmp_path):
    upload_dir = tmp_path / "src" / "static" / "images" / "saved"
    upload_dir.mkdir(parents=True)
    upload_path = upload_dir / "existing.png"
    upload_path.write_bytes(b"existing")
    config = SuccessfulWriteConfig(plugins=[{
        "plugin_id": "weather",
        "name": "Weather",
        "plugin_settings": {"backgroundImageFile": str(upload_path)},
        "refresh": {"interval": 3600}
    }])

    from utils import app_utils
    monkeypatch.setattr(app_utils, "resolve_path", lambda path: str(tmp_path / "src" / path))
    monkeypatch.setattr(plugin_module, "get_plugin_instance", lambda plugin_config: PluginWithCleanup())

    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = config
    app.register_blueprint(plugin_bp)

    response = app.test_client().post("/delete_plugin_instance", json={
        "playlist_name": "Default",
        "plugin_id": "weather",
        "plugin_instance": "Weather"
    })

    assert response.status_code == 200
    assert not upload_path.exists()
    assert config.playlist_manager.playlist.find_plugin("weather", "Weather") is None


def test_update_now_rejects_unsupported_plugin_id():
    client = create_app().test_client()

    response = client.post("/update_now", data={"plugin_id": "clock"})

    assert response.status_code == 404
    assert response.get_json()["error"] == "Unsupported plugin 'clock'"


def test_update_now_rejects_unsupported_plugin_before_saving_upload(monkeypatch):
    def fail_if_called(request_files):
        raise AssertionError("uploads should not be saved before plugin validation")

    monkeypatch.setattr(plugin_module, "handle_request_files", fail_if_called)
    client = create_app().test_client()

    response = client.post("/update_now", data={
        "plugin_id": "clock",
        "backgroundImageFile": (io.BytesIO(b"image"), "image.png")
    })

    assert response.status_code == 404
    assert response.get_json()["error"] == "Unsupported plugin 'clock'"


def test_update_now_direct_refresh_cleans_up_manual_upload(monkeypatch, tmp_path):
    upload_dir = tmp_path / "src" / "static" / "images" / "saved"
    upload_dir.mkdir(parents=True)
    upload_path = upload_dir / "manual.png"
    upload_path.write_bytes(b"manual")

    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = SupportedPluginConfig()
    app.config["REFRESH_TASK"] = DirectRefreshTask()
    app.config["DISPLAY_MANAGER"] = MagicMock()
    app.register_blueprint(plugin_bp)

    monkeypatch.setattr(plugin_module, "get_plugin_instance", lambda plugin_config: DirectPlugin())
    monkeypatch.setattr(plugin_module, "handle_request_files", lambda request_files: {
        "backgroundImageFile": str(upload_path)
    })
    from utils import app_utils
    monkeypatch.setattr(app_utils, "resolve_path", lambda path: str(tmp_path / "src" / path))

    response = app.test_client().post("/update_now", data={"plugin_id": "weather"})

    assert response.status_code == 200
    assert not upload_path.exists()


def test_update_now_rejects_request_over_app_upload_limit():
    app = create_app()
    app.config["MAX_CONTENT_LENGTH"] = 8

    response = app.test_client().post("/update_now", data={
        "plugin_id": "weather",
        "backgroundImageFile": (io.BytesIO(b"too large"), "large.png")
    })

    assert response.status_code == 413


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
