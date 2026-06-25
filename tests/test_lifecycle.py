import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.lifecycle import shutdown_display_stack


class FakeRefreshTask:
    def __init__(self, events, fail=False):
        self.events = events
        self.fail = fail

    def stop(self):
        self.events.append("stop")
        if self.fail:
            raise RuntimeError("stop failed")


class FakeDisplayManager:
    def __init__(self, events, fail=False):
        self.events = events
        self.fail = fail

    def close(self):
        self.events.append("close")
        if self.fail:
            raise RuntimeError("close failed")


def test_shutdown_display_stack_closes_display_after_stopping_refresh_task():
    events = []

    shutdown_display_stack(FakeRefreshTask(events), FakeDisplayManager(events))

    assert events == ["stop", "close"]


def test_shutdown_display_stack_still_closes_display_when_refresh_stop_fails(caplog):
    events = []

    shutdown_display_stack(FakeRefreshTask(events, fail=True), FakeDisplayManager(events))

    assert events == ["stop", "close"]
    assert "Exception while stopping refresh task during shutdown" in caplog.text


def test_shutdown_display_stack_swallows_display_close_errors(caplog):
    events = []

    shutdown_display_stack(FakeRefreshTask(events), FakeDisplayManager(events, fail=True))

    assert events == ["stop", "close"]
    assert "Exception while closing display manager during shutdown" in caplog.text


def test_inkypi_shutdown_uses_display_stack_lifecycle_helper():
    source = (Path(__file__).resolve().parents[1] / "src" / "inkypi.py").read_text(encoding="utf-8")

    assert "from utils.lifecycle import shutdown_display_stack" in source
    assert "finally:\n        shutdown_display_stack(refresh_task, display_manager)" in source
