#!/usr/bin/env python3
"""Update installer-managed device config fields safely."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def update_display_type(config_path: Path, display_type: str) -> None:
    with config_path.open(encoding="utf-8") as config_file:
        data = json.load(config_file)

    data["display_type"] = display_type
    serialized = json.dumps(data, indent=4) + "\n"

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(serialized)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, config_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: update_device_config.py <device.json> <display_type>", file=sys.stderr)
        return 2

    config_path = Path(argv[1])
    display_type = argv[2]

    try:
        update_display_type(config_path, display_type)
    except Exception as exc:
        print(f"Failed to update display_type in {config_path}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
