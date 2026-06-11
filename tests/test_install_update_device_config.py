import json
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


HELPER = Path(__file__).resolve().parents[1] / "install" / "update_device_config.py"


def load_helper_module():
    spec = importlib.util.spec_from_file_location("update_device_config", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_helper(config_path, display_type="epd7in3f"):
    return subprocess.run(
        [sys.executable, str(HELPER), str(config_path), display_type],
        capture_output=True,
        text=True,
    )


def test_update_device_config_updates_valid_json_atomically(tmp_path):
    helper = load_helper_module()
    config_path = tmp_path / "device.json"
    config_path.write_text(json.dumps({"display_type": "epd2in13", "name": "InkyPi"}), encoding="utf-8")
    replacements = []

    original_replace = helper.os.replace

    def capture_replace(src, dst):
        replacements.append((Path(src), Path(dst), Path(src).read_text(encoding="utf-8")))
        original_replace(src, dst)

    helper.os.replace = capture_replace
    try:
        helper.update_display_type(config_path, "epd7in3f")
    finally:
        helper.os.replace = original_replace

    assert len(replacements) == 1
    assert replacements[0][0].parent == tmp_path
    assert replacements[0][1] == config_path
    assert json.loads(replacements[0][2])["display_type"] == "epd7in3f"
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "display_type": "epd7in3f",
        "name": "InkyPi",
    }
    assert list(tmp_path.glob(".device.json.*.tmp")) == []


def test_update_device_config_rejects_invalid_json_without_overwriting(tmp_path):
    config_path = tmp_path / "device.json"
    original = '{"display_type": "epd2in13",'
    config_path.write_text(original, encoding="utf-8")

    result = run_helper(config_path)

    assert result.returncode == 1
    assert "Failed to update display_type" in result.stderr
    assert config_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".device.json.*.tmp")) == []


@pytest.mark.parametrize("script_name", ["install.sh", "update.sh"])
def test_install_scripts_stop_when_device_config_helper_fails(script_name):
    script = (Path(__file__).resolve().parents[1] / "install" / script_name).read_text(encoding="utf-8")

    assert 'if python3 "$SCRIPT_DIR/update_device_config.py" "$DEVICE_JSON" "$WS_TYPE"; then' in script
    assert 'echo_error "ERROR: Failed to update display_type in $DEVICE_JSON."' in script
    assert "exit 1" in script
