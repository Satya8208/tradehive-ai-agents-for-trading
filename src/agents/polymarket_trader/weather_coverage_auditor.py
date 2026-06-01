"""Coverage funnel audits for weather alpha lanes."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from .weather_blockers import blocker_summary


WEATHER_COVERAGE_AUDIT_SCHEMA_VERSION = "weather_coverage_audit_v1"


class WeatherCoverageAuditor:
    """Turn weather scan counts into an explicit proof/disproof funnel."""

    def audit_known_outcome(self, report: Dict[str, Any]) -> Dict[str, Any]:
        stages = self._known_outcome_stages(report)
        blocker_counts = self._merged_blocker_counts(report)
        top_blockers = self._top_blockers(blocker_counts)
        bottleneck = self._bottleneck(stages)
        return {
            "schema_version": WEATHER_COVERAGE_AUDIT_SCHEMA_VERSION,
            "lane": "known_outcome_observation_lag",
            "funnel": stages,
            "bottleneck_stage": bottleneck,
            "top_blockers": top_blockers,
            "blocker_summary": blocker_summary(blocker_counts.keys() if isinstance(blocker_counts, dict) else []),
            "verdict": self._verdict(report, bottleneck, top_blockers),
            "next_actions": self._next_actions(bottleneck, top_blockers),
        }

    @staticmethod
    def _known_outcome_stages(report: Dict[str, Any]) -> List[Dict[str, Any]]:
        markets = _safe_int(report.get("markets_scanned"))
        routed = _safe_int(report.get("routed_markets"))
        eligibility = report.get("observation_eligibility") or {}
        if isinstance(eligibility, dict) and "eligible_count" in eligibility:
            eligible = _safe_int(eligibility.get("eligible_count"))
        else:
            eligible = _safe_int(report.get("observation_eligible_count") or report.get("observation_pool_candidates"))
        pool = _safe_int(report.get("observation_pool_candidates"))
        selected = _safe_int(report.get("observation_lane_candidates"))
        evaluated = _safe_int(report.get("evaluated_candidates"))
        accepted = _safe_int(report.get("candidate_count"))
        return [
            _stage("scan_to_router", markets, routed, "Markets surviving weather router classification."),
            _stage("router_to_observation_eligible", routed, eligible, "Routed markets with station, source, threshold, and near-window observation eligibility."),
            _stage("observation_eligible_to_pool_selection", eligible, pool, "Eligible observation-lag markets retained by pool size and diversity rules."),
            _stage("observation_pool_to_orderbook_selection", pool, selected, "Observation candidates selected for orderbook budget."),
            _stage("orderbook_selection_to_evaluation", selected, evaluated, "Selected markets with enough observation and tape context to evaluate."),
            _stage("evaluation_to_accepted_paper", evaluated, accepted, "Evaluated markets that cleared threshold, depth, and cost-buffer gates."),
        ]

    @staticmethod
    def _merged_blocker_counts(report: Dict[str, Any]) -> Dict[str, int]:
        counts: Counter[str] = Counter()
        if not isinstance(report, dict):
            return {}
        for source in (report.get("blocker_counts"), (report.get("observation_eligibility") or {}).get("blocker_counts")):
            if not isinstance(source, dict):
                continue
            for blocker, count in source.items():
                counts[str(blocker)] += _safe_int(count)
        return dict(sorted(counts.items()))

    @staticmethod
    def _bottleneck(stages: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        rows = list(stages)
        if not rows:
            return {"stage": "none", "drop_count": 0, "drop_rate": 0.0}
        return max(rows, key=lambda row: (float(row.get("drop_rate") or 0.0), int(row.get("drop_count") or 0)))

    @staticmethod
    def _top_blockers(blocker_counts: Any, limit: int = 8) -> List[Dict[str, Any]]:
        if not isinstance(blocker_counts, dict):
            return []
        rows = sorted(blocker_counts.items(), key=lambda item: _safe_int(item[1]), reverse=True)
        return [{"blocker": str(key), "count": _safe_int(value)} for key, value in rows[:limit]]

    @staticmethod
    def _verdict(report: Dict[str, Any], bottleneck: Dict[str, Any], top_blockers: List[Dict[str, Any]]) -> str:
        routed = _safe_int(report.get("routed_markets"))
        eligibility = report.get("observation_eligibility") or {}
        eligible = _safe_int(eligibility.get("eligible_count") if isinstance(eligibility, dict) else None)
        pool = _safe_int(report.get("observation_pool_candidates"))
        evaluated = _safe_int(report.get("evaluated_candidates"))
        accepted = _safe_int(report.get("candidate_count"))
        blocker_names = {row["blocker"] for row in top_blockers}
        if routed > 0 and isinstance(eligibility, dict) and "eligible_count" in eligibility and eligible <= 0:
            return "observation_eligibility_blocked"
        if eligible > 0 and pool <= 0:
            return "observation_pool_selection_blocked"
        if evaluated <= 0:
            return "observation_context_or_orderbook_selection_needed"
        if accepted <= 0:
            return "no_paper_candidates_survived_current_gates"
        if accepted < max(3, int(evaluated * 0.05)):
            if {"executable_price_missing", "executable_fill_below_minimum"} & blocker_names:
                return "paper_candidates_exist_but_depth_is_primary_bottleneck"
            if "threshold_not_known_from_observations" in blocker_names:
                return "paper_candidates_exist_but_threshold_proof_is_primary_bottleneck"
            return "paper_candidates_exist_but_sample_not_promotable"
        if str(bottleneck.get("stage")) == "evaluation_to_accepted_paper":
            return "accepted_candidates_need_disproof_backlog_review"
        return "coverage_sufficient_for_next_replay_check"

    @staticmethod
    def _next_actions(bottleneck: Dict[str, Any], top_blockers: List[Dict[str, Any]]) -> List[str]:
        blockers = {row["blocker"] for row in top_blockers}
        actions: List[str] = []
        if str(bottleneck.get("stage")) == "router_to_observation_eligible":
            if _has_prefix(blockers, "observation_lane_missing"):
                actions.append("Repair router/classifier coverage for near-window station threshold markets before spending orderbook budget.")
            if _has_prefix(blockers, "missing_station", "missing_observation_source", "missing_target_date", "missing_threshold_rule"):
                actions.append("Build observation context compiler records with station, official source, local date, and threshold rule per market.")
            if _has_prefix(blockers, "future_window_not_observation_relevant", "closed_or_expired_window"):
                actions.append("Split future and expired contracts out of the known-outcome lane and route them to forecast/replay lanes.")
        if {"executable_price_missing", "executable_fill_below_minimum", "no_depth"} & blockers:
            actions.append("Build fillability subtype report with book age, hash, walked price, and positive-edge capacity.")
        if {"threshold_not_known_from_observations", "threshold_boundary_rounding_risk"} & blockers:
            actions.append("Persist threshold-state disproof rows with station, observed value, margin, and rounding reason.")
        if str(bottleneck.get("stage")) == "observation_pool_to_orderbook_selection":
            actions.append("Tune orderbook budget selection by proof-backed station/date diversity.")
        if not actions:
            actions.append("Review rejected candidates and promote only evidence-backed disproof categories.")
        return actions


def _stage(stage: str, input_count: int, output_count: int, description: str) -> Dict[str, Any]:
    drop = max(0, input_count - output_count)
    pass_rate: Optional[float] = round(output_count / input_count, 6) if input_count > 0 else None
    return {
        "stage": stage,
        "description": description,
        "input_count": input_count,
        "output_count": output_count,
        "drop_count": drop,
        "drop_rate": round(drop / input_count, 6) if input_count > 0 else 0.0,
        "pass_rate": pass_rate,
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _has_prefix(blockers: Iterable[str], *prefixes: str) -> bool:
    return any(str(blocker).startswith(prefix) for blocker in blockers for prefix in prefixes)
