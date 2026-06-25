import inspect
import importlib
import logging
import sys
import time

from display.abstract_display import AbstractDisplay
from PIL import Image
from pathlib import Path
from plugins.plugin_registry import get_plugin_instance

logger = logging.getLogger(__name__)
WAVESHARE_CLEANUP_HOOKS = ("module_exit", "Dev_exit", "cleanup", "close")
WAVESHARE_CLEANUP_FLAG_HOOKS = {"module_exit", "Dev_exit"}


def get_bool_config(device_config, key, default):
    """Read a boolean config value, accepting common string forms."""
    value = device_config.get_config(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
        logger.warning(
            "Invalid boolean config value for %s: %r. Using default %s.",
            key,
            value,
            default
        )
        return default
    return bool(value)


def split_image_for_bi_color_epd(image):
    """
    Convert image into two 1-bit layers for bi-color (black and red) e-paper displays.
    """
    black = (0, 0, 0)
    white = (255, 255, 255)
    red = (255, 0, 0)

    palette_data = [*black, *white, *red]
    palette_img = Image.new('P', (1, 1))
    indexed_img = None
    try:
        palette_img.putpalette(palette_data)
        indexed_img = image.quantize(palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG)
        black_layer = indexed_img.point(lambda p: 0 if p == 0 else 1, mode='1')
        red_layer = indexed_img.point(lambda p: 0 if p == 2 else 1, mode='1')
        return black_layer, red_layer
    finally:
        if indexed_img is not None:
            indexed_img.close()
        palette_img.close()


class WaveshareDisplay(AbstractDisplay):
    """
    Handles Waveshare e-paper display dynamically based on device type.

    This class loads the appropriate display driver dynamically based on the 
    `display_type` specified in the device configuration, allowing support for 
    multiple Waveshare EPD models.  

    The module drivers are in display.waveshare_epd.
    """

    def initialize_display(self):
        
        """
        Initializes the Waveshare display device.

        Retrieves the display type from the device configuration and dynamically 
        loads the corresponding Waveshare EPD driver from display.waveshare_epd.

        Raises:
            ValueError: If `display_type` is missing or the specified module is 
                        not found.
        """
        
        logger.info("Initializing Waveshare display")

        # get the device type which should be the model number of the device.
        display_type = self.device_config.get_config("display_type")  
        logger.info(f"Loading EPD display for {display_type} display")

        if not display_type:
            raise ValueError("Waveshare driver but 'display_type' not specified in configuration.")

        # Construct module path dynamically - e.g. "display.waveshare_epd.epd7in3e"
        module_name = f"display.waveshare_epd.{display_type}" 

        # Workaround for some Waveshare drivers using 'import epdconfig' causing import errors
        epd_dir = Path(__file__).parent / "waveshare_epd"
        if str(epd_dir) not in sys.path:
            sys.path.insert(0, str(epd_dir))

        try:
            # Dynamically load module
            epd_module = importlib.import_module(module_name)
            self.epd_module = epd_module
            self.epd_display = epd_module.EPD()
            # Workaround for init functions with inconsistent casing
            self.epd_display_init = getattr(self.epd_display, "Init", getattr(self.epd_display, "init", None))

            if not callable(self.epd_display_init):
                raise AttributeError("No Init/init method found")

            self.epd_display_init()

            display_args_spec = inspect.getfullargspec(self.epd_display.display)
        except ModuleNotFoundError:
            raise ValueError(f"Unsupported Waveshare display type: {display_type}")
        except AttributeError:
            raise ValueError(f"Display does not support required methods: {display_type}")

        self.bi_color_display = len(display_args_spec.args) > 2

        # update the resolution directly from the loaded device context
        if not self.device_config.get_config("resolution"):
            w, h = int(self.epd_display.width), int(self.epd_display.height)
            resolution = [w, h] if w >= h else [h, w]
            self.device_config.update_value(
                "resolution",
                resolution,
                write=True)

    def _cleanup_hook_accepts_flag(self, hook):
        try:
            signature = inspect.signature(hook)
        except (TypeError, ValueError):
            return False

        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                return True
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY
            ):
                return True
        return False

    def _run_cleanup_hook(self, owner_name, hook_name, hook):
        args = (True,) if hook_name in WAVESHARE_CLEANUP_FLAG_HOOKS and self._cleanup_hook_accepts_flag(hook) else ()
        try:
            hook(*args)
            suffix = "(cleanup=True)" if args else ""
            logger.info("Waveshare cleanup hook %s.%s%s completed.", owner_name, hook_name, suffix)
            return True
        except Exception:
            logger.exception("Exception during Waveshare cleanup hook %s.%s", owner_name, hook_name)

        return False

    def _cleanup_owner(self, owner, owner_name):
        attempted = False
        for hook_name in WAVESHARE_CLEANUP_HOOKS:
            hook = getattr(owner, hook_name, None)
            if not callable(hook):
                continue
            attempted = True
            if self._run_cleanup_hook(owner_name, hook_name, hook):
                break
        return attempted

    def close(self):
        """Best-effort release of Waveshare display driver resources."""
        logger.info("Running Waveshare display cleanup.")

        epd_display = getattr(self, "epd_display", None)
        if epd_display is not None and callable(getattr(epd_display, "sleep", None)):
            try:
                epd_display.sleep()
                logger.info("Waveshare display sleep completed during cleanup.")
            except Exception:
                logger.exception("Exception while putting Waveshare display to sleep during cleanup")

        attempted_cleanup = False
        epd_module = getattr(self, "epd_module", None)
        if epd_module is not None:
            attempted_cleanup = self._cleanup_owner(epd_module, "epd_module") or attempted_cleanup
            epdconfig = getattr(epd_module, "epdconfig", None)
            if epdconfig is not None:
                attempted_cleanup = self._cleanup_owner(epdconfig, "epdconfig") or attempted_cleanup

        if epd_display is not None:
            attempted_cleanup = self._cleanup_owner(epd_display, "epd_display") or attempted_cleanup

        if not attempted_cleanup:
            logger.info("No Waveshare driver cleanup hook found.")

    def display_image(self, image, image_settings=[]):
        
        """
        Displays an image on the Waveshare display.

        The image has been processed by adjusting orientation, resizing, and converting it
        into the buffer format required for e-paper rendering.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): Additional settings to modify image rendering.

        Raises:
            ValueError: If no image is provided.
        """

        logger.info("Displaying image to Waveshare display.")
        if not image:
            raise ValueError(f"No image provided.")

        reinitialize_before_display = get_bool_config(
            self.device_config,
            "waveshare_reinitialize_before_display",
            True
        )
        clear_before_display = get_bool_config(
            self.device_config,
            "waveshare_clear_before_display",
            True
        )
        sleep_after_display = get_bool_config(
            self.device_config,
            "waveshare_sleep_after_display",
            True
        )

        if sleep_after_display and not reinitialize_before_display:
            logger.warning(
                "waveshare_reinitialize_before_display=false is unsafe while "
                "waveshare_sleep_after_display=true; forcing reinitialize before display."
            )
            reinitialize_before_display = True

        if reinitialize_before_display:
            init_started = time.monotonic()
            # Assume device was in sleep mode.
            self.epd_display_init()
            logger.info("Waveshare init completed in %.2fs", time.monotonic() - init_started)
        else:
            logger.info("Skipping Waveshare init before display.")

        if clear_before_display:
            clear_started = time.monotonic()
            # Clear residual pixels before updating the image.
            self.epd_display.Clear()
            logger.info("Waveshare clear completed in %.2fs", time.monotonic() - clear_started)
        else:
            logger.info("Skipping Waveshare clear before display.")

        black_layer = None
        red_layer = None
        display_buffers = None
        try:
            buffer_started = time.monotonic()
            if not self.bi_color_display:
                display_buffers = (self.epd_display.getbuffer(image),)
            else:
                black_layer, red_layer = split_image_for_bi_color_epd(image)
                display_buffers = (
                    self.epd_display.getbuffer(black_layer),
                    self.epd_display.getbuffer(red_layer),
                )
            logger.info("Waveshare buffer conversion completed in %.2fs", time.monotonic() - buffer_started)

            display_started = time.monotonic()
            self.epd_display.display(*display_buffers)
            logger.info("Waveshare display update completed in %.2fs", time.monotonic() - display_started)
        finally:
            display_buffers = None
            for layer in (black_layer, red_layer):
                if layer is not None:
                    layer.close()

        if sleep_after_display:
            sleep_started = time.monotonic()
            # Put device into low power mode (EPD displays maintain image when powered off)
            logger.info("Putting Waveshare display into sleep mode for power saving.")
            self.epd_display.sleep()
            logger.info("Waveshare sleep completed in %.2fs", time.monotonic() - sleep_started)
        else:
            logger.info("Skipping Waveshare sleep after display.")
