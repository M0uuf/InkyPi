import logging
import os
import re
import tempfile

from dotenv import dotenv_values


logger = logging.getLogger(__name__)

ENV_FILE_MODE = 0o600
CONTROL_CHARACTER_PATTERN = re.compile(r'[\x00-\x1f\x7f]')
ENV_KEY_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def parse_env_file(filepath):
    """Parse .env file and return list of (key, value) tuples."""
    if not os.path.exists(filepath):
        return []

    try:
        env_dict = dotenv_values(filepath)
        return list(env_dict.items())
    except Exception as e:
        logger.error("Error parsing .env file: %s", e)
        return []


def serialize_env_value(value):
    """Serialize a value as a single-quoted dotenv string."""
    if value is None:
        value = ""
    return "'{}'".format(str(value).replace("\\", "\\\\").replace("'", "\\'"))


def validate_env_value(value):
    if value is None:
        return ""
    value = str(value)
    if CONTROL_CHARACTER_PATTERN.search(value):
        raise ValueError("API key values cannot contain newlines or control characters")
    return value


def write_env_file(filepath, entries):
    """Write entries to .env file atomically with restrictive permissions."""
    temp_path = None
    try:
        env_dir = os.path.dirname(filepath) or "."
        os.makedirs(env_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".env.",
            suffix=".tmp",
            dir=env_dir
        )
        os.fchmod(fd, ENV_FILE_MODE)
        with os.fdopen(fd, 'w') as f:
            f.write("# InkyPi API Keys and Secrets\n")
            f.write("# Managed via web interface\n\n")
            for key, value in entries:
                f.write(f"{key}={serialize_env_value(value)}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, filepath)
        os.chmod(filepath, ENV_FILE_MODE)
        temp_path = None
        return True
    except Exception as e:
        logger.error("Error writing .env file: %s", e)
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
