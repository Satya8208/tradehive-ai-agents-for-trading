"""
Central release-certificate gate for live Polymarket weather trading.

This module is the single place that decides whether weather can leave
research/replay/paper mode. It intentionally does not perform authenticated
trading actions; it only reads explicit release evidence and returns blockers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import PolymarketCLIConfig
from .weather_contracts import (
    WEATHER_RELEASE_CERTIFICATE_SCHEMA_VERSION,
    WeatherLiveEligibilityReport,
)


NON_NEGOTIABLES = [
    "market_spec_gate_passes",
    "data_freshness_gate_passes",
    "fillability_gate_passes",
    "risk_gate_passes",
    "geoblock_check_passes",
    "live_block_tests_pass_for_git_sha",
    "operator_explicitly_arms_live_mode",
]


class WeatherLiveEligibilityGate:
    def __init__(self, config: PolymarketCLIConfig):
        self.config = config

    @property
    def release_certificate_path(self) -> Path:
        explicit = str(getattr(self.config, "weather_release_certificate_path", "") or "").strip()
        if explicit:
            return Path(explicit).expanduser()
        return self.config.data_dir / "weather_live_release" / "latest_weather_release_certificate.json"

    @property
    def evidence_report_path(self) -> Path:
        return self.config.data_dir / "weather_evidence" / "latest_weather_evidence_report.json"

    def evaluate(
        self,
        *,
        evidence_report: Optional[Dict[str, Any]] = None,
        release_certificate: Optional[Dict[str, Any]] = None,
    ) -> WeatherLiveEligibilityReport:
        blockers: list[str] = []
        warnings: list[str] = []

        if getattr(self.config, "market_vertical", "crypto") != "weather":
            blockers.append("market_vertical_not_weather")

        allow_live = bool(getattr(self.config, "allow_live_weather_trading", False))
        if not allow_live:
            blockers.append("allow_live_weather_trading_false")

        evidence_payload, evidence_meta = self._load_evidence(evidence_report)
        evidence_verdict = evidence_payload.get("deployment_verdict", {}) if isinstance(evidence_payload, dict) else {}
        if not evidence_payload:
            blockers.append("weather_evidence_report_missing")
        elif not isinstance(evidence_verdict, dict):
            blockers.append("weather_evidence_deployment_verdict_missing")
        else:
            if evidence_verdict.get("accepted_for_live_weather_trading") is not True:
                blockers.append("weather_replay_not_live_accepted")
            if evidence_verdict.get("accepted_for_paper_weather_trading") is not True:
                warnings.append("weather_replay_not_paper_accepted")
            blockers.extend(str(item) for item in evidence_verdict.get("live_blockers", []) or [])
            blockers.extend(str(item) for item in evidence_verdict.get("blockers", []) or [])

        generated_at = self._parse_dt(evidence_payload.get("generated_at") if isinstance(evidence_payload, dict) else None)
        if generated_at is None and evidence_meta.get("mtime") is not None:
            generated_at = evidence_meta["mtime"]
        if generated_at is None:
            blockers.append("weather_evidence_freshness_unknown")
        else:
            age_hours = (_utc_now() - generated_at).total_seconds() / 3600.0
            evidence_meta["age_hours"] = round(age_hours, 3)
            if age_hours > 48.0:
                blockers.append("weather_evidence_report_stale")

        certificate_payload, certificate_meta = self._load_certificate(release_certificate)
        if not certificate_payload:
            blockers.append("weather_release_certificate_missing")
        else:
            blockers.extend(self._certificate_blockers(certificate_payload))

        blockers = _unique(blockers)
        warnings = _unique(warnings)
        eligible = not blockers
        status = "eligible" if eligible else "hard_blocked" if not allow_live else "blocked"

        return WeatherLiveEligibilityReport(
            status=status,
            eligible=eligible,
            allow_live_weather_trading=allow_live,
            blockers=blockers,
            warnings=warnings,
            release_certificate={
                "required": True,
                "present": bool(certificate_payload),
                "path": str(self.release_certificate_path),
                "status": certificate_payload.get("status", "missing") if certificate_payload else "missing",
                "certificate_id": certificate_payload.get("certificate_id", "") if certificate_payload else "",
                "git_sha": certificate_payload.get("git_sha", "") if certificate_payload else "",
                "issued_at": certificate_payload.get("issued_at", "") if certificate_payload else "",
                "valid_until": certificate_payload.get("valid_until", "") if certificate_payload else "",
                "operator_armed_live_mode": bool(certificate_payload.get("operator_armed_live_mode", False))
                if certificate_payload
                else False,
                "qa_gate_passed": bool(certificate_payload.get("qa_gate_passed", False)) if certificate_payload else False,
                "geoblock_check_passed": bool(certificate_payload.get("geoblock_check_passed", False))
                if certificate_payload
                else False,
                "live_block_tests_passed": bool(certificate_payload.get("live_block_tests_passed", False))
                if certificate_payload
                else False,
                "loaded_from": certificate_meta.get("loaded_from", ""),
            },
            evidence={
                "required": True,
                "present": bool(evidence_payload),
                "path": str(self.evidence_report_path),
                "generated_at": evidence_payload.get("generated_at", "") if isinstance(evidence_payload, dict) else "",
                "age_hours": evidence_meta.get("age_hours"),
                "accepted_for_live_weather_trading": bool(
                    evidence_verdict.get("accepted_for_live_weather_trading", False)
                )
                if isinstance(evidence_verdict, dict)
                else False,
                "accepted_for_paper_weather_trading": bool(
                    evidence_verdict.get("accepted_for_paper_weather_trading", False)
                )
                if isinstance(evidence_verdict, dict)
                else False,
                "loaded_from": evidence_meta.get("loaded_from", ""),
            },
            non_negotiables=list(NON_NEGOTIABLES),
        )

    def _load_evidence(self, supplied: Optional[Dict[str, Any]]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        if supplied is not None:
            return dict(supplied), {"loaded_from": "supplied"}
        return self._read_json(self.evidence_report_path)

    def _load_certificate(self, supplied: Optional[Dict[str, Any]]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        if supplied is not None:
            return dict(supplied), {"loaded_from": "supplied"}
        return self._read_json(self.release_certificate_path)

    @staticmethod
    def _read_json(path: Path) -> tuple[Dict[str, Any], Dict[str, Any]]:
        meta: Dict[str, Any] = {"loaded_from": str(path)}
        try:
            if path.exists():
                meta["mtime"] = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}, meta
        return payload if isinstance(payload, dict) else {}, meta

    def _certificate_blockers(self, payload: Dict[str, Any]) -> list[str]:
        blockers: list[str] = []
        schema = str(payload.get("schema_version") or "")
        if schema != WEATHER_RELEASE_CERTIFICATE_SCHEMA_VERSION:
            blockers.append(f"weather_release_certificate_schema_mismatch:{schema or 'missing'}")
        if str(payload.get("status") or "").strip().lower() != "approved":
            blockers.append("weather_release_certificate_not_approved")
        if not str(payload.get("certificate_id") or "").strip():
            blockers.append("weather_release_certificate_id_missing")
        if not str(payload.get("git_sha") or "").strip():
            blockers.append("weather_release_certificate_git_sha_missing")
        if not bool(payload.get("operator_armed_live_mode", False)):
            blockers.append("operator_live_mode_not_armed")
        if not bool(payload.get("qa_gate_passed", False)):
            blockers.append("release_qa_gate_not_passed")
        if not bool(payload.get("geoblock_check_passed", False)):
            blockers.append("release_geoblock_check_not_passed")
        if not bool(payload.get("live_block_tests_passed", False)):
            blockers.append("release_live_block_tests_not_passed")

        valid_until = self._parse_dt(payload.get("valid_until"))
        if valid_until is None:
            blockers.append("weather_release_certificate_valid_until_missing")
        elif valid_until <= _utc_now():
            blockers.append("weather_release_certificate_expired")

        required_checks = {str(item) for item in payload.get("required_checks", []) or []}
        for check in NON_NEGOTIABLES:
            if check not in required_checks:
                blockers.append(f"weather_release_certificate_missing_check:{check}")

        blockers.extend(str(item) for item in payload.get("blockers", []) or [])
        return blockers

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen
