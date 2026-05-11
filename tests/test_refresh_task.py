import sys
import threading
import time
import logging
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import refresh_task as refresh_task_module
from model import Playlist, RefreshInfo
from refresh_task import ManualUpdateBusy, PlaylistRefresh, RefreshTask


class FakePlugin:
    config = {"image_settings": []}


class FakePlaylistManager:
    def __init__(self, playlist=None):
        self.playlist = playlist
        self.active_playlist = None

    def determine_active_playlist(self, current_dt):
        return self.playlist

    def get_playlist(self, playlist_name):
        if self.playlist and self.playlist.name == playlist_name:
            return self.playlist
        return None


class FakeDeviceConfig:
    def __init__(self, playlist=None, values=None):
        self.refresh_info = RefreshInfo(None, None, None, None)
        self.playlist_manager = FakePlaylistManager(playlist)
        self.writes = 0
        self.plugin_image_dir = "/tmp"
        self.values = values or {}

    def get_config(self, key, default=None):
        return self.values.get(key, default)

    def get_playlist_manager(self):
        return self.playlist_manager

    def get_refresh_info(self):
        return self.refresh_info

    def get_plugin(self, plugin_id):
        return {"id": plugin_id}

    def write_config(self):
        self.writes += 1


class FakeDisplayManager:
    def __init__(self):
        self.images = []
        self.lock = threading.Lock()

    def display_image(self, image, image_settings=None):
        with self.lock:
            self.images.append(image)


class FakeManualAction:
    def __init__(self, plugin_id, first_started=None, release_first=None, exception=None):
        self.plugin_id = plugin_id
        self.first_started = first_started
        self.release_first = release_first
        self.exception = exception

    def execute(self, plugin, device_config, current_dt):
        if self.first_started:
            self.first_started.set()
        if self.release_first:
            assert self.release_first.wait(timeout=2)
        if self.exception:
            raise self.exception
        return Image.new("RGB", (16, 16), "white")

    def get_refresh_info(self):
        return {"refresh_type": "Manual Update", "plugin_id": self.plugin_id}

    def get_plugin_id(self):
        return self.plugin_id


def test_concurrent_manual_updates_are_single_flight(monkeypatch):
    monkeypatch.setattr(refresh_task_module, "get_plugin_instance", lambda plugin_config: FakePlugin())
    first_started = threading.Event()
    release_first = threading.Event()

    task = RefreshTask(FakeDeviceConfig(), FakeDisplayManager())
    task.start()

    try:
        first_job = task.enqueue_manual_update(FakeManualAction("first", first_started, release_first))
        assert first_started.wait(timeout=2)

        with pytest.raises(ManualUpdateBusy) as exc_info:
            task.enqueue_manual_update(FakeManualAction("second"))

        assert exc_info.value.active_job["id"] == first_job["id"]
        assert exc_info.value.active_job["state"] == "running"
        with task.condition:
            assert len(task.manual_update_queue) == 0

        release_first.set()
    finally:
        task.stop()

    assert task.get_manual_update_status(first_job["id"])["state"] == "done"


def test_enqueue_manual_update_returns_status_and_completes(monkeypatch):
    monkeypatch.setattr(refresh_task_module, "get_plugin_instance", lambda plugin_config: FakePlugin())

    task = RefreshTask(FakeDeviceConfig(), FakeDisplayManager())
    task.start()

    try:
        job = task.enqueue_manual_update(FakeManualAction("weather"))

        assert job["id"]
        assert job["state"] == "queued"
        assert job["plugin_id"] == "weather"

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = task.get_manual_update_status(job["id"])
            if status["state"] == "done":
                break
            time.sleep(0.01)
        else:
            pytest.fail("manual update job did not complete")

        assert status["error"] is None
        assert status["finished_at"] is not None
    finally:
        task.stop()


def test_enqueue_manual_update_reports_errors(monkeypatch):
    monkeypatch.setattr(refresh_task_module, "get_plugin_instance", lambda plugin_config: FakePlugin())
    expected_error = RuntimeError("refresh failed")

    task = RefreshTask(FakeDeviceConfig(), FakeDisplayManager())
    task.start()

    try:
        job = task.enqueue_manual_update(FakeManualAction("weather", exception=expected_error))

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = task.get_manual_update_status(job["id"])
            if status["state"] == "error":
                break
            time.sleep(0.01)
        else:
            pytest.fail("manual update job did not report an error")

        assert status["error"] == "refresh failed"
    finally:
        task.stop()


def test_playlist_refresh_re_resolves_deleted_plugin_instance(monkeypatch):
    monkeypatch.setattr(refresh_task_module, "get_plugin_instance", lambda plugin_config: FakePlugin())
    playlist = Playlist("Default", "00:00", "24:00", [{
        "plugin_id": "weather",
        "name": "Weather",
        "plugin_settings": {},
        "refresh": {"interval": 3600}
    }])
    plugin_instance = playlist.find_plugin("weather", "Weather")
    action = PlaylistRefresh(playlist, plugin_instance, force=True)
    playlist.delete_plugin("weather", "Weather")

    task = RefreshTask(FakeDeviceConfig(playlist), FakeDisplayManager())
    task.start()

    try:
        job = task.enqueue_manual_update(action)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = task.get_manual_update_status(job["id"])
            if status["state"] == "error":
                break
            time.sleep(0.01)
        else:
            pytest.fail("deleted plugin instance job did not fail")

        assert "no longer exists" in status["error"]
    finally:
        task.stop()


def test_refresh_diagnostics_log_phase_breakdown_when_enabled(monkeypatch, caplog):
    monkeypatch.setattr(refresh_task_module, "get_plugin_instance", lambda plugin_config: FakePlugin())
    config = FakeDeviceConfig(values={"performance_diagnostics": True})
    task = RefreshTask(config, FakeDisplayManager())

    caplog.set_level(logging.INFO, logger="refresh_task")
    task.start()

    try:
        job = task.enqueue_manual_update(FakeManualAction("weather"))

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = task.get_manual_update_status(job["id"])
            if status["state"] == "done":
                break
            time.sleep(0.01)
        else:
            pytest.fail("manual update job did not complete")
    finally:
        task.stop()

    assert "Refresh diagnostics phase completed" in caplog.text
    assert "phase: plugin image generation" in caplog.text
    assert "phase: image hash calculation" in caplog.text
    assert "phase: display manager processing" in caplog.text
    assert "phase: config write" in caplog.text
    assert "Refresh diagnostics summary" in caplog.text
    assert "display_updated=True" in caplog.text


def test_refresh_diagnostics_are_disabled_by_default(monkeypatch, caplog):
    monkeypatch.setattr(refresh_task_module, "get_plugin_instance", lambda plugin_config: FakePlugin())
    task = RefreshTask(FakeDeviceConfig(), FakeDisplayManager())

    caplog.set_level(logging.INFO, logger="refresh_task")
    task.start()

    try:
        job = task.enqueue_manual_update(FakeManualAction("weather"))

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = task.get_manual_update_status(job["id"])
            if status["state"] == "done":
                break
            time.sleep(0.01)
        else:
            pytest.fail("manual update job did not complete")
    finally:
        task.stop()

    assert "Refresh diagnostics summary" not in caplog.text


def test_determine_next_plugin_honors_short_plugin_interval_despite_scheduler_check_interval():
    playlist = Playlist("Default", "00:00", "24:00", [{
        "plugin_id": "weather",
        "name": "Weather",
        "plugin_settings": {},
        "refresh": {"interval": 300},
        "latest_refresh_time": "2026-05-09T08:00:00"
    }])
    config = FakeDeviceConfig(
        playlist,
        values={"scheduler_check_interval_seconds": 3600}
    )
    task = RefreshTask(config, FakeDisplayManager())

    selected_playlist, plugin = task._determine_next_plugin(
        config.get_playlist_manager(),
        config.get_refresh_info(),
        datetime_from_iso("2026-05-09T08:05:00")
    )

    assert selected_playlist is playlist
    assert plugin.name == "Weather"


def test_determine_next_plugin_skips_when_plugin_refresh_not_due():
    playlist = Playlist("Default", "00:00", "24:00", [{
        "plugin_id": "weather",
        "name": "Weather",
        "plugin_settings": {},
        "refresh": {"interval": 300},
        "latest_refresh_time": "2026-05-09T08:00:00"
    }], current_plugin_index=0)
    config = FakeDeviceConfig(playlist)
    task = RefreshTask(config, FakeDisplayManager())

    selected_playlist, plugin = task._determine_next_plugin(
        config.get_playlist_manager(),
        config.get_refresh_info(),
        datetime_from_iso("2026-05-09T08:04:59")
    )

    assert selected_playlist is None
    assert plugin is None
    assert playlist.current_plugin_index == 0


def test_scheduler_check_interval_defaults_and_validates_config():
    task = RefreshTask(FakeDeviceConfig(values={"scheduler_check_interval_seconds": "5"}), FakeDisplayManager())
    assert task._get_scheduler_check_interval_seconds() == 5

    invalid_task = RefreshTask(FakeDeviceConfig(values={"scheduler_check_interval_seconds": "later"}), FakeDisplayManager())
    assert invalid_task._get_scheduler_check_interval_seconds() == RefreshTask.DEFAULT_SCHEDULER_CHECK_INTERVAL_SECONDS


def datetime_from_iso(value):
    from datetime import datetime
    return datetime.fromisoformat(value)
