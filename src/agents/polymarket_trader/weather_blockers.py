"""Typed blocker taxonomy for weather-market research and gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Tuple


WEATHER_BLOCKER_SCHEMA_VERSION = "weather_blocker_taxonomy_v1"


@dataclass(frozen=True)
class WeatherBlockerRecord:
    raw: str
    code: str
    detail: str
    category: str
    severity: str
    owner_role: str
    route: str
    live_gate_impact: str
    retryable: bool = False
    schema_version: str = WEATHER_BLOCKER_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_PREFIX_RULES: Tuple[Tuple[str, Dict[str, Any]], ...] = (
    ("allow_live_weather_trading_false", {"category": "live_safety", "severity": "P0", "owner_role": "release_gatekeeper", "route": "live_eligibility", "live_gate_impact": "blocks_live"}),
    ("weather_live_", {"category": "live_safety", "severity": "P0", "owner_role": "release_gatekeeper", "route": "live_eligibility", "live_gate_impact": "blocks_live"}),
    ("geoblock_", {"category": "live_safety", "severity": "P0", "owner_role": "release_gatekeeper", "route": "live_eligibility", "live_gate_impact": "blocks_live"}),
    ("weather_release_certificate", {"category": "live_safety", "severity": "P0", "owner_role": "release_gatekeeper", "route": "release_certificate", "live_gate_impact": "blocks_live"}),
    ("release_certificate", {"category": "live_safety", "severity": "P0", "owner_role": "release_gatekeeper", "route": "release_certificate", "live_gate_impact": "blocks_live"}),
    ("weather_evidence_report", {"category": "alpha_evidence", "severity": "P1", "owner_role": "calibration_scientist", "route": "weather_evidence_report", "live_gate_impact": "blocks_live"}),
    ("weather_feature_schema_", {"category": "schema_contract", "severity": "P1", "owner_role": "test_safety_engineer", "route": "weather_feature_packet", "live_gate_impact": "blocks_promotion"}),
    ("weather_alpha_schema_", {"category": "schema_contract", "severity": "P1", "owner_role": "test_safety_engineer", "route": "alpha_evidence_report", "live_gate_impact": "blocks_promotion"}),
    ("weather_context_", {"category": "market_spec", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "market_spec_compiler", "live_gate_impact": "blocks_paper"}),
    ("weather_source_", {"category": "weather_source_freshness", "severity": "P1", "owner_role": "meteorological_alpha_lead", "route": "source_registry", "live_gate_impact": "blocks_paper", "retryable": True}),
    ("weather_high_resolution_", {"category": "high_resolution_source", "severity": "P1", "owner_role": "meteorological_alpha_lead", "route": "high_resolution_ingest", "live_gate_impact": "blocks_promotion", "retryable": True}),
    ("weather_station_bias_", {"category": "station_calibration", "severity": "P2", "owner_role": "meteorological_alpha_lead", "route": "station_bias_catalog", "live_gate_impact": "blocks_promotion"}),
    ("station_bias_", {"category": "station_calibration", "severity": "P2", "owner_role": "meteorological_alpha_lead", "route": "station_bias_catalog", "live_gate_impact": "improves_replay_gate"}),
    ("observation_lane_", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("observation_context_", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("unsupported_market_type", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("unsupported_observation_", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("missing_threshold_rule", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("missing_upper_threshold_rule", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("missing_target_date", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("missing_station", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("missing_observation_source", {"category": "observation_eligibility", "severity": "P1", "owner_role": "meteorological_alpha_lead", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper", "retryable": True}),
    ("closed_or_expired_window", {"category": "observation_eligibility", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("future_window_not_observation_relevant", {"category": "observation_eligibility", "severity": "P2", "owner_role": "meteorological_alpha_lead", "route": "observation_pool_eligibility", "live_gate_impact": "blocks_paper"}),
    ("threshold_", {"category": "threshold_state", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "threshold_state", "live_gate_impact": "blocks_paper"}),
    ("upper_threshold_", {"category": "threshold_state", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "threshold_state", "live_gate_impact": "blocks_paper"}),
    ("observation_metric_", {"category": "threshold_state", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "threshold_state", "live_gate_impact": "blocks_paper"}),
    ("executable_", {"category": "execution_microstructure", "severity": "P1", "owner_role": "microstructure_alpha_lead", "route": "fillability_report", "live_gate_impact": "blocks_promotion", "retryable": True}),
    ("no_depth", {"category": "execution_microstructure", "severity": "P1", "owner_role": "microstructure_alpha_lead", "route": "fillability_report", "live_gate_impact": "blocks_promotion", "retryable": True}),
    ("weather_liquidity_", {"category": "execution_microstructure", "severity": "P2", "owner_role": "microstructure_alpha_lead", "route": "candidate_ranker", "live_gate_impact": "blocks_paper", "retryable": True}),
    ("weather_probability_", {"category": "alpha_probability", "severity": "P1", "owner_role": "calibration_scientist", "route": "forecast_model", "live_gate_impact": "blocks_paper"}),
    ("weather_edge_", {"category": "alpha_probability", "severity": "P2", "owner_role": "calibration_scientist", "route": "candidate_ranker", "live_gate_impact": "blocks_paper"}),
    ("weather_side_", {"category": "alpha_probability", "severity": "P1", "owner_role": "calibration_scientist", "route": "candidate_ranker", "live_gate_impact": "blocks_paper"}),
    ("weather_ai_", {"category": "ai_decision", "severity": "P2", "owner_role": "calibration_scientist", "route": "weather_ai_decision", "live_gate_impact": "blocks_paper", "retryable": True}),
    ("weather_alpha_", {"category": "alpha_evidence", "severity": "P1", "owner_role": "calibration_scientist", "route": "alpha_evidence_report", "live_gate_impact": "blocks_promotion"}),
    ("condition_id_", {"category": "market_spec", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "market_spec_compiler", "live_gate_impact": "blocks_paper"}),
    ("question_", {"category": "market_spec", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "market_spec_compiler", "live_gate_impact": "blocks_paper"}),
    ("yes_no_token_", {"category": "market_spec", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "market_spec_compiler", "live_gate_impact": "blocks_paper"}),
    ("market_end_date_", {"category": "market_spec", "severity": "P1", "owner_role": "contract_resolution_counsel", "route": "market_spec_compiler", "live_gate_impact": "blocks_paper"}),
    ("market_price_", {"category": "market_spec", "severity": "P1", "owner_role": "microstructure_alpha_lead", "route": "market_spec_compiler", "live_gate_impact": "blocks_paper"}),
)


def classify_weather_blocker(blocker: Any) -> WeatherBlockerRecord:
    raw = str(blocker or "").strip()
    code, detail = (raw.split(":", 1) + [""])[:2] if ":" in raw else (raw, "")
    rule = _rule_for(code)
    return WeatherBlockerRecord(
        raw=raw,
        code=code or "unknown_blocker",
        detail=detail,
        category=rule["category"],
        severity=rule["severity"],
        owner_role=rule["owner_role"],
        route=rule["route"],
        live_gate_impact=rule["live_gate_impact"],
        retryable=bool(rule.get("retryable", False)),
    )


def blockers_to_records(blockers: Iterable[Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen = set()
    for blocker in blockers or []:
        text = str(blocker or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        records.append(classify_weather_blocker(text).to_dict())
    return records


def blocker_summary(blockers: Iterable[Any]) -> Dict[str, Any]:
    records = blockers_to_records(blockers)
    return {
        "schema_version": WEATHER_BLOCKER_SCHEMA_VERSION,
        "count": len(records),
        "by_category": _counts(records, "category"),
        "by_severity": _counts(records, "severity"),
        "by_owner_role": _counts(records, "owner_role"),
        "records": records,
    }


def _rule_for(code: str) -> Dict[str, Any]:
    for prefix, rule in _PREFIX_RULES:
        if code.startswith(prefix):
            return rule
    if code.endswith("_missing"):
        return {"category": "evidence_gap", "severity": "P2", "owner_role": "evidence_lineage_reviewer", "route": "evidence_store", "live_gate_impact": "improves_replay_gate", "retryable": True}
    return {"category": "uncategorized", "severity": "P2", "owner_role": "system_architecture_reviewer", "route": "review_backlog", "live_gate_impact": "review_required"}


def _counts(records: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts
