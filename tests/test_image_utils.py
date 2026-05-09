import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.image_utils import (
    RESIZE_FILTERS,
    change_orientation,
    get_resize_filter,
    is_default_image_enhancement,
    normalize_image_mode_for_enhancement,
    resize_image
)


def test_resize_image_returns_original_when_target_size_matches():
    image = Image.new("RGB", (16, 16), "white")

    resized = resize_image(image, (16, 16))

    assert resized is image


def test_change_orientation_returns_original_for_horizontal_noop():
    image = Image.new("RGB", (16, 16), "white")

    oriented = change_orientation(image, "horizontal")

    assert oriented is image


def test_resize_filter_lookup_uses_config_names():
    assert get_resize_filter("bilinear") == RESIZE_FILTERS["bilinear"]
    assert get_resize_filter("BICUBIC") == RESIZE_FILTERS["bicubic"]
    assert get_resize_filter("unknown", default="lanczos") == RESIZE_FILTERS["lanczos"]


def test_default_image_enhancement_detection_accepts_missing_defaults():
    assert is_default_image_enhancement({})
    assert is_default_image_enhancement({
        "brightness": "1.0",
        "contrast": 1.0,
        "saturation": 1,
        "sharpness": 1.0
    })
    assert not is_default_image_enhancement({"contrast": 1.2})


def test_normalize_image_mode_for_enhancement_converts_rgba_to_rgb():
    image = Image.new("RGBA", (16, 16), "white")

    normalized = normalize_image_mode_for_enhancement(image)

    assert normalized.mode == "RGB"
