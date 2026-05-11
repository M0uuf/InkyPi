from utils.time_utils import calculate_seconds


class SettingsValidationError(ValueError):
    pass


RESIZE_FILTER_OPTIONS = {"nearest", "bilinear", "bicubic", "lanczos"}


def _parse_positive_int(form_data, key, label, minimum=1, maximum=86400):
    raw_value = form_data.get(key)
    if raw_value is None or raw_value == "":
        raise SettingsValidationError(f"{label} is required")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise SettingsValidationError(f"{label} must be a whole number")
    if value < minimum or value > maximum:
        raise SettingsValidationError(f"{label} must be between {minimum} and {maximum}")
    return value


def _parse_checkbox(form_data, key, label):
    raw_value = form_data.get(key)
    if raw_value is None:
        return False
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise SettingsValidationError(f"{label} must be a boolean value")


def _parse_optional_bool(form_data, key, label):
    raw_value = form_data.get(key, "auto")
    if raw_value == "auto":
        return None
    if raw_value == "true":
        return True
    if raw_value == "false":
        return False
    raise SettingsValidationError(f"{label} must be Auto, Enabled, or Disabled")


def _parse_resize_filter(form_data):
    raw_value = form_data.get("displayResizeFilter", "")
    if raw_value == "":
        return None
    if raw_value not in RESIZE_FILTER_OPTIONS:
        raise SettingsValidationError("Display resize filter is invalid")
    return raw_value


def _normalize_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def build_device_settings_update(form_data, previous_config=None):
    if isinstance(previous_config, dict):
        previous_scheduler_check_interval = previous_config.get("scheduler_check_interval_seconds")
    else:
        previous_scheduler_check_interval = previous_config

    unit = form_data.get('unit')
    interval = form_data.get("interval")
    time_format = form_data.get("timeFormat")

    if not unit or unit not in ["minute", "hour"]:
        raise SettingsValidationError("Scheduler check interval unit is required")
    if not interval or not interval.isnumeric():
        raise SettingsValidationError("Scheduler check interval is required")
    if not form_data.get("timezoneName"):
        raise SettingsValidationError("Time Zone is required")
    if not time_format or time_format not in ["12h", "24h"]:
        raise SettingsValidationError("Time format is required")

    scheduler_check_interval_seconds = calculate_seconds(int(interval), unit)
    if scheduler_check_interval_seconds > 86400 or scheduler_check_interval_seconds <= 0:
        raise SettingsValidationError("Scheduler check interval must be less than 24 hours")

    current_image_poll_interval_seconds = _parse_positive_int(
        form_data,
        "currentImagePollIntervalSeconds",
        "Current image poll interval",
        minimum=5,
        maximum=3600
    )
    web_server_threads = _parse_positive_int(
        form_data,
        "webServerThreads",
        "Web server threads",
        minimum=1,
        maximum=8
    )

    settings = {
        "name": form_data.get("deviceName"),
        "orientation": form_data.get("orientation"),
        "inverted_image": form_data.get("invertImage"),
        "log_system_stats": form_data.get("logSystemStats"),
        "timezone": form_data.get("timezoneName"),
        "time_format": form_data.get("timeFormat"),
        "scheduler_check_interval_seconds": scheduler_check_interval_seconds,
        "current_image_poll_interval_seconds": current_image_poll_interval_seconds,
        "display_low_resource_mode": _parse_optional_bool(
            form_data,
            "displayLowResourceMode",
            "Display low-resource mode"
        ),
        "display_resize_filter": _parse_resize_filter(form_data),
        "performance_diagnostics": _parse_checkbox(
            form_data,
            "performanceDiagnostics",
            "Performance diagnostics"
        ),
        "waveshare_clear_before_display": _parse_checkbox(
            form_data,
            "waveshareClearBeforeDisplay",
            "Waveshare clear before display"
        ),
        "waveshare_sleep_after_display": _parse_checkbox(
            form_data,
            "waveshareSleepAfterDisplay",
            "Waveshare sleep after display"
        ),
        "waveshare_reinitialize_before_display": _parse_checkbox(
            form_data,
            "waveshareReinitializeBeforeDisplay",
            "Waveshare reinitialize before display"
        ),
        "web_server_threads": web_server_threads,
        "image_settings": {
            "saturation": float(form_data.get("saturation", "1.0")),
            "brightness": float(form_data.get("brightness", "1.0")),
            "sharpness": float(form_data.get("sharpness", "1.0")),
            "contrast": float(form_data.get("contrast", "1.0"))
        }
    }

    previous_scheduler_check_interval = _normalize_int(previous_scheduler_check_interval)
    return settings, scheduler_check_interval_seconds != previous_scheduler_check_interval
