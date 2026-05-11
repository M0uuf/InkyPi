import sys
import types
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import astral  # noqa: F401
except ModuleNotFoundError:
    astral_module = types.ModuleType("astral")
    astral_module.moon = types.SimpleNamespace(phase=lambda target_date: 7.0)
    sys.modules["astral"] = astral_module

from plugins.weather.weather import Weather
import plugins.base_plugin.base_plugin as base_plugin_module


class FakeDeviceConfig:
    def __init__(self, resolution=(800, 480), orientation="horizontal", timezone_name="UTC"):
        self.resolution = resolution
        self.orientation = orientation
        self.timezone_name = timezone_name

    def get_resolution(self):
        return self.resolution

    def get_config(self, key=None, default=None):
        values = {
            "orientation": self.orientation,
            "timezone": self.timezone_name,
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


def render_weather_template(monkeypatch, display_graph):
    plugin = build_weather_plugin()
    template_params = build_template_params()
    template_params["hourly_forecast"] = [
        {
            "time": "08:00",
            "temperature": 20,
            "precipitation": 0.1,
            "rain": 0.0,
            "icon": plugin.get_plugin_dir("icons/01d.png")
        },
        {
            "time": "09:00",
            "temperature": 21,
            "precipitation": 0.2,
            "rain": 0.1,
            "icon": plugin.get_plugin_dir("icons/02d.png")
        }
    ]
    template_params["plugin_settings"]["displayGraph"] = display_graph
    template_params["plugin_settings"]["displayGraphIcons"] = "false"
    template_params["plugin_settings"]["displayRain"] = "false"

    captured = {}

    def fake_take_screenshot_html(rendered_html, dimensions, cache_extra=None):
        captured["rendered_html"] = rendered_html
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(base_plugin_module, "take_screenshot_html", fake_take_screenshot_html)

    image = plugin.render_image((800, 480), "weather.html", "weather.css", template_params)

    assert image.size == (800, 480)
    return captured["rendered_html"]


def test_weather_html_omits_graph_script_when_graph_disabled(monkeypatch):
    rendered_html = render_weather_template(monkeypatch, "false")

    assert 'id="hourlyTemperatureChart"' not in rendered_html
    assert "scripts/chart.js" not in rendered_html
    assert "getContext('2d')" not in rendered_html


def test_weather_html_keeps_graph_script_and_canvas_when_graph_enabled(monkeypatch):
    rendered_html = render_weather_template(monkeypatch, "true")

    assert 'id="hourlyTemperatureChart"' in rendered_html
    assert "scripts/chart.js" in rendered_html
    assert "if (!canvas)" in rendered_html
    assert "new Chart(ctx" in rendered_html


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


def build_openmeteo_payload():
    return {
        "timezone": "Pacific/Honolulu",
        "current": {
            "time": "2026-05-09T23:30",
            "temperature": 24,
            "apparent_temperature": 25,
            "weather_code": 0,
            "is_day": 0,
            "windspeed": 4,
            "winddirection": 90
        },
        "daily": {
            "sunrise": ["2026-05-09T06:00", "2026-05-10T06:01"],
            "sunset": ["2026-05-09T18:00", "2026-05-10T18:01"],
            "time": ["2026-05-09", "2026-05-10"],
            "weathercode": [0, 1],
            "temperature_2m_max": [27, 28],
            "temperature_2m_min": [20, 21]
        },
        "hourly": {
            "time": ["2026-05-09T22:00", "2026-05-09T23:00", "2026-05-10T00:00"],
            "temperature_2m": [22, 23, 24],
            "precipitation_probability": [10, 20, 30],
            "precipitation": [0.1, 0.2, 0.3],
            "weather_code": [0, 0, 1],
            "relative_humidity_2m": [50, 60, 70],
            "surface_pressure": [1000, 1001, 1002],
            "visibility": [8000, 9000, 10000]
        }
    }


def build_openmeteo_air_quality_payload():
    return {
        "hourly": {
            "time": ["2026-05-09T22:00", "2026-05-09T23:00", "2026-05-10T00:00"],
            "uv_index": [1, 2, 3],
            "european_aqi": [20, 40, 60]
        }
    }


def build_base_weather_settings(provider="OpenWeatherMap", latitude="52.5", longitude="13.4"):
    return {
        "latitude": latitude,
        "longitude": longitude,
        "units": "metric",
        "weatherProvider": provider,
        "weatherTimeZone": "localTimeZone",
        "titleSelection": "custom",
        "customTitle": "Test Location",
        "renderMode": "fast",
        "displayRefreshTime": "true",
        "displayMetrics": "true",
        "displayForecast": "true",
        "forecastDays": "3",
        "moonPhase": "false"
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


def test_weather_openweather_accepts_zero_latitude_and_longitude(monkeypatch):
    plugin = build_weather_plugin()
    captured = {}

    def fake_get_weather_data(api_key, units, lat, long):
        captured["weather"] = (lat, long)
        return build_openweather_payload()

    def fake_get_air_quality(api_key, lat, long):
        captured["air_quality"] = (lat, long)
        return {"list": [{"main": {"aqi": 1}}]}

    monkeypatch.setattr(plugin, "get_weather_data", fake_get_weather_data)
    monkeypatch.setattr(plugin, "get_air_quality", fake_get_air_quality)

    image = plugin.generate_image(
        build_base_weather_settings(latitude="0", longitude="0"),
        FakeDeviceConfig()
    )

    assert image.size == (800, 480)
    assert captured["weather"] == (0.0, 0.0)
    assert captured["air_quality"] == (0.0, 0.0)


def test_weather_openmeteo_accepts_zero_latitude_and_longitude(monkeypatch):
    plugin = build_weather_plugin()
    captured = {}

    def fake_get_open_meteo_data(lat, long, units, forecast_days, timezone_name="auto"):
        captured["weather"] = (lat, long, timezone_name)
        return {}

    def fake_get_open_meteo_air_quality(lat, long, timezone_name="auto"):
        captured["air_quality"] = (lat, long, timezone_name)
        return {}

    monkeypatch.setattr(plugin, "get_open_meteo_data", fake_get_open_meteo_data)
    monkeypatch.setattr(plugin, "get_open_meteo_air_quality", fake_get_open_meteo_air_quality)
    monkeypatch.setattr(plugin, "parse_open_meteo_data", lambda *args, **kwargs: build_template_params())

    image = plugin.generate_image(
        build_base_weather_settings(provider="OpenMeteo", latitude="0", longitude="0"),
        FakeDeviceConfig()
    )

    assert image.size == (800, 480)
    assert captured["weather"] == (0.0, 0.0, "UTC")
    assert captured["air_quality"] == (0.0, 0.0, "UTC")


def test_openmeteo_location_timezone_parses_offsetless_times_as_location_local():
    plugin = build_weather_plugin()
    weather_data = build_openmeteo_payload()
    air_quality = build_openmeteo_air_quality_payload()
    location_tz = plugin.parse_open_meteo_timezone(weather_data, pytz.timezone("UTC"))

    parsed = plugin.parse_open_meteo_data(weather_data, air_quality, location_tz, "metric", "24h", 21.3)
    data_points = {point["label"]: point for point in parsed["data_points"]}

    assert parsed["current_date"] == "Saturday, May 09"
    assert parsed["forecast"][0]["day"] == "Sat"
    assert parsed["hourly_forecast"][0]["time"] == "23:00"
    assert data_points["Sunrise"]["measurement"] == "06:00"
    assert data_points["Sunset"]["measurement"] == "18:00"
    assert data_points["Humidity"]["measurement"] == 60
    assert data_points["Pressure"]["measurement"] == 1001
    assert data_points["UV Index"]["measurement"] == 2
    assert data_points["Visibility"]["measurement"] == "9.0"


def test_openmeteo_visibility_uses_na_when_current_hour_is_missing():
    plugin = build_weather_plugin()
    weather_data = deepcopy(build_openmeteo_payload())
    weather_data["hourly"]["time"] = ["2026-05-09T20:00", "2026-05-09T21:00", "2026-05-09T22:00"]
    air_quality = build_openmeteo_air_quality_payload()
    location_tz = plugin.parse_open_meteo_timezone(weather_data, pytz.timezone("UTC"))

    parsed = plugin.parse_open_meteo_data(weather_data, air_quality, location_tz, "metric", "24h", 21.3)
    data_points = {point["label"]: point for point in parsed["data_points"]}

    assert data_points["Visibility"]["measurement"] == "N/A"


def test_openmeteo_visibility_uses_na_when_values_are_shorter_than_times():
    plugin = build_weather_plugin()
    weather_data = deepcopy(build_openmeteo_payload())
    weather_data["hourly"]["visibility"] = [8000]
    air_quality = build_openmeteo_air_quality_payload()
    location_tz = plugin.parse_open_meteo_timezone(weather_data, pytz.timezone("UTC"))

    parsed = plugin.parse_open_meteo_data(weather_data, air_quality, location_tz, "metric", "24h", 21.3)
    data_points = {point["label"]: point for point in parsed["data_points"]}

    assert data_points["Visibility"]["measurement"] == "N/A"


def test_openmeteo_visibility_keeps_max_prefix_for_valid_data():
    plugin = build_weather_plugin()
    weather_data = deepcopy(build_openmeteo_payload())
    weather_data["hourly"]["visibility"] = [8000, 10000, 9000]
    air_quality = build_openmeteo_air_quality_payload()
    location_tz = plugin.parse_open_meteo_timezone(weather_data, pytz.timezone("UTC"))

    parsed = plugin.parse_open_meteo_data(weather_data, air_quality, location_tz, "metric", "24h", 21.3)
    data_points = {point["label"]: point for point in parsed["data_points"]}

    assert data_points["Visibility"]["measurement"] == "\u226510.0"


def test_openmeteo_configured_timezone_is_requested_and_used(monkeypatch):
    plugin = build_weather_plugin()
    captured = {}

    def fake_get_open_meteo_data(lat, long, units, forecast_days, timezone_name="auto"):
        captured["weather_timezone"] = timezone_name
        weather_data = build_openmeteo_payload()
        return {
            **weather_data,
            "timezone": "Pacific/Honolulu",
            "current": {**weather_data["current"], "time": "2026-05-10T09:30"},
            "hourly": {
                **weather_data["hourly"],
                "time": ["2026-05-10T08:00", "2026-05-10T09:00", "2026-05-10T10:00"]
            }
        }

    def fake_get_open_meteo_air_quality(lat, long, timezone_name="auto"):
        captured["air_quality_timezone"] = timezone_name
        air_quality_data = build_openmeteo_air_quality_payload()
        return {
            "hourly": {
                **air_quality_data["hourly"],
                "time": ["2026-05-10T08:00", "2026-05-10T09:00", "2026-05-10T10:00"]
            }
        }

    def fake_render_fast_image(dimensions, template_params):
        captured["current_date"] = template_params["current_date"]
        captured["first_forecast_day"] = template_params["forecast"][0]["day"]
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(plugin, "get_open_meteo_data", fake_get_open_meteo_data)
    monkeypatch.setattr(plugin, "get_open_meteo_air_quality", fake_get_open_meteo_air_quality)
    monkeypatch.setattr(plugin, "render_fast_image", fake_render_fast_image)

    settings = build_base_weather_settings(provider="OpenMeteo", latitude="0", longitude="0")
    settings["weatherTimeZone"] = "localTimeZone"

    image = plugin.generate_image(settings, FakeDeviceConfig(timezone_name="Europe/Berlin"))

    assert image.size == (800, 480)
    assert captured["weather_timezone"] == "Europe/Berlin"
    assert captured["air_quality_timezone"] == "Europe/Berlin"
    assert captured["current_date"] == "Sunday, May 10"
    assert captured["first_forecast_day"] == "Sat"


def test_openmeteo_location_timezone_requests_auto(monkeypatch):
    plugin = build_weather_plugin()
    captured = {}

    def fake_get_open_meteo_data(lat, long, units, forecast_days, timezone_name="auto"):
        captured["weather_timezone"] = timezone_name
        return build_openmeteo_payload()

    def fake_get_open_meteo_air_quality(lat, long, timezone_name="auto"):
        captured["air_quality_timezone"] = timezone_name
        return build_openmeteo_air_quality_payload()

    monkeypatch.setattr(plugin, "get_open_meteo_data", fake_get_open_meteo_data)
    monkeypatch.setattr(plugin, "get_open_meteo_air_quality", fake_get_open_meteo_air_quality)
    monkeypatch.setattr(plugin, "render_fast_image", lambda dimensions, template_params: Image.new("RGB", dimensions, "white"))

    settings = build_base_weather_settings(provider="OpenMeteo", latitude="0", longitude="0")
    settings["weatherTimeZone"] = "locationTimeZone"

    image = plugin.generate_image(settings, FakeDeviceConfig())

    assert image.size == (800, 480)
    assert captured["weather_timezone"] == "auto"
    assert captured["air_quality_timezone"] == "auto"


def test_weather_accepts_zero_longitude(monkeypatch):
    plugin = build_weather_plugin()
    captured = {}

    def fake_get_weather_data(api_key, units, lat, long):
        captured["coords"] = (lat, long)
        return build_openweather_payload()

    monkeypatch.setattr(plugin, "get_weather_data", fake_get_weather_data)
    monkeypatch.setattr(plugin, "get_air_quality", lambda api_key, lat, long: {"list": [{"main": {"aqi": 1}}]})

    image = plugin.generate_image(
        build_base_weather_settings(latitude="51.5", longitude="0"),
        FakeDeviceConfig()
    )

    assert image.size == (800, 480)
    assert captured["coords"] == (51.5, 0.0)


def test_weather_rejects_missing_empty_and_non_numeric_coordinates():
    plugin = build_weather_plugin()
    settings = build_base_weather_settings()

    for key, value, expected_error in [
        ("latitude", None, "Latitude is required."),
        ("latitude", "", "Latitude is required."),
        ("longitude", None, "Longitude is required."),
        ("longitude", " ", "Longitude is required."),
        ("latitude", "north", "Latitude must be a valid number."),
        ("longitude", "east", "Longitude must be a valid number."),
        ("latitude", "nan", "Latitude must be a valid number."),
        ("longitude", "nan", "Longitude must be a valid number."),
        ("latitude", "inf", "Latitude must be a valid number."),
        ("longitude", "-inf", "Longitude must be a valid number.")
    ]:
        invalid_settings = dict(settings)
        invalid_settings[key] = value
        try:
            plugin.generate_image(invalid_settings, FakeDeviceConfig())
        except RuntimeError as exc:
            assert str(exc) == expected_error
        else:
            raise AssertionError(f"Expected RuntimeError for {key}={value!r}")


def test_weather_rejects_out_of_range_coordinates():
    plugin = build_weather_plugin()

    for key, value, expected_error in [
        ("latitude", "90.1", "Latitude must be between -90 and 90."),
        ("latitude", "-90.1", "Latitude must be between -90 and 90."),
        ("longitude", "180.1", "Longitude must be between -180 and 180."),
        ("longitude", "-180.1", "Longitude must be between -180 and 180.")
    ]:
        invalid_settings = build_base_weather_settings()
        invalid_settings[key] = value
        try:
            plugin.generate_image(invalid_settings, FakeDeviceConfig())
        except RuntimeError as exc:
            assert str(exc) == expected_error
        else:
            raise AssertionError(f"Expected RuntimeError for {key}={value!r}")


def test_weather_unknown_render_mode_warns_and_uses_html_renderer(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="plugins.weather.weather")
    plugin = build_weather_plugin()
    settings = {
        "latitude": "52.5",
        "longitude": "13.4",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
        "weatherTimeZone": "localTimeZone",
        "titleSelection": "custom",
        "customTitle": "Berlin",
        "renderMode": "unexpected",
        "displayRefreshTime": "true",
        "displayMetrics": "true",
        "displayForecast": "true",
        "forecastDays": "3",
        "moonPhase": "false"
    }

    monkeypatch.setattr(plugin, "get_weather_data", lambda api_key, units, lat, long: build_openweather_payload())
    monkeypatch.setattr(plugin, "get_air_quality", lambda api_key, lat, long: {"list": [{"main": {"aqi": 1}}]})
    monkeypatch.setattr(plugin, "render_image", lambda *args, **kwargs: Image.new("RGB", (800, 480), "white"))

    image = plugin.generate_image(settings, FakeDeviceConfig())

    assert image.size == (800, 480)
    assert "Unknown Weather renderMode" in caplog.text
