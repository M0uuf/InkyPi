from utils.time_utils import calculate_seconds


class SettingsValidationError(ValueError):
    pass


def build_device_settings_update(form_data, previous_scheduler_check_interval):
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

    settings = {
        "name": form_data.get("deviceName"),
        "orientation": form_data.get("orientation"),
        "inverted_image": form_data.get("invertImage"),
        "log_system_stats": form_data.get("logSystemStats"),
        "timezone": form_data.get("timezoneName"),
        "time_format": form_data.get("timeFormat"),
        "scheduler_check_interval_seconds": scheduler_check_interval_seconds,
        "image_settings": {
            "saturation": float(form_data.get("saturation", "1.0")),
            "brightness": float(form_data.get("brightness", "1.0")),
            "sharpness": float(form_data.get("sharpness", "1.0")),
            "contrast": float(form_data.get("contrast", "1.0"))
        }
    }

    try:
        previous_scheduler_check_interval = int(previous_scheduler_check_interval)
    except (TypeError, ValueError):
        pass

    return settings, scheduler_check_interval_seconds != previous_scheduler_check_interval
