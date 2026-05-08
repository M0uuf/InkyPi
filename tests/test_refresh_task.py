import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import refresh_task as refresh_task_module
from model import RefreshInfo
from refresh_task import RefreshTask


class FakePlugin:
    config = {"image_settings": []}


class FakePlaylistManager:
    def determine_active_playlist(self, current_dt):
        return None


class FakeDeviceConfig:
    def __init__(self):
        self.refresh_info = RefreshInfo(None, None, None, None)
        self.playlist_manager = FakePlaylistManager()
        self.writes = 0

    def get_config(self, key, default=None):
        return default

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


def test_concurrent_manual_updates_keep_caller_specific_results(monkeypatch):
    monkeypatch.setattr(refresh_task_module, "get_plugin_instance", lambda plugin_config: FakePlugin())
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    expected_error = RuntimeError("second refresh failed")
    errors = {}
    first_errors = []

    task = RefreshTask(FakeDeviceConfig(), FakeDisplayManager())
    task.start()

    def run_first_update():
        try:
            task.manual_update(FakeManualAction("first", first_started, release_first))
        except Exception as exc:
            first_errors.append(exc)

    first_thread = threading.Thread(target=run_first_update)

    def run_second_update():
        second_started.set()
        with pytest.raises(RuntimeError, match="second refresh failed") as exc_info:
            task.manual_update(FakeManualAction("second", exception=expected_error))
        errors["second"] = exc_info.value

    second_thread = threading.Thread(target=run_second_update)

    try:
        first_thread.start()
        assert first_started.wait(timeout=2)

        second_thread.start()
        assert second_started.wait(timeout=2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with task.condition:
                if len(task.manual_update_queue) == 1:
                    break
            time.sleep(0.01)
        else:
            pytest.fail("second manual update was not queued while first update was running")

        release_first.set()

        first_thread.join(timeout=2)
        second_thread.join(timeout=2)
    finally:
        task.stop()

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert first_errors == []
    assert errors["second"] is expected_error
