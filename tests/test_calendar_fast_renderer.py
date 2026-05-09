import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if "icalendar" not in sys.modules:
    sys.modules["icalendar"] = types.SimpleNamespace(Calendar=types.SimpleNamespace(from_ical=lambda text: text))
if "recurring_ical_events" not in sys.modules:
    sys.modules["recurring_ical_events"] = types.SimpleNamespace(
        of=lambda calendar: types.SimpleNamespace(between=lambda start, end: [])
    )

from plugins.calendar.calendar import Calendar


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


def build_calendar_plugin():
    return Calendar({"id": "calendar"})


def build_settings(render_mode="fast", view_mode="dayGridMonth"):
    return {
        "calendarURLs[]": ["https://example.invalid/calendar.ics"],
        "calendarColors[]": ["#007BFF"],
        "viewMode": view_mode,
        "renderMode": render_mode,
        "displayTitle": "true",
        "displayWeekends": "true",
        "displayEventTime": "true",
        "displayNowIndicator": "true",
        "displayPreviousDays": "true",
        "weekStartDay": "1",
        "startTimeInterval": "8",
        "endTimeInterval": "18",
        "displayWeeks": "4",
        "fontSize": "normal",
        "backgroundColor": "#ffffff",
        "textColor": "#000000",
        "nowIndicatorColor": "#ff0000"
    }


def build_events():
    start = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    return [
        {
            "title": "Planning",
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
            "backgroundColor": "#007BFF",
            "textColor": "#ffffff",
            "allDay": False
        },
        {
            "title": "Release",
            "start": (start + timedelta(days=1)).date().isoformat(),
            "backgroundColor": "#00AA66",
            "textColor": "#000000",
            "allDay": True
        }
    ]


def build_template_params(view="dayGridMonth"):
    settings = build_settings(view_mode=view)
    return {
        "view": view,
        "events": build_events(),
        "current_dt": datetime.now().replace(minute=0, second=0, microsecond=0).isoformat(),
        "view_start": (datetime.now() - timedelta(weeks=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "view_end": (datetime.now() + timedelta(weeks=4)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "timezone": "UTC",
        "plugin_settings": settings,
        "time_format": "24h",
        "font_scale": 1
    }


def test_calendar_fast_renderer_outputs_horizontal_and_vertical_images():
    plugin = build_calendar_plugin()
    params = build_template_params()
    current_dt = datetime.fromisoformat(params["current_dt"])

    horizontal = plugin.render_fast_image((800, 480), params, current_dt)
    vertical = plugin.render_fast_image((480, 800), params, current_dt)

    assert horizontal.size == (800, 480)
    assert vertical.size == (480, 800)


def test_calendar_fast_mode_generate_image_does_not_use_html_renderer(monkeypatch):
    plugin = build_calendar_plugin()
    settings = build_settings()

    monkeypatch.setattr(plugin, "fetch_ics_events", lambda *args, **kwargs: build_events())
    monkeypatch.setattr(
        plugin,
        "render_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTML renderer should not be used in fast mode"))
    )

    image = plugin.generate_image(settings, FakeDeviceConfig())

    assert isinstance(image, Image.Image)
    assert image.size == (800, 480)


def test_calendar_unknown_render_mode_warns_and_uses_html_renderer(monkeypatch, caplog):
    plugin = build_calendar_plugin()
    settings = build_settings(render_mode="unexpected")

    monkeypatch.setattr(plugin, "fetch_ics_events", lambda *args, **kwargs: build_events())
    monkeypatch.setattr(plugin, "render_image", lambda *args, **kwargs: Image.new("RGB", (800, 480), "white"))

    image = plugin.generate_image(settings, FakeDeviceConfig())

    assert image.size == (800, 480)
    assert "Unknown Calendar renderMode" in caplog.text


def test_calendar_fast_daygrid_uses_rolling_view_start_for_grid_start():
    plugin = build_calendar_plugin()
    current_dt = datetime(2026, 5, 20, 12, 0)
    settings = build_settings(view_mode="dayGrid")
    view_start, _ = plugin.get_view_range("dayGrid", current_dt, settings)

    grid_start = plugin._get_fast_grid_start("dayGrid", current_dt, int(settings["weekStartDay"]), view_start.isoformat())

    assert grid_start.date() == datetime(2026, 5, 11).date()
    assert grid_start.month == 5
