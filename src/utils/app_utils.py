import logging
import os
import socket
import subprocess
import uuid

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_EXTENSIONS = {'pdf', 'png', 'avif', 'jpg', 'jpeg', 'gif', 'webp', 'heif', 'heic'}
MAX_UPLOAD_BYTES = int(os.getenv("INKYPI_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
SAVED_UPLOAD_DIR = os.path.join("static", "images", "saved")


class UploadValidationError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code

FONT_FAMILIES = {
    "Dogica": [{
        "font-weight": "normal",
        "file": "dogicapixel.ttf"
    },{
        "font-weight": "bold",
        "file": "dogicapixelbold.ttf"
    }],
    "Jost": [{
        "font-weight": "normal",
        "file": "Jost.ttf"
    },{
        "font-weight": "bold",
        "file": "Jost-SemiBold.ttf"
    }],
    "Napoli": [{
        "font-weight": "normal",
        "file": "Napoli.ttf"
    }],
    "DS-Digital": [{
        "font-weight": "normal",
        "file": os.path.join("DS-DIGI", "DS-DIGI.TTF")
    }]
}

FONTS = {
    "ds-gigi": "DS-DIGI.TTF",
    "napoli": "Napoli.ttf",
    "jost": "Jost.ttf",
    "jost-semibold": "Jost-SemiBold.ttf"
}

def resolve_path(file_path):
    src_dir = os.getenv("SRC_DIR")
    if src_dir is None:
        # Default to the src directory
        src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    src_path = Path(src_dir)
    return str(src_path / file_path)

def get_ip_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
    return ip_address

def get_wifi_name():
    try:
        output = subprocess.check_output(['iwgetid', '-r']).decode('utf-8').strip()
        return output
    except subprocess.CalledProcessError:
        return None

def is_connected():
    """Check if the Raspberry Pi has an internet connection."""
    try:
        # Try to connect to Google's public DNS server
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def get_font(font_name, font_size=50, font_weight="normal"):
    if font_name in FONT_FAMILIES:
        font_variants = FONT_FAMILIES[font_name]

        font_entry = next((entry for entry in font_variants if entry["font-weight"] == font_weight), None)
        if font_entry is None:
            font_entry = font_variants[0]  # Default to first available variant

        if font_entry:
            font_path = resolve_path(os.path.join("static", "fonts", font_entry["file"]))
            return ImageFont.truetype(font_path, font_size)
        else:
            logger.warning(f"Requested font weight not found: font_name={font_name}, font_weight={font_weight}")
    else:
        logger.warning(f"Requested font not found: font_name={font_name}")

    return None

def get_fonts():
    fonts_list = []
    for font_family, variants in FONT_FAMILIES.items():
        for variant in variants:
            fonts_list.append({
                "font_family": font_family,
                "url": resolve_path(os.path.join("static", "fonts", variant["file"])),
                "font_weight": variant.get("font-weight", "normal"),
                "font_style": variant.get("font-style", "normal"),
            })
    return fonts_list

def get_font_path(font_name):
    return resolve_path(os.path.join("static", "fonts", FONTS[font_name]))

def generate_startup_image(dimensions=(800,480)):
    bg_color = (255,255,255)
    text_color = (0,0,0)
    width, height = dimensions

    hostname = socket.gethostname()
    ip = get_ip_address()

    image = Image.new("RGBA", dimensions, bg_color)
    image_draw = ImageDraw.Draw(image)

    title_font_size = width * 0.145
    image_draw.text((width/2, height/2), "inkypi", anchor="mm", fill=text_color, font=get_font("Jost", title_font_size))

    text = f"To get started, visit http://{hostname}.local"
    text_font_size = width * 0.032

    # Draw the instructions
    y_text = height * 3 / 4
    image_draw.text((width/2, y_text), text, anchor="mm", fill=text_color, font=get_font("Jost", text_font_size))

    # Draw the IP on a line below
    ip_text = f"or http://{ip}"
    ip_text_font_size = width * 0.032
    bbox = image_draw.textbbox((0, 0), text, font=get_font("Jost", text_font_size))
    text_height = bbox[3] - bbox[1]
    ip_y = y_text + text_height * 1.35
    image_draw.text((width/2, ip_y), ip_text, anchor="mm", fill=text_color, font=get_font("Jost", ip_text_font_size))

    return image

def parse_form(request_form):
    request_dict = request_form.to_dict()
    for key in request_form.keys():
        if key.endswith('[]'):
            request_dict[key] = request_form.getlist(key)
    return request_dict


def get_saved_upload_dir():
    return resolve_path(SAVED_UPLOAD_DIR)


def _get_upload_extension(filename):
    extension = Path(filename or "").suffix.lower().lstrip(".")
    if not extension or extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise UploadValidationError(f"Unsupported file extension: {extension or 'none'}")
    return extension


def _get_upload_size(file):
    content_length = getattr(file, "content_length", None)
    if content_length:
        return int(content_length)

    stream = getattr(file, "stream", file)
    try:
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(position)
        return size
    except (AttributeError, OSError):
        return None


def _validate_upload_size(file):
    size = _get_upload_size(file)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise UploadValidationError(
            f"Uploaded file exceeds the {MAX_UPLOAD_BYTES} byte limit",
            status_code=413
        )


def _build_unique_upload_path(extension):
    file_save_dir = get_saved_upload_dir()
    os.makedirs(file_save_dir, exist_ok=True)

    for _ in range(10):
        file_name = f"{uuid.uuid4().hex}.{extension}"
        file_path = os.path.join(file_save_dir, file_name)
        try:
            fd = os.open(file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            return file_path
        except FileExistsError:
            continue
    raise RuntimeError("Unable to allocate a unique upload filename")


def _rewind_upload(file):
    stream = getattr(file, "stream", file)
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass


def _save_upload(file, extension, file_path):
    if extension in {'jpg', 'jpeg'}:
        try:
            _rewind_upload(file)
            with Image.open(file) as img:
                img = ImageOps.exif_transpose(img)
                img.save(file_path)
            return
        except Exception as e:
            logger.warning("EXIF processing error for uploaded JPEG: %s", e)
            _rewind_upload(file)

    file.save(file_path)


def is_saved_upload_path(file_path):
    if not file_path or not isinstance(file_path, str):
        return False
    try:
        saved_dir = os.path.abspath(get_saved_upload_dir())
        candidate = os.path.abspath(file_path)
        return os.path.commonpath([saved_dir, candidate]) == saved_dir
    except (OSError, ValueError):
        return False


def iter_saved_upload_paths(value):
    if isinstance(value, dict):
        for nested_value in value.values():
            yield from iter_saved_upload_paths(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from iter_saved_upload_paths(nested_value)
    elif is_saved_upload_path(value):
        yield value


def delete_saved_uploads_for_settings(settings, retained_paths=None):
    retained_paths = set(retained_paths or [])
    deleted = []
    for file_path in set(iter_saved_upload_paths(settings)):
        if file_path in retained_paths:
            continue
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                deleted.append(file_path)
                logger.info("Deleted saved upload: %s", file_path)
        except Exception as e:
            logger.warning("Failed to delete saved upload %s: %s", file_path, e)
    return deleted


def cleanup_replaced_saved_uploads(previous_settings, current_settings, retained_paths=None):
    current_paths = set(iter_saved_upload_paths(current_settings))
    current_paths.update(retained_paths or [])
    deleted = []
    for file_path in set(iter_saved_upload_paths(previous_settings)) - current_paths:
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                deleted.append(file_path)
                logger.info("Deleted stale saved upload: %s", file_path)
        except Exception as e:
            logger.warning("Failed to delete stale saved upload %s: %s", file_path, e)
    return deleted


def collect_saved_upload_paths_from_playlist_manager(
    playlist_manager,
    exclude_plugin_instance=None,
    exclude_plugin_instances=None
):
    excluded_instances = {id(instance) for instance in (exclude_plugin_instances or [])}
    if exclude_plugin_instance is not None:
        excluded_instances.add(id(exclude_plugin_instance))

    retained_paths = set()
    for playlist in getattr(playlist_manager, "playlists", []):
        for plugin_instance in getattr(playlist, "plugins", []):
            if id(plugin_instance) in excluded_instances:
                continue
            retained_paths.update(iter_saved_upload_paths(getattr(plugin_instance, "settings", {})))
    return retained_paths


def handle_request_files(request_files, form_data={}):
    file_location_map = {}
    saved_paths = []
    # handle existing file locations being provided as part of the form data
    for key in set(request_files.keys()):
        is_list = key.endswith('[]')
        if key in form_data:
            file_location_map[key] = form_data.getlist(key) if is_list else form_data.get(key)
    # add new files in the request
    try:
        for key, file in request_files.items(multi=True):
            is_list = key.endswith('[]')
            file_name = file.filename
            if not file_name:
                continue

            extension = _get_upload_extension(file_name)
            _validate_upload_size(file)
            file_path = _build_unique_upload_path(extension)
            try:
                _save_upload(file, extension, file_path)
                saved_paths.append(file_path)
            except Exception:
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise

            if is_list:
                file_location_map.setdefault(key, [])
                file_location_map[key].append(file_path)
            else:
                file_location_map[key] = file_path
    except Exception:
        for file_path in saved_paths:
            if os.path.exists(file_path):
                os.remove(file_path)
        raise
    return file_location_map
