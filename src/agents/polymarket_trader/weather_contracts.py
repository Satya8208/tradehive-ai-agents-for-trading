"""
Shared contracts for Polymarket weather trading.

These objects are intentionally plain dataclasses so the research, paper, and
live-gated lanes can exchange the same source-stamped payloads without pulling
in the execution layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .weather_blockers import blocker_summary, blockers_to_records


FEATURE_SCHEMA_VERSION = "weather_feature_packet_v1"
FORECAST_ENGINE_SCHEMA_VERSION = "weather_forecast_model_packet_v1"
AI_DECISION_SCHEMA_VERSION = "weather_ai_decision_v1"
WEATHER_MARKET_SPEC_SCHEMA_VERSION = "weather_market_spec_v1"
WEATHER_RELEASE_CERTIFICATE_SCHEMA_VERSION = "weather_release_certificate_v1"
WEATHER_LIVE_ELIGIBILITY_SCHEMA_VERSION = "weather_live_eligibility_report_v1"


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


@dataclass(frozen=True)
class WeatherResolutionTarget:
    market_id: str
    location_name: str
    latitude: float
    longitude: float
    resolution_station: str
    station_name: str = ""
    station_type: str = "grid"
    metar_station: str = ""
    nexrad_station: str = ""
    source: str = "manual_station_map"
    bias_correction_f: float = 0.0
    quality_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "ok" if not self.blockers else "fail_closed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherMarketSpec:
    market_id: str
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    contract_type: str
    metric: str
    operator: str
    threshold: Optional[float]
    upper_threshold: Optional[float]
    threshold_unit: str
    target_date: str
    location_name: str
    resolution_station: str
    station_type: str
    region: str
    horizon_bucket: str
    alpha_lanes: List[str]
    source_applicability: List[str]
    settlement_source: str = "contract_text_unverified"
    schema_version: str = WEATHER_MARKET_SPEC_SCHEMA_VERSION
    market_url: str = ""
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)

    @property
    def status(self) -> str:
        return "ok" if not self.blockers else "fail_closed"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


@dataclass(frozen=True)
class WeatherReleaseCertificate:
    certificate_id: str
    status: str
    git_sha: str
    issued_at: str
    valid_until: str
    operator: str = ""
    operator_armed_live_mode: bool = False
    qa_gate_passed: bool = False
    geoblock_check_passed: bool = False
    live_block_tests_passed: bool = False
    evidence_report_path: str = ""
    notes: str = ""
    required_checks: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    schema_version: str = WEATHER_RELEASE_CERTIFICATE_SCHEMA_VERSION

    @property
    def accepted(self) -> bool:
        return (
            self.status == "approved"
            and self.operator_armed_live_mode
            and self.qa_gate_passed
            and self.geoblock_check_passed
            and self.live_block_tests_passed
            and not self.blockers
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["accepted"] = self.accepted
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


@dataclass(frozen=True)
class WeatherLiveEligibilityReport:
    status: str
    eligible: bool
    allow_live_weather_trading: bool
    blockers: List[str]
    warnings: List[str] = field(default_factory=list)
    release_certificate: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    non_negotiables: List[str] = field(default_factory=list)
    schema_version: str = WEATHER_LIVE_ELIGIBILITY_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


@dataclass(frozen=True)
class WeatherForecastSnapshot:
    source_id: str
    source_family: str
    status: str
    generated_at: str
    asof_time: str
    run_id: str = ""
    source_age_minutes: Optional[float] = None
    forecast_metrics: Dict[str, Any] = field(default_factory=dict)
    probability: Optional[float] = None
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherAIDecision:
    status: str
    provider: str
    model_name: str
    p_yes: Optional[float]
    side: str
    strategy_lane: str
    confidence: float
    uncertainty_band: Dict[str, Optional[float]] = field(default_factory=dict)
    trade_thesis: str = ""
    veto_reasons: List[str] = field(default_factory=list)
    data_quality: str = "unknown"
    recommended_size_usd: float = 0.0
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    raw_response: str = ""
    schema_version: str = AI_DECISION_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)

    @property
    def usable_for_paper(self) -> bool:
        return self.status == "ok" and not self.blockers and self.p_yes is not None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["usable_for_paper"] = self.usable_for_paper
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


@dataclass(frozen=True)
class WeatherFeaturePacket:
    market_id: str
    feature_schema_version: str
    resolution_target: WeatherResolutionTarget
    selected_source_id: str
    selected_source_family: str
    forecast_snapshots: List[WeatherForecastSnapshot]
    model_probability: Optional[float]
    market_probability: float
    edge_percent: float
    confidence: float
    recommended_side: str
    edge_reason_flags: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    station_bias: Dict[str, Any] = field(default_factory=dict)
    latency_signals: Dict[str, Any] = field(default_factory=dict)
    run_lag_signals: Dict[str, Any] = field(default_factory=dict)
    model_update_events: List[Dict[str, Any]] = field(default_factory=list)
    high_resolution_sources: List[Dict[str, Any]] = field(default_factory=list)
    forecast_model_packet: Dict[str, Any] = field(default_factory=dict)
    ai_decision: Dict[str, Any] = field(default_factory=dict)
    market_spec: Dict[str, Any] = field(default_factory=dict)
    market_tape_snapshot: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: Dict[str, Any] = field(default_factory=dict)
    raw_forecast_metrics: Dict[str, Any] = field(default_factory=dict)
    forecast_adjustments: Dict[str, Any] = field(default_factory=dict)
    asof_time: str = field(default_factory=utc_now_iso)
    generated_at: str = field(default_factory=utc_now_iso)

    @property
    def status(self) -> str:
        return "ok" if not self.blockers else "fail_closed"

    @property
    def source_statuses(self) -> Dict[str, str]:
        statuses = {"station_mapper": self.resolution_target.status}
        statuses.update({snapshot.source_id: snapshot.status for snapshot in self.forecast_snapshots})
        return statuses

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "feature_schema_version": self.feature_schema_version,
            "resolution_target": self.resolution_target.to_dict(),
            "selected_source_id": self.selected_source_id,
            "selected_source_family": self.selected_source_family,
            "forecast_snapshots": [snapshot.to_dict() for snapshot in self.forecast_snapshots],
            "source_statuses": self.source_statuses,
            "model_probability": self.model_probability,
            "market_probability": self.market_probability,
            "edge_percent": self.edge_percent,
            "confidence": self.confidence,
            "recommended_side": self.recommended_side,
            "edge_reason_flags": list(self.edge_reason_flags),
            "quality_flags": list(self.quality_flags),
            "blockers": list(self.blockers),
            "station_bias": dict(self.station_bias),
            "latency_signals": dict(self.latency_signals),
            "run_lag_signals": dict(self.run_lag_signals),
            "model_update_events": [dict(item) for item in self.model_update_events],
            "high_resolution_sources": [dict(item) for item in self.high_resolution_sources],
            "forecast_model_packet": dict(self.forecast_model_packet),
            "ai_decision": dict(self.ai_decision),
            "market_spec": dict(self.market_spec),
            "market_tape_snapshot": dict(self.market_tape_snapshot),
            "evidence_refs": dict(self.evidence_refs),
            "raw_forecast_metrics": dict(self.raw_forecast_metrics),
            "forecast_adjustments": dict(self.forecast_adjustments),
            "status": self.status,
            "asof_time": self.asof_time,
            "generated_at": self.generated_at,
        }

    def context_extensions(self) -> Dict[str, Any]:
        return {
            "feature_schema_version": self.feature_schema_version,
            "station_mapping": self.resolution_target.to_dict(),
            "forecast_snapshots": [snapshot.to_dict() for snapshot in self.forecast_snapshots],
            "source_statuses": self.source_statuses,
            "selected_source_id": self.selected_source_id,
            "selected_source_family": self.selected_source_family,
            "edge_reason_flags": list(self.edge_reason_flags),
            "quality_flags": list(self.quality_flags),
            "feature_blockers": list(self.blockers),
            "station_bias": dict(self.station_bias),
            "latency_signals": dict(self.latency_signals),
            "run_lag_signals": dict(self.run_lag_signals),
            "model_update_events": [dict(item) for item in self.model_update_events],
            "high_resolution_sources": [dict(item) for item in self.high_resolution_sources],
            "forecast_model_packet": dict(self.forecast_model_packet),
            "ai_decision": dict(self.ai_decision),
            "market_spec": dict(self.market_spec),
            "market_tape_snapshot": dict(self.market_tape_snapshot),
            "evidence_refs": dict(self.evidence_refs),
            "raw_forecast_metrics": dict(self.raw_forecast_metrics),
            "forecast_adjustments": dict(self.forecast_adjustments),
            "asof_time": self.asof_time,
            "feature_packet": self.to_dict(),
        }


@dataclass(frozen=True)
class WeatherCandidate:
    market_id: str
    side: str
    model_probability: float
    market_probability: float
    edge_percent: float
    confidence: float
    score: float
    size_usd: float
    limit_price: float
    edge_reason_flags: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    station_bias: Dict[str, Any] = field(default_factory=dict)
    latency_signals: Dict[str, Any] = field(default_factory=dict)
    model_update_events: List[Dict[str, Any]] = field(default_factory=list)
    high_resolution_sources: List[Dict[str, Any]] = field(default_factory=list)
    forecast_model_packet: Dict[str, Any] = field(default_factory=dict)
    ai_decision: Dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return not self.blockers

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["accepted"] = self.accepted
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


@dataclass(frozen=True)
class WeatherGateVerdict:
    accepted: bool
    phase: str
    reason: str
    blockers: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload
