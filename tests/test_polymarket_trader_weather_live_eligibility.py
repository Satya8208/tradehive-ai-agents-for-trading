import json
from datetime import datetime, timedelta, timezone

import pytest

from src.agents.polymarket_trader.config import ExecutionMode, get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.weather_contracts import (
    WEATHER_MARKET_SPEC_SCHEMA_VERSION,
    WEATHER_RELEASE_CERTIFICATE_SCHEMA_VERSION,
)
from src.agents.polymarket_trader.weather_live_eligibility import NON_NEGOTIABLES, WeatherLiveEligibilityGate
from src.agents.polymarket_trader.weather_market_spec_compiler import WeatherMarketSpecCompiler


def _market(question="Will the high temperature in New York City exceed 85°F on May 8?"):
    return CLIMarket(
        condition_id="weather-spec-1",
        question=question,
        symbol="WEATHER",
        yes_token_id="yes-token",
        no_token_id="no-token",
        yes_price=0.43,
        no_price=0.57,
        liquidity=1000.0,
        volume_24h=100.0,
        end_date=datetime.utcnow() + timedelta(hours=4),
        slug="weather-spec",
    )


def _accepted_evidence():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "weather_evidence_report_v1",
        "generated_at": now,
        "deployment_verdict": {
            "accepted_for_live_weather_trading": True,
            "accepted_for_paper_weather_trading": True,
            "blockers": [],
            "live_blockers": [],
        },
    }


def _valid_certificate():
    return {
        "schema_version": WEATHER_RELEASE_CERTIFICATE_SCHEMA_VERSION,
        "certificate_id": "cert-weather-1",
        "status": "approved",
        "git_sha": "abc123",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "valid_until": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
        "operator_armed_live_mode": True,
        "qa_gate_passed": True,
        "geoblock_check_passed": True,
        "live_block_tests_passed": True,
        "required_checks": list(NON_NEGOTIABLES),
        "blockers": [],
    }


def test_weather_market_spec_compiler_creates_canonical_fail_closed_contract():
    spec = WeatherMarketSpecCompiler().compile(_market())

    assert spec.schema_version == WEATHER_MARKET_SPEC_SCHEMA_VERSION
    assert spec.status == "ok"
    assert spec.market_id == "weather-spec-1"
    assert spec.yes_token_id == "yes-token"
    assert spec.no_token_id == "no-token"
    assert spec.resolution_station == "KNYC"
    assert "observation_lag_station_threshold" in spec.alpha_lanes
    assert spec.settlement_source == "station_threshold_requires_official_resolution_check"

    broken = WeatherMarketSpecCompiler().compile(
        CLIMarket(
            condition_id="",
            question="Will Atlantis temperature be above 80F?",
            symbol="WEATHER",
            yes_token_id="same",
            no_token_id="same",
            yes_price=1.4,
            no_price=0.2,
            liquidity=1.0,
            volume_24h=0.0,
            end_date=None,
        )
    )

    assert broken.status == "fail_closed"
    assert "condition_id_missing" in broken.blockers
    assert "yes_no_token_mapping_ambiguous" in broken.blockers
    assert "market_end_date_missing" in broken.blockers
    assert "market_price_missing" in broken.blockers
    broken_payload = broken.to_dict()
    assert broken_payload["blocker_summary"]["by_category"]["market_spec"] >= 3
    assert any(record["code"] == "market_price_missing" for record in broken_payload["blocker_records"])


def test_weather_live_eligibility_defaults_to_hard_blocked_without_certificate(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm",
    )

    report = WeatherLiveEligibilityGate(cfg).evaluate()

    assert report.eligible is False
    assert report.status == "hard_blocked"
    assert "allow_live_weather_trading_false" in report.blockers
    assert "weather_release_certificate_missing" in report.blockers
    assert "weather_evidence_report_missing" in report.blockers
    assert report.to_dict()["blocker_summary"]["by_category"]["live_safety"] >= 2
    rendered = str(report.to_dict()).lower()
    assert "private_key" not in rendered


def test_weather_live_eligibility_requires_operator_allow_flag_even_with_clean_release(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        _data_dir_override=tmp_path / "pm",
    )

    report = WeatherLiveEligibilityGate(cfg).evaluate(
        evidence_report=_accepted_evidence(),
        release_certificate=_valid_certificate(),
    )

    assert report.eligible is False
    assert "allow_live_weather_trading_false" in report.blockers
    assert report.release_certificate["present"] is True


def test_weather_live_eligibility_can_only_pass_with_explicit_valid_certificate(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        allow_live_weather_trading=True,
        _data_dir_override=tmp_path / "pm",
    )

    report = WeatherLiveEligibilityGate(cfg).evaluate(
        evidence_report=_accepted_evidence(),
        release_certificate=_valid_certificate(),
    )

    assert report.eligible is True
    assert report.status == "eligible"
    assert report.blockers == []
    assert report.release_certificate["status"] == "approved"


def test_weather_live_eligibility_reads_certificate_and_evidence_from_disk(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        allow_live_weather_trading=True,
        _data_dir_override=tmp_path / "pm",
    )
    evidence_path = cfg.data_dir / "weather_evidence" / "latest_weather_evidence_report.json"
    cert_path = cfg.data_dir / "weather_live_release" / "latest_weather_release_certificate.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(_accepted_evidence()), encoding="utf-8")
    cert_path.write_text(json.dumps(_valid_certificate()), encoding="utf-8")

    report = WeatherLiveEligibilityGate(cfg).evaluate()

    assert report.eligible is True
    assert report.evidence["loaded_from"] == str(evidence_path)
    assert report.release_certificate["loaded_from"] == str(cert_path)


def test_weather_live_eligibility_blocks_incomplete_certificate(tmp_path):
    cfg = get_polymarket_cli_config(
        execution_mode=ExecutionMode.LIVE,
        market_vertical="weather",
        allow_live_weather_trading=True,
        _data_dir_override=tmp_path / "pm",
    )
    certificate = _valid_certificate()
    certificate["required_checks"] = ["market_spec_gate_passes"]
    certificate["geoblock_check_passed"] = False

    report = WeatherLiveEligibilityGate(cfg).evaluate(
        evidence_report=_accepted_evidence(),
        release_certificate=certificate,
    )

    assert report.eligible is False
    assert "release_geoblock_check_not_passed" in report.blockers
    assert "weather_release_certificate_missing_check:geoblock_check_passes" in report.blockers
