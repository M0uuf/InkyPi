import sys
import threading
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from display import display_manager as display_manager_module
from display.display_manager import DisplayManager
from utils.image_utils import RESIZE_FILTERS


class FakeDeviceConfig:
    def __init__(self, current_image_file):
        self.current_image_file = str(current_image_file)
        self.values = {
            "orientation": "horizontal",
            "inverted_image": False,
            "image_settings": {},
            "display_low_resource_mode": False
        }

    def get_config(self, key=None, default=None):
        if key is None:
            return self.values
        return self.values.get(key, default)

    def get_resolution(self):
        return (16, 16)


class BlockingDisplay:
    def __init__(self):
        self.active_writes = 0
        self.max_active_writes = 0
        self.lock = threading.Lock()

    def display_image(self, image, image_settings):
        with self.lock:
            self.active_writes += 1
            self.max_active_writes = max(self.max_active_writes, self.active_writes)

        time.sleep(0.05)

        with self.lock:
            self.active_writes -= 1


class CapturingDisplay:
    def __init__(self):
        self.images = []

    def display_image(self, image, image_settings):
        self.images.append(image)


class CloseableDisplay(CapturingDisplay):
    def __init__(self):
        super().__init__()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class FailingCloseDisplay(CapturingDisplay):
    def close(self):
        raise RuntimeError("close failed")


class RaisingDisplay:
    def display_image(self, image, image_settings):
        raise RuntimeError("display failed")


def make_manager(tmp_path, values=None):
    manager = DisplayManager.__new__(DisplayManager)
    manager.device_config = FakeDeviceConfig(tmp_path / "current.png")
    if values:
        manager.device_config.values.update(values)
    manager.display_lock = threading.Lock()
    manager.display = CapturingDisplay()
    return manager


def test_display_manager_serializes_concrete_display_writes(tmp_path):
    manager = DisplayManager.__new__(DisplayManager)
    manager.device_config = FakeDeviceConfig(tmp_path / "current.png")
    manager.display_lock = threading.Lock()
    manager.display = BlockingDisplay()
    image = Image.new("RGB", (16, 16), "white")

    threads = [
        threading.Thread(target=manager.display_image, args=(image.copy(), [])),
        threading.Thread(target=manager.display_image, args=(image.copy(), []))
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert manager.display.max_active_writes == 1


def test_display_manager_skips_noop_resize_and_default_enhancement(monkeypatch, tmp_path):
    manager = make_manager(tmp_path)
    image = Image.new("RGB", (16, 16), "white")

    def fail_resize(*args, **kwargs):
        raise AssertionError("resize should be skipped")

    def fail_enhancement(*args, **kwargs):
        raise AssertionError("enhancement should be skipped")

    monkeypatch.setattr(display_manager_module, "resize_image", fail_resize)
    monkeypatch.setattr(display_manager_module, "apply_image_enhancement", fail_enhancement)

    manager.display_image(image, [])

    assert manager.display.images[0].size == (16, 16)
    assert Path(manager.device_config.current_image_file).exists()


def test_display_manager_preserves_mode_normalization_when_enhancement_is_default(tmp_path):
    manager = make_manager(tmp_path)
    image = Image.new("RGBA", (16, 16), "white")

    manager.display_image(image, [])

    assert manager.display.images[0].mode == "RGB"


def test_display_manager_uses_low_resource_resize_filter(monkeypatch, tmp_path):
    manager = make_manager(tmp_path, {"display_low_resource_mode": True})
    image = Image.new("RGB", (32, 16), "white")
    captured = {}

    def capture_resize(image, desired_size, image_settings, resample_filter):
        captured["filter"] = resample_filter
        return Image.new("RGB", desired_size, "white")

    monkeypatch.setattr(display_manager_module, "resize_image", capture_resize)

    manager.display_image(image, [])

    assert captured["filter"] == RESIZE_FILTERS["bicubic"]


def test_display_manager_uses_configured_resize_filter(monkeypatch, tmp_path):
    manager = make_manager(tmp_path, {
        "display_low_resource_mode": True,
        "display_resize_filter": "bilinear"
    })
    image = Image.new("RGB", (32, 16), "white")
    captured = {}

    def capture_resize(image, desired_size, image_settings, resample_filter):
        captured["filter"] = resample_filter
        return Image.new("RGB", desired_size, "white")

    monkeypatch.setattr(display_manager_module, "resize_image", capture_resize)

    manager.display_image(image, [])

    assert captured["filter"] == RESIZE_FILTERS["bilinear"]


def test_display_manager_logs_processing_phase_timing(caplog, tmp_path):
    manager = make_manager(tmp_path)
    image = Image.new("RGB", (16, 16), "white")

    caplog.set_level("INFO", logger="display.display_manager")

    manager.display_image(image, [])

    log_text = caplog.text
    assert "Display pipeline save current image completed" in log_text
    assert "Display pipeline orientation transform completed" in log_text
    assert "Display pipeline resize skipped" in log_text
    assert "Display pipeline enhancement skipped" in log_text
    assert "Display pipeline enhancement phase completed" in log_text
    assert "Display pipeline concrete display completed" in log_text
    assert "Display pipeline total completed" in log_text


def test_display_manager_closes_replaced_internal_images_in_low_resource_mode(monkeypatch, tmp_path):
    manager = make_manager(tmp_path, {
        "display_low_resource_mode": True,
        "orientation": "vertical"
    })
    original = Image.new("RGB", (16, 16), "white")
    oriented = Image.new("RGB", (32, 16), "blue")
    resized = Image.new("RGB", (16, 16), "red")
    closed = []

    original_close = original.close
    oriented_close = oriented.close
    resized_close = resized.close

    def close_original():
        closed.append("original")
        original_close()

    def close_oriented():
        closed.append("oriented")
        oriented_close()

    def close_resized():
        closed.append("resized")
        resized_close()

    original.close = close_original
    oriented.close = close_oriented
    resized.close = close_resized

    monkeypatch.setattr(display_manager_module, "change_orientation", lambda image, orientation: oriented)
    monkeypatch.setattr(
        display_manager_module,
        "resize_image",
        lambda image, desired_size, image_settings, resample_filter: resized
    )

    manager.display_image(original, [])

    assert closed == ["oriented"]
    assert manager.display.images == [resized]
    assert manager.display.images[0].size == (16, 16)


def test_display_manager_collects_only_in_low_resource_mode(monkeypatch, tmp_path):
    collect_calls = []
    monkeypatch.setattr(display_manager_module.gc, "collect", lambda: collect_calls.append("collect"))

    make_manager(tmp_path, {"display_low_resource_mode": False}).display_image(
        Image.new("RGB", (16, 16), "white"),
        []
    )
    assert collect_calls == []

    make_manager(tmp_path, {"display_low_resource_mode": True}).display_image(
        Image.new("RGB", (16, 16), "white"),
        []
    )
    assert collect_calls == ["collect"]


def test_display_manager_collects_in_low_resource_mode_when_display_raises(monkeypatch, tmp_path):
    manager = make_manager(tmp_path, {"display_low_resource_mode": True})
    manager.display = RaisingDisplay()
    collect_calls = []
    monkeypatch.setattr(display_manager_module.gc, "collect", lambda: collect_calls.append("collect"))

    try:
        manager.display_image(Image.new("RGB", (16, 16), "white"), [])
    except RuntimeError:
        pass

    assert collect_calls == ["collect"]


def test_display_manager_close_calls_concrete_display_under_lock(tmp_path):
    manager = make_manager(tmp_path)
    display = CloseableDisplay()
    manager.display = display

    manager.close()

    assert display.close_calls == 1


def test_display_manager_close_is_harmless_without_cleanup_hook(tmp_path, caplog):
    manager = make_manager(tmp_path)

    caplog.set_level("INFO", logger="display.display_manager")
    manager.close()

    assert "has no cleanup hook" in caplog.text


def test_display_manager_close_logs_and_swallows_cleanup_exceptions(tmp_path, caplog):
    manager = make_manager(tmp_path)
    manager.display = FailingCloseDisplay()

    caplog.set_level("ERROR", logger="display.display_manager")
    manager.close()

    assert "Exception during display cleanup" in caplog.text
