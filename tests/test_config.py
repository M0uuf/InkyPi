import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Config


def test_config_loads_only_supported_builtin_plugins(tmp_path):
    config_file = tmp_path / "device.json"
    config_file.write_text(json.dumps({
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
    }))

    original_config_file = Config.config_file
    Config.config_file = str(config_file)
    try:
        config = Config()
    finally:
        Config.config_file = original_config_file

    assert [plugin["id"] for plugin in config.get_plugins()] == ["weather", "calendar"]
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
