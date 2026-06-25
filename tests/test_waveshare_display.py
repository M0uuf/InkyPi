import sys
import logging
from types import SimpleNamespace
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from display import waveshare_display as waveshare_display_module
from display.waveshare_display import WaveshareDisplay, get_bool_config


class FakeDeviceConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get_config(self, key, default=None):
        return self.values.get(key, default)


class FakeEpd:
    def __init__(self):
        self.init_calls = 0
        self.clear_calls = 0
        self.display_calls = []
        self.sleep_calls = 0
        self.buffer_calls = []

    def Init(self):
        self.init_calls += 1

    def Clear(self):
        self.clear_calls += 1

    def getbuffer(self, image):
        self.buffer_calls.append(image)
        return f"buffer-{len(self.buffer_calls)}"

    def display(self, *buffers):
        self.display_calls.append(buffers)

    def sleep(self):
        self.sleep_calls += 1


class FakeCleanupEpd(FakeEpd):
    def __init__(self):
        super().__init__()
        self.cleanup_calls = 0

    def module_exit(self):
        self.cleanup_calls += 1


class FailingCleanupEpd(FakeEpd):
    def module_exit(self):
        raise RuntimeError("cleanup failed")


class RaisingDisplayEpd(FakeEpd):
    def display(self, *buffers):
        self.display_calls.append(buffers)
        raise RuntimeError("display failed")


def make_display(config_values=None, bi_color=False):
    display = WaveshareDisplay.__new__(WaveshareDisplay)
    display.device_config = FakeDeviceConfig(config_values)
    display.epd_display = FakeEpd()
    display.epd_display_init = display.epd_display.Init
    display.bi_color_display = bi_color
    return display


def test_bool_config_accepts_common_string_values():
    config = FakeDeviceConfig({
        "enabled": "true",
        "disabled": "off"
    })

    assert get_bool_config(config, "enabled", False) is True
    assert get_bool_config(config, "disabled", True) is False
    assert get_bool_config(config, "missing", True) is True


def test_bool_config_warns_and_uses_default_for_unknown_string(caplog):
    config = FakeDeviceConfig({"enabled": "treu"})

    caplog.set_level(logging.WARNING, logger="display.waveshare_display")

    assert get_bool_config(config, "enabled", True) is True
    assert "Invalid boolean config value" in caplog.text


def test_waveshare_display_keeps_existing_default_sequence(caplog):
    display = make_display()
    image = Image.new("RGB", (4, 4), "white")

    caplog.set_level(logging.INFO, logger="display.waveshare_display")
    display.display_image(image)

    assert display.epd_display.init_calls == 1
    assert display.epd_display.clear_calls == 1
    assert display.epd_display.display_calls == [("buffer-1",)]
    assert display.epd_display.sleep_calls == 1
    log_text = caplog.text
    assert "Waveshare init completed" in log_text
    assert "Waveshare clear completed" in log_text
    assert "Waveshare buffer conversion completed" in log_text
    assert "Waveshare display update completed" in log_text
    assert "Waveshare sleep completed" in log_text


def test_waveshare_display_can_skip_reinitialize_clear_and_sleep():
    display = make_display({
        "waveshare_reinitialize_before_display": False,
        "waveshare_clear_before_display": False,
        "waveshare_sleep_after_display": False
    })
    image = Image.new("RGB", (4, 4), "white")

    display.display_image(image)

    assert display.epd_display.init_calls == 0
    assert display.epd_display.clear_calls == 0
    assert display.epd_display.display_calls == [("buffer-1",)]
    assert display.epd_display.sleep_calls == 0


def test_waveshare_display_forces_reinitialize_when_sleep_enabled(caplog):
    display = make_display({
        "waveshare_reinitialize_before_display": False,
        "waveshare_sleep_after_display": True
    })
    image = Image.new("RGB", (4, 4), "white")

    caplog.set_level(logging.WARNING, logger="display.waveshare_display")
    display.display_image(image)

    assert display.epd_display.init_calls == 1
    assert display.epd_display.sleep_calls == 1
    assert "forcing reinitialize before display" in caplog.text


def test_waveshare_bi_color_display_converts_two_buffers():
    display = make_display(bi_color=True)
    image = Image.new("RGB", (4, 4), "white")

    display.display_image(image)

    assert len(display.epd_display.buffer_calls) == 2
    assert display.epd_display.display_calls == [("buffer-1", "buffer-2")]


def test_waveshare_bi_color_display_closes_generated_layers(monkeypatch):
    display = make_display(bi_color=True)
    image = Image.new("RGB", (4, 4), "white")
    black_layer = Image.new("1", (4, 4), 1)
    red_layer = Image.new("1", (4, 4), 1)
    closed = []

    black_close = black_layer.close
    red_close = red_layer.close

    def close_black():
        closed.append("black")
        black_close()

    def close_red():
        closed.append("red")
        red_close()

    black_layer.close = close_black
    red_layer.close = close_red
    monkeypatch.setattr(
        waveshare_display_module,
        "split_image_for_bi_color_epd",
        lambda source_image: (black_layer, red_layer)
    )

    display.display_image(image)

    assert closed == ["black", "red"]
    assert image.size == (4, 4)


def test_waveshare_bi_color_display_closes_layers_when_display_raises(monkeypatch):
    display = make_display(bi_color=True)
    display.epd_display = RaisingDisplayEpd()
    display.epd_display_init = display.epd_display.Init
    image = Image.new("RGB", (4, 4), "white")
    black_layer = Image.new("1", (4, 4), 1)
    red_layer = Image.new("1", (4, 4), 1)
    closed = []

    black_layer.close = lambda: closed.append("black")
    red_layer.close = lambda: closed.append("red")
    monkeypatch.setattr(
        waveshare_display_module,
        "split_image_for_bi_color_epd",
        lambda source_image: (black_layer, red_layer)
    )

    try:
        display.display_image(image)
    except RuntimeError:
        pass

    assert closed == ["black", "red"]


def test_waveshare_close_calls_sleep_and_module_cleanup_hook():
    display = make_display()
    display.epd_display = FakeCleanupEpd()

    display.close()

    assert display.epd_display.sleep_calls == 1
    assert display.epd_display.cleanup_calls == 1


def test_waveshare_close_calls_epdconfig_cleanup_hook_with_cleanup_argument():
    calls = []

    def module_exit(cleanup):
        calls.append(cleanup)

    display = make_display()
    display.epd_module = SimpleNamespace(epdconfig=SimpleNamespace(module_exit=module_exit))

    display.close()

    assert calls == [True]


def test_waveshare_close_is_safe_without_known_cleanup_hook(caplog):
    display = make_display()

    caplog.set_level(logging.INFO, logger="display.waveshare_display")
    display.close()

    assert display.epd_display.sleep_calls == 1
    assert "No Waveshare driver cleanup hook found" in caplog.text


def test_waveshare_close_logs_and_swallows_cleanup_exceptions(caplog):
    display = make_display()
    display.epd_display = FailingCleanupEpd()

    caplog.set_level(logging.ERROR, logger="display.waveshare_display")
    display.close()

    assert display.epd_display.sleep_calls == 1
    assert "Exception during Waveshare cleanup hook epd_display.module_exit" in caplog.text
