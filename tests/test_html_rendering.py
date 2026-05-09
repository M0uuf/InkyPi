import logging
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jinja2 import DictLoader, Environment

from plugins.base_plugin.base_plugin import BasePlugin
import plugins.base_plugin.base_plugin as base_plugin_module
import utils.image_utils as image_utils


def test_take_screenshot_html_uses_disk_cache(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="utils.image_utils")
    monkeypatch.setenv(image_utils.HTML_RENDER_CACHE_DIR_ENV, str(tmp_path))

    calls = []

    def fake_take_screenshot(target, dimensions, timeout_ms=None):
        calls.append((target, dimensions, timeout_ms))
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(image_utils, "take_screenshot", fake_take_screenshot)

    first_image = image_utils.take_screenshot_html("<html>same</html>", (16, 12))
    second_image = image_utils.take_screenshot_html("<html>same</html>", (16, 12))

    assert first_image.size == (16, 12)
    assert second_image.size == (16, 12)
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.png"))) == 1
    assert "HTML screenshot cache miss" in caplog.text
    assert "HTML screenshot cache hit" in caplog.text


def test_take_screenshot_html_cache_key_includes_dimensions(monkeypatch, tmp_path):
    monkeypatch.setenv(image_utils.HTML_RENDER_CACHE_DIR_ENV, str(tmp_path))

    calls = []

    def fake_take_screenshot(target, dimensions, timeout_ms=None):
        calls.append(dimensions)
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(image_utils, "take_screenshot", fake_take_screenshot)

    image_utils.take_screenshot_html("<html>same</html>", (16, 12))
    image_utils.take_screenshot_html("<html>same</html>", (12, 16))

    assert calls == [(16, 12), (12, 16)]
    assert len(list(tmp_path.glob("*.png"))) == 2


def test_take_screenshot_logs_chromium_duration(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="utils.image_utils")
    monkeypatch.setattr(image_utils, "_find_chromium_binary", lambda: "chromium")

    def fake_run(command, capture_output, check):
        screenshot_arg = next(arg for arg in command if arg.startswith("--screenshot="))
        screenshot_path = screenshot_arg.split("=", 1)[1]
        Image.new("RGB", (10, 8), "white").save(screenshot_path)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(image_utils.subprocess, "run", fake_run)

    image = image_utils.take_screenshot("/tmp/source.html", (10, 8))

    assert image.size == (10, 8)
    assert "Starting Chromium screenshot capture" in caplog.text
    assert "Chromium screenshot process completed" in caplog.text


def test_base_plugin_render_image_logs_template_and_screenshot(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="plugins.base_plugin.base_plugin")

    plugin = BasePlugin.__new__(BasePlugin)
    plugin.config = {"id": "test"}
    plugin.render_dir = "/tmp"
    plugin.env = Environment(loader=DictLoader({"test.html": "<p>{{ value }}</p>"}))

    captured = {}

    def fake_take_screenshot_html(rendered_html, dimensions):
        captured["rendered_html"] = rendered_html
        captured["dimensions"] = dimensions
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(base_plugin_module, "take_screenshot_html", fake_take_screenshot_html)

    image = plugin.render_image((20, 10), "test.html", template_params={"value": "hello"})

    assert image.size == (20, 10)
    assert captured == {"rendered_html": "<p>hello</p>", "dimensions": (20, 10)}
    assert "Rendered HTML template for plugin 'test'" in caplog.text
    assert "Rendered plugin 'test' HTML to image" in caplog.text
