from src.plugins.plugin_registry import load_plugins, get_plugin_instance
from src.utils.image_utils import resize_image, change_orientation
from unittest.mock import patch, MagicMock
from PIL import Image
import json
import os
import icalendar

RESOLUTIONS = [
    [640, 400], # Waveshare 4.0" e-Paper
    [800, 480], # Waveshare 7.3" e-Paper
    [880, 528], # Waveshare 7.5" e-Paper
    [1600, 1200], # Waveshare 13.3" e-Paper
]
ORIENTATIONS = ["horizontal", "vertical"]

plugin_id = "calendar"
plugin_settings = {
    "calendarURLs[]": ["https://example.com/calendar.ics"],
    "calendarColors[]": ["#4285f4"],
    "viewMode": "timeGridDay"
}

mock_device_config = MagicMock()
plugin_info_file = os.path.join("src", "plugins", plugin_id, "plugin-info.json")
with open(plugin_info_file) as f:
    plugin_config = json.load(f)

load_plugins([plugin_config])
plugin_instance = get_plugin_instance(plugin_config)

total_height = sum([max(resolution) for resolution in RESOLUTIONS])
total_width = max([max(resolution) for resolution in RESOLUTIONS]) * 2

composite = Image.new('RGB', (total_width, total_height), color='gray')
y = 0
for resolution in RESOLUTIONS:
    x = 0
    width, height = resolution
    for orientation in ORIENTATIONS:
        mock_device_config.get_resolution.return_value = resolution
        mock_device_config.get_config.side_effect = lambda key, default=None: {
            "orientation": orientation,
            "timezone": "UTC",
            "time_format": "24h"
        }.get(key, default)

        with patch.object(plugin_instance, "fetch_calendar") as mock_fetch_calendar:
            mock_fetch_calendar.return_value = icalendar.Calendar()
            img = plugin_instance.generate_image(plugin_settings, mock_device_config)

        # post processing thats applied before being displayed
        img = change_orientation(img, orientation)
        img = resize_image(img, resolution, plugin_config.get('image_settings', []))
        # rotate the image again when pasting
        if orientation == "vertical":
            img = img.rotate(-90, expand=1)
        composite.paste(img, (x, y))
        x= int(total_width/2)
    y+= max(width, height)

composite.show()
