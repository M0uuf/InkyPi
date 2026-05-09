import threading
import time
import os
import logging
import psutil
import pytz
import uuid
from collections import deque
from datetime import datetime, timezone
from plugins.plugin_registry import get_plugin_instance
from utils.image_utils import compute_image_hash
from utils.performance import PerformanceDiagnostics, is_performance_diagnostics_enabled
from model import RefreshInfo
from PIL import Image

logger = logging.getLogger(__name__)

class ManualUpdateBusy(RuntimeError):
    """Raised when a manual refresh is already queued or running."""

    def __init__(self, active_job):
        self.active_job = active_job
        super().__init__("Manual display update already in progress")

class ManualUpdateJob:
    """Tracks one manual refresh request and its caller-specific outcome."""

    def __init__(self, refresh_action):
        self.id = uuid.uuid4().hex
        self.refresh_action = refresh_action
        self.event = threading.Event()
        self.result = {}
        self.state = "queued"
        self.error = None
        self.created_at = datetime.now(timezone.utc)
        self.started_at = None
        self.finished_at = None

    def mark_running(self):
        self.state = "running"
        self.started_at = datetime.now(timezone.utc)

    def mark_done(self):
        self.state = "done"
        self.finished_at = datetime.now(timezone.utc)
        self.event.set()

    def mark_error(self, exception):
        self.state = "error"
        self.error = str(exception)
        self.result["exception"] = exception
        self.finished_at = datetime.now(timezone.utc)
        self.event.set()

    def to_dict(self):
        return {
            "id": self.id,
            "state": self.state,
            "error": self.error,
            "plugin_id": self.refresh_action.get_plugin_id(),
            "refresh_type": self.refresh_action.get_refresh_info().get("refresh_type"),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None
        }

class RefreshTask:
    """Handles the logic for refreshing the display using a background thread."""
    DEFAULT_SCHEDULER_CHECK_INTERVAL_SECONDS = 60

    def __init__(self, device_config, display_manager):
        self.device_config = device_config
        self.display_manager = display_manager

        self.thread = None
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.running = False
        self.manual_update_queue = deque()
        self.manual_update_jobs = {}
        self.max_manual_update_jobs = 20

    def start(self):
        """Starts the background thread for refreshing the display."""
        if not self.thread or not self.thread.is_alive():
            logger.info("Starting refresh task")
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.running = True
            self.thread.start()

    def stop(self):
        """Stops the refresh task by notifying the background thread to exit."""
        with self.condition:
            self.running = False
            while self.manual_update_queue:
                job = self.manual_update_queue.popleft()
                job.mark_error(RuntimeError("Refresh task stopped before manual update completed"))
            self.condition.notify_all()  # Wake the thread to let it exit
        if self.thread:
            logger.info("Stopping refresh task")
            self.thread.join()

    def _run(self):
        """Background task that manages the periodic refresh of the display.

        This function runs in a loop, sleeping for a configured duration (`plugin_cycle_interval_seconds`) or until
        manually triggered via `manual_update()`. Determines the next plugin to refresh based on active playlists and
        updates the display accordingly.

        Workflow:
        1. Waits for the configured sleep duration or until notified of a manual update.
        2. Checks if a manual update has been requested:
        - If so, refreshes the specified plugin immediately.
        3. Otherwise, determines the next plugin to refresh based on the active playlist and generates an image.
        4. Compares the image hash with the last displayed image hash.
        - If the image has changed, updates the display.
        - If the image is the same, skips the refresh.
        5. Updates the refresh metadata in the device configuration.
        6. Repeats the process until `stop()` is called.

        Handles any exceptions that occur during the refresh process and ensures the refresh event is set 
        to indicate completion.

        Exceptions:
        - Captures and logs any unexpected errors during execution to prevent the thread from exiting.
        """
        while True:
            job = None
            refresh_action = None
            latest_refresh = None
            current_dt = None
            try:
                diagnostics = self._performance_diagnostics()
                with self.condition:
                    sleep_time = self._get_scheduler_check_interval_seconds()

                    # Exit promptly if `stop()` was called while a refresh was executing.
                    if not self.running:
                        break

                    # Wait for sleep_time or until notified
                    if not self.manual_update_queue:
                        self.condition.wait(timeout=sleep_time)

                    # Exit if `stop()` is called
                    if not self.running:
                        break

                    with diagnostics.phase("determine active playlist"):
                        playlist_manager = self.device_config.get_playlist_manager()
                        latest_refresh = self.device_config.get_refresh_info()
                        current_dt = self._get_current_datetime()

                        if not self.manual_update_queue:
                            if self.device_config.get_config("log_system_stats"):
                                self.log_system_stats()

                            # handle refresh based on playlists
                            logger.info(f"Running interval refresh check. | current_time: {current_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                            playlist, plugin_instance = self._determine_next_plugin(playlist_manager, latest_refresh, current_dt)
                            if plugin_instance:
                                refresh_action = PlaylistRefresh(playlist, plugin_instance)

                    if self.manual_update_queue:
                        # handle immediate update request
                        logger.info("Manual update requested")
                        job = self.manual_update_queue.popleft()
                        job.mark_running()
                        refresh_action = job.refresh_action

                if refresh_action:
                    display_updated = False
                    refresh_info = None

                    with diagnostics.phase("load plugin"):
                        plugin_config = self.device_config.get_plugin(refresh_action.get_plugin_id())
                        if plugin_config is None:
                            message = f"Plugin config not found for '{refresh_action.get_plugin_id()}'."
                            if job:
                                raise ValueError(message)
                            logger.error(message)
                            continue
                        plugin = get_plugin_instance(plugin_config)

                    with diagnostics.phase("plugin image generation"):
                        image = refresh_action.execute(plugin, self.device_config, current_dt)

                    with diagnostics.phase("image hash calculation"):
                        image_hash = compute_image_hash(image)

                    refresh_info = refresh_action.get_refresh_info()
                    refresh_info.update({"refresh_time": current_dt.isoformat(), "image_hash": image_hash})
                    # check if image is the same as current image
                    if image_hash != latest_refresh.image_hash:
                        logger.info(f"Updating display. | refresh_info: {refresh_info}")
                        with diagnostics.phase("display manager processing"):
                            self.display_manager.display_image(image, image_settings=plugin.config.get("image_settings", []))
                        display_updated = True
                    else:
                        logger.info(f"Image already displayed, skipping refresh. | refresh_info: {refresh_info}")

                    # update latest refresh data in the device config
                    with diagnostics.phase("config write"):
                        self.device_config.refresh_info = RefreshInfo(**refresh_info)
                        self.device_config.write_config()

                    diagnostics.log_summary(
                        "refresh_type=%s | plugin_id=%s | display_updated=%s"
                        % (
                            refresh_info.get("refresh_type"),
                            refresh_info.get("plugin_id"),
                            display_updated
                        )
                    )

                    if job:
                        with self.condition:
                            job.mark_done()

            except Exception as e:
                logger.exception('Exception during refresh')
                if job:
                    with self.condition:
                        job.mark_error(e)  # Capture exception for this manual caller

    def _enqueue_manual_update_job(self, refresh_action):
        """Queues a manual refresh and returns the job without waiting for completion."""
        if not self.running:
            logger.warning("Background refresh task is not running, unable to queue a manual update")
            return None

        with self.condition:
            active_job = self._get_active_manual_update_job()
            if active_job:
                raise ManualUpdateBusy(active_job.to_dict())

            job = ManualUpdateJob(refresh_action)
            self.manual_update_jobs[job.id] = job
            self.manual_update_queue.append(job)
            self._trim_manual_update_jobs()
            self.condition.notify_all()  # Wake the thread to process manual update
            return job

    def enqueue_manual_update(self, refresh_action):
        """Queues a manual refresh and returns its status without waiting for completion."""
        job = self._enqueue_manual_update_job(refresh_action)
        if not job:
            return None
        return job.to_dict()

    def manual_update(self, refresh_action):
        """Manually triggers an update for the specified plugin id and plugin settings by notifying the background process."""
        job = self._enqueue_manual_update_job(refresh_action)
        if not job:
            return

        job.event.wait()
        if job.result.get("exception"):
            raise job.result.get("exception")

    def get_manual_update_job(self, job_id):
        """Returns a manual update job by ID."""
        with self.condition:
            return self.manual_update_jobs.get(job_id)

    def get_manual_update_status(self, job_id):
        """Returns a serializable status for a manual update job."""
        with self.condition:
            job = self.manual_update_jobs.get(job_id)
            if not job:
                return None
            return job.to_dict()

    def _get_active_manual_update_job(self):
        """Returns the active queued or running manual update job, if present."""
        return next(
            (
                job for job in self.manual_update_jobs.values()
                if job.state in {"queued", "running"}
            ),
            None
        )

    def _trim_manual_update_jobs(self):
        """Keep a small bounded history of manual refresh jobs."""
        while len(self.manual_update_jobs) > self.max_manual_update_jobs:
            oldest_done_job_id = next(
                (
                    job_id for job_id, job in self.manual_update_jobs.items()
                    if job.state in {"done", "error"}
                ),
                None
            )
            if not oldest_done_job_id:
                break
            self.manual_update_jobs.pop(oldest_done_job_id, None)

    def signal_config_change(self):
        """Notify the background thread that config has changed (e.g., interval updated)."""
        if self.running:
            with self.condition:
                self.condition.notify_all()

    def _get_current_datetime(self):
        """Retrieves the current datetime based on the device's configured timezone."""
        tz_str = self.device_config.get_config("timezone", default="UTC")
        return datetime.now(pytz.timezone(tz_str))

    def _get_scheduler_check_interval_seconds(self):
        configured_interval = self.device_config.get_config(
            "scheduler_check_interval_seconds",
            default=self.DEFAULT_SCHEDULER_CHECK_INTERVAL_SECONDS
        )
        try:
            interval = int(configured_interval)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid scheduler_check_interval_seconds value %r. Using %s.",
                configured_interval,
                self.DEFAULT_SCHEDULER_CHECK_INTERVAL_SECONDS
            )
            return self.DEFAULT_SCHEDULER_CHECK_INTERVAL_SECONDS

        if interval < 1:
            logger.warning(
                "Invalid scheduler_check_interval_seconds value %r. Using %s.",
                configured_interval,
                self.DEFAULT_SCHEDULER_CHECK_INTERVAL_SECONDS
            )
            return self.DEFAULT_SCHEDULER_CHECK_INTERVAL_SECONDS
        return interval

    def _determine_next_plugin(self, playlist_manager, latest_refresh_info, current_dt):
        """Determines the next plugin to refresh based on the active playlist and plugin refresh rules."""
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if not playlist:
            playlist_manager.active_playlist = None
            logger.info(f"No active playlist determined.")
            return None, None

        playlist_manager.active_playlist = playlist.name
        if not playlist.plugins:
            logger.info(f"Active playlist '{playlist.name}' has no plugins.")
            return None, None

        plugin = playlist.find_next_refreshable_plugin(current_dt)
        if not plugin:
            logger.info(f"No plugin refresh due. | active_playlist: {playlist.name}")
            return None, None

        logger.info(f"Determined next plugin. | active_playlist: {playlist.name} | plugin_instance: {plugin.name}")

        return playlist, plugin
    
    def log_system_stats(self):
        metrics = {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent,
            'load_avg_1_5_15': os.getloadavg(),
            'swap_percent': psutil.swap_memory().percent,
            'net_io': {
                'bytes_sent': psutil.net_io_counters().bytes_sent,
                'bytes_recv': psutil.net_io_counters().bytes_recv
            }
        }

        logger.info(f"System Stats: {metrics}")

    def _performance_diagnostics(self):
        return PerformanceDiagnostics(
            enabled=is_performance_diagnostics_enabled(self.device_config),
            logger=logger,
            prefix="Refresh diagnostics"
        )

class RefreshAction:
    """Base class for a refresh action. Subclasses should override the methods below."""
    
    def refresh(self, plugin, device_config, current_dt):
        """Perform a refresh operation and return the updated image."""
        raise NotImplementedError("Subclasses must implement the refresh method.")
    
    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        raise NotImplementedError("Subclasses must implement the get_refresh_info method.")
    
    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        raise NotImplementedError("Subclasses must implement the get_plugin_id method.")

class ManualRefresh(RefreshAction):
    """Performs a manual refresh based on a plugin's ID and its associated settings.
    
    Attributes:
        plugin_id (str): The ID of the plugin to refresh.
        plugin_settings (dict): The settings for the manual refresh.
    """

    def __init__(self, plugin_id: str, plugin_settings: dict):
        self.plugin_id = plugin_id
        self.plugin_settings = plugin_settings

    def execute(self, plugin, device_config, current_dt: datetime):
        """Performs a manual refresh using the stored plugin ID and settings."""
        return plugin.generate_image(self.plugin_settings, device_config)

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {"refresh_type": "Manual Update", "plugin_id": self.plugin_id}

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_id

class PlaylistRefresh(RefreshAction):
    """Performs a refresh using a plugin instance within a playlist context.

    Attributes:
        playlist: The playlist object associated with the refresh.
        plugin_instance: The plugin instance to refresh.
    """

    def __init__(self, playlist, plugin_instance, force=False):
        self.playlist_name = playlist.name
        self.plugin_id = plugin_instance.plugin_id
        self.plugin_instance_name = plugin_instance.name
        self.force = force

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {
            "refresh_type": "Playlist",
            "playlist": self.playlist_name,
            "plugin_id": self.plugin_id,
            "plugin_instance": self.plugin_instance_name
        }

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_id

    def execute(self, plugin, device_config, current_dt: datetime):
        """Performs a refresh for the specified plugin instance within its playlist context."""
        playlist = device_config.get_playlist_manager().get_playlist(self.playlist_name)
        if not playlist:
            raise ValueError(f"Playlist '{self.playlist_name}' no longer exists")

        plugin_instance = playlist.find_plugin(self.plugin_id, self.plugin_instance_name)
        if not plugin_instance:
            raise ValueError(
                f"Plugin instance '{self.plugin_instance_name}' no longer exists in playlist '{self.playlist_name}'"
            )

        # Determine the file path for the plugin's image
        plugin_image_path = os.path.join(device_config.plugin_image_dir, plugin_instance.get_image_path())

        # Check if a refresh is needed based on the plugin instance's criteria
        if plugin_instance.should_refresh(current_dt) or self.force:
            logger.info(f"Refreshing plugin instance. | plugin_instance: '{plugin_instance.name}'")
            # Generate a new image
            image = plugin.generate_image(plugin_instance.settings, device_config)
            image.save(plugin_image_path)
            plugin_instance.latest_refresh_time = current_dt.isoformat()
        else:
            logger.info(f"Not time to refresh plugin instance, using latest image. | plugin_instance: {plugin_instance.name}.")
            # Load the existing image from disk
            with Image.open(plugin_image_path) as img:
                image = img.copy()

        return image
