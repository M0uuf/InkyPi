import pytest
from datetime import datetime

import pytz

from src.model import Playlist, PluginInstance

class TestPlaylist:

    @pytest.mark.parametrize(
        "start,end,current,expected,priority",
        [
            # --- Non-wrapping cases 09:00 <-> 15:00 ---
            ("09:00", "15:00", "08:59", False, 360),  # just before start
            ("09:00", "15:00", "09:00", True, 360),   # exactly at start
            ("09:00", "15:00", "12:00", True, 360),   # during
            ("09:00", "15:00", "14:59", True, 360),   # just before end
            ("09:00", "15:00", "15:00", False, 360),  # exactly at end
            ("09:00", "15:00", "23:00", False, 360),  # way after
    
            # --- Wrapping cases (crossing midnight) 21:00 <-> 03:00 ---
            ("21:00", "03:00", "20:59", False, 360),  # just before start
            ("21:00", "03:00", "21:00", True, 360),   # exactly at start
            ("21:00", "03:00", "23:59", True, 360),   # before midnight
            ("21:00", "03:00", "00:00", True, 360),   # after midnight, inside
            ("21:00", "03:00", "02:59", True, 360),   # just before end
            ("21:00", "03:00", "03:00", False, 360),  # exactly at end
            ("21:00", "03:00", "11:00", False, 360),  # way after
    
            # --- Equal start and end 12:00 <-> 12:00 ---
            ("12:00", "12:00", "11:59", False, 0),
            ("12:00", "12:00", "12:00", False, 0),
            ("12:00", "12:00", "12:01", False, 0),
    
            # --- Midnight boundaries 18:00 <-> 00:00 ---
            ("18:00", "00:00", "17:59", False, 360),  # before start
            ("18:00", "00:00", "23:59", True, 360),   # before end
            ("18:00", "00:00", "00:00", False, 360),  # exactly at end
    
            # --- Midnight boundaries 00:00 <-> 06:00 ---
            ("00:00", "06:00", "00:00", True, 360),   # start at midnight
            ("00:00", "06:00", "05:59", True, 360),   # before end
            ("00:00", "06:00", "06:00", False, 360),  # exactly at end

            # --- All day 00:00 <-> 24:00 ---
            ("00:00", "24:00", "00:00", True, 1440),   # exactly at start
            ("00:00", "24:00", "10:00", True, 1440),   # during
            ("00:00", "24:00", "24:00", False, 1440),  # exactly at end
        ]
    )
    def test_is_active_and_priority(self, start, end, current, expected, priority):
        playlist = Playlist("Test Playlist", start, end)
        assert playlist.is_active(current) == expected
        assert playlist.get_priority() == priority


def test_scheduled_plugin_does_not_refresh_before_configured_time_without_history():
    plugin = PluginInstance("weather", "Weather", {}, {"scheduled": "08:00"})

    assert not plugin.should_refresh(datetime.fromisoformat("2026-05-09T07:59:00"))


def test_scheduled_plugin_refreshes_at_configured_time_without_history():
    plugin = PluginInstance("weather", "Weather", {}, {"scheduled": "08:00"})

    assert plugin.should_refresh(datetime.fromisoformat("2026-05-09T08:00:00"))


def test_scheduled_plugin_accepts_timezone_aware_current_time():
    plugin = PluginInstance("weather", "Weather", {}, {"scheduled": "08:00"})

    assert plugin.should_refresh(datetime.fromisoformat("2026-05-09T08:00:00+02:00"))


def test_interval_plugin_normalizes_legacy_naive_latest_refresh_to_current_timezone():
    plugin = PluginInstance(
        "weather",
        "Weather",
        {},
        {"interval": 300},
        latest_refresh_time="2026-05-09T08:00:00"
    )

    assert plugin.should_refresh(datetime.fromisoformat("2026-05-09T08:05:00+02:00"))


def test_interval_plugin_keeps_legacy_naive_latest_refresh_not_due_with_aware_current_time():
    plugin = PluginInstance(
        "weather",
        "Weather",
        {},
        {"interval": 300},
        latest_refresh_time="2026-05-09T08:00:00"
    )

    assert not plugin.should_refresh(datetime.fromisoformat("2026-05-09T08:04:59+02:00"))


def test_latest_refresh_preserves_existing_aware_timestamp():
    plugin = PluginInstance(
        "weather",
        "Weather",
        {},
        {"interval": 300},
        latest_refresh_time="2026-05-09T08:00:00+02:00"
    )

    latest_refresh = plugin.get_latest_refresh_dt(pytz.timezone("UTC"))

    assert latest_refresh == datetime.fromisoformat("2026-05-09T08:00:00+02:00")
    assert latest_refresh.utcoffset().total_seconds() == 7200


def test_interval_plugin_handles_aware_latest_refresh_with_naive_current_time():
    plugin = PluginInstance(
        "weather",
        "Weather",
        {},
        {"interval": 300},
        latest_refresh_time="2026-05-09T08:00:00+02:00"
    )

    assert plugin.should_refresh(datetime.fromisoformat("2026-05-09T08:05:00"))


def test_latest_refresh_keeps_naive_timestamp_when_no_fallback_timezone_is_provided():
    plugin = PluginInstance(
        "weather",
        "Weather",
        {},
        {"interval": 300},
        latest_refresh_time="2026-05-09T08:00:00"
    )

    assert plugin.get_latest_refresh_dt().tzinfo is None


def test_scheduled_plugin_refreshes_after_configured_time_once_per_day():
    plugin = PluginInstance(
        "weather",
        "Weather",
        {},
        {"scheduled": "08:00"},
        latest_refresh_time="2026-05-08T08:05:00"
    )

    assert plugin.should_refresh(datetime.fromisoformat("2026-05-09T08:01:00"))

    plugin.latest_refresh_time = "2026-05-09T08:01:00"
    assert not plugin.should_refresh(datetime.fromisoformat("2026-05-09T12:00:00"))


def test_scheduled_plugin_refreshes_if_last_refresh_today_before_scheduled_time():
    plugin = PluginInstance(
        "weather",
        "Weather",
        {},
        {"scheduled": "08:00"},
        latest_refresh_time="2026-05-09T07:30:00"
    )

    assert plugin.should_refresh(datetime.fromisoformat("2026-05-09T08:00:00"))


def test_playlist_selects_next_due_plugin_without_advancing_when_none_due():
    playlist = Playlist("Default", "00:00", "24:00", [
        {
            "plugin_id": "weather",
            "name": "Weather",
            "plugin_settings": {},
            "refresh": {"interval": 300},
            "latest_refresh_time": "2026-05-09T08:00:00"
        },
        {
            "plugin_id": "calendar",
            "name": "Calendar",
            "plugin_settings": {},
            "refresh": {"interval": 300},
            "latest_refresh_time": "2026-05-09T08:00:00"
        }
    ], current_plugin_index=0)

    plugin = playlist.find_next_refreshable_plugin(datetime.fromisoformat("2026-05-09T08:04:00"))

    assert plugin is None
    assert playlist.current_plugin_index == 0


def test_playlist_scans_forward_to_next_due_plugin():
    playlist = Playlist("Default", "00:00", "24:00", [
        {
            "plugin_id": "weather",
            "name": "Weather",
            "plugin_settings": {},
            "refresh": {"interval": 300},
            "latest_refresh_time": "2026-05-09T08:00:00"
        },
        {
            "plugin_id": "calendar",
            "name": "Calendar",
            "plugin_settings": {},
            "refresh": {"interval": 300},
            "latest_refresh_time": "2026-05-09T07:55:00"
        }
    ], current_plugin_index=0)

    plugin = playlist.find_next_refreshable_plugin(datetime.fromisoformat("2026-05-09T08:01:00"))

    assert plugin.name == "Calendar"
    assert playlist.current_plugin_index == 1
