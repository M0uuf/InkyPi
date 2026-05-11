from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image, ImageDraw, ImageFont
import os
import requests
import logging
import time
from datetime import datetime, timedelta, timezone, date
from astral import moon
import pytz
from io import BytesIO
import math
from urllib.parse import quote
from utils.app_utils import get_font
from utils.performance import is_performance_diagnostics_enabled

logger = logging.getLogger(__name__)
        
def get_moon_phase_name(phase_age: float) -> str:
    """Determines the name of the lunar phase based on the age of the moon."""
    PHASES_THRESHOLDS = [
        (1.0, "newmoon"),
        (7.0, "waxingcrescent"),
        (8.5, "firstquarter"),
        (14.0, "waxinggibbous"),
        (15.5, "fullmoon"),
        (22.0, "waninggibbous"),
        (23.5, "lastquarter"),
        (29.0, "waningcrescent"),
    ]

    for threshold, phase_name in PHASES_THRESHOLDS:
        if phase_age <= threshold:
            return phase_name  
    return "newmoon"

UNITS = {
    "standard": {
        "temperature": "K",
        "speed": "m/s",
        "distance":"km"
    },
    "metric": {
        "temperature": "°C",
        "speed": "m/s",
        "distance":"km"

    },
    "imperial": {
        "temperature": "°F",
        "speed": "mph",
        "distance":"mi"
    }
}

WEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={long}&units={units}&exclude=minutely&appid={api_key}"
AIR_QUALITY_URL = "http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={long}&appid={api_key}"
GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={long}&limit=1&appid={api_key}"

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={long}&hourly=weather_code,temperature_2m,precipitation,precipitation_probability,relative_humidity_2m,surface_pressure,visibility&daily=weathercode,temperature_2m_max,temperature_2m_min,sunrise,sunset&current=temperature,windspeed,winddirection,is_day,precipitation,weather_code,apparent_temperature&timezone={timezone}&models=best_match&forecast_days={forecast_days}"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={long}&hourly=european_aqi,uv_index,uv_index_clear_sky&timezone={timezone}"
OPEN_METEO_UNIT_PARAMS = {
    "standard": "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",  # temperature is converted to Kelvin later
    "metric":   "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",
    "imperial": "temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
}

class Weather(BasePlugin):
    def _parse_coordinate(self, settings, key, label, minimum, maximum):
        raw_value = settings.get(key)
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            raise RuntimeError(f"{label} is required.")

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise RuntimeError(f"{label} must be a valid number.")

        if not math.isfinite(value):
            raise RuntimeError(f"{label} must be a valid number.")

        if value < minimum or value > maximum:
            raise RuntimeError(f"{label} must be between {minimum} and {maximum}.")
        return value

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "OpenWeatherMap",
            "expected_key": "OPEN_WEATHER_MAP_SECRET"
        }
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        lat = self._parse_coordinate(settings, "latitude", "Latitude", -90, 90)
        long = self._parse_coordinate(settings, "longitude", "Longitude", -180, 180)

        units = settings.get('units')
        if not units or units not in ['metric', 'imperial', 'standard']:
            raise RuntimeError("Units are required.")

        weather_provider = settings.get('weatherProvider', 'OpenWeatherMap')
        title = settings.get('customTitle', '')

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)

        try:
            if weather_provider == "OpenWeatherMap":
                api_key = device_config.load_env_key("OPEN_WEATHER_MAP_SECRET")
                if not api_key:
                    raise RuntimeError("Open Weather Map API Key not configured.")
                weather_data = self.get_weather_data(api_key, units, lat, long)
                aqi_data = self.get_air_quality(api_key, lat, long)
                if settings.get('titleSelection', 'location') == 'location':
                    title = self.get_location(api_key, lat, long)
                if settings.get('weatherTimeZone', 'locationTimeZone') == 'locationTimeZone':
                    logger.info("Using location timezone for OpenWeatherMap data.")
                    wtz = self.parse_timezone(weather_data)
                    template_params = self.parse_weather_data(weather_data, aqi_data, wtz, units, time_format, lat)
                else:
                    logger.info("Using configured timezone for OpenWeatherMap data.")
                    template_params = self.parse_weather_data(weather_data, aqi_data, tz, units, time_format, lat)
            elif weather_provider == "OpenMeteo":
                forecast_days = 7
                if settings.get('weatherTimeZone', 'locationTimeZone') == 'locationTimeZone':
                    logger.info("Using location timezone for Open-Meteo data.")
                    open_meteo_timezone = "auto"
                    weather_data = self.get_open_meteo_data(lat, long, units, forecast_days + 1, open_meteo_timezone)
                    wtz = self.parse_open_meteo_timezone(weather_data, tz)
                    aqi_data = self.get_open_meteo_air_quality(lat, long, open_meteo_timezone)
                    template_params = self.parse_open_meteo_data(weather_data, aqi_data, wtz, units, time_format, lat)
                else:
                    logger.info("Using configured timezone for Open-Meteo data.")
                    open_meteo_timezone = timezone
                    weather_data = self.get_open_meteo_data(lat, long, units, forecast_days + 1, open_meteo_timezone)
                    aqi_data = self.get_open_meteo_air_quality(lat, long, open_meteo_timezone)
                    template_params = self.parse_open_meteo_data(weather_data, aqi_data, tz, units, time_format, lat)
            else:
                raise RuntimeError(f"Unknown weather provider: {weather_provider}")

            template_params['title'] = title
        except Exception as e:
            logger.error(f"{weather_provider} request failed: {str(e)}")
            raise RuntimeError(f"{weather_provider} request failure, please check logs.")
       
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        template_params["plugin_settings"] = settings

        # Add last refresh time
        now = datetime.now(tz)
        if time_format == "24h":
            last_refresh_time = now.strftime("%Y-%m-%d %H:%M")
        else:
            last_refresh_time = now.strftime("%Y-%m-%d %I:%M %p")
        template_params["last_refresh_time"] = last_refresh_time

        render_mode = settings.get("renderMode", "html")
        if render_mode not in {"html", "fast"}:
            logger.warning("Unknown Weather renderMode '%s'; falling back to HTML renderer.", render_mode)
            render_mode = "html"
        render_started = time.monotonic()
        if render_mode == "fast":
            image = self.render_fast_image(dimensions, template_params)
            logger.info(
                "Rendered Weather plugin with fast Pillow renderer in %.2fs | dimensions: %sx%s",
                time.monotonic() - render_started,
                dimensions[0],
                dimensions[1]
            )
        else:
            image = self.render_image(
                dimensions,
                "weather.html",
                "weather.css",
                template_params,
                diagnostics_enabled=is_performance_diagnostics_enabled(device_config)
            )

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    def render_fast_image(self, dimensions, template_params):
        """Render a simplified Weather image without launching Chromium."""
        width, height = int(dimensions[0]), int(dimensions[1])
        settings = template_params.get("plugin_settings", {})
        background_color = settings.get("backgroundColor") or "#ffffff"
        text_color = settings.get("textColor") or "#000000"
        accent_color = settings.get("accentColor") or text_color

        image = Image.new("RGB", (width, height), background_color)
        draw = ImageDraw.Draw(image)

        margin = max(8, int(min(width, height) * 0.035))
        y = margin

        if settings.get("displayRefreshTime") == "true":
            refresh_font = self._get_fast_font(max(10, int(height * 0.035)), "normal")
            refresh_text = f"Last refresh: {template_params.get('last_refresh_time', '')}"
            self._draw_right_text(draw, refresh_text, width - margin, y, refresh_font, text_color)
            y += self._text_height(draw, refresh_text, refresh_font) + max(2, margin // 4)

        title_font = self._get_fast_font(max(18, int(height * 0.085)), "bold")
        date_font = self._get_fast_font(max(12, int(height * 0.045)), "normal")
        title = template_params.get("title") or "Weather"
        self._draw_centered_fit_text(draw, title, margin, y, width - (2 * margin), title_font, text_color)
        y += self._text_height(draw, title, title_font) + max(2, margin // 5)
        current_date = template_params.get("current_date", "")
        self._draw_centered_fit_text(draw, current_date, margin, y, width - (2 * margin), date_font, text_color)
        y += self._text_height(draw, current_date, date_font) + margin

        forecast = template_params.get("forecast") or []
        data_points = template_params.get("data_points") or []
        units = template_params.get("units")
        current_section_height = max(int(height * 0.34), int(height * 0.25))
        forecast_enabled = settings.get("displayForecast") == "true" and len(forecast) > 1
        if not forecast_enabled:
            current_section_height = max(1, height - y - margin)
        current_bottom = max(y + 1, min(height - margin, y + current_section_height))

        self._draw_fast_current_conditions(
            image,
            draw,
            template_params,
            forecast,
            data_points,
            units,
            (margin, y, width - margin, current_bottom),
            text_color,
            accent_color
        )

        if forecast_enabled:
            forecast_y = min(height - margin, current_bottom + margin)
            self._draw_fast_forecast(
                image,
                draw,
                forecast,
                settings,
                (margin, forecast_y, width - margin, height - margin),
                text_color,
                accent_color,
                units
            )

        return image

    def _draw_fast_current_conditions(self, image, draw, template_params, forecast, data_points, units, bounds, text_color, accent_color):
        left, top, right, bottom = bounds
        width = max(1, right - left)
        height = max(1, bottom - top)
        icon_size = max(36, min(int(width * 0.22), int(height * 0.7)))
        icon_x = left
        icon_y = top + max(0, (height - icon_size) // 2)
        self._paste_icon(image, template_params.get("current_day_icon"), (icon_x, icon_y), icon_size)

        temp_font = self._get_fast_font(max(28, int(height * 0.38)), "bold")
        small_font = self._get_fast_font(max(12, int(height * 0.09)), "normal")
        temp_x = icon_x + icon_size + max(8, int(width * 0.03))
        temp_text = f"{template_params.get('current_temperature', '')}{template_params.get('temperature_unit', '')}"
        draw.text((temp_x, top), temp_text, fill=text_color, font=temp_font)
        small_y = top + self._text_height(draw, temp_text, temp_font)
        feels_like = f"Feels like {template_params.get('feels_like', '')}"
        if units != "standard":
            feels_like += "°"
        draw.text((temp_x, small_y), feels_like, fill=text_color, font=small_font)
        if forecast:
            min_max = f"{forecast[0].get('high', '')}° / {forecast[0].get('low', '')}°" if units != "standard" else f"{forecast[0].get('high', '')} / {forecast[0].get('low', '')}"
            draw.text((temp_x, small_y + self._text_height(draw, feels_like, small_font) + 2), min_max, fill=accent_color, font=small_font)

        settings = template_params.get("plugin_settings", {})
        if settings.get("displayMetrics") != "true":
            return

        metrics_left = left + int(width * 0.58)
        metrics_width = right - metrics_left
        metric_font = self._get_fast_font(max(11, int(height * 0.075)), "normal")
        metric_value_font = self._get_fast_font(max(12, int(height * 0.085)), "bold")
        metric_rows = data_points[:6]
        row_height = max(16, height // max(1, len(metric_rows)))
        for index, data_point in enumerate(metric_rows):
            row_y = top + (index * row_height)
            label = str(data_point.get("label", ""))
            value = str(data_point.get("measurement", ""))
            unit = str(data_point.get("unit", "") or "")
            if label == "Wind":
                value = f"{value} {unit} {data_point.get('arrow', '')}".strip()
            elif unit:
                value = f"{value} {unit}"
            draw.text((metrics_left, row_y), label, fill=accent_color, font=metric_font)
            self._draw_right_text(draw, value, metrics_left + metrics_width, row_y, metric_value_font, text_color)

    def _draw_fast_forecast(self, image, draw, forecast, settings, bounds, text_color, accent_color, units):
        left, top, right, bottom = bounds
        days = int(settings.get("forecastDays") or 3)
        forecast_days = forecast[1:days + 1]
        if not forecast_days:
            return

        card_gap = max(4, int((right - left) * 0.015))
        card_width = max(24, ((right - left) - (card_gap * (len(forecast_days) - 1))) // len(forecast_days))
        card_height = max(1, bottom - top)
        day_font = self._get_fast_font(max(10, int(card_height * 0.18)), "bold")
        temp_font = self._get_fast_font(max(10, int(card_height * 0.16)), "normal")
        moon_font = self._get_fast_font(max(8, int(card_height * 0.11)), "normal")

        for index, day in enumerate(forecast_days):
            card_left = left + index * (card_width + card_gap)
            card_right = card_left + card_width
            draw.rounded_rectangle(
                (card_left, top, card_right, bottom),
                radius=max(3, card_gap),
                outline=accent_color,
                width=1
            )
            day_label = str(day.get("day", ""))
            self._draw_centered_fit_text(draw, day_label, card_left + 2, top + 3, card_width - 4, day_font, text_color)
            icon_size = max(20, min(int(card_width * 0.55), int(card_height * 0.38)))
            self._paste_icon(image, day.get("icon"), (card_left + (card_width - icon_size) // 2, top + int(card_height * 0.25)), icon_size)
            suffix = "" if units == "standard" else "°"
            temps = f"{day.get('high', '')}{suffix} / {day.get('low', '')}{suffix}"
            self._draw_centered_fit_text(draw, temps, card_left + 2, top + int(card_height * 0.66), card_width - 4, temp_font, text_color)
            if settings.get("moonPhase") == "true":
                moon = f"{day.get('moon_phase_pct', '')}% moon"
                self._draw_centered_fit_text(draw, moon, card_left + 2, top + int(card_height * 0.82), card_width - 4, moon_font, accent_color)

    def _paste_icon(self, image, icon_path, position, size):
        try:
            with Image.open(icon_path) as icon:
                icon = icon.convert("RGBA")
                icon.thumbnail((size, size), Image.LANCZOS)
                x, y = position
                image.paste(icon, (x + (size - icon.width) // 2, y + (size - icon.height) // 2), icon)
        except Exception as e:
            logger.warning("Unable to draw weather icon %s: %s", icon_path, e)

    def _get_fast_font(self, size, weight="normal"):
        return get_font("Jost", size, weight) or get_font("Jost", size) or ImageFont.load_default()

    def _text_height(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    def _text_width(self, draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _draw_right_text(self, draw, text, right_x, y, font, fill):
        draw.text((right_x - self._text_width(draw, text, font), y), text, fill=fill, font=font)

    def _draw_centered_fit_text(self, draw, text, x, y, width, font, fill):
        text = str(text)
        while self._text_width(draw, text, font) > width and len(text) > 4:
            text = text[:-4].rstrip() + "..."
        draw.text((x + max(0, (width - self._text_width(draw, text, font)) // 2), y), text, fill=fill, font=font)

    def parse_weather_data(self, weather_data, aqi_data, tz, units, time_format, lat):
        current = weather_data.get("current")
        daily_forecast = weather_data.get("daily", [])
        dt = datetime.fromtimestamp(current.get('dt'), tz=timezone.utc).astimezone(tz)
        current_icon = current.get("weather")[0].get("icon")
        icon_codes_to_preserve = ["01", "02", "10"]
        icon_code = current_icon[:2]
        current_suffix = current_icon[-1]

        if icon_code not in icon_codes_to_preserve:
            if current_icon.endswith('n'):
                current_icon = current_icon.replace("n", "d")
        data = {
            "current_date": dt.strftime("%A, %B %d"),
            "current_day_icon": self.get_plugin_dir(f'icons/{current_icon}.png'),
            "current_temperature": str(round(current.get("temp"))),
            "feels_like": str(round(current.get("feels_like"))),
            "temperature_unit": UNITS[units]["temperature"],
            "units": units,
            "time_format": time_format
        }
        data['forecast'] = self.parse_forecast(weather_data.get('daily'), tz, current_suffix, lat)
        data['data_points'] = self.parse_data_points(weather_data, aqi_data, tz, units, time_format)

        data['hourly_forecast'] = self.parse_hourly(weather_data.get('hourly'), tz, time_format, units, daily_forecast)
        return data

    def parse_open_meteo_timezone(self, weather_data, fallback_tz):
        timezone_name = weather_data.get("timezone")
        if not timezone_name:
            return fallback_tz
        try:
            return pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError:
            logger.warning("Unknown Open-Meteo timezone '%s'; using configured timezone.", timezone_name)
            return fallback_tz

    def parse_open_meteo_time(self, time_str, tz):
        parsed_time = datetime.fromisoformat(time_str)
        if parsed_time.tzinfo is None:
            if hasattr(tz, "localize"):
                return tz.localize(parsed_time)
            return parsed_time.replace(tzinfo=tz)
        return parsed_time.astimezone(tz)

    def parse_open_meteo_data(self, weather_data, aqi_data, tz, units, time_format, lat):
        current = weather_data.get("current", {})
        daily = weather_data.get('daily', {})
        dt = self.parse_open_meteo_time(current.get('time'), tz) if current.get('time') else datetime.now(tz)
        weather_code = current.get("weather_code", 0)
        is_day = current.get("is_day", 1)
        current_icon = self.map_weather_code_to_icon(weather_code, is_day)
        
        temperature_conversion = 273.15 if units == "standard" else 0.

        data = {
            "current_date": dt.strftime("%A, %B %d"),
            "current_day_icon": self.get_plugin_dir(f'icons/{current_icon}.png'),
            "current_temperature": str(round(current.get("temperature", 0) + temperature_conversion)),
            "feels_like": str(round(current.get("apparent_temperature", current.get("temperature", 0)) + temperature_conversion)),
            "temperature_unit": UNITS[units]["temperature"],
            "units": units,
            "time_format": time_format
        }

        data['forecast'] = self.parse_open_meteo_forecast(weather_data.get('daily', {}), units, tz, is_day, lat)
        data['data_points'] = self.parse_open_meteo_data_points(weather_data, aqi_data, units, tz, time_format, dt)
        
        data['hourly_forecast'] = self.parse_open_meteo_hourly(weather_data.get('hourly', {}), units, tz, time_format, daily.get('sunrise', []), daily.get('sunset', []), dt)
        return data

    def map_weather_code_to_icon(self, weather_code, is_day):

        icon = "01d" # Default to clear day icon
        
        if weather_code in [0]:   # Clear sky
            icon = "01d"
        elif weather_code in [1]: # Mainly clear
            icon = "022d"
        elif weather_code in [2]: # Partly cloudy
            icon = "02d"
        elif weather_code in [3]: # Overcast
            icon = "04d"
        elif weather_code in [51, 61, 80]: # Drizzle, showers, rain: Light
            icon = "51d"          
        elif weather_code in [53, 63, 81]: # Drizzle, showers, rain: Moderatr
            icon = "53d"
        elif weather_code in [55, 65, 82]: # Drizzle, showers, rain: Heavy
            icon = "09d"
        elif weather_code in [45]: # Fog
            icon = "50d"                       
        elif weather_code in [48]: # Icy fog
            icon = "48d"
        elif weather_code in [56, 66]: # Light freezing Drizzle
            icon = "56d"            
        elif weather_code in [57, 67]: # Freezing Drizzle
            icon = "57d"            
        elif weather_code in [71, 85]: # Snow fall: Slight
            icon = "71d"
        elif weather_code in [73]:     # Snow fall: Moderate
            icon = "73d"
        elif weather_code in [75, 86]: # Snow fall: Heavy
            icon = "13d"
        elif weather_code in [77]:     # Snow grain
            icon = "77d"
        elif weather_code in [95]: # Thunderstorm
            icon = "11d"
        elif weather_code in [96, 99]: # Thunderstorm with slight and heavy hail
            icon = "11d"

        if is_day == 0:
            if icon == "01d":
                icon = "01n"      # Clear sky night
            elif icon == "022d":
                icon = "022n"     # Mainly clear night
            elif icon == "02d":
                icon = "02n"      # Partly cloudy night                
            elif icon == "10d":
                icon = "10n"      # Rain night

        return icon

    def get_moon_phase_icon_path(self, phase_name: str, lat: float) -> str:
        """Determines the path to the moon icon, inverting it if the location is in the Southern Hemisphere."""
        # Waxing, Waning, First and Last quarter phases are inverted between hemispheres.
        if lat < 0: # Southern Hemisphere
            if phase_name == "waxingcrescent":
                phase_name = "waningcrescent"
            elif phase_name == "waxinggibbous":
                phase_name = "waninggibbous"
            elif phase_name == "waningcrescent":
                phase_name = "waxingcrescent"
            elif phase_name == "waninggibbous":
                phase_name = "waxinggibbous"
            elif phase_name == "firstquarter":
                phase_name = "lastquarter"
            elif phase_name == "lastquarter":
                phase_name = "firstquarter"
        
        return self.get_plugin_dir(f"icons/{phase_name}.png")

    def parse_forecast(self, daily_forecast, tz, current_suffix, lat):
        """
        - daily_forecast: list of daily entries from One‑Call v3 (each has 'dt', 'weather', 'temp', 'moon_phase')
        - tz: your target tzinfo (e.g. from zoneinfo or pytz)
        """
        PHASES = [
            (0.0, "newmoon"),
            (0.25, "firstquarter"),
            (0.5, "fullmoon"),
            (0.75, "lastquarter"),
            (1.0, "newmoon"),
        ]

        def choose_phase_name(phase: float) -> str:
            for target, name in PHASES:
                if math.isclose(phase, target, abs_tol=1e-3):
                    return name
            if 0.0 < phase < 0.25:
                return "waxingcrescent"
            elif 0.25 < phase < 0.5:
                return "waxinggibbous"
            elif 0.5 < phase < 0.75:
                return "waninggibbous"
            else:
                return "waningcrescent"

        forecast = []
        icon_codes_to_apply_current_suffix = ["01", "02", "10"]
        for day in daily_forecast:
            # --- weather icon ---
            weather_icon = day["weather"][0]["icon"]  # e.g. "10d", "01n"
            icon_code = weather_icon[:2]
            if icon_code in icon_codes_to_apply_current_suffix:
                weather_icon_base = weather_icon[:-1]
                weather_icon = weather_icon_base + current_suffix
            else:
                if weather_icon.endswith('n'):
                    weather_icon = weather_icon.replace("n", "d")
            weather_icon = f"{icon_code}d"        
            weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            # --- moon phase & icon ---
            moon_phase = float(day["moon_phase"])  # [0.0–1.0]
            phase_name_north_hemi = choose_phase_name(moon_phase)
            moon_icon_path = self.get_moon_phase_icon_path(phase_name_north_hemi, lat)
            # --- true illumination percent, no decimals ---
            illum_fraction = (1 - math.cos(2 * math.pi * moon_phase)) / 2
            moon_pct = f"{illum_fraction * 100:.0f}"

            # --- date & temps ---
            dt = datetime.fromtimestamp(day["dt"], tz=timezone.utc).astimezone(tz)
            day_label = dt.strftime("%a")

            forecast.append(
                {
                    "day": day_label,
                    "high": int(day["temp"]["max"]),
                    "low": int(day["temp"]["min"]),
                    "icon": weather_icon_path,
                    "moon_phase_pct": moon_pct,
                    "moon_phase_icon": moon_icon_path,
                }
            )

        return forecast
        
    def parse_open_meteo_forecast(self, daily_data, units, tz, is_day, lat):
        """
        Parse the daily forecast from Open-Meteo API and calculate moon phase and illumination using the local 'astral' library.
        """
        times = daily_data.get('time', [])
        weather_codes = daily_data.get('weathercode', [])
        temp_max = daily_data.get('temperature_2m_max', [])
        temp_min = daily_data.get('temperature_2m_min', [])
        if units == "standard":
            temp_max = [T + 273.15 for T in temp_max]
            temp_min = [T + 273.15 for T in temp_min]

        forecast = []

        for i in range(0, len(times)): 
            dt = self.parse_open_meteo_time(times[i], tz)
            day_label = dt.strftime("%a")

            code = weather_codes[i] if i < len(weather_codes) else 0
            weather_icon = self.map_weather_code_to_icon(code, is_day=1)
            weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            timestamp = int(dt.replace(hour=12, minute=0, second=0).timestamp())
            target_date: date = dt.date() + timedelta(days=1)

            try:
                phase_age = moon.phase(target_date)
                phase_name_north_hemi = get_moon_phase_name(phase_age)
                LUNAR_CYCLE_DAYS = 29.530588853
                phase_fraction = phase_age / LUNAR_CYCLE_DAYS
                illum_pct = (1 - math.cos(2 * math.pi * phase_fraction)) / 2 * 100
            except Exception as e:
                logger.error(f"Error calculating moon phase for {target_date}: {e}")
                illum_pct = 0
                phase_name_north_hemi = "newmoon"
            moon_icon_path = self.get_moon_phase_icon_path(phase_name_north_hemi, lat)

            forecast.append({
                "day": day_label,
                "high": int(temp_max[i]) if i < len(temp_max) else 0,
                "low": int(temp_min[i]) if i < len(temp_min) else 0,
                "icon": weather_icon_path,
                "moon_phase_pct": f"{illum_pct:.0f}",
                "moon_phase_icon": moon_icon_path
            })

        return forecast

    def parse_hourly(self, hourly_forecast, tz, time_format, units, daily_forecast):
        hourly = []
        icon_codes_to_preserve = ["01", "02", "10"]
        
        sun_map = {}
        for day in daily_forecast:
            day_date = datetime.fromtimestamp(day['dt'], tz=timezone.utc).astimezone(tz).date()
            sun_map[day_date] = (day['sunrise'], day['sunset'])
        
        for hour in hourly_forecast[:24]:
            dt_epoch = hour.get('dt')
            dt = datetime.fromtimestamp(dt_epoch, tz=timezone.utc).astimezone(tz)
            rain_mm = hour.get("rain", {}).get("1h", 0.0)
            snow_mm = hour.get("snow", {}).get("1h", 0.0)
            total_precip_mm = rain_mm + snow_mm
            sunrise, sunset = sun_map.get(dt.date(), (0, 0))
        
            is_day = sunrise <= dt_epoch < sunset
            suffix = 'd' if is_day else 'n'
        
            raw_icon = hour.get("weather", [{}])[0].get("icon", "01d")
            icon_base = raw_icon[:2]
            icon_name = f"{icon_base}{suffix}" if icon_base in icon_codes_to_preserve else f"{icon_base}d"
            
            if units == "imperial":
                precip_value = total_precip_mm / 25.4
            else:
                precip_value = total_precip_mm 
            hour_forecast = {
                "time": self.format_time(dt, time_format, hour_only=True),
                "temperature": int(hour.get("temp")),
                "precipitation": hour.get("pop"),
                "rain": round(precip_value, 2),
                "icon": self.get_plugin_dir(f'icons/{icon_name}.png')
            }
            hourly.append(hour_forecast)
        return hourly

    def parse_open_meteo_hourly(self, hourly_data, units, tz, time_format, sunrises, sunsets, current_time=None):
        hourly = []
        times = hourly_data.get('time', [])
        temperatures = hourly_data.get('temperature_2m', [])
        if units == "standard":
            temperatures = [temperature + 273.15 for temperature in temperatures]
        precipitation_probabilities = hourly_data.get('precipitation_probability', [])
        rain = hourly_data.get('precipitation', [])
        codes = hourly_data.get('weather_code', [])
        
        sun_map = {}
        for sr_s, ss_s in zip(sunrises, sunsets):
            sr_dt = self.parse_open_meteo_time(sr_s, tz)
            ss_dt = self.parse_open_meteo_time(ss_s, tz)
            sun_map[sr_dt.date()] = (sr_dt, ss_dt)
        
        current_time_in_tz = current_time or datetime.now(tz)
        start_index = 0
        for i, time_str in enumerate(times):
            try:
                dt_hourly = self.parse_open_meteo_time(time_str, tz)
                if dt_hourly.date() == current_time_in_tz.date() and dt_hourly.hour >= current_time_in_tz.hour:
                    start_index = i
                    break
                if dt_hourly.date() > current_time_in_tz.date():
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} in hourly data.")
                continue

        sliced_times = times[start_index:]
        sliced_temperatures = temperatures[start_index:]
        sliced_precipitation_probabilities = precipitation_probabilities[start_index:]
        sliced_rain = rain[start_index:]
        sliced_codes = codes[start_index:]

        for i in range(min(24, len(sliced_times))):
            dt = self.parse_open_meteo_time(sliced_times[i], tz)
            sunrise, sunset = sun_map.get(dt.date(), (None, None))
            is_day = 0
            if sunrise and sunset:
                is_day = 1 if sunrise <= dt < sunset else 0
            code = sliced_codes[i] if i < len(sliced_codes) else 0
            icon_name = self.map_weather_code_to_icon(code, is_day)
            hour_forecast = {
                "time": self.format_time(dt, time_format, True),
                "temperature": int(sliced_temperatures[i]) if i < len(sliced_temperatures) else 0,
                "precipitation": (sliced_precipitation_probabilities[i] / 100) if i < len(sliced_precipitation_probabilities) else 0,
                "rain": (sliced_rain[i]) if i < len(sliced_rain) else 0,
                "icon": self.get_plugin_dir(f"icons/{icon_name}.png")
            }
            hourly.append(hour_forecast)
        return hourly

    def parse_data_points(self, weather, air_quality, tz, units, time_format):
        data_points = []
        sunrise_epoch = weather.get('current', {}).get("sunrise")

        if sunrise_epoch:
            sunrise_dt = datetime.fromtimestamp(sunrise_epoch, tz=timezone.utc).astimezone(tz)
            data_points.append({
                "label": "Sunrise",
                "measurement": self.format_time(sunrise_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunrise_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })
        else:
            logger.error(f"Sunrise not found in OpenWeatherMap response, this is expected for polar areas in midnight sun and polar night periods.")

        sunset_epoch = weather.get('current', {}).get("sunset")
        if sunset_epoch:
            sunset_dt = datetime.fromtimestamp(sunset_epoch, tz=timezone.utc).astimezone(tz)
            data_points.append({
                "label": "Sunset",
                "measurement": self.format_time(sunset_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunset_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunset.png')
            })
        else:
            logger.error(f"Sunset not found in OpenWeatherMap response, this is expected for polar areas in midnight sun and polar night periods.")

        wind_deg = weather.get('current', {}).get("wind_deg", 0)
        wind_arrow = self.get_wind_arrow(wind_deg)
        data_points.append({
            "label": "Wind",
            "measurement": weather.get('current', {}).get("wind_speed"),
            "unit": UNITS[units]["speed"],
            "icon": self.get_plugin_dir('icons/wind.png'),
            "arrow": wind_arrow
        })

        data_points.append({
            "label": "Humidity",
            "measurement": weather.get('current', {}).get("humidity"),
            "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        data_points.append({
            "label": "Pressure",
            "measurement": weather.get('current', {}).get("pressure"),
            "unit": 'hPa',
            "icon": self.get_plugin_dir('icons/pressure.png')
        })

        data_points.append({
            "label": "UV Index",
            "measurement": weather.get('current', {}).get("uvi"),
            "unit": '',
            "icon": self.get_plugin_dir('icons/uvi.png')
        })

        visibility = weather.get('current', {}).get("visibility")
        if units == "imperial":
            # convert from m to mi
            visibility /= 1609.
            at_max_visibility = visibility >= 6.2
        else:
            # convert from m to km
            visibility /= 1000.
            at_max_visibility = visibility >= 10
        visibility_str = f"{visibility:.1f}"
        if at_max_visibility:
            visibility_str = u"\u2265" + visibility_str
        data_points.append({
            "label": "Visibility",
            "measurement": visibility_str,
            "unit": UNITS[units]["distance"],
            "icon": self.get_plugin_dir('icons/visibility.png')
        })

        aqi = air_quality.get('list', [])[0].get("main", {}).get("aqi")
        data_points.append({
            "label": "Air Quality",
            "measurement": aqi,
            "unit": ["Good", "Fair", "Moderate", "Poor", "Very Poor"][int(aqi)-1],
            "icon": self.get_plugin_dir('icons/aqi.png')
        })

        return data_points

    def parse_open_meteo_data_points(self, weather_data, aqi_data, units, tz, time_format, current_time=None):
        """Parses current data points from Open-Meteo API response."""
        data_points = []
        daily_data = weather_data.get('daily', {})
        current_data = weather_data.get('current', {})
        hourly_data = weather_data.get('hourly', {})

        current_time = current_time or datetime.now(tz)

        # Sunrise
        sunrise_times = daily_data.get('sunrise', [])
        if sunrise_times:
            sunrise_dt = self.parse_open_meteo_time(sunrise_times[0], tz)
            data_points.append({
                "label": "Sunrise",
                "measurement": self.format_time(sunrise_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunrise_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })
        else:
            logger.error(f"Sunrise not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods.")

        # Sunset
        sunset_times = daily_data.get('sunset', [])
        if sunset_times:
            sunset_dt = self.parse_open_meteo_time(sunset_times[0], tz)
            data_points.append({
                "label": "Sunset",
                "measurement": self.format_time(sunset_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunset_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunset.png')
            })
        else:
            logger.error(f"Sunset not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods.")

        # Wind
        wind_speed = current_data.get("windspeed", 0)
        wind_deg = current_data.get("winddirection", 0)
        wind_arrow = self.get_wind_arrow(wind_deg)
        wind_unit = UNITS[units]["speed"]
        data_points.append({
            "label": "Wind", "measurement": wind_speed, "unit": wind_unit,
            "icon": self.get_plugin_dir('icons/wind.png'), "arrow": wind_arrow
        })

        # Humidity
        current_humidity = "N/A"
        humidity_hourly_times = hourly_data.get('time', [])
        humidity_values = hourly_data.get('relative_humidity_2m', [])
        for i, time_str in enumerate(humidity_hourly_times):
            try:
                parsed_time = self.parse_open_meteo_time(time_str, tz)
                if parsed_time.date() == current_time.date() and parsed_time.hour == current_time.hour:
                    current_humidity = int(humidity_values[i])
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for humidity.")
                continue
        data_points.append({
            "label": "Humidity", "measurement": current_humidity, "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        # Pressure
        current_pressure = "N/A"
        pressure_hourly_times = hourly_data.get('time', [])
        pressure_values = hourly_data.get('surface_pressure', [])
        for i, time_str in enumerate(pressure_hourly_times):
            try:
                parsed_time = self.parse_open_meteo_time(time_str, tz)
                if parsed_time.date() == current_time.date() and parsed_time.hour == current_time.hour:
                    current_pressure = int(pressure_values[i])
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for pressure.")
                continue
        data_points.append({
            "label": "Pressure", "measurement": current_pressure, "unit": 'hPa',
            "icon": self.get_plugin_dir('icons/pressure.png')
        })

        # UV Index
        uv_index_hourly_times = aqi_data.get('hourly', {}).get('time', [])
        uv_index_values = aqi_data.get('hourly', {}).get('uv_index', [])
        current_uv_index = "N/A"
        for i, time_str in enumerate(uv_index_hourly_times):
            try:
                parsed_time = self.parse_open_meteo_time(time_str, tz)
                if parsed_time.date() == current_time.date() and parsed_time.hour == current_time.hour:
                    current_uv_index = uv_index_values[i]
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for UV Index.")
                continue
        data_points.append({
            "label": "UV Index", "measurement": current_uv_index, "unit": '',
            "icon": self.get_plugin_dir('icons/uvi.png')
        })

        # Visibility
        current_visibility = "N/A"
        visibility_hourly_times = hourly_data.get('time', [])
        visibility_values = hourly_data.get('visibility', [])
        if units == "imperial":
            visibility_conversion = 1/5280.     # ft to mi
            visibility_max = 6.2                # mi
        else:
            visibility_conversion = 0.001       # m to km
            visibility_max = 10.                # km
        for i, time_str in enumerate(visibility_hourly_times):
            try:
                parsed_time = self.parse_open_meteo_time(time_str, tz)
                if parsed_time.date() == current_time.date() and parsed_time.hour == current_time.hour:
                    current_visibility = visibility_values[i]*visibility_conversion
                    at_max_visibility = current_visibility >= visibility_max
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for visibility.")
                continue
        visibility_str = f"{current_visibility:.1f}"
        if at_max_visibility:
            visibility_str = u"\u2265" + visibility_str
        data_points.append({
            "label": "Visibility", 
            "measurement": visibility_str, 
            "unit": UNITS[units]["distance"],
            "icon": self.get_plugin_dir('icons/visibility.png')
        })

        # Air Quality
        aqi_hourly_times = aqi_data.get('hourly', {}).get('time', [])
        aqi_values = aqi_data.get('hourly', {}).get('european_aqi', [])
        current_aqi = "N/A"
        for i, time_str in enumerate(aqi_hourly_times):
            try:
                parsed_time = self.parse_open_meteo_time(time_str, tz)
                if parsed_time.date() == current_time.date() and parsed_time.hour == current_time.hour:
                    current_aqi = round(aqi_values[i], 1)
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for AQI.")
                continue
        scale = ""
        if current_aqi and current_aqi != "N/A":
            scale = ["Good","Fair","Moderate","Poor","Very Poor","Ext Poor"][min(current_aqi//20,5)]
        data_points.append({
            "label": "Air Quality", "measurement": current_aqi,
            "unit": scale, "icon": self.get_plugin_dir('icons/aqi.png')
        })

        return data_points

    def get_wind_arrow(self, wind_deg: float) -> str:
        DIRECTIONS = [
            ("↓", 22.5),    # North (N)
            ("↙", 67.5),    # North-East (NE)
            ("←", 112.5),   # East (E)
            ("↖", 157.5),   # South-East (SE)
            ("↑", 202.5),   # South (S)
            ("↗", 247.5),   # South-West (SW)
            ("→", 292.5),   # West (W)
            ("↘", 337.5),   # North-West (NW)
            ("↓", 360.0)    # Wrap back to North
        ]
        wind_deg = wind_deg % 360
        for arrow, upper_bound in DIRECTIONS:
            if wind_deg < upper_bound:
                return arrow

        return "↑"

    def get_weather_data(self, api_key, units, lat, long):
        url = WEATHER_URL.format(lat=lat, long=long, units=units, api_key=api_key)
        response = requests.get(url, timeout=30)
        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve weather data: {response.content}")
            raise RuntimeError("Failed to retrieve weather data.")

        return response.json()

    def get_air_quality(self, api_key, lat, long):
        url = AIR_QUALITY_URL.format(lat=lat, long=long, api_key=api_key)
        response = requests.get(url, timeout=30)

        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to get air quality data: {response.content}")
            raise RuntimeError("Failed to retrieve air quality data.")

        return response.json()

    def get_location(self, api_key, lat, long):
        url = GEOCODING_URL.format(lat=lat, long=long, api_key=api_key)
        response = requests.get(url, timeout=30)

        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to get location: {response.content}")
            raise RuntimeError("Failed to retrieve location.")

        location_data = response.json()[0]
        location_str = f"{location_data.get('name')}, {location_data.get('state', location_data.get('country'))}"

        return location_str

    def get_open_meteo_data(self, lat, long, units, forecast_days, timezone_name="auto"):
        unit_params = OPEN_METEO_UNIT_PARAMS[units]
        url = OPEN_METEO_FORECAST_URL.format(
            lat=lat,
            long=long,
            forecast_days=forecast_days,
            timezone=quote(timezone_name, safe="")
        ) + f"&{unit_params}"
        response = requests.get(url, timeout=30)

        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve Open-Meteo weather data: {response.content}")
            raise RuntimeError("Failed to retrieve Open-Meteo weather data.")
        
        return response.json()

    def get_open_meteo_air_quality(self, lat, long, timezone_name="auto"):
        url = OPEN_METEO_AIR_QUALITY_URL.format(lat=lat, long=long, timezone=quote(timezone_name, safe=""))
        response = requests.get(url, timeout=30)
        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve Open-Meteo air quality data: {response.content}")
            raise RuntimeError("Failed to retrieve Open-Meteo air quality data.")
        
        return response.json()
    
    def format_time(self, dt, time_format, hour_only=False, include_am_pm=True):
        """Format datetime based on 12h or 24h preference"""
        if time_format == "24h":
            return dt.strftime("%H:00" if hour_only else "%H:%M")
        
        if include_am_pm:
            fmt = "%I %p" if hour_only else "%I:%M %p"
        else:
            fmt = "%I" if hour_only else "%I:%M"

        return dt.strftime(fmt).lstrip("0")
    
    def parse_timezone(self, weatherdata):
        """Parse timezone from weather data"""
        if 'timezone' in weatherdata:
            logger.info(f"Using timezone from weather data: {weatherdata['timezone']}")
            return pytz.timezone(weatherdata['timezone'])
        else:
            logger.error("Failed to retrieve Timezone from weather data")
            raise RuntimeError("Timezone not found in weather data.")
