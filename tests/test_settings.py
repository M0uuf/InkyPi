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
        "contrast": "1.0"
    }


def test_settings_template_describes_scheduler_check_interval():
    template = TEMPLATE_PATH.read_text()

    assert "Scheduler Check Interval" in template
    assert "checks whether any plugin instance is due" in template
    assert "Plugin Cycle Interval" not in template
    assert "pluginCycleIntervalSeconds" not in template
    assert "schedulerCheckIntervalSeconds" in template
    assert "scheduler_check_interval_seconds" in template


def test_settings_update_uses_scheduler_check_interval_key():
    settings, scheduler_interval_changed = build_device_settings_update(
        valid_settings_form(interval="2", unit="minute"),
        previous_scheduler_check_interval=60
    )

    assert settings["scheduler_check_interval_seconds"] == 120
    assert "plugin_cycle_interval_seconds" not in settings
    assert scheduler_interval_changed is True


def test_settings_update_marks_scheduler_interval_unchanged():
    settings, scheduler_interval_changed = build_device_settings_update(
        valid_settings_form(interval="2", unit="minute"),
        previous_scheduler_check_interval="120"
    )

    assert settings["scheduler_check_interval_seconds"] == 120
    assert scheduler_interval_changed is False


def test_settings_validation_uses_scheduler_interval_name():
    form_data = valid_settings_form()
    form_data["unit"] = "second"

    with pytest.raises(SettingsValidationError, match="Scheduler check interval unit is required"):
        build_device_settings_update(form_data, previous_scheduler_check_interval=60)
