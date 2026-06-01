"""
Weather-specific gate enforcement for paper/live promotion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .config import ExecutionMode, PolymarketCLIConfig
from .models import CLIMarket
from .weather_blockers import blocker_summary, blockers_to_records
from .weather_contracts import FEATURE_SCHEMA_VERSION, WeatherCandidate, WeatherGateVerdict
from .weather_live_eligibility import WeatherLiveEligibilityGate


class WeatherGate:
    def __init__(self, config: PolymarketCLIConfig):
        self.config = config

    def evaluate(
        self,
        market: CLIMarket,
        context: Dict[str, Any],
        candidate: Optional[WeatherCandidate],
    ) -> WeatherGateVerdict:
        blockers = []
        details: Dict[str, Any] = {
            "market_id": str(getattr(market, "condition_id", "")),
            "execution_mode": self.config.execution_mode.value,
        }

        if context.get("status") != "ok":
            blockers.append(f"weather_context_{context.get('status', 'missing')}")

        schema = str(context.get("feature_schema_version", "") or "")
        if schema and schema != FEATURE_SCHEMA_VERSION:
            blockers.append(f"weather_feature_schema_mismatch:{schema}")
        elif not schema:
            blockers.append("weather_feature_schema_missing")

        source_statuses = context.get("source_statuses", {})
        if not isinstance(source_statuses, dict) or not source_statuses:
            blockers.append("weather_source_statuses_missing")
        else:
            for source_id, status in source_statuses.items():
                if str(status) in {"unavailable", "fail_closed", "stale"}:
                    blockers.append(f"weather_source_{source_id}_{status}")

        for snapshot in context.get("forecast_snapshots", []) or []:
            if not isinstance(snapshot, dict):
                continue
            age = self._safe_float(snapshot.get("source_age_minutes"))
            max_age = self._safe_float(getattr(self.config, "weather_max_selected_source_age_minutes", 180.0))
            if age is not None and max_age is not None and age > max_age:
                blockers.append(f"weather_source_age_exceeds_max:{snapshot.get('source_id', 'unknown')}")

        if bool(getattr(self.config, "weather_require_station_bias_validation", False)):
            station_bias = context.get("station_bias", {})
            status = str(station_bias.get("status") if isinstance(station_bias, dict) else "")
            if status not in {"validated", "manual_override"}:
                blockers.append(f"weather_station_bias_not_validated:{status or 'missing'}")

        if bool(getattr(self.config, "weather_require_high_resolution_confirmation", False)):
            blockers.extend(self._high_resolution_blockers(context))

        if candidate is None:
            blockers.append("weather_candidate_missing")
        else:
            details["candidate"] = candidate.to_dict()
            blockers.extend(candidate.blockers)

        if bool(getattr(self.config, "weather_require_alpha_verification", False)):
            blockers.extend(self._alpha_report_blockers(context, candidate))

        if self.config.execution_mode == ExecutionMode.LIVE:
            blockers.append("weather_live_requires_preflight_and_manual_enablement")
            live_report = WeatherLiveEligibilityGate(self.config).evaluate()
            details["live_eligibility"] = live_report.to_dict()
            blockers.extend(live_report.blockers)

        unique_blockers = []
        for blocker in blockers:
            text = str(blocker or "").strip()
            if text and text not in unique_blockers:
                unique_blockers.append(text)

        if unique_blockers:
            details["blocker_records"] = blockers_to_records(unique_blockers)
            details["blocker_summary"] = blocker_summary(unique_blockers)
            return WeatherGateVerdict(
                accepted=False,
                phase="weather_gate",
                reason=unique_blockers[0],
                blockers=unique_blockers,
                details=details,
            )
        return WeatherGateVerdict(
            accepted=True,
            phase="weather_gate",
            reason="ok",
            blockers=[],
            details=details,
        )

    def _alpha_report_blockers(
        self,
        context: Dict[str, Any],
        candidate: Optional[WeatherCandidate],
    ) -> list[str]:
        path = self._alpha_report_path()
        if not path.exists():
            return [f"weather_alpha_report_missing:{path}"]
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"weather_alpha_report_invalid:{type(exc).__name__}"]
        if not isinstance(report, dict):
            return ["weather_alpha_report_invalid:shape"]

        verdict = report.get("deployment_verdict", {})
        if not isinstance(verdict, dict):
            return ["weather_alpha_report_invalid:deployment_verdict"]
        blockers = []
        if not verdict.get("accepted_for_live_weather_trading", False):
            report_blockers = ",".join(str(item) for item in verdict.get("blockers", [])[:3])
            blockers.append(f"weather_alpha_not_accepted:{report_blockers}")

        report_schema = str(
            report.get("feature_schema_version")
            or verdict.get("feature_schema_version")
            or verdict.get("accepted_feature_schema_version")
            or ""
        )
        if report_schema != FEATURE_SCHEMA_VERSION:
            blockers.append(f"weather_alpha_schema_mismatch:{report_schema or 'missing'}")

        selected_family = str(context.get("selected_source_family", "") or "")
        validated_families = report.get("validated_source_families") or verdict.get("validated_source_families") or []
        if validated_families and selected_family and selected_family not in {str(item) for item in validated_families}:
            blockers.append(f"weather_alpha_source_family_mismatch:{selected_family}")

        min_gap = self._safe_float(
            report.get("validated_min_probability_gap")
            or verdict.get("validated_min_probability_gap")
            or report.get("min_edge_gap")
        )
        if candidate is not None and min_gap is not None:
            if abs(float(candidate.edge_percent or 0.0)) / 100.0 < min_gap:
                blockers.append("weather_alpha_edge_below_validated_gap")
        return blockers

    @staticmethod
    def _high_resolution_blockers(context: Dict[str, Any]) -> list[str]:
        manifests = context.get("high_resolution_sources", [])
        if not isinstance(manifests, list) or not manifests:
            return ["weather_high_resolution_sources_missing"]
        blockers: list[str] = []
        usable = 0
        for manifest in manifests:
            if not isinstance(manifest, dict):
                continue
            source_id = str(manifest.get("source_id") or "unknown")
            status = str(manifest.get("status") or "")
            if status == "live_safe" and not manifest.get("parser_required", True):
                usable += 1
                continue
            if status in {"not_applicable", "unavailable", "stale"}:
                blockers.append(f"weather_high_resolution_{status}:{source_id}")
            elif status == "parser_required" or manifest.get("parser_required", False):
                blockers.append(f"weather_high_resolution_parser_required:{source_id}")
        if usable <= 0 and not blockers:
            blockers.append("weather_high_resolution_confirmation_missing")
        return blockers

    def _alpha_report_path(self) -> Path:
        report_path = str(getattr(self.config, "weather_alpha_report_path", "") or "").strip()
        if report_path:
            return Path(report_path)
        return self.config.data_dir / "weather_alpha" / "latest_weather_alpha_report.json"

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
