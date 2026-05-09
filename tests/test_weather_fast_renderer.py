import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import astral  # noqa: F401
except ModuleNotFoundError:
    astral_module = types.ModuleType("astral")
    astral_module.moon = types.SimpleNamespace(phase=lambda target_date: 7.0)
    sys.modules["astral"] = astral_module

from plugins.weather.weather import Weather


class FakeDeviceConfig:
    def __init__(self, resolution=(800, 480), orientation="horizontal"):
        self.resolution = resolution
        self.orientation = orientation

    def get_resolution(self):
        return self.resolution

    def get_config(self, key=None, default=None):
        values = {
            "orientation": self.orientation,
            "timezone": "UTC",
            "time_format": "24h"
        }
        if key is None:
            return values
        return values.get(key, default)

    def load_env_key(self, key):
        return "test-api-key"


def build_weather_plugin():
    return Weather({"id": "weather"})


def build_template_params():
    plugin = build_weather_plugin()
    forecast = [
        {
            "day": "Mon",
            "high": 24,
            "low": 12,
            "icon": plugin.get_plugin_dir("icons/01d.png"),
            "moon_phase_pct": "20"
        },
        {
            "day": "Tue",
            "high": 22,
            "low": 10,
            "icon": plugin.get_plugin_dir("icons/02d.png"),
            "moon_phase_pct": "30"
        },
        {
            "day": "Wed",
            "high": 21,
            "low": 9,
            "icon": plugin.get_plugin_dir("icons/10d.png"),
            "moon_phase_pct": "40"
        },
        {
            "day": "Thu",
            "high": 20,
            "low": 8,
            "icon": plugin.get_plugin_dir("icons/04d.png"),
            "moon_phase_pct": "50"
        }
    ]
    return {
        "title": "Test Weather",
        "current_date": "Monday, May 09",
        "current_day_icon": plugin.get_plugin_dir("icons/01d.png"),
        "current_temperature": "23",
        "temperature_unit": "°C",
        "feels_like": "22",
        "units": "metric",
        "forecast": forecast,
        "data_points": [
            {"label": "Wind", "measurement": 4, "unit": "m/s", "arrow": "→"},
            {"label": "Humidity", "measurement": 52, "unit": "%"},
            {"label": "Pressure", "measurement": 1013, "unit": "hPa"},
            {"label": "UV Index", "measurement": 3, "unit": ""},
            {"label": "Visibility", "measurement": "10.0", "unit": "km"},
            {"label": "Air Quality", "measurement": 1, "unit": "Good"}
        ],
        "last_refresh_time": "2026-05-09 08:00",
        "plugin_settings": {
            "renderMode": "fast",
            "displayRefreshTime": "true",
            "displayMetrics": "true",
            "displayForecast": "true",
            "forecastDays": "3",
            "moonPhase": "true",
            "backgroundColor": "#ffffff",
            "textColor": "#000000",
            "accentColor": "#333333"
        }
    }


def build_openweather_payload():
    base = datetime(2026, 5, 9, 8, tzinfo=timezone.utc)
    return {
        "current": {
            "dt": int(base.timestamp()),
            "sunrise": int((base - timedelta(hours=2)).timestamp()),
            "sunset": int((base + timedelta(hours=10)).timestamp()),
            "weather": [{"icon": "01d"}],
            "temp": 23,
            "feels_like": 22,
            "wind_deg": 90,
            "wind_speed": 4,
            "humidity": 52,
            "pressure": 1013,
            "uvi": 3,
            "visibility": 10000
        },
        "daily": [
            {
                "dt": int((base + timedelta(days=day)).timestamp()),
                "sunrise": int((base + timedelta(days=day, hours=-2)).timestamp()),
                "sunset": int((base + timedelta(days=day, hours=10)).timestamp()),
                "weather": [{"icon": "01d"}],
                "temp": {"max": 24 - day, "min": 12 - day},
                "moon_phase": 0.25
            }
            for day in range(8)
        ],
        "hourly": [
            {
                "dt": int((base + timedelta(hours=hour)).timestamp()),
                "weather": [{"icon": "01d"}],
                "temp": 20 + hour,
                "pop": 0.1,
                "rain": {"1h": 0}
            }
            for hour in range(24)
        ]
    }


def test_weather_fast_renderer_outputs_horizontal_and_vertical_images():
    plugin = build_weather_plugin()
    params = build_template_params()

    horizontal = plugin.render_fast_image((800, 480), params)
    vertical = plugin.render_fast_image((480, 800), params)

    assert horizontal.size == (800, 480)
    assert vertical.size == (480, 800)


def test_weather_fast_mode_generate_image_does_not_use_html_renderer(monkeypatch):
    plugin = build_weather_plugin()
    settings = {
        "latitude": "52.5",
        "longitude": "13.4",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
        "weatherTimeZone": "localTimeZone",
        "titleSelection": "custom",
        "customTitle": "Berlin",
        "renderMode": "fast",
        "displayRefreshTime": "true",
        "displayMetrics": "true",
        "displayForecast": "true",
        "forecastDays": "3",
        "moonPhase": "false"
    }

    monkeypatch.setattr(plugin, "get_weather_data", lambda api_key, units, lat, long: build_openweather_payload())
    monkeypatch.setattr(plugin, "get_air_quality", lambda api_key, lat, long: {"list": [{"main": {"aqi": 1}}]})
    monkeypatch.setattr(
        plugin,
        "render_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTML renderer should not be used in fast mode"))
    )

    image = plugin.generate_image(settings, FakeDeviceConfig())

    assert isinstance(image, Image.Image)
    assert image.size == (800, 480)
