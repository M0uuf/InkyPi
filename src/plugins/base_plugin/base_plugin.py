import logging
import os
import time
import hashlib
from utils.app_utils import resolve_path, get_fonts
from utils.image_utils import take_screenshot_html
from utils.image_loader import AdaptiveImageLoader
from utils.performance import PerformanceDiagnostics
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
import asyncio
import base64

logger = logging.getLogger(__name__)

STATIC_DIR = resolve_path("static")
PLUGINS_DIR = resolve_path("plugins")
BASE_PLUGIN_DIR =  os.path.join(PLUGINS_DIR, "base_plugin")
BASE_PLUGIN_RENDER_DIR = os.path.join(BASE_PLUGIN_DIR, "render")


def _fingerprint_local_files(file_paths):
    digest = hashlib.sha256()
    for file_path in sorted(str(path) for path in file_paths if path):
        digest.update(file_path.encode("utf-8"))
        digest.update(b"\0")
        try:
            path = Path(file_path)
            stat = path.stat()
            digest.update(str(stat.st_size).encode("utf-8"))
            digest.update(b":")
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        except OSError as e:
            logger.warning("Unable to fingerprint render resource %s: %s", file_path, e)
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest()

FRAME_STYLES = [
    {
        "name": "None",
        "icon": "frames/blank.png"
    },
    {
        "name": "Corner",
        "icon": "frames/corner.png"
    },
    {
        "name": "Top and Bottom",
        "icon": "frames/top_and_bottom.png"
    },
    {
        "name": "Rectangle",
        "icon": "frames/rectangle.png"
    }
]

class BasePlugin:
    """Base class for all plugins."""
    def __init__(self, config, **dependencies):
        self.config = config

        # Initialize adaptive image loader for device-aware image processing
        self.image_loader = AdaptiveImageLoader()

        self.render_dir = self.get_plugin_dir("render")
        if os.path.exists(self.render_dir):
            # instantiate jinja2 env with base plugin and current plugin render directories
            loader = FileSystemLoader([self.render_dir, BASE_PLUGIN_RENDER_DIR])
            self.env = Environment(
                loader=loader,
                autoescape=select_autoescape(['html', 'xml'])
            )

    def generate_image(self, settings, device_config):
        raise NotImplementedError("generate_image must be implemented by subclasses")

    def cleanup(self, settings):
        """Optional cleanup method that plugins can override to delete associated resources.

        Called when a plugin instance is deleted. Plugins should override this to clean up
        any files, external resources, or other data associated with the plugin instance.

        Args:
            settings: The plugin instance's settings dict, which may contain file paths or other resources
        """
        pass  # Default implementation does nothing

    def get_plugin_id(self):
        return self.config.get("id")

    def get_plugin_dir(self, path=None):
        plugin_dir = os.path.join(PLUGINS_DIR, self.get_plugin_id())
        if path:
            plugin_dir = os.path.join(plugin_dir, path)
        return plugin_dir

    def generate_settings_template(self):
        template_params = {"settings_template": "base_plugin/settings.html"}

        settings_path = self.get_plugin_dir("settings.html")
        if Path(settings_path).is_file():
            template_params["settings_template"] = f"{self.get_plugin_id()}/settings.html"

        template_params['frame_styles'] = FRAME_STYLES
        return template_params

    def render_image(self, dimensions, html_file, css_file=None, template_params=None, diagnostics_enabled=False):
        if template_params is None:
            template_params = {}
        diagnostics = PerformanceDiagnostics(
            enabled=diagnostics_enabled,
            logger=logger,
            prefix=f"HTML render diagnostics plugin={self.get_plugin_id()}"
        )

        # load the base plugin and current plugin css files
        css_files = [os.path.join(BASE_PLUGIN_RENDER_DIR, "plugin.css")]
        if css_file:
            plugin_css = os.path.join(self.render_dir, css_file)
            css_files.append(plugin_css)

        template_params["style_sheets"] = css_files
        template_params["width"] = dimensions[0]
        template_params["height"] = dimensions[1]
        font_faces = get_fonts()
        template_params["font_faces"] = font_faces
        template_params["static_dir"] = STATIC_DIR
        render_resource_fingerprint = _fingerprint_local_files(
            [*css_files, *(font.get("url") for font in font_faces)]
        )

        # load and render the given html template
        render_started = time.monotonic()
        with diagnostics.phase("jinja render"):
            template = self.env.get_template(html_file)
            rendered_html = template.render(template_params)
        render_elapsed = time.monotonic() - render_started
        logger.info(
            "Rendered HTML template for plugin '%s' in %.2fs | template: %s | size: %d bytes",
            self.get_plugin_id(),
            render_elapsed,
            html_file,
            len(rendered_html.encode("utf-8"))
        )

        screenshot_started = time.monotonic()
        with diagnostics.phase("html screenshot"):
            if diagnostics_enabled:
                image = take_screenshot_html(
                    rendered_html,
                    dimensions,
                    cache_extra=render_resource_fingerprint,
                    diagnostics_enabled=True
                )
            else:
                image = take_screenshot_html(
                    rendered_html,
                    dimensions,
                    cache_extra=render_resource_fingerprint
                )
        logger.info(
            "Rendered plugin '%s' HTML to image in %.2fs | dimensions: %sx%s",
            self.get_plugin_id(),
            time.monotonic() - screenshot_started,
            dimensions[0],
            dimensions[1]
        )
        diagnostics.log_summary("template=%s | dimensions=%sx%s" % (html_file, dimensions[0], dimensions[1]))
        return image
