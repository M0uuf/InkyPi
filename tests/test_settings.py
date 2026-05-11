import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.settings_utils import SettingsValidationError, build_device_settings_update


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "src" / "templates" / "settings.html"


def valid_settings_form(interval="2", unit="minute"):
    return {
        "deviceName": "Kitchen Display",
        "orientation": "horizontal",
        "timezoneName": "UTC",
        "timeFormat": "24h",
        "interval": interval,
        "unit": unit,
        "saturation": "1.0",
        "brightness": "1.0",
        "sharpness": "1.0",
        "contrast": "1.0",
        "currentImagePollIntervalSeconds": "15",
        "displayLowResourceMode": "auto",
        "displayResizeFilter": "",
        "webServerThreads": "2",
        "waveshareClearBeforeDisplay": "on",
        "waveshareSleepAfterDisplay": "on",
        "waveshareReinitializeBeforeDisplay": "on"
    }


def test_settings_template_describes_scheduler_check_interval():
    template = TEMPLATE_PATH.read_text()

    assert "Scheduler Check Interval" in template
    assert "checks whether any plugin instance is due" in template
    assert "Plugin Cycle Interval" not in template
    assert "pluginCycleIntervalSeconds" not in template
    assert "schedulerCheckIntervalSeconds" in template
    assert "scheduler_check_interval_seconds" in template


def test_settings_template_exposes_advanced_settings():
    template = TEMPLATE_PATH.read_text()

    assert "Advanced Settings" in template
    assert "currentImagePollIntervalSeconds" in template
    assert "displayLowResourceMode" in template
    assert "displayResizeFilter" in template
    assert "performanceDiagnostics" in template
    assert "waveshareClearBeforeDisplay" in template
    assert "waveshareSleepAfterDisplay" in template
    assert "waveshareReinitializeBeforeDisplay" in template
    assert "webServerThreads" in template


def test_settings_update_uses_scheduler_check_interval_key():
    settings, scheduler_interval_changed = build_device_settings_update(
        valid_settings_form(interval="2", unit="minute"),
        previous_config={"scheduler_check_interval_seconds": 60}
    )

    assert settings["scheduler_check_interval_seconds"] == 120
    assert "plugin_cycle_interval_seconds" not in settings
    assert scheduler_interval_changed is True


def test_settings_update_persists_advanced_settings():
    form_data = valid_settings_form()
    form_data.update({
        "currentImagePollIntervalSeconds": "30",
        "displayLowResourceMode": "true",
        "displayResizeFilter": "bicubic",
        "performanceDiagnostics": "on",
        "webServerThreads": "4"
    })
    form_data.pop("waveshareSleepAfterDisplay")

    settings, scheduler_interval_changed = build_device_settings_update(
        form_data,
        previous_config={"scheduler_check_interval_seconds": 120}
    )

    assert scheduler_interval_changed is False
    assert settings["current_image_poll_interval_seconds"] == 30
    assert settings["display_low_resource_mode"] is True
    assert settings["display_resize_filter"] == "bicubic"
    assert settings["performance_diagnostics"] is True
    assert settings["waveshare_clear_before_display"] is True
    assert settings["waveshare_sleep_after_display"] is False
    assert settings["waveshare_reinitialize_before_display"] is True
    assert settings["web_server_threads"] == 4


def test_settings_update_preserves_auto_advanced_defaults():
    settings, _ = build_device_settings_update(
        valid_settings_form(),
        previous_config={"scheduler_check_interval_seconds": 60}
    )

    assert settings["display_low_resource_mode"] is None
    assert settings["display_resize_filter"] is None
    assert settings["performance_diagnostics"] is False


def test_settings_update_marks_scheduler_interval_unchanged():
    settings, scheduler_interval_changed = build_device_settings_update(
        valid_settings_form(interval="2", unit="minute"),
        previous_config={"scheduler_check_interval_seconds": "120"}
    )

    assert settings["scheduler_check_interval_seconds"] == 120
    assert scheduler_interval_changed is False


def test_settings_validation_uses_scheduler_interval_name():
    form_data = valid_settings_form()
    form_data["unit"] = "second"

    with pytest.raises(SettingsValidationError, match="Scheduler check interval unit is required"):
        build_device_settings_update(form_data, previous_config={"scheduler_check_interval_seconds": 60})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("currentImagePollIntervalSeconds", "4", "Current image poll interval must be between 5 and 3600"),
        ("webServerThreads", "9", "Web server threads must be between 1 and 8"),
        ("displayResizeFilter", "mitchell", "Display resize filter is invalid"),
        ("displayLowResourceMode", "sometimes", "Display low-resource mode must be Auto, Enabled, or Disabled"),
        ("performanceDiagnostics", "maybe", "Performance diagnostics must be a boolean value"),
        ("waveshareClearBeforeDisplay", "maybe", "Waveshare clear before display must be a boolean value")
    ]
)
def test_settings_validation_rejects_invalid_advanced_settings(field, value, message):
    form_data = valid_settings_form()
    form_data[field] = value

    with pytest.raises(SettingsValidationError, match=message):
        build_device_settings_update(form_data, previous_config={"scheduler_check_interval_seconds": 60})
