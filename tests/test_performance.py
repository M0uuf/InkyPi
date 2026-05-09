import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.performance import PerformanceDiagnostics, is_performance_diagnostics_enabled


class FakeDeviceConfig:
    def __init__(self, value):
        self.value = value

    def get_config(self, key, default=None):
        return self.value if key == "performance_diagnostics" else default


def test_performance_diagnostics_flag_accepts_common_values():
    assert is_performance_diagnostics_enabled(FakeDeviceConfig(True))
    assert is_performance_diagnostics_enabled(FakeDeviceConfig("yes"))
    assert not is_performance_diagnostics_enabled(FakeDeviceConfig(False))
    assert not is_performance_diagnostics_enabled(FakeDeviceConfig("off"))


def test_performance_diagnostics_noop_when_disabled(caplog):
    diagnostics = PerformanceDiagnostics(enabled=False, logger=logging.getLogger("test"), prefix="Test diagnostics")

    caplog.set_level(logging.INFO, logger="test")
    with diagnostics.phase("work"):
        pass
    diagnostics.log_summary("context=value")

    assert diagnostics.phases == []
    assert caplog.text == ""


def test_performance_diagnostics_logs_phase_and_summary(caplog):
    diagnostics = PerformanceDiagnostics(enabled=True, logger=logging.getLogger("test"), prefix="Test diagnostics")

    caplog.set_level(logging.INFO, logger="test")
    with diagnostics.phase("work"):
        pass
    diagnostics.log_summary("context=value")

    assert diagnostics.phases[0][0] == "work"
    assert "Test diagnostics phase completed" in caplog.text
    assert "phase: work" in caplog.text
    assert "Test diagnostics summary" in caplog.text
    assert "context=value" in caplog.text
