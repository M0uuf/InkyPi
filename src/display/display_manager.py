import gc
import logging
import re
import threading
import time

from utils.image_loader import _is_low_resource_device
from utils.image_utils import (
    resize_image,
    change_orientation,
    apply_image_enhancement,
    get_resize_filter,
    get_resize_filter_name,
    is_default_image_enhancement,
    normalize_image_mode_for_enhancement
)
from display.mock_display import MockDisplay

logger = logging.getLogger(__name__)
WAVESHARE_DISPLAY_TYPE_PATTERN = re.compile(r"^epd\d+(?:in\d+)?[A-Za-z0-9_]*$")
DEFAULT_HIGH_QUALITY_RESIZE_FILTER = "lanczos"
DEFAULT_LOW_RESOURCE_RESIZE_FILTER = "bicubic"

try:
    from display.waveshare_display import WaveshareDisplay
except ImportError:
    WaveshareDisplay = None
    logger.info("Waveshare display not available, hardware support disabled")

class DisplayManager:

    """Manages the display and rendering of images."""

    def __init__(self, device_config):

        """
        Initializes the display manager and selects the correct display type 
        based on the configuration.

        Args:
            device_config (object): Configuration object containing display settings.

        Raises:
            ValueError: If an unsupported display type is specified.
        """
        
        self.device_config = device_config
        self.display_lock = threading.Lock()
     
        display_type = device_config.get_config("display_type")

        if display_type == "mock":
            self.display = MockDisplay(device_config)
        elif isinstance(display_type, str) and WAVESHARE_DISPLAY_TYPE_PATTERN.fullmatch(display_type):
            if WaveshareDisplay is None:
                raise ValueError("Waveshare display support is not available.")
            self.display = WaveshareDisplay(device_config)
        else:
            raise ValueError(
                f"Unsupported display type: {display_type}. "
                "Only Waveshare EPD display types and 'mock' are supported."
            )

    def _get_bool_config(self, key, default=None):
        value = self.device_config.get_config(key, default)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized_value = value.strip().lower()
            if normalized_value in {"1", "true", "yes", "on"}:
                return True
            if normalized_value in {"0", "false", "no", "off"}:
                return False
            logger.warning("Invalid boolean config value for %s: %r. Using %s.", key, value, default)
            return default
        return bool(value)

    def _is_low_resource_mode(self):
        configured_value = self._get_bool_config("display_low_resource_mode")
        if configured_value is not None:
            return configured_value

        configured_value = self._get_bool_config("low_resource_mode")
        if configured_value is not None:
            return configured_value

        return _is_low_resource_device()

    def _get_display_resize_filter(self):
        configured_filter = self.device_config.get_config("display_resize_filter")
        if configured_filter:
            return get_resize_filter(configured_filter, default=DEFAULT_LOW_RESOURCE_RESIZE_FILTER)

        if self._is_low_resource_mode():
            return get_resize_filter(DEFAULT_LOW_RESOURCE_RESIZE_FILTER)

        return get_resize_filter(DEFAULT_HIGH_QUALITY_RESIZE_FILTER)

    def _close_pipeline_image(self, image, owned_image_ids, low_resource_mode):
        if not low_resource_mode or id(image) not in owned_image_ids:
            return

        try:
            image.close()
        except Exception as exc:
            logger.debug("Failed to close intermediate display image: %s", exc)

    def _replace_pipeline_image(self, current_image, next_image, owned_image_ids, low_resource_mode):
        if next_image is current_image:
            return next_image

        self._close_pipeline_image(current_image, owned_image_ids, low_resource_mode)
        owned_image_ids.add(id(next_image))
        return next_image

    def close(self):
        """Release concrete display resources when the application shuts down."""
        display = getattr(self, "display", None)
        if display is None:
            logger.info("Display cleanup skipped; no concrete display is initialized.")
            return

        cleanup_method = getattr(display, "close", None) or getattr(display, "cleanup", None)
        if not callable(cleanup_method):
            logger.info("Display cleanup skipped; %s has no cleanup hook.", display.__class__.__name__)
            return

        with self.display_lock:
            try:
                logger.info("Running display cleanup for %s.", display.__class__.__name__)
                cleanup_method()
            except Exception:
                logger.exception("Exception during display cleanup")

    def display_image(self, image, image_settings=[]):
        
        """
        Delegates image rendering to the appropriate display instance.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify image rendering.

        Raises:
            ValueError: If no valid display instance is found.
        """

        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")
        
        pipeline_started = time.monotonic()
        low_resource_mode = self._is_low_resource_mode()
        owned_image_ids = set()

        try:
            save_started = time.monotonic()
            logger.info(f"Saving image to {self.device_config.current_image_file}")
            image.save(self.device_config.current_image_file)
            logger.info("Display pipeline save current image completed in %.2fs", time.monotonic() - save_started)

            orientation_started = time.monotonic()
            image = self._replace_pipeline_image(
                image,
                change_orientation(image, self.device_config.get_config("orientation")),
                owned_image_ids,
                low_resource_mode
            )
            logger.info("Display pipeline orientation transform completed in %.2fs", time.monotonic() - orientation_started)

            target_resolution = self.device_config.get_resolution()
            resize_started = time.monotonic()
            resize_filter = self._get_display_resize_filter()
            resize_filter_name = get_resize_filter_name(resize_filter)
            if tuple(image.size) == tuple(int(value) for value in target_resolution):
                logger.info(
                    "Display pipeline resize skipped; image already matches target %sx%s",
                    int(target_resolution[0]),
                    int(target_resolution[1])
                )
            else:
                logger.info("Display pipeline resize using %s filter", resize_filter_name)
                image = self._replace_pipeline_image(
                    image,
                    resize_image(image, target_resolution, image_settings, resize_filter),
                    owned_image_ids,
                    low_resource_mode
                )
            logger.info("Display pipeline resize phase completed in %.2fs", time.monotonic() - resize_started)

            if self.device_config.get_config("inverted_image"):
                inversion_started = time.monotonic()
                image = self._replace_pipeline_image(
                    image,
                    image.rotate(180),
                    owned_image_ids,
                    low_resource_mode
                )
                logger.info("Display pipeline inversion completed in %.2fs", time.monotonic() - inversion_started)
            else:
                logger.info("Display pipeline inversion skipped")

            enhancement_settings = self.device_config.get_config("image_settings", {})
            enhancement_started = time.monotonic()
            if is_default_image_enhancement(enhancement_settings):
                image = self._replace_pipeline_image(
                    image,
                    normalize_image_mode_for_enhancement(image),
                    owned_image_ids,
                    low_resource_mode
                )
                logger.info("Display pipeline enhancement skipped; settings are defaults")
            else:
                image = self._replace_pipeline_image(
                    image,
                    apply_image_enhancement(image, enhancement_settings),
                    owned_image_ids,
                    low_resource_mode
                )
            logger.info("Display pipeline enhancement phase completed in %.2fs", time.monotonic() - enhancement_started)

            # Pass to the concrete instance to render to the device.
            display_started = time.monotonic()
            with self.display_lock:
                self.display.display_image(image, image_settings)
            logger.info("Display pipeline concrete display completed in %.2fs", time.monotonic() - display_started)
            logger.info("Display pipeline total completed in %.2fs", time.monotonic() - pipeline_started)
        finally:
            if low_resource_mode:
                gc.collect()
