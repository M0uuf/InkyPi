import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Config


class StubModel:
    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return self.data


def build_writable_config(tmp_path):
    config = Config.__new__(Config)
    config.config_file = str(tmp_path / "device.json")
    config.config = {"name": "Before"}
    config.playlist_manager = StubModel({"playlists": [], "active_playlist": None})
    config.refresh_info = StubModel({
        "refresh_time": None,
        "image_hash": None,
        "refresh_type": None,
        "plugin_id": None
    })
    return config


def load_config_from_temp_file(tmp_path, data):
    config_file = tmp_path / "device.json"
    config_file.write_text(json.dumps(data))

    original_config_file = Config.config_file
    Config.config_file = str(config_file)
    try:
        config = Config()
    finally:
        Config.config_file = original_config_file

    return config, config_file


def test_config_loads_only_supported_builtin_plugins(tmp_path):
    config, config_file = load_config_from_temp_file(tmp_path, {
        "plugin_order": ["clock", "weather", "calendar"],
        "playlist_config": {
            "playlists": [
                {
                    "name": "Default",
                    "start_time": "00:00",
                    "end_time": "24:00",
                    "plugins": [
                        {
                            "plugin_id": "weather",
                            "name": "Weather",
                            "plugin_settings": {},
                            "refresh": {"interval": 3600}
                        },
                        {
                            "plugin_id": "clock",
                            "name": "Clock",
                            "plugin_settings": {},
                            "refresh": {"interval": 3600}
                        }
                    ],
                    "current_plugin_index": 1
                }
            ],
            "active_playlist": None
        },
        "refresh_info": {
            "refresh_time": "2026-05-08T08:00:00",
            "image_hash": "old",
            "refresh_type": "Playlist",
            "plugin_id": "clock"
        }
    })

    assert [plugin["id"] for plugin in config.get_plugins()] == ["weather", "calendar"]
    assert all(plugin["icon_version"].isdigit() for plugin in config.get_plugins())
    assert config.get_config("plugin_order") == ["weather", "calendar"]
    playlist = config.get_playlist_manager().get_playlist("Default")
    assert [plugin.plugin_id for plugin in playlist.plugins] == ["weather"]
    assert playlist.current_plugin_index is None
    assert config.get_refresh_info().plugin_id is None

    saved_config = json.loads(config_file.read_text())
    assert saved_config["plugin_order"] == ["weather", "calendar"]
    assert saved_config["playlist_config"]["playlists"][0]["plugins"][0]["plugin_id"] == "weather"
    assert saved_config["refresh_info"]["plugin_id"] is None

    backups = list(tmp_path.glob("device.pre-weather-calendar-only-*.json"))
    assert len(backups) == 1
    backup_config = json.loads(backups[0].read_text())
    assert backup_config["plugin_order"] == ["clock", "weather", "calendar"]
    assert backup_config["playlist_config"]["playlists"][0]["plugins"][1]["plugin_id"] == "clock"


def test_config_sanitizes_malformed_top_level_plugin_config_shapes(tmp_path):
    config, config_file = load_config_from_temp_file(tmp_path, {
        "plugin_order": "weather",
        "playlist_config": None,
        "refresh_info": ["bad"]
    })

    assert config.get_config("plugin_order") == []
    assert config.get_playlist_manager().get_playlist("Default") is not None
    assert config.get_refresh_info().plugin_id is None

    saved_config = json.loads(config_file.read_text())
    assert saved_config["plugin_order"] == []
    assert saved_config["playlist_config"] == {"playlists": [], "active_playlist": None}
    assert saved_config["refresh_info"] == {
        "refresh_time": None,
        "image_hash": None,
        "refresh_type": None,
        "plugin_id": None
    }

    backups = list(tmp_path.glob("device.pre-weather-calendar-only-*.json"))
    assert len(backups) == 1
    backup_config = json.loads(backups[0].read_text())
    assert backup_config["plugin_order"] == "weather"
    assert backup_config["playlist_config"] is None
    assert backup_config["refresh_info"] == ["bad"]


def test_config_sanitizes_malformed_playlist_shapes(tmp_path):
    config, config_file = load_config_from_temp_file(tmp_path, {
        "plugin_order": ["weather", "clock", 42, "calendar"],
        "playlist_config": {
            "playlists": [
                "not-a-playlist",
                {
                    "name": "Malformed plugins",
                    "start_time": "00:00",
                    "end_time": "24:00",
                    "plugins": {"plugin_id": "weather"},
                    "current_plugin_index": 0
                },
                {
                    "name": "Missing plugins",
                    "start_time": "00:00",
                    "end_time": "24:00",
                    "current_plugin_index": 0
                },
                {
                    "start_time": "00:00",
                    "end_time": "24:00",
                    "plugins": []
                },
                {
                    "name": "Missing start",
                    "end_time": "24:00",
                    "plugins": []
                },
                {
                    "name": "Missing end",
                    "start_time": "00:00",
                    "plugins": []
                },
                {
                    "name": "Mixed plugins",
                    "start_time": "00:00",
                    "end_time": "24:00",
                    "plugins": [
                        {
                            "plugin_id": "weather",
                            "name": "Weather",
                            "plugin_settings": {},
                            "refresh": {"interval": 3600}
                        },
                        {
                            "plugin_id": "calendar",
                            "plugin_settings": {},
                            "refresh": {"interval": 3600}
                        },
                        {
                            "plugin_id": "weather",
                            "name": "Weather missing settings",
                            "refresh": {"interval": 3600}
                        },
                        {
                            "plugin_id": "calendar",
                            "name": "Calendar missing refresh",
                            "plugin_settings": {}
                        },
                        {
                            "plugin_id": "calendar",
                            "name": "Calendar malformed settings",
                            "plugin_settings": "bad",
                            "refresh": {"interval": 3600}
                        },
                        {
                            "plugin_id": "weather",
                            "name": "Weather malformed refresh",
                            "plugin_settings": {},
                            "refresh": "hourly"
                        },
                        "not-a-plugin",
                        {
                            "plugin_id": "clock",
                            "name": "Clock",
                            "plugin_settings": {},
                            "refresh": {"interval": 3600}
                        }
                    ],
                    "current_plugin_index": 2
                }
            ],
            "active_playlist": None
        },
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": None,
            "plugin_id": None
        }
    })

    assert config.get_config("plugin_order") == ["weather", "calendar"]
    malformed_playlist = config.get_playlist_manager().get_playlist("Malformed plugins")
    assert malformed_playlist.plugins == []
    assert malformed_playlist.current_plugin_index is None
    missing_plugins_playlist = config.get_playlist_manager().get_playlist("Missing plugins")
    assert missing_plugins_playlist.plugins == []
    assert missing_plugins_playlist.current_plugin_index is None
    mixed_playlist = config.get_playlist_manager().get_playlist("Mixed plugins")
    assert [plugin.plugin_id for plugin in mixed_playlist.plugins] == ["weather"]
    assert mixed_playlist.current_plugin_index is None

    saved_config = json.loads(config_file.read_text())
    assert saved_config["plugin_order"] == ["weather", "calendar"]
    saved_playlists = saved_config["playlist_config"]["playlists"]
    assert [playlist["name"] for playlist in saved_playlists] == [
        "Malformed plugins",
        "Missing plugins",
        "Mixed plugins"
    ]
    assert saved_playlists[0]["plugins"] == []
    assert saved_playlists[0]["current_plugin_index"] is None
    assert saved_playlists[1]["plugins"] == []
    assert saved_playlists[1]["current_plugin_index"] is None
    assert [plugin["plugin_id"] for plugin in saved_playlists[2]["plugins"]] == ["weather"]
    assert saved_playlists[2]["current_plugin_index"] is None


def test_config_sanitizes_non_list_playlists(tmp_path):
    config, config_file = load_config_from_temp_file(tmp_path, {
        "playlist_config": {
            "playlists": {"name": "Bad shape"},
            "active_playlist": "Bad shape"
        },
        "refresh_info": {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": None,
            "plugin_id": None
        }
    })

    assert config.get_playlist_manager().get_playlist("Default") is not None

    saved_config = json.loads(config_file.read_text())
    assert saved_config["playlist_config"]["playlists"] == []


def test_config_returns_validated_web_server_threads():
    config = Config.__new__(Config)
    config.config = {"web_server_threads": "4"}

    assert config.get_web_server_threads() == 4


def test_config_defaults_web_server_threads_for_invalid_values():
    config = Config.__new__(Config)

    for value in ("", "many", 0, -1, None):
        config.config = {"web_server_threads": value}
        assert config.get_web_server_threads(default=2) == 2


def test_config_caps_web_server_threads():
    config = Config.__new__(Config)
    config.config = {"web_server_threads": 99}

    assert config.get_web_server_threads(default=2, max_threads=8) == 8


def test_write_config_uses_same_directory_atomic_replace(monkeypatch, tmp_path):
    config = build_writable_config(tmp_path)
    replace_calls = []
    real_replace = os.replace

    def capture_replace(src, dst):
        replace_calls.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", capture_replace)

    config.update_config({"name": "Atomic"})

    assert replace_calls
    temp_path, destination = replace_calls[0]
    assert temp_path.parent == tmp_path
    assert destination == tmp_path / "device.json"
    assert not temp_path.exists()

    raw_config = (tmp_path / "device.json").read_text()
    assert raw_config.endswith("\n")
    assert '\n    "name": "Atomic",' in raw_config
    saved_config = json.loads(raw_config)
    assert saved_config["name"] == "Atomic"
    assert saved_config["playlist_config"] == {"playlists": [], "active_playlist": None}
    assert saved_config["refresh_info"]["plugin_id"] is None


def test_write_raw_config_uses_atomic_writer(monkeypatch, tmp_path):
    config = build_writable_config(tmp_path)
    called = {}

    def capture_atomic_write(config_data):
        called["config_data"] = config_data.copy()

    monkeypatch.setattr(config, "_atomic_write_json", capture_atomic_write)

    config.write_raw_config()

    assert called["config_data"] == {"name": "Before"}


def test_write_config_serializes_concurrent_writes(monkeypatch, tmp_path):
    config = build_writable_config(tmp_path)
    active_writes = 0
    max_active_writes = 0
    counter_lock = threading.Lock()

    def slow_atomic_write(config_data):
        nonlocal active_writes, max_active_writes
        with counter_lock:
            active_writes += 1
            max_active_writes = max(max_active_writes, active_writes)
        time.sleep(0.02)
        with counter_lock:
            active_writes -= 1

    monkeypatch.setattr(config, "_atomic_write_json", slow_atomic_write)

    threads = [threading.Thread(target=config.write_config) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active_writes == 1
