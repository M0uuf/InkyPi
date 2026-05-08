import sys
import threading
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from display.display_manager import DisplayManager


class FakeDeviceConfig:
    def __init__(self, current_image_file):
        self.current_image_file = str(current_image_file)
        self.values = {
            "orientation": "horizontal",
            "inverted_image": False,
            "image_settings": {}
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
