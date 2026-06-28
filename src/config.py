import os
import json
import logging
import shutil
import tempfile
import threading
from datetime import datetime
from dotenv import load_dotenv
from model import PlaylistManager, RefreshInfo

logger = logging.getLogger(__name__)
_DEFAULT_CONFIG_VALUE = object()

class Config:
    SUPPORTED_PLUGIN_IDS = {"weather", "calendar"}

    # Base path for the project directory
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # File paths relative to the script's directory
    config_file = os.path.join(BASE_DIR, "config", "device.json")

    # File path for storing the current image being displayed
    current_image_file = os.path.join(BASE_DIR, "static", "images", "current_image.png")

    # Directory path for storing plugin instance images
    plugin_image_dir = os.path.join(BASE_DIR, "static", "images", "plugins")

    REQUIRED_PLAYLIST_FIELDS = ("name", "start_time", "end_time")
    REQUIRED_PLUGIN_INSTANCE_FIELDS = ("plugin_id", "name", "plugin_settings", "refresh")

    def __init__(self):
        self._write_lock = threading.RLock()
        self.config = self.read_config()
        self.plugins_list = self.read_plugins_list()
        if self.sanitize_plugin_config():
            self.backup_config_before_sanitizing()
            self.write_raw_config()
        self.playlist_manager = self.load_playlist_manager()
        self.refresh_info = self.load_refresh_info()

    def read_config(self):
        """Reads the device config JSON file and returns it as a dictionary."""
        logger.debug(f"Reading device config from {self.config_file}")
        with open(self.config_file) as f:
            config = json.load(f)

        logger.debug("Loaded config:\n%s", json.dumps(config, indent=3))

        return config

    def read_plugins_list(self):
        """Reads supported built-in plugin-info.json config files."""
        # Iterate over all plugin folders
        plugins_list = []
        for plugin in sorted(os.listdir(os.path.join(self.BASE_DIR, "plugins"))):
            if plugin not in self.SUPPORTED_PLUGIN_IDS:
                continue
            plugin_path = os.path.join(self.BASE_DIR, "plugins", plugin)
            if os.path.isdir(plugin_path) and plugin != "__pycache__":
                # Check if the plugin-info.json file exists
                plugin_info_file = os.path.join(plugin_path, "plugin-info.json")
                if os.path.isfile(plugin_info_file):
                    logger.debug(f"Reading plugin info from {plugin_info_file}")
                    with open(plugin_info_file) as f:
                        plugin_info = json.load(f)
                    icon_path = os.path.join(plugin_path, "icon.png")
                    if os.path.isfile(icon_path):
                        plugin_info["icon_version"] = str(int(os.path.getmtime(icon_path)))
                    plugins_list.append(plugin_info)

        return plugins_list

    def sanitize_plugin_config(self):
        """Remove unsupported plugin references and malformed playlist shapes.

        Playlist and plugin entries must keep the required fields consumed by
        their model from_dict() loaders. Missing plugin lists are repairable,
        but entries without required metadata are removed instead of invented.
        """
        changed = False

        plugin_order = self.config.get("plugin_order")
        if plugin_order is None:
            pass
        elif not isinstance(plugin_order, list):
            logger.warning(
                "Ignoring malformed plugin_order; expected list, got %s.",
                type(plugin_order).__name__
            )
            self.config["plugin_order"] = []
            changed = True
        else:
            supported_order = [plugin_id for plugin_id in plugin_order if plugin_id in self.SUPPORTED_PLUGIN_IDS]
            removed = [plugin_id for plugin_id in plugin_order if plugin_id not in self.SUPPORTED_PLUGIN_IDS]
            if removed:
                removed_names = sorted({str(plugin_id) for plugin_id in removed})
                logger.warning("Ignoring unsupported plugin_order entries: %s", ", ".join(removed_names))
                self.config["plugin_order"] = supported_order
                changed = True

        playlist_config = self.config.get("playlist_config", {})
        if playlist_config is None or not isinstance(playlist_config, dict):
            logger.warning(
                "Ignoring malformed playlist_config; expected object, got %s.",
                type(playlist_config).__name__
            )
            playlist_config = {"playlists": [], "active_playlist": None}
            self.config["playlist_config"] = playlist_config
            changed = True

        playlists = playlist_config.get("playlists", [])
        if playlists is None:
            playlists = []
            playlist_config["playlists"] = playlists
            changed = True
        elif not isinstance(playlists, list):
            logger.warning(
                "Ignoring malformed playlist_config.playlists; expected list, got %s.",
                type(playlists).__name__
            )
            playlists = []
            playlist_config["playlists"] = playlists
            changed = True

        supported_playlists = []
        removed_malformed_playlists = False
        for playlist in playlists:
            if not isinstance(playlist, dict):
                removed_malformed_playlists = True
                continue

            missing_required_fields = [
                field
                for field in self.REQUIRED_PLAYLIST_FIELDS
                if not isinstance(playlist.get(field), str)
            ]
            if missing_required_fields:
                logger.warning(
                    "Ignoring malformed playlist entry missing required fields: %s.",
                    ", ".join(missing_required_fields)
                )
                removed_malformed_playlists = True
                continue

            plugins = playlist.get("plugins", [])
            if "plugins" not in playlist or plugins is None:
                plugins = []
                playlist["plugins"] = plugins
                playlist["current_plugin_index"] = None
                changed = True
            elif not isinstance(plugins, list):
                playlist_name = playlist.get("name", "Unnamed")
                logger.warning(
                    "Ignoring malformed plugins list in playlist '%s'; expected list, got %s.",
                    playlist_name,
                    type(plugins).__name__
                )
                plugins = []
                playlist["plugins"] = plugins
                playlist["current_plugin_index"] = None
                changed = True

            supported_plugins = []
            removed_plugins = []
            for plugin in plugins:
                if not isinstance(plugin, dict):
                    removed_plugins.append(type(plugin).__name__)
                    continue

                plugin_id = plugin.get("plugin_id")
                if plugin_id not in self.SUPPORTED_PLUGIN_IDS:
                    removed_plugins.append(plugin.get("plugin_id", "unknown"))
                    continue

                missing_plugin_fields = [
                    field
                    for field in self.REQUIRED_PLUGIN_INSTANCE_FIELDS
                    if field not in plugin
                ]
                if (
                    missing_plugin_fields
                    or not isinstance(plugin.get("name"), str)
                    or not isinstance(plugin.get("plugin_settings"), dict)
                    or not isinstance(plugin.get("refresh"), dict)
                ):
                    removed_plugins.append(plugin_id)
                    logger.warning(
                        "Ignoring malformed plugin instance '%s' in playlist '%s'.",
                        plugin_id,
                        playlist.get("name", "Unnamed")
                    )
                    continue

                supported_plugins.append(plugin)

            if removed_plugins:
                playlist_name = playlist.get("name", "Unnamed")
                removed_plugin_names = sorted({str(plugin_id) for plugin_id in removed_plugins})
                logger.warning(
                    "Ignoring unsupported plugin instances in playlist '%s': %s",
                    playlist_name,
                    ", ".join(removed_plugin_names)
                )
                playlist["plugins"] = supported_plugins
                playlist["current_plugin_index"] = None
                changed = True

            supported_playlists.append(playlist)

        if removed_malformed_playlists:
            logger.warning("Ignoring malformed playlist entries; expected objects.")
            playlist_config["playlists"] = supported_playlists
            changed = True

        refresh_info = self.config.get("refresh_info", {})
        if refresh_info is None or not isinstance(refresh_info, dict):
            logger.warning(
                "Ignoring malformed refresh_info; expected object, got %s.",
                type(refresh_info).__name__
            )
            self.config["refresh_info"] = self.empty_refresh_info()
            changed = True
        else:
            refresh_plugin_id = refresh_info.get("plugin_id")
            if refresh_plugin_id and refresh_plugin_id not in self.SUPPORTED_PLUGIN_IDS:
                logger.warning("Clearing refresh_info for unsupported plugin '%s'.", refresh_plugin_id)
                self.config["refresh_info"] = self.empty_refresh_info()
                changed = True

        return changed

    @staticmethod
    def empty_refresh_info():
        return {
            "refresh_time": None,
            "image_hash": None,
            "refresh_type": None,
            "plugin_id": None
        }

    def write_raw_config(self):
        """Writes the current config dictionary without syncing model objects first."""
        logger.debug(f"Writing sanitized device config to {self.config_file}")
        self._write_config_data(self.config)

    def backup_config_before_sanitizing(self):
        """Back up the original config before writing a sanitized replacement."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        config_dir = os.path.dirname(self.config_file)
        backup_file = os.path.join(
            config_dir,
            f"device.pre-weather-calendar-only-{timestamp}.json"
        )
        shutil.copy2(self.config_file, backup_file)
        logger.warning("Backed up original device config before plugin scope migration: %s", backup_file)
        return backup_file

    def write_config(self):
        """Updates the cached config from the model objects and writes to the config file."""
        logger.debug(f"Writing device config to {self.config_file}")
        with self._get_write_lock():
            self.update_value("playlist_config", self.playlist_manager.to_dict())
            self.update_value("refresh_info", self.refresh_info.to_dict())
            self._write_config_data(self.config)

    def _get_write_lock(self):
        if not hasattr(self, "_write_lock"):
            self._write_lock = threading.RLock()
        return self._write_lock

    def _write_config_data(self, config_data):
        with self._get_write_lock():
            self._atomic_write_json(config_data)

    def _atomic_write_json(self, config_data):
        config_dir = os.path.dirname(self.config_file)
        temp_path = None
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.config_file)}.",
            suffix=".tmp",
            dir=config_dir
        )
        try:
            with os.fdopen(fd, "w") as outfile:
                json.dump(config_data, outfile, indent=4)
                outfile.write("\n")
                outfile.flush()
                os.fsync(outfile.fileno())
            os.replace(temp_path, self.config_file)
            self._fsync_config_dir(config_dir)
            temp_path = None
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    def _fsync_config_dir(self, config_dir):
        if not hasattr(os, "O_DIRECTORY"):
            return
        try:
            dir_fd = os.open(config_dir, os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def get_config(self, key=None, default=_DEFAULT_CONFIG_VALUE):
        """Gets the value of a specific configuration key or returns the entire config if none provided."""
        if key is not None:
            if default is _DEFAULT_CONFIG_VALUE:
                default = {}
            return self.config.get(key, default)
        return self.config

    def get_web_server_threads(self, default=2, max_threads=8):
        """Returns the configured Waitress worker thread count."""
        configured_threads = self.get_config("web_server_threads", default)
        try:
            thread_count = int(configured_threads)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid web_server_threads value %r; using default %s.",
                configured_threads,
                default
            )
            return default

        if thread_count < 1:
            logger.warning(
                "Invalid web_server_threads value %r; using default %s.",
                configured_threads,
                default
            )
            return default

        if thread_count > max_threads:
            logger.warning(
                "web_server_threads value %s exceeds maximum %s; using %s.",
                thread_count,
                max_threads,
                max_threads
            )
            return max_threads

        return thread_count

    def get_plugins(self):
        """Returns the list of plugin configurations, sorted by custom order if set."""
        plugin_order = self.config.get('plugin_order', [])

        if not plugin_order:
            return self.plugins_list

        # Create a dict for quick lookup
        plugins_dict = {p['id']: p for p in self.plugins_list}

        # Build ordered list
        ordered = []
        for plugin_id in plugin_order:
            if plugin_id in plugins_dict:
                ordered.append(plugins_dict.pop(plugin_id))

        # Append any remaining plugins not in the order (new plugins)
        ordered.extend(plugins_dict.values())

        return ordered

    def set_plugin_order(self, order):
        """Sets the custom plugin display order."""
        self.update_value('plugin_order', order, write=True)

    def get_plugin(self, plugin_id):
        """Finds and returns a plugin config by its ID."""
        if plugin_id not in self.SUPPORTED_PLUGIN_IDS:
            logger.warning("Unsupported plugin requested: %s", plugin_id)
            return None
        return next((plugin for plugin in self.plugins_list if plugin['id'] == plugin_id), None)

    def get_resolution(self):
        """Returns the display resolution as a tuple (width, height) from the configuration."""
        resolution = self.get_config("resolution")
        width, height = resolution
        return (int(width), int(height))

    def update_config(self, config):
        """Updates the config with the new values provided and writes to the config file."""
        with self._get_write_lock():
            self.config.update(config)
            self.write_config()

    def update_value(self, key, value, write=False):
        """Updates a specific key in the configuration with a new value and optionally writes it to the config file."""
        with self._get_write_lock():
            self.config[key] = value
            if write:
                self.write_config()

    def load_env_key(self, key):
        """Loads an environment variable using dotenv and returns its value."""
        load_dotenv(override=True)
        return os.getenv(key)

    def load_playlist_manager(self):
        """Loads the playlist manager object from the config."""
        playlist_manager = PlaylistManager.from_dict(self.get_config("playlist_config"))
        if not playlist_manager.playlists:
            playlist_manager.add_default_playlist()
        return playlist_manager

    def load_refresh_info(self):
        """Loads the refresh information from the config."""
        return RefreshInfo.from_dict(self.get_config("refresh_info"))

    def get_playlist_manager(self):
        """Returns the playlist manager."""
        return self.playlist_manager

    def get_refresh_info(self):
        """Returns the refresh information."""
        return self.refresh_info
