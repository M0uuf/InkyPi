import requests
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from io import BytesIO
import os
import logging
import hashlib
import tempfile
import subprocess
import shutil
import time
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from utils.performance import PerformanceDiagnostics

logger = logging.getLogger(__name__)

HTML_RENDER_CACHE_VERSION = "v1"
HTML_RENDER_CACHE_DIR_ENV = "INKYPI_HTML_RENDER_CACHE_DIR"
HTML_RENDER_CACHE_MAX_ENTRIES = 32
DEFAULT_IMAGE_ENHANCEMENT_SETTINGS = {
    "brightness": 1.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "sharpness": 1.0
}
RESIZE_FILTERS = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS
}


class _HtmlRenderCacheLockEntry:
    def __init__(self):
        self.lock = threading.Lock()
        self.active_count = 0


_html_render_cache_locks = OrderedDict()
_html_render_cache_locks_guard = threading.Lock()

def get_image(image_url):
    response = requests.get(image_url, timeout=30)
    img = None
    if 200 <= response.status_code < 300 or response.status_code == 304:
        img = Image.open(BytesIO(response.content))
    else:
        logger.error(f"Received non-200 response from {image_url}: status_code: {response.status_code}")
    return img

def change_orientation(image, orientation, inverted=False):
    if orientation == 'horizontal':
        angle = 0
    elif orientation == 'vertical':
        angle = 90

    if inverted:
        angle = (angle + 180) % 360

    if angle == 0:
        logger.info("Skipping orientation transform; image is already horizontal")
        return image

    return image.rotate(angle, expand=1)

def get_resize_filter(filter_name, default="lanczos"):
    """Return a PIL resampling filter by config name."""
    if not isinstance(filter_name, str):
        filter_name = default
    normalized_filter = filter_name.strip().lower()
    selected_filter = RESIZE_FILTERS.get(normalized_filter)
    if selected_filter is not None:
        return selected_filter

    logger.warning("Unsupported resize filter %r. Using %s.", filter_name, default)
    return RESIZE_FILTERS[default]


def get_resize_filter_name(resample_filter):
    """Return a stable config/log name for a PIL resampling filter."""
    for filter_name, filter_value in RESIZE_FILTERS.items():
        if filter_value == resample_filter:
            return filter_name
    return str(resample_filter)


def is_default_image_enhancement(image_settings):
    """Return True when enhancement settings would leave the image unchanged."""
    if not isinstance(image_settings, dict):
        return True

    for setting_name, default_value in DEFAULT_IMAGE_ENHANCEMENT_SETTINGS.items():
        try:
            setting_value = float(image_settings.get(setting_name, default_value))
        except (TypeError, ValueError):
            return False
        if setting_value != default_value:
            return False
    return True


def normalize_image_mode_for_enhancement(img):
    """Convert image modes that ImageEnhance/display drivers do not handle consistently."""
    if img.mode not in ('RGB', 'L'):
        return img.convert('RGB')
    return img


def resize_image(image, desired_size, image_settings=[], resample_filter=Image.Resampling.LANCZOS):
    img_width, img_height = image.size
    desired_width, desired_height = desired_size
    desired_width, desired_height = int(desired_width), int(desired_height)

    if (img_width, img_height) == (desired_width, desired_height):
        logger.info("Skipping resize; image already matches target size %sx%s", desired_width, desired_height)
        return image

    img_ratio = img_width / img_height
    desired_ratio = desired_width / desired_height

    keep_width = "keep-width" in image_settings

    x_offset, y_offset = 0,0
    new_width, new_height = img_width,img_height
    # Step 1: Determine crop dimensions
    desired_ratio = desired_width / desired_height
    if img_ratio > desired_ratio:
        # Image is wider than desired aspect ratio
        new_width = int(img_height * desired_ratio)
        if not keep_width:
            x_offset = (img_width - new_width) // 2
    else:
        # Image is taller than desired aspect ratio
        new_height = int(img_width / desired_ratio)
        if not keep_width:
            y_offset = (img_height - new_height) // 2

    # Step 2: Crop the image
    image = image.crop((x_offset, y_offset, x_offset + new_width, y_offset + new_height))

    # Step 3: Resize to the exact desired dimensions (if necessary)
    return image.resize((desired_width, desired_height), resample_filter)

def apply_image_enhancement(img, image_settings={}):
    img = normalize_image_mode_for_enhancement(img)

    if is_default_image_enhancement(image_settings):
        logger.info("Skipping image enhancement; settings are defaults")
        return img

    # Apply Brightness
    img = ImageEnhance.Brightness(img).enhance(image_settings.get("brightness", 1.0))

    # Apply Contrast
    img = ImageEnhance.Contrast(img).enhance(image_settings.get("contrast", 1.0))

    # Apply Saturation (Color)
    img = ImageEnhance.Color(img).enhance(image_settings.get("saturation", 1.0))

    # Apply Sharpness
    img = ImageEnhance.Sharpness(img).enhance(image_settings.get("sharpness", 1.0))

    return img

def compute_image_hash(image):
    """Compute SHA-256 hash of an image."""
    image = image.convert("RGB")
    img_bytes = image.tobytes()
    return hashlib.sha256(img_bytes).hexdigest()

def _get_html_render_cache_dir():
    cache_dir = os.getenv(HTML_RENDER_CACHE_DIR_ENV)
    if not cache_dir:
        cache_dir = os.path.join(tempfile.gettempdir(), "inkypi-html-render-cache")
    return Path(cache_dir)


def _is_default_html_render_cache_dir(cache_dir):
    return cache_dir == Path(tempfile.gettempdir(), "inkypi-html-render-cache")


def _ensure_html_render_cache_dir(cache_dir):
    if cache_dir.exists() and not cache_dir.is_dir():
        raise RuntimeError(f"HTML render cache path is not a directory: {cache_dir}")

    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _is_default_html_render_cache_dir(cache_dir):
        os.chmod(cache_dir, 0o700)


def _get_html_render_cache_key(html_str, dimensions, timeout_ms=None, cache_extra=None):
    digest = hashlib.sha256()
    digest.update(HTML_RENDER_CACHE_VERSION.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(dimensions[0]).encode("utf-8"))
    digest.update(b"x")
    digest.update(str(dimensions[1]).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(timeout_ms or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(cache_extra or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(html_str.encode("utf-8"))
    return digest.hexdigest()


def _get_html_render_cache_path(html_str, dimensions, timeout_ms=None, cache_extra=None):
    cache_key = _get_html_render_cache_key(html_str, dimensions, timeout_ms, cache_extra)
    return _get_html_render_cache_dir() / f"{cache_key}.png"


def _get_html_render_cache_lock(cache_key):
    with _html_render_cache_locks_guard:
        entry = _html_render_cache_locks.get(cache_key)
        if entry is None:
            entry = _HtmlRenderCacheLockEntry()
            _html_render_cache_locks[cache_key] = entry
        else:
            _html_render_cache_locks.move_to_end(cache_key)
        _prune_html_render_cache_locks(excluded_cache_keys={cache_key})
        return entry.lock


def _prune_html_render_cache_locks(excluded_cache_keys=frozenset()):
    """Evict inactive render-cache locks. Caller must hold the registry guard."""
    for cache_key in list(_html_render_cache_locks.keys()):
        if len(_html_render_cache_locks) <= HTML_RENDER_CACHE_MAX_ENTRIES:
            break
        if cache_key in excluded_cache_keys:
            continue
        entry = _html_render_cache_locks[cache_key]
        if entry.active_count == 0 and not entry.lock.locked():
            del _html_render_cache_locks[cache_key]


def _discard_html_render_cache_lock(cache_key):
    with _html_render_cache_locks_guard:
        entry = _html_render_cache_locks.get(cache_key)
        if entry is not None and entry.active_count == 0 and not entry.lock.locked():
            del _html_render_cache_locks[cache_key]


@contextmanager
def _html_render_cache_lock(cache_key):
    with _html_render_cache_locks_guard:
        entry = _html_render_cache_locks.get(cache_key)
        if entry is None:
            entry = _HtmlRenderCacheLockEntry()
            _html_render_cache_locks[cache_key] = entry
        else:
            _html_render_cache_locks.move_to_end(cache_key)
        entry.active_count += 1
        _prune_html_render_cache_locks(excluded_cache_keys={cache_key})

    try:
        with entry.lock:
            yield
    finally:
        with _html_render_cache_locks_guard:
            entry.active_count -= 1
            if _html_render_cache_locks.get(cache_key) is entry:
                _html_render_cache_locks.move_to_end(cache_key)
            _prune_html_render_cache_locks()


def _load_cached_html_render(cache_path):
    if not cache_path.exists():
        return None

    try:
        with Image.open(cache_path) as img:
            image = img.copy()
        os.utime(cache_path, None)
        logger.info("HTML screenshot cache hit. | cache_file: %s", cache_path)
        return image
    except Exception as e:
        logger.warning("Failed to load cached HTML screenshot %s: %s", cache_path, e)
        try:
            cache_path.unlink()
        except OSError:
            pass
        return None


def _prune_html_render_cache(cache_dir):
    cache_files = []
    for cache_file in cache_dir.glob("*.png"):
        try:
            cache_files.append((cache_file.stat().st_mtime, cache_file))
        except OSError as e:
            logger.debug("Skipping HTML screenshot cache file during prune: %s | error: %s", cache_file, e)

    cache_files.sort(key=lambda entry: entry[0], reverse=True)
    for _, cache_file in cache_files[HTML_RENDER_CACHE_MAX_ENTRIES:]:
        try:
            cache_file.unlink()
            _discard_html_render_cache_lock(cache_file.stem)
            logger.debug("Deleted stale HTML screenshot cache file: %s", cache_file)
        except OSError as e:
            logger.warning("Failed to delete stale HTML screenshot cache file %s: %s", cache_file, e)


def _store_cached_html_render(cache_path, image):
    try:
        _ensure_html_render_cache_dir(cache_path.parent)
        with tempfile.NamedTemporaryFile(suffix=".png", dir=cache_path.parent, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        image.save(temp_path)
        os.replace(temp_path, cache_path)
        _prune_html_render_cache(cache_path.parent)
        logger.info("Stored HTML screenshot cache entry. | cache_file: %s", cache_path)
    except Exception as e:
        logger.warning("Failed to store HTML screenshot cache entry %s: %s", cache_path, e)
        try:
            if "temp_path" in locals() and temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def take_screenshot_html(html_str, dimensions, timeout_ms=None, cache_extra=None, diagnostics_enabled=False):
    cache_key = _get_html_render_cache_key(html_str, dimensions, timeout_ms, cache_extra)
    cache_path = _get_html_render_cache_dir() / f"{cache_key}.png"

    with _html_render_cache_lock(cache_key):
        return _take_screenshot_html_uncached(
            html_str,
            dimensions,
            timeout_ms,
            cache_path,
            diagnostics_enabled=diagnostics_enabled
        )


def _take_screenshot_html_uncached(html_str, dimensions, timeout_ms, cache_path, diagnostics_enabled=False):
    image = None
    html_file_path = None
    diagnostics = PerformanceDiagnostics(
        enabled=diagnostics_enabled,
        logger=logger,
        prefix="HTML screenshot diagnostics"
    )
    with diagnostics.phase("cache lookup"):
        cached_image = _load_cached_html_render(cache_path)
    if cached_image is not None:
        diagnostics.log_summary("cache=hit | dimensions=%sx%s" % (dimensions[0], dimensions[1]))
        return cached_image

    logger.info(
        "HTML screenshot cache miss. Capturing with Chromium. | dimensions: %sx%s | html_size: %d bytes",
        dimensions[0],
        dimensions[1],
        len(html_str.encode("utf-8"))
    )
    capture_started = time.monotonic()
    try:
        # Create a temporary HTML file
        with diagnostics.phase("temporary html write"):
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
                html_file.write(html_str.encode("utf-8"))
                html_file_path = html_file.name

        with diagnostics.phase("chromium screenshot"):
            if diagnostics_enabled:
                image = take_screenshot(
                    html_file_path,
                    dimensions,
                    timeout_ms,
                    diagnostics_enabled=True
                )
            else:
                image = take_screenshot(html_file_path, dimensions, timeout_ms)
        if image is not None:
            _store_cached_html_render(cache_path, image)

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
    finally:
        if html_file_path and os.path.exists(html_file_path):
            os.remove(html_file_path)
        logger.info(
            "HTML screenshot capture path completed in %.2fs | cache_file: %s | success: %s",
            time.monotonic() - capture_started,
            cache_path,
            image is not None
        )
        diagnostics.log_summary(
            "cache=miss | dimensions=%sx%s | success=%s" % (dimensions[0], dimensions[1], image is not None)
        )

    return image

def _find_chromium_binary():
    """Find the first available Chromium-based binary in system PATH."""
    candidates = ["chromium-headless-shell", "chromium", "chrome"]
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            logger.debug(f"Found browser binary: {candidate} at {path}")
            return candidate
    return None


def take_screenshot(target, dimensions, timeout_ms=None, diagnostics_enabled=False):
    image = None
    img_file_path = None
    chromium_timeout_seconds = ((timeout_ms or 30000) / 1000) + 10
    diagnostics = PerformanceDiagnostics(
        enabled=diagnostics_enabled,
        logger=logger,
        prefix="Chromium screenshot diagnostics"
    )
    try:
        # Find available browser binary
        browser = _find_chromium_binary()
        if not browser:
            logger.error("No Chromium-based browser found. Install chromium, chromium-headless-shell, or chrome.")
            return None

        # Create a temporary output file for the screenshot
        with diagnostics.phase("temporary png allocation"):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
                img_file_path = img_file.name

        command = [
            browser,
            target,
            "--headless",
            f"--screenshot={img_file_path}",
            f"--window-size={dimensions[0]},{dimensions[1]}",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--use-gl=swiftshader",
            "--hide-scrollbars",
            "--in-process-gpu",
            "--js-flags=--jitless",
            "--disable-zero-copy",
            "--disable-gpu-memory-buffer-compositor-resources",
            "--disable-extensions",
            "--disable-plugins",
            "--mute-audio",
            "--renderer-process-limit=1",
            "--no-zygote",
            "--no-sandbox"
        ]
        if timeout_ms:
            command.append(f"--timeout={timeout_ms}")
        logger.info(
            "Starting Chromium screenshot capture. | browser: %s | dimensions: %sx%s | target: %s",
            browser,
            dimensions[0],
            dimensions[1],
            target
        )
        chromium_started = time.monotonic()
        with diagnostics.phase("chromium process"):
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=chromium_timeout_seconds,
                check=False
            )
        chromium_elapsed = time.monotonic() - chromium_started
        logger.info(
            "Chromium screenshot process completed in %.2fs | return_code: %s",
            chromium_elapsed,
            result.returncode
        )

        # Check if the process failed or the output file is missing
        if result.returncode != 0 or not os.path.exists(img_file_path):
            logger.error(f"Failed to take screenshot (return code: {result.returncode})")
            if result.stderr:
                logger.error("Chromium stderr: %s", result.stderr.decode("utf-8", errors="replace").strip())
            return None

        # Load the image using PIL
        with diagnostics.phase("png load"):
            with Image.open(img_file_path) as img:
                image = img.copy()

    except subprocess.TimeoutExpired:
        logger.error("Chromium screenshot timed out after %.1fs", chromium_timeout_seconds)
    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
    finally:
        if img_file_path and os.path.exists(img_file_path):
            os.remove(img_file_path)
        diagnostics.log_summary("dimensions=%sx%s | success=%s" % (dimensions[0], dimensions[1], image is not None))

    return image

def pad_image_blur(img: Image, dimensions: tuple[int, int]) -> Image:
    bkg = ImageOps.fit(img, dimensions)
    bkg = bkg.filter(ImageFilter.BoxBlur(8))
    img = ImageOps.contain(img, dimensions)

    img_size = img.size
    bkg.paste(img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2))
    return bkg
