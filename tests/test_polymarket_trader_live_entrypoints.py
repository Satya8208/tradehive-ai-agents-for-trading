from pathlib import Path
import subprocess
import sys

import pytest

from src.agents.polymarket_trader import live_run, paper_run


class StubOrchestrator:
    def __init__(self, _config):
        self._config = _config

    def get_run_status(self):
        return {}

    def run(self, cycles=0):
        raise AssertionError(f"run() should not be called in this test (cycles={cycles})")


def test_live_runner_refuses_skip_preflight(monkeypatch):
    monkeypatch.setattr(live_run, "PolymarketCLIOrchestrator", StubOrchestrator)
    monkeypatch.setattr(sys, "argv", ["live_run", "--confirm-live", "--skip-preflight"])

    with pytest.raises(SystemExit) as exc:
        live_run.main()

    assert exc.value.code == 2


def test_paper_runner_preserves_default_expiry_cap(monkeypatch):
    captured = {}

    class CaptureOrchestrator(StubOrchestrator):
        def __init__(self, config):
            captured["config"] = config
            super().__init__(config)

    monkeypatch.setattr(paper_run, "PolymarketCLIOrchestrator", CaptureOrchestrator)
    monkeypatch.setattr(sys, "argv", ["paper_run", "--status"])

    paper_run.main()

    assert captured["config"].max_expiry_hours == 24.0
    assert captured["config"].min_expiry_hours is None


def test_paper_runner_respects_explicit_expiry_overrides(monkeypatch):
    captured = {}

    class CaptureOrchestrator(StubOrchestrator):
        def __init__(self, config):
            captured["config"] = config
            super().__init__(config)

    monkeypatch.setattr(paper_run, "PolymarketCLIOrchestrator", CaptureOrchestrator)
    monkeypatch.setattr(
        sys,
        "argv",
        ["paper_run", "--status", "--max-expiry-hours", "4", "--min-expiry-hours", "1"],
    )

    paper_run.main()

    assert captured["config"].max_expiry_hours == 4.0
    assert captured["config"].min_expiry_hours == 1.0


def test_paper_runner_weather_mode_builds_weather_config(monkeypatch):
    captured = {}

    class CaptureOrchestrator(StubOrchestrator):
        def __init__(self, config):
            captured["config"] = config
            super().__init__(config)

    monkeypatch.setattr(paper_run, "PolymarketCLIOrchestrator", CaptureOrchestrator)
    monkeypatch.setattr(sys, "argv", ["paper_run", "--status", "--weather"])

    paper_run.main()

    assert captured["config"].market_vertical == "weather"
    assert captured["config"].search_symbols == ["WEATHER"]
    assert captured["config"].min_volume_24h_usd == 0.0


def test_live_runner_weather_mode_requires_alpha_report(monkeypatch):
    captured = {}

    class CaptureOrchestrator(StubOrchestrator):
        def __init__(self, config):
            captured["config"] = config
            super().__init__(config)

    monkeypatch.setattr(live_run, "PolymarketCLIOrchestrator", CaptureOrchestrator)
    monkeypatch.setattr(
        sys,
        "argv",
        ["live_run", "--status", "--weather", "--weather-alpha-report", "/tmp/weather-alpha.json"],
    )

    live_run.main()

    assert captured["config"].market_vertical == "weather"
    assert captured["config"].weather_require_alpha_verification is True
    assert captured["config"].weather_alpha_report_path == "/tmp/weather-alpha.json"
    assert captured["config"].min_arb_edge_percent == 2.0
    assert captured["config"].max_position_usd == 10.0
    assert captured["config"].max_per_market_usd == 10.0
    assert captured["config"].live_max_position_usd == 10.0
    assert captured["config"].max_positions_per_direction == 64


def test_live_runner_weather_max_position_override(monkeypatch):
    captured = {}

    class CaptureOrchestrator(StubOrchestrator):
        def __init__(self, config):
            captured["config"] = config
            super().__init__(config)

    monkeypatch.setattr(live_run, "PolymarketCLIOrchestrator", CaptureOrchestrator)
    monkeypatch.setattr(
        sys,
        "argv",
        ["live_run", "--status", "--weather", "--max-position", "6"],
    )

    live_run.main()

    assert captured["config"].max_position_usd == 6.0
    assert captured["config"].max_per_market_usd == 6.0
    assert captured["config"].live_max_position_usd == 6.0


def test_live_runner_weather_confirm_aborts_before_preflight_without_release(monkeypatch):
    captured = {}

    class CaptureOrchestrator(StubOrchestrator):
        def __init__(self, config):
            captured["config"] = config
            super().__init__(config)

    monkeypatch.setattr(live_run, "PolymarketCLIOrchestrator", CaptureOrchestrator)
    monkeypatch.setattr(live_run, "PolymarketCLI", lambda _config: (_ for _ in ()).throw(AssertionError("CLI should not start")))
    monkeypatch.setattr(live_run, "run_preflight_checks", lambda _config, _cli: (_ for _ in ()).throw(AssertionError("preflight should not run")))
    monkeypatch.setattr(sys, "argv", ["live_run", "--confirm-live", "--weather"])

    with pytest.raises(SystemExit) as exc:
        live_run.main()

    assert exc.value.code == 2
    assert captured["config"].market_vertical == "weather"


def test_live_runner_preserves_default_expiry_cap_in_status_mode(monkeypatch):
    captured = {}

    class CaptureOrchestrator(StubOrchestrator):
        def __init__(self, config):
            captured["config"] = config
            super().__init__(config)

    monkeypatch.setattr(live_run, "PolymarketCLIOrchestrator", CaptureOrchestrator)
    monkeypatch.setattr(sys, "argv", ["live_run", "--status"])

    live_run.main()

    assert captured["config"].max_expiry_hours == 24.0
    assert captured["config"].min_expiry_hours is None


def test_legacy_runner_exits_with_clear_deprecation_message():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_crypto_polymarket.py"
    result = subprocess.run(
        [sys.executable, str(script_path), "--mode", "paper"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "deprecated" in result.stdout.lower()
    assert "crypto_polymarket" in result.stdout
