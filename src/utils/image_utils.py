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
from pathlib import Path

logger = logging.getLogger(__name__)

HTML_RENDER_CACHE_VERSION = "v1"
HTML_RENDER_CACHE_DIR_ENV = "INKYPI_HTML_RENDER_CACHE_DIR"
HTML_RENDER_CACHE_MAX_ENTRIES = 32
_html_render_cache_locks = {}
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

    return image.rotate(angle, expand=1)

def resize_image(image, desired_size, image_settings=[]):
    img_width, img_height = image.size
    desired_width, desired_height = desired_size
    desired_width, desired_height = int(desired_width), int(desired_height)

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
    return image.resize((desired_width, desired_height), Image.LANCZOS)

def apply_image_enhancement(img, image_settings={}):
    # Convert image to RGB mode if necessary for enhancement operations
    # ImageEnhance requires RGB mode for operations like blend
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
        

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
        return _html_render_cache_locks.setdefault(cache_key, threading.Lock())


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


def take_screenshot_html(html_str, dimensions, timeout_ms=None, cache_extra=None):
    cache_key = _get_html_render_cache_key(html_str, dimensions, timeout_ms, cache_extra)
    cache_path = _get_html_render_cache_dir() / f"{cache_key}.png"
    cache_lock = _get_html_render_cache_lock(cache_key)

    with cache_lock:
        return _take_screenshot_html_uncached(html_str, dimensions, timeout_ms, cache_path)


def _take_screenshot_html_uncached(html_str, dimensions, timeout_ms, cache_path):
    image = None
    html_file_path = None
    cached_image = _load_cached_html_render(cache_path)
    if cached_image is not None:
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
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
            html_file.write(html_str.encode("utf-8"))
            html_file_path = html_file.name

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


def take_screenshot(target, dimensions, timeout_ms=None):
    image = None
    img_file_path = None
    try:
        # Find available browser binary
        browser = _find_chromium_binary()
        if not browser:
            logger.error("No Chromium-based browser found. Install chromium, chromium-headless-shell, or chrome.")
            return None

        # Create a temporary output file for the screenshot
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
        result = subprocess.run(command, capture_output=True, check=False)
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
        with Image.open(img_file_path) as img:
            image = img.copy()

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
    finally:
        if img_file_path and os.path.exists(img_file_path):
            os.remove(img_file_path)

    return image

def pad_image_blur(img: Image, dimensions: tuple[int, int]) -> Image:
    bkg = ImageOps.fit(img, dimensions)
    bkg = bkg.filter(ImageFilter.BoxBlur(8))
    img = ImageOps.contain(img, dimensions)

    img_size = img.size
    bkg.paste(img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2))
    return bkg
