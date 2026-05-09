import os
from utils.app_utils import resolve_path, get_font
from plugins.base_plugin.base_plugin import BasePlugin
from plugins.calendar.constants import LOCALE_MAP, FONT_SIZES
from PIL import Image, ImageColor, ImageDraw, ImageFont
import icalendar
import recurring_ical_events
from io import BytesIO
import logging
import requests
import time
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

class Calendar(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        template_params['locale_map'] = LOCALE_MAP
        return template_params

    def generate_image(self, settings, device_config):
        calendar_urls = settings.get('calendarURLs[]')
        calendar_colors = settings.get('calendarColors[]')
        view = settings.get("viewMode")

        if not view:
            raise RuntimeError("View is required")
        elif view not in ["timeGridDay", "timeGridWeek", "dayGrid", "dayGridMonth", "listMonth"]:
            raise RuntimeError("Invalid view")

        if not calendar_urls:
            raise RuntimeError("At least one calendar URL is required")
        for url in calendar_urls:
            if not url.strip():
                raise RuntimeError("Invalid calendar URL")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        
        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)

        current_dt = datetime.now(tz)
        start, end = self.get_view_range(view, current_dt, settings)
        logger.debug(f"Fetching events for {start} --> [{current_dt}] --> {end}")
        events = self.fetch_ics_events(calendar_urls, calendar_colors, tz, start, end)
        if not events:
            logger.warning("No events found for ics url")

        if view == 'timeGridWeek' and settings.get("displayPreviousDays") != "true":
            view = 'timeGrid'

        template_params = {
            "view": view,
            "events": events,
            "current_dt": current_dt.replace(minute=0, second=0, microsecond=0).isoformat(),
            "timezone": timezone,
            "plugin_settings": settings,
            "time_format": time_format,
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal"))
        }

        render_mode = settings.get("renderMode", "html")
        if render_mode not in {"html", "fast"}:
            logger.warning("Unknown Calendar renderMode '%s'; falling back to HTML renderer.", render_mode)
            render_mode = "html"

        render_started = time.monotonic()
        if render_mode == "fast":
            image = self.render_fast_image(dimensions, template_params, current_dt)
            logger.info(
                "Rendered Calendar plugin with fast Pillow renderer in %.2fs | dimensions: %sx%s",
                time.monotonic() - render_started,
                dimensions[0],
                dimensions[1]
            )
        else:
            image = self.render_image(dimensions, "calendar.html", "calendar.css", template_params)

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    def render_fast_image(self, dimensions, template_params, current_dt=None):
        """Render a simplified Calendar image without launching Chromium."""
        width, height = int(dimensions[0]), int(dimensions[1])
        settings = template_params.get("plugin_settings", {})
        background_color = settings.get("backgroundColor") or "#ffffff"
        text_color = settings.get("textColor") or "#000000"
        accent_color = settings.get("nowIndicatorColor") or settings.get("accentColor") or "#555555"

        image = Image.new("RGB", (width, height), background_color)
        draw = ImageDraw.Draw(image)
        margin = max(8, int(min(width, height) * 0.035))
        y = margin

        current_dt = current_dt or datetime.fromisoformat(template_params["current_dt"])
        view = template_params.get("view")
        events = self._prepare_fast_events(template_params.get("events", []), current_dt.tzinfo)

        if settings.get("displayTitle") == "true":
            title_font = self._get_fast_font(max(16, int(height * 0.07)), "bold")
            title = self._get_fast_title(view, current_dt, settings)
            self._draw_centered_fit_text(draw, title, margin, y, width - (2 * margin), title_font, text_color)
            y += self._text_height(draw, title, title_font) + max(4, margin // 2)

        if view in {"dayGridMonth", "dayGrid"}:
            self._draw_fast_month_grid(
                draw,
                events,
                current_dt,
                settings,
                (margin, y, width - margin, height - margin),
                text_color,
                accent_color
            )
        else:
            self._draw_fast_event_list(
                draw,
                events,
                current_dt,
                settings,
                template_params.get("time_format", "12h"),
                (margin, y, width - margin, height - margin),
                text_color,
                accent_color
            )

        return image

    def _prepare_fast_events(self, events, fallback_tz):
        parsed_events = []
        for event in events:
            start = self._parse_fast_datetime(event.get("start"), fallback_tz)
            end = self._parse_fast_datetime(event.get("end"), fallback_tz) if event.get("end") else None
            if not start:
                continue
            parsed_events.append({
                "title": event.get("title") or "Untitled",
                "start": start,
                "end": end,
                "all_day": event.get("allDay", False),
                "background_color": event.get("backgroundColor") or "#007BFF",
                "text_color": event.get("textColor") or "#000000"
            })
        parsed_events.sort(key=lambda event: event["start"])
        return parsed_events

    def _parse_fast_datetime(self, value, fallback_tz):
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None and fallback_tz is not None:
            parsed = fallback_tz.localize(parsed) if hasattr(fallback_tz, "localize") else parsed.replace(tzinfo=fallback_tz)
        return parsed

    def _get_fast_title(self, view, current_dt, settings):
        if view in {"timeGridDay", "listMonth"}:
            return current_dt.strftime("%A, %B %-d")
        if view in {"timeGridWeek", "timeGrid"}:
            return f"Week of {current_dt.strftime('%b %-d')}"
        if view == "dayGrid":
            weeks = settings.get("displayWeeks") or 4
            return f"Next {weeks} Weeks"
        return current_dt.strftime("%B %Y")

    def _draw_fast_event_list(self, draw, events, current_dt, settings, time_format, bounds, text_color, accent_color):
        left, top, right, bottom = bounds
        width = max(1, right - left)
        line_gap = max(3, int((bottom - top) * 0.015))
        date_font = self._get_fast_font(max(12, int((bottom - top) * 0.055)), "bold")
        event_font = self._get_fast_font(max(10, int((bottom - top) * 0.045)), "normal")
        time_font = self._get_fast_font(max(9, int((bottom - top) * 0.038)), "normal")
        y = top
        visible_events = events[:24]
        if not visible_events:
            self._draw_centered_fit_text(draw, "No events", left, y, width, event_font, accent_color)
            return

        last_date = None
        for event in visible_events:
            if y >= bottom:
                break
            event_date = event["start"].date()
            if event_date != last_date:
                label = event["start"].strftime("%a, %b %-d")
                draw.text((left, y), label, fill=accent_color, font=date_font)
                y += self._text_height(draw, label, date_font) + line_gap
                last_date = event_date

            marker_size = max(6, self._text_height(draw, event["title"], event_font) // 2)
            draw.rounded_rectangle(
                (left, y + marker_size // 2, left + marker_size, y + marker_size + marker_size // 2),
                radius=max(1, marker_size // 3),
                fill=event["background_color"]
            )
            time_label = "All day" if event["all_day"] else self._format_fast_time(event["start"], time_format)
            draw.text((left + marker_size + 6, y), time_label, fill=accent_color, font=time_font)
            title_x = left + marker_size + 6 + max(55, int(width * 0.18))
            self._draw_fit_text(draw, event["title"], title_x, y, right - title_x, event_font, text_color)
            y += max(self._text_height(draw, event["title"], event_font), self._text_height(draw, time_label, time_font)) + line_gap

    def _draw_fast_month_grid(self, draw, events, current_dt, settings, bounds, text_color, accent_color):
        left, top, right, bottom = bounds
        width = max(1, right - left)
        height = max(1, bottom - top)
        week_start = int(settings.get("weekStartDay") or 0)
        first_day = datetime(current_dt.year, current_dt.month, 1, tzinfo=current_dt.tzinfo)
        start_offset = (first_day.weekday() - ((week_start - 1) % 7)) % 7
        grid_start = first_day - timedelta(days=start_offset)
        rows = 6 if settings.get("viewMode") != "dayGrid" else max(1, int(settings.get("displayWeeks") or 4))
        header_height = max(14, int(height * 0.08))
        cell_width = width / 7
        cell_height = max(1, (height - header_height) / rows)
        day_font = self._get_fast_font(max(8, int(header_height * 0.55)), "bold")
        number_font = self._get_fast_font(max(9, int(cell_height * 0.16)), "bold")
        event_font = self._get_fast_font(max(7, int(cell_height * 0.13)), "normal")

        weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        weekdays = weekdays[week_start:] + weekdays[:week_start]
        for column, weekday in enumerate(weekdays):
            x = int(left + column * cell_width)
            self._draw_centered_fit_text(draw, weekday, x, top, int(cell_width), day_font, accent_color)

        events_by_date = {}
        for event in events:
            events_by_date.setdefault(event["start"].date(), []).append(event)

        today = current_dt.date()
        for row in range(rows):
            for column in range(7):
                date_value = (grid_start + timedelta(days=(row * 7) + column)).date()
                cell_left = int(left + column * cell_width)
                cell_top = int(top + header_height + row * cell_height)
                cell_right = int(left + (column + 1) * cell_width)
                cell_bottom = int(top + header_height + (row + 1) * cell_height)
                outline = accent_color if date_value == today else text_color
                draw.rectangle((cell_left, cell_top, cell_right, cell_bottom), outline=outline, width=2 if date_value == today else 1)
                number_fill = text_color if date_value.month == current_dt.month else accent_color
                draw.text((cell_left + 3, cell_top + 2), str(date_value.day), fill=number_fill, font=number_font)

                event_y = cell_top + self._text_height(draw, str(date_value.day), number_font) + 4
                for event in events_by_date.get(date_value, [])[:3]:
                    if event_y >= cell_bottom - 2:
                        break
                    text = event["title"]
                    chip_height = self._text_height(draw, text, event_font) + 2
                    draw.rounded_rectangle(
                        (cell_left + 2, event_y, cell_right - 2, min(cell_bottom - 1, event_y + chip_height)),
                        radius=2,
                        fill=event["background_color"]
                    )
                    self._draw_fit_text(draw, text, cell_left + 4, event_y + 1, cell_right - cell_left - 8, event_font, event["text_color"])
                    event_y += chip_height + 2

    def _get_fast_font(self, size, weight="normal"):
        return get_font("Jost", size, weight) or get_font("Jost", size) or ImageFont.load_default()

    def _format_fast_time(self, dt, time_format):
        if time_format == "24h":
            return dt.strftime("%H:%M")
        return dt.strftime("%I:%M %p").lstrip("0")

    def _text_height(self, draw, text, font):
        bbox = draw.textbbox((0, 0), str(text), font=font)
        return bbox[3] - bbox[1]

    def _text_width(self, draw, text, font):
        bbox = draw.textbbox((0, 0), str(text), font=font)
        return bbox[2] - bbox[0]

    def _draw_fit_text(self, draw, text, x, y, width, font, fill):
        text = self._truncate_text(draw, text, width, font)
        draw.text((x, y), text, fill=fill, font=font)

    def _draw_centered_fit_text(self, draw, text, x, y, width, font, fill):
        text = self._truncate_text(draw, text, width, font)
        draw.text((x + max(0, (width - self._text_width(draw, text, font)) // 2), y), text, fill=fill, font=font)

    def _truncate_text(self, draw, text, width, font):
        text = str(text)
        while self._text_width(draw, text, font) > width and len(text) > 4:
            text = text[:-4].rstrip() + "..."
        return text
    
    def fetch_ics_events(self, calendar_urls, colors, tz, start_range, end_range):
        parsed_events = []

        for calendar_url, color in zip(calendar_urls, colors):
            cal = self.fetch_calendar(calendar_url)
            events = recurring_ical_events.of(cal).between(start_range, end_range)
            contrast_color = self.get_contrast_color(color)

            for event in events:
                start, end, all_day = self.parse_data_points(event, tz)
                parsed_event = {
                    "title": str(event.get("summary")),
                    "start": start,
                    "backgroundColor": color,
                    "textColor": contrast_color,
                    "allDay": all_day
                }
                if end:
                    parsed_event['end'] = end

                parsed_events.append(parsed_event)

        return parsed_events
    
    def get_view_range(self, view, current_dt, settings):
        start = datetime(current_dt.year, current_dt.month, current_dt.day)
        if view == "timeGridDay":
            end = start + timedelta(days=1)
        elif view == "timeGridWeek":
            if settings.get("displayPreviousDays") == "true":
                week_start_day = int(settings.get("weekStartDay", 1))
                python_week_start = (week_start_day - 1) % 7
                offset = (current_dt.weekday() - python_week_start) % 7
                start = current_dt - timedelta(days=offset)
                start = datetime(start.year, start.month, start.day)
            end = start + timedelta(days=7)
        elif view == "dayGrid":
            start = current_dt - timedelta(weeks=1)
            end = current_dt + timedelta(weeks=int(settings.get("displayWeeks") or 4))
        elif view == "dayGridMonth":
            start = datetime(current_dt.year, current_dt.month, 1) - timedelta(weeks=1)
            end = datetime(current_dt.year, current_dt.month, 1) + timedelta(weeks=6)
        elif view == "listMonth":
            end = start + timedelta(weeks=5)
        return start, end
        
    def parse_data_points(self, event, tz):
        all_day = False
        dtstart = event.decoded("dtstart")
        if isinstance(dtstart, datetime):
            start = dtstart.astimezone(tz).isoformat()
        else:
            start = dtstart.isoformat()
            all_day = True

        end = None
        if "dtend" in event:
            dtend = event.decoded("dtend")
            if isinstance(dtend, datetime):
                end = dtend.astimezone(tz).isoformat()
            else:
                end = dtend.isoformat()
        elif "duration" in event:
            duration = event.decoded("duration")
            end = (dtstart + duration).isoformat()
        return start, end, all_day

    def fetch_calendar(self, calendar_url):
        # workaround for webcal urls
        if calendar_url.startswith("webcal://"):
            calendar_url = calendar_url.replace("webcal://", "https://")
        try:
            response = requests.get(calendar_url, timeout=30)
            response.raise_for_status()
            return icalendar.Calendar.from_ical(response.text)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch iCalendar url: {str(e)}")

    def get_contrast_color(self, color):
        """
        Returns '#000000' (black) or '#ffffff' (white) depending on the contrast
        against the given color.
        """
        r, g, b = ImageColor.getrgb(color)
        # YIQ formula to estimate brightness
        yiq = (r * 299 + g * 587 + b * 114) / 1000

        return '#000000' if yiq >= 150 else '#ffffff'
