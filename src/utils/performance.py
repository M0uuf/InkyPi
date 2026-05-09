import logging
import time
from contextlib import contextmanager


logger = logging.getLogger(__name__)


def is_performance_diagnostics_enabled(device_config):
    """Read the opt-in diagnostics flag from device config."""
    if not device_config:
        return False

    value = device_config.get_config("performance_diagnostics", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
        logger.warning("Invalid performance_diagnostics value %r. Diagnostics disabled.", value)
        return False
    return bool(value)


class PerformanceDiagnostics:
    """Collect and log named phase durations when diagnostics are enabled."""

    def __init__(self, enabled=False, logger=None, prefix="Performance"):
        self.enabled = enabled
        self.logger = logger or logging.getLogger(__name__)
        self.prefix = prefix
        self.phases = []

    @contextmanager
    def phase(self, name):
        if not self.enabled:
            yield
            return

        started = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - started
            self.phases.append((name, elapsed))
            self.logger.info("%s phase completed in %.2fs | phase: %s", self.prefix, elapsed, name)

    def log_summary(self, context=None):
        if not self.enabled:
            return

        total = sum(elapsed for _, elapsed in self.phases)
        breakdown = ", ".join(f"{name}={elapsed:.2f}s" for name, elapsed in self.phases)
        if context:
            self.logger.info(
                "%s summary | total=%.2fs | %s | %s",
                self.prefix,
                total,
                context,
                breakdown
            )
        else:
            self.logger.info("%s summary | total=%.2fs | %s", self.prefix, total, breakdown)
