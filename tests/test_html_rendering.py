import logging
import stat
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


def test_take_screenshot_html_cache_key_includes_extra_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setenv(image_utils.HTML_RENDER_CACHE_DIR_ENV, str(tmp_path))

    calls = []

    def fake_take_screenshot(target, dimensions, timeout_ms=None):
        calls.append((dimensions, timeout_ms))
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(image_utils, "take_screenshot", fake_take_screenshot)

    image_utils.take_screenshot_html("<html>same</html>", (16, 12), cache_extra="css-v1")
    image_utils.take_screenshot_html("<html>same</html>", (16, 12), cache_extra="css-v2")

    assert len(calls) == 2
    assert len(list(tmp_path.glob("*.png"))) == 2


def test_default_html_render_cache_directory_is_private(monkeypatch, tmp_path):
    monkeypatch.delenv(image_utils.HTML_RENDER_CACHE_DIR_ENV, raising=False)
    monkeypatch.setattr(image_utils.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_take_screenshot(target, dimensions, timeout_ms=None):
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(image_utils, "take_screenshot", fake_take_screenshot)

    image_utils.take_screenshot_html("<html>private</html>", (16, 12))

    cache_dir = tmp_path / "inkypi-html-render-cache"
    assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o700


def test_take_screenshot_logs_chromium_duration(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="utils.image_utils")
    monkeypatch.setattr(image_utils, "_find_chromium_binary", lambda: "chromium")

    def fake_run(command, stdout, stderr, timeout, check):
        screenshot_arg = next(arg for arg in command if arg.startswith("--screenshot="))
        screenshot_path = screenshot_arg.split("=", 1)[1]
        Image.new("RGB", (10, 8), "white").save(screenshot_path)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(image_utils.subprocess, "run", fake_run)

    image = image_utils.take_screenshot("/tmp/source.html", (10, 8))

    assert image.size == (10, 8)
    assert "Starting Chromium screenshot capture" in caplog.text
    assert "Chromium screenshot process completed" in caplog.text


def test_take_screenshot_html_logs_diagnostics_when_enabled(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="utils.image_utils")
    monkeypatch.setenv(image_utils.HTML_RENDER_CACHE_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(image_utils, "_find_chromium_binary", lambda: "chromium")

    def fake_run(command, stdout, stderr, timeout, check):
        screenshot_arg = next(arg for arg in command if arg.startswith("--screenshot="))
        screenshot_path = screenshot_arg.split("=", 1)[1]
        Image.new("RGB", (10, 8), "white").save(screenshot_path)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(image_utils.subprocess, "run", fake_run)

    image = image_utils.take_screenshot_html(
        "<html><body>diagnostics</body></html>",
        (10, 8),
        diagnostics_enabled=True
    )

    assert image.size == (10, 8)
    assert "HTML screenshot diagnostics phase completed" in caplog.text
    assert "phase: temporary html write" in caplog.text
    assert "phase: chromium screenshot" in caplog.text
    assert "Chromium screenshot diagnostics phase completed" in caplog.text
    assert "phase: chromium process" in caplog.text
    assert "phase: png load" in caplog.text
    assert "HTML screenshot diagnostics summary" in caplog.text


def test_take_screenshot_passes_hard_timeout_and_does_not_capture_stdout(monkeypatch):
    monkeypatch.setattr(image_utils, "_find_chromium_binary", lambda: "chromium")
    captured = {}

    def fake_run(command, stdout, stderr, timeout, check):
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["timeout"] = timeout
        captured["check"] = check
        screenshot_arg = next(arg for arg in command if arg.startswith("--screenshot="))
        screenshot_path = screenshot_arg.split("=", 1)[1]
        Image.new("RGB", (10, 8), "white").save(screenshot_path)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(image_utils.subprocess, "run", fake_run)

    image = image_utils.take_screenshot("/tmp/source.html", (10, 8), timeout_ms=5000)

    assert image.size == (10, 8)
    assert captured["stdout"] == image_utils.subprocess.DEVNULL
    assert captured["stderr"] == image_utils.subprocess.PIPE
    assert captured["timeout"] == 15
    assert captured["check"] is False


def test_take_screenshot_timeout_returns_none_and_removes_temp_png(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="utils.image_utils")
    monkeypatch.setattr(image_utils, "_find_chromium_binary", lambda: "chromium")
    screenshot_paths = []

    def fake_run(command, stdout, stderr, timeout, check):
        screenshot_arg = next(arg for arg in command if arg.startswith("--screenshot="))
        screenshot_path = screenshot_arg.split("=", 1)[1]
        screenshot_paths.append(Path(screenshot_path))
        Image.new("RGB", (10, 8), "white").save(screenshot_path)
        raise image_utils.subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(image_utils.subprocess, "run", fake_run)

    image = image_utils.take_screenshot("/tmp/source.html", (10, 8), timeout_ms=1000)

    assert image is None
    assert "Chromium screenshot timed out after 11.0s" in caplog.text
    assert len(screenshot_paths) == 1
    assert not screenshot_paths[0].exists()


def test_take_screenshot_nonzero_return_logs_stderr(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="utils.image_utils")
    monkeypatch.setattr(image_utils, "_find_chromium_binary", lambda: "chromium")

    def fake_run(command, stdout, stderr, timeout, check):
        return SimpleNamespace(returncode=1, stderr=b"chromium failed")

    monkeypatch.setattr(image_utils.subprocess, "run", fake_run)

    image = image_utils.take_screenshot("/tmp/source.html", (10, 8))

    assert image is None
    assert "Failed to take screenshot (return code: 1)" in caplog.text
    assert "Chromium stderr: chromium failed" in caplog.text


def test_base_plugin_render_image_logs_template_and_screenshot(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="plugins.base_plugin.base_plugin")

    plugin = BasePlugin.__new__(BasePlugin)
    plugin.config = {"id": "test"}
    plugin.render_dir = "/tmp"
    plugin.env = Environment(loader=DictLoader({"test.html": "<p>{{ value }}</p>"}))

    captured = {}

    def fake_take_screenshot_html(rendered_html, dimensions, cache_extra=None):
        captured["rendered_html"] = rendered_html
        captured["dimensions"] = dimensions
        captured["cache_extra"] = cache_extra
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(base_plugin_module, "take_screenshot_html", fake_take_screenshot_html)

    image = plugin.render_image((20, 10), "test.html", template_params={"value": "hello"})

    assert image.size == (20, 10)
    assert captured["rendered_html"] == "<p>hello</p>"
    assert captured["dimensions"] == (20, 10)
    assert captured["cache_extra"]
    assert "Rendered HTML template for plugin 'test'" in caplog.text
    assert "Rendered plugin 'test' HTML to image" in caplog.text


def test_base_plugin_render_image_logs_diagnostics_when_enabled(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="plugins.base_plugin.base_plugin")

    plugin = BasePlugin.__new__(BasePlugin)
    plugin.config = {"id": "test"}
    plugin.render_dir = "/tmp"
    plugin.env = Environment(loader=DictLoader({"test.html": "<p>{{ value }}</p>"}))

    def fake_take_screenshot_html(rendered_html, dimensions, cache_extra=None, diagnostics_enabled=False):
        assert diagnostics_enabled is True
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(base_plugin_module, "take_screenshot_html", fake_take_screenshot_html)

    image = plugin.render_image(
        (20, 10),
        "test.html",
        template_params={"value": "hello"},
        diagnostics_enabled=True
    )

    assert image.size == (20, 10)
    assert "HTML render diagnostics plugin=test phase completed" in caplog.text
    assert "phase: jinja render" in caplog.text
    assert "phase: html screenshot" in caplog.text
    assert "HTML render diagnostics plugin=test summary" in caplog.text


def test_base_plugin_render_image_cache_misses_when_css_changes(monkeypatch, tmp_path):
    monkeypatch.setenv(image_utils.HTML_RENDER_CACHE_DIR_ENV, str(tmp_path / "cache"))

    base_render_dir = tmp_path / "base_render"
    plugin_render_dir = tmp_path / "plugin_render"
    base_render_dir.mkdir()
    plugin_render_dir.mkdir()
    (base_render_dir / "plugin.css").write_text("body { color: black; }")
    plugin_css = plugin_render_dir / "test.css"
    plugin_css.write_text(".plugin { color: black; }")

    monkeypatch.setattr(base_plugin_module, "BASE_PLUGIN_RENDER_DIR", str(base_render_dir))

    plugin = BasePlugin.__new__(BasePlugin)
    plugin.config = {"id": "test"}
    plugin.render_dir = str(plugin_render_dir)
    plugin.env = Environment(loader=DictLoader({"test.html": "<p>same html</p>"}))

    calls = []

    def fake_take_screenshot(target, dimensions, timeout_ms=None):
        calls.append(target)
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(image_utils, "take_screenshot", fake_take_screenshot)

    plugin.render_image((20, 10), "test.html", css_file="test.css", template_params={})
    plugin_css.write_text(".plugin { color: white; padding: 1px; }")
    plugin.render_image((20, 10), "test.html", css_file="test.css", template_params={})

    assert len(calls) == 2
