import gc
import os
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils import image_loader as image_loader_module
from utils.image_loader import AdaptiveImageLoader


class ImageOpenSpy:
    def __init__(self, image, closed_sources):
        self.image = image
        self.closed_sources = closed_sources

    def __enter__(self):
        return self.image.__enter__()

    def __exit__(self, exc_type, exc, traceback):
        self.closed_sources.append(self.image)
        return self.image.__exit__(exc_type, exc, traceback)

    def __getattr__(self, name):
        return getattr(self.image, name)


def make_loader(low_resource):
    loader = AdaptiveImageLoader.__new__(AdaptiveImageLoader)
    loader.is_low_resource = low_resource
    return loader


def save_test_image(path, size=(24, 16), mode="RGB"):
    Image.new(mode, size, "white").save(path)


def assert_usable_image(image):
    assert image is not None
    assert image.size[0] > 0
    assert image.copy().tobytes()


def test_fast_file_load_closes_source_and_returns_detached_image(monkeypatch, tmp_path):
    image_path = tmp_path / "image.png"
    save_test_image(image_path)
    closed_sources = []
    real_open = image_loader_module.Image.open

    def spy_open(source):
        return ImageOpenSpy(real_open(source), closed_sources)

    monkeypatch.setattr(image_loader_module.Image, "open", spy_open)

    image = make_loader(low_resource=False).from_file(str(image_path), (24, 16), resize=False)

    assert len(closed_sources) == 1
    assert_usable_image(image)


def test_low_resource_file_load_closes_source_and_keeps_draft_mode_resize(monkeypatch, tmp_path):
    image_path = tmp_path / "large.jpg"
    save_test_image(image_path, size=(96, 64))
    closed_sources = []
    draft_calls = []
    real_open = image_loader_module.Image.open

    class DraftSpy(ImageOpenSpy):
        def __enter__(self):
            image = super().__enter__()
            original_draft = image.draft

            def draft(mode, size):
                draft_calls.append((mode, size))
                return original_draft(mode, size)

            image.draft = draft
            return image

    def spy_open(source):
        return DraftSpy(real_open(source), closed_sources)

    monkeypatch.setattr(image_loader_module.Image, "open", spy_open)

    image = make_loader(low_resource=True).from_file(str(image_path), (24, 16), resize=True)

    assert len(closed_sources) == 1
    assert draft_calls == [("RGB", (48, 32))]
    assert image.size == (24, 16)
    assert_usable_image(image)


def test_bytesio_load_closes_source_and_returns_detached_image(monkeypatch):
    data = BytesIO()
    Image.new("RGB", (24, 16), "white").save(data, format="PNG")
    data.seek(0)
    closed_sources = []
    real_open = image_loader_module.Image.open

    def spy_open(source):
        return ImageOpenSpy(real_open(source), closed_sources)

    monkeypatch.setattr(image_loader_module.Image, "open", spy_open)

    image = make_loader(low_resource=False).from_bytesio(data, (24, 16), resize=False)

    assert len(closed_sources) == 1
    assert_usable_image(image)


def test_invalid_file_load_returns_none_and_does_not_leave_fd_open(tmp_path):
    image_path = tmp_path / "not-an-image.txt"
    image_path.write_text("not image data", encoding="utf-8")

    image = make_loader(low_resource=False).from_file(str(image_path), (24, 16), resize=False)

    assert image is None


def test_repeated_file_loads_do_not_increase_file_descriptors(tmp_path):
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.exists():
        return

    image_path = tmp_path / "image.png"
    save_test_image(image_path)
    loader = make_loader(low_resource=False)
    before = len(os.listdir(fd_dir))

    for _ in range(20):
        image = loader.from_file(str(image_path), (24, 16), resize=False)
        assert_usable_image(image)
        image.close()

    gc.collect()
    after = len(os.listdir(fd_dir))

    assert after <= before + 1
