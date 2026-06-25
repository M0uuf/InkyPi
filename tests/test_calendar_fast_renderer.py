import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if "icalendar" not in sys.modules:
    sys.modules["icalendar"] = types.SimpleNamespace(Calendar=types.SimpleNamespace(from_ical=lambda text: text))
if "recurring_ical_events" not in sys.modules:
    sys.modules["recurring_ical_events"] = types.SimpleNamespace(
        of=lambda calendar: types.SimpleNamespace(between=lambda start, end: [])
    )

from plugins.calendar.calendar import Calendar
import plugins.calendar.calendar as calendar_module


class FakeResponse:
    def __init__(self, status_code=200, text="BEGIN:VCALENDAR\nEND:VCALENDAR"):
        self.status_code = status_code
        self.text = text
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise RuntimeError(f"HTTP {self.status_code}")


def patch_calendar_response(monkeypatch, response):
    calls = []

    def fake_get(url, timeout):
        calls.append({"url": url, "timeout": timeout})
        return response

    monkeypatch.setattr(calendar_module.requests, "get", fake_get)
    return calls


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


def fake_ics_event(summary):
    return {"summary": summary}


def run_fetch_with_urls_and_colors(monkeypatch, calendar_urls, colors):
    plugin = build_calendar_plugin()
    fetched_urls = []

    def fake_fetch_calendar(url):
        fetched_urls.append(url)
        return url

    def fake_events_for(calendar):
        return types.SimpleNamespace(
            between=lambda start, end: [fake_ics_event(f"Event for {calendar}")]
        )

    monkeypatch.setattr(plugin, "fetch_calendar", fake_fetch_calendar)
    monkeypatch.setattr(plugin, "parse_data_points", lambda event, tz: (
        "2026-06-11T09:00:00+00:00",
        "2026-06-11T10:00:00+00:00",
        False
    ))
    import plugins.calendar.calendar as calendar_module
    monkeypatch.setattr(calendar_module.recurring_ical_events, "of", fake_events_for)

    events = plugin.fetch_ics_events(
        calendar_urls,
        colors,
        "UTC",
        datetime(2026, 6, 11),
        datetime(2026, 6, 12)
    )
    return fetched_urls, events


def test_calendar_fetch_uses_default_color_when_colors_missing(monkeypatch):
    calendar_urls = [
        "https://example.invalid/work.ics",
        "https://example.invalid/home.ics"
    ]

    fetched_urls, events = run_fetch_with_urls_and_colors(monkeypatch, calendar_urls, None)

    assert fetched_urls == calendar_urls
    assert [event["backgroundColor"] for event in events] == ["#007BFF", "#007BFF"]


def test_calendar_fetch_fills_shorter_color_list(monkeypatch):
    calendar_urls = [
        "https://example.invalid/work.ics",
        "https://example.invalid/home.ics"
    ]

    fetched_urls, events = run_fetch_with_urls_and_colors(monkeypatch, calendar_urls, ["#112233"])

    assert fetched_urls == calendar_urls
    assert [event["backgroundColor"] for event in events] == ["#112233", "#007BFF"]


def test_calendar_fetch_ignores_extra_colors_and_preserves_matching_colors(monkeypatch):
    calendar_urls = [
        "https://example.invalid/work.ics",
        "https://example.invalid/home.ics"
    ]

    fetched_urls, events = run_fetch_with_urls_and_colors(
        monkeypatch,
        calendar_urls,
        ["#112233", "#445566", "#778899"]
    )

    assert fetched_urls == calendar_urls
    assert [event["backgroundColor"] for event in events] == ["#112233", "#445566"]


def test_calendar_fetch_closes_response_and_parses_ics(monkeypatch):
    plugin = build_calendar_plugin()
    response = FakeResponse(text="BEGIN:VCALENDAR\nSUMMARY:Test\nEND:VCALENDAR")
    calls = patch_calendar_response(monkeypatch, response)
    parsed_calendar = object()

    monkeypatch.setattr(
        calendar_module.icalendar.Calendar,
        "from_ical",
        staticmethod(lambda text: parsed_calendar)
    )

    result = plugin.fetch_calendar("webcal://example.invalid/calendar.ics")

    assert result is parsed_calendar
    assert response.closed is True
    assert calls == [{"url": "https://example.invalid/calendar.ics", "timeout": 30}]


def test_calendar_fetch_failure_closes_response_and_raises(monkeypatch):
    plugin = build_calendar_plugin()
    response = FakeResponse(status_code=404, text="missing")
    patch_calendar_response(monkeypatch, response)

    with pytest.raises(RuntimeError, match="Failed to fetch iCalendar url"):
        plugin.fetch_calendar("https://example.invalid/missing.ics")

    assert response.closed is True
