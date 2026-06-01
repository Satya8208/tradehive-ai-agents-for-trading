"""
Resolved weather-market alpha research for Polymarket.

This module tests the weather forecast heuristic against real resolved
Polymarket markets and historical CLOB prices. It does not infer winners from
weather data; labels come from unambiguous Polymarket outcome prices.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests
from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .models import CLIMarket
from .weather_contracts import FEATURE_SCHEMA_VERSION
from .weather_edge_features import WeatherHighResolutionSourceBuilder, WeatherStationBiasResolver
from .weather_alpha_model import WeatherAlphaCalibrationEvaluator
from .weather_price_history import WeatherPricePoint, fetch_yes_price_points_near_batch
from .weather_signals import WeatherDataSignals, WeatherLocation, WeatherMarketParse


GAMMA_API = "https://gamma-api.polymarket.com"
PREVIOUS_RUNS_API = "https://previous-runs-api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_API = "https://historical-forecast-api.open-meteo.com/v1/forecast"


@dataclass
class WeatherAlphaRecord:
    market_id: str
    question: str
    slug: str
    end_date: str
    target_date: str
    location: str
    metric: str
    operator: str
    threshold: Optional[float]
    upper_threshold: Optional[float]
    lead_days: int
    asof_time: str
    yes_price: float
    model_probability: float
    edge: float
    recommended_side: str
    side_price: float
    yes_resolved: bool
    selected_win: bool
    pnl_per_usd: float
    price_source: str
    forecast_source: str
    forecast_metrics: Dict[str, Any]
    clob_price_age_hours: float = 0.0
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    station_mapping: Dict[str, Any] = field(default_factory=dict)
    source_statuses: Dict[str, str] = field(default_factory=dict)
    station_bias: Dict[str, Any] = field(default_factory=dict)
    high_resolution_sources: List[Dict[str, Any]] = field(default_factory=list)
    latency_signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherAlphaBacktester:
    """Build and score a resolved-weather benchmark with real market data."""

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        session: Optional[requests.Session] = None,
        output_dir: Optional[Path] = None,
    ):
        self.config = config or PolymarketCLIConfig(
            execution_mode=ExecutionMode.DRY_RUN,
            market_vertical="weather",
            search_symbols=["WEATHER"],
        )
        self.session = session or requests.Session()
        self.signals = WeatherDataSignals(self.config, session=self.session)
        self.output_dir = Path(output_dir) if output_dir else self.config.data_dir / "weather_alpha"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.skip_reasons: Counter[str] = Counter()
        self._previous_runs_cache: Dict[str, Dict[str, Any]] = {}
        self._historical_forecast_cache: Dict[str, Dict[str, Any]] = {}
        self.station_bias_resolver = WeatherStationBiasResolver(
            getattr(self.config, "weather_station_bias_path", "") or None
        )
        self.high_resolution_builder = WeatherHighResolutionSourceBuilder(
            cache_dir=getattr(self.config, "weather_high_resolution_cache_dir", "") or None,
            allow_latest_fallback=False,
        )

    def run(
        self,
        max_events: int = 80,
        max_markets: int = 250,
        min_volume: float = 0.0,
        lead_days: int = 1,
        past_days: int = 7,
        min_edge_gap: float = 0.08,
        min_records: int = 30,
        min_candidates: int = 5,
        fetch_prices: bool = True,
        forecast_source: str = "previous_runs",
    ) -> Dict[str, Any]:
        records = self.build_dataset(
            max_events=max_events,
            max_markets=max_markets,
            min_volume=min_volume,
            lead_days=lead_days,
            past_days=past_days,
            fetch_prices=fetch_prices,
            forecast_source=forecast_source,
        )
        report = self.score_records(
            records,
            min_edge_gap=min_edge_gap,
            min_records=min_records,
            min_candidates=min_candidates,
        )
        self.write_artifacts(records, report)
        return report

    def build_dataset(
        self,
        max_events: int,
        max_markets: int,
        min_volume: float,
        lead_days: int,
        past_days: int,
        fetch_prices: bool = True,
        forecast_source: str = "previous_runs",
    ) -> List[WeatherAlphaRecord]:
        self.skip_reasons.clear()
        records: List[WeatherAlphaRecord] = []
        seen_markets: set[str] = set()
        events = self.fetch_resolved_weather_events(max_events=max_events)
        today = self._reference_today(events)

        for event in events:
            event_price_cache = self._event_yes_price_cache(event, lead_days) if fetch_prices else {}
            for raw_market in event.get("markets", []) or []:
                if len(records) >= max_markets:
                    return records

                volume = self._safe_float(
                    raw_market.get("volumeNum", raw_market.get("volume", event.get("volume", 0.0))),
                    0.0,
                )
                if volume < min_volume:
                    self.skip_reasons["low_volume"] += 1
                    continue

                yes_resolved = self.parse_yes_resolution(raw_market)
                if yes_resolved is None:
                    self.skip_reasons["ambiguous_resolution"] += 1
                    continue

                market = self._market_from_gamma(raw_market, event)
                if not market:
                    self.skip_reasons["invalid_market_shape"] += 1
                    continue
                if market.condition_id in seen_markets:
                    self.skip_reasons["duplicate_market"] += 1
                    continue
                seen_markets.add(market.condition_id)

                parsed = self.signals.parse_market(market)
                skip_reason = self._parse_skip_reason(parsed)
                if skip_reason:
                    self.skip_reasons[skip_reason] += 1
                    continue
                if parsed.target_date is None:
                    self.skip_reasons["missing_target_date"] += 1
                    continue
                source_name = self._normalize_forecast_source(forecast_source)
                if source_name == "previous_runs" and parsed.target_date < today - timedelta(days=max(1, past_days)):
                    self.skip_reasons["outside_previous_runs_window"] += 1
                    continue
                if parsed.target_date > today + timedelta(days=2):
                    self.skip_reasons["target_not_resolved_yet"] += 1
                    continue

                asof_time = (market.end_date or datetime.utcnow()) - timedelta(days=lead_days)
                price_point = None
                price_source = ""
                if fetch_prices:
                    price_point = event_price_cache.get(market.yes_token_id)
                    if price_point is None:
                        price_point = self.fetch_yes_price_point_near(market.yes_token_id, asof_time)
                    price_source = "clob_prices_history_asof"
                if price_point is None:
                    self.skip_reasons["price_history_missing"] += 1
                    continue
                yes_price = price_point.price

                metrics = self.fetch_forecast_metrics(parsed, market, lead_days, past_days, source_name)
                if not metrics:
                    self.skip_reasons["forecast_missing"] += 1
                    continue

                probability = self.signals.estimate_yes_probability(
                    parsed,
                    metrics,
                    max(1.0, float(lead_days) * 24.0),
                )
                if probability is None:
                    self.skip_reasons["probability_missing"] += 1
                    continue

                records.append(
                    self._record_from_inputs(
                        market=market,
                        parsed=parsed,
                        metrics=metrics,
                        yes_price=yes_price,
                        yes_resolved=yes_resolved,
                        probability=probability,
                        lead_days=lead_days,
                        asof_time=asof_time,
                        price_source=price_source,
                        forecast_source=self._forecast_source_label(source_name, lead_days),
                        clob_price_age_hours=price_point.age_hours,
                    )
                )

        return records

    def _reference_today(self, events: Iterable[Dict[str, Any]]) -> Any:
        """Anchor replay windows to the dataset so old fixtures do not drift."""

        target_dates = []
        for event in events:
            for raw_market in event.get("markets", []) or []:
                market = self._market_from_gamma(raw_market, event)
                if not market:
                    continue
                parsed = self.signals.parse_market(market)
                if parsed.target_date is not None:
                    target_dates.append(parsed.target_date)
        return max(target_dates) if target_dates else datetime.utcnow().date()

    def fetch_resolved_weather_events(self, max_events: int) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        offset = 0
        while len(events) < max_events:
            response = self.session.get(
                f"{GAMMA_API}/events",
                params={
                    "closed": "true",
                    "tag_slug": "weather",
                    "limit": min(100, max_events - len(events)),
                    "offset": offset,
                    "order": "endDate",
                    "ascending": "false",
                },
                timeout=20,
            )
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            events.extend(batch)
            offset += len(batch)
            if len(batch) < 100:
                break
            time.sleep(0.15)
        return events[:max_events]

    def fetch_yes_price_near(self, token_id: str, asof_time: datetime) -> Optional[float]:
        if not token_id:
            return None
        point = self.fetch_yes_price_point_near(token_id, asof_time)
        return point.price if point is not None else None

    def fetch_yes_price_point_near(self, token_id: str, asof_time: datetime) -> Optional[WeatherPricePoint]:
        if not token_id:
            return None
        return fetch_yes_price_points_near_batch(self.session, [token_id], asof_time).get(token_id)

    def _event_yes_price_cache(self, event: Dict[str, Any], lead_days: int) -> Dict[str, WeatherPricePoint]:
        grouped: Dict[int, List[str]] = defaultdict(list)
        seen: set[str] = set()
        asof_by_ts: Dict[int, datetime] = {}
        for raw_market in event.get("markets", []) or []:
            market = self._market_from_gamma(raw_market, event)
            if not market or not market.yes_token_id or not market.end_date:
                continue
            if market.yes_token_id in seen:
                continue
            asof_time = market.end_date - timedelta(days=lead_days)
            asof_ts = int(asof_time.timestamp())
            grouped[asof_ts].append(market.yes_token_id)
            asof_by_ts[asof_ts] = asof_time
            seen.add(market.yes_token_id)

        prices: Dict[str, WeatherPricePoint] = {}
        for asof_ts, token_ids in grouped.items():
            prices.update(fetch_yes_price_points_near_batch(self.session, token_ids, asof_by_ts[asof_ts]))
        return prices

    def fetch_previous_run_metrics(
        self,
        parsed: WeatherMarketParse,
        market: CLIMarket,
        lead_days: int,
        past_days: int,
    ) -> Optional[Dict[str, Any]]:
        if parsed.location is None or parsed.target_date is None:
            return None
        base_key = self._weather_hourly_key(parsed.metric)
        if not base_key:
            return None
        lead_key = f"{base_key}_previous_day{lead_days}"
        payload = self._fetch_previous_runs_payload(parsed.location, base_key, lead_key, past_days)
        hourly = payload.get("hourly", {}) if isinstance(payload, dict) else {}
        values = hourly.get(lead_key)
        if not isinstance(values, list):
            return None
        rewritten = {
            **payload,
            "hourly": {
                "time": hourly.get("time", []),
                base_key: values,
            },
        }
        return self.signals._summarize_forecast(rewritten, market.end_date, parsed.target_date)

    def fetch_forecast_metrics(
        self,
        parsed: WeatherMarketParse,
        market: CLIMarket,
        lead_days: int,
        past_days: int,
        forecast_source: str,
    ) -> Optional[Dict[str, Any]]:
        if forecast_source == "historical_forecast":
            return self.fetch_historical_forecast_metrics(parsed, market)
        return self.fetch_previous_run_metrics(parsed, market, lead_days, past_days)

    def fetch_historical_forecast_metrics(
        self,
        parsed: WeatherMarketParse,
        market: CLIMarket,
    ) -> Optional[Dict[str, Any]]:
        if parsed.location is None or parsed.target_date is None:
            return None
        payload = self._fetch_historical_forecast_payload(parsed.location, parsed.target_date.isoformat())
        return self.signals._summarize_forecast(payload, market.end_date, parsed.target_date)

    def _fetch_historical_forecast_payload(self, location: WeatherLocation, target_date: str) -> Dict[str, Any]:
        cache_key = f"{location.latitude:.4f},{location.longitude:.4f}:{target_date}"
        if cache_key in self._historical_forecast_cache:
            return dict(self._historical_forecast_cache[cache_key])
        response = self.session.get(
            HISTORICAL_FORECAST_API,
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "start_date": target_date,
                "end_date": target_date,
                "hourly": "temperature_2m,precipitation,snowfall,wind_speed_10m,wind_gusts_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "auto",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected historical forecast payload")
        self._historical_forecast_cache[cache_key] = dict(payload)
        return payload

    def _fetch_previous_runs_payload(
        self,
        location: WeatherLocation,
        base_key: str,
        lead_key: str,
        past_days: int,
    ) -> Dict[str, Any]:
        cache_key = f"{location.latitude:.4f},{location.longitude:.4f}:{base_key}:{lead_key}:{int(past_days)}"
        if cache_key in self._previous_runs_cache:
            return dict(self._previous_runs_cache[cache_key])
        response = self.session.get(
            PREVIOUS_RUNS_API,
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "hourly": f"{base_key},{lead_key}",
                "past_days": max(1, int(past_days)),
                "forecast_days": 2,
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "auto",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected previous-runs payload")
        self._previous_runs_cache[cache_key] = dict(payload)
        return payload

    def score_records(
        self,
        records: Iterable[WeatherAlphaRecord],
        min_edge_gap: float,
        min_records: int,
        min_candidates: int,
    ) -> Dict[str, Any]:
        rows = list(records)
        forecast_sources = sorted({row.forecast_source for row in rows})
        candidates = [row for row in rows if abs(row.edge) >= min_edge_gap]
        model_brier = self._brier(rows, "model")
        market_brier = self._brier(rows, "market")
        model_log_loss = self._log_loss(rows, "model")
        market_log_loss = self._log_loss(rows, "market")
        candidate_pnl = sum(row.pnl_per_usd for row in candidates)
        candidate_roi = candidate_pnl / len(candidates) if candidates else 0.0
        candidate_wins = sum(1 for row in candidates if row.selected_win)

        raw_blockers = []
        if len(rows) < min_records:
            raw_blockers.append(f"need_at_least_{min_records}_records")
        if len(candidates) < min_candidates:
            raw_blockers.append(f"need_at_least_{min_candidates}_candidate_edges")
        if model_brier is None or market_brier is None or model_brier >= market_brier:
            raw_blockers.append("model_brier_not_better_than_market")
        if model_log_loss is None or market_log_loss is None or model_log_loss >= market_log_loss:
            raw_blockers.append("model_log_loss_not_better_than_market")
        if candidate_roi <= 0:
            raw_blockers.append("candidate_roi_not_positive")
        source_blockers = self._forecast_source_blockers(forecast_sources)
        source_families = sorted({self._forecast_source_family(source) for source in forecast_sources})
        raw_blockers.extend(source_blockers)
        station_bias_status_counts = Counter(
            str(row.station_bias.get("status", "missing") if isinstance(row.station_bias, dict) else "missing")
            for row in rows
        )
        high_resolution_status_counts = Counter(
            str(manifest.get("status", "missing"))
            for row in rows
            for manifest in (row.high_resolution_sources or [])
            if isinstance(manifest, dict)
        )
        feature_coverage_blockers = self._feature_coverage_blockers(
            rows=rows,
            station_bias_status_counts=station_bias_status_counts,
            high_resolution_status_counts=high_resolution_status_counts,
        )
        raw_blockers.extend(feature_coverage_blockers)

        calibrated = WeatherAlphaCalibrationEvaluator().evaluate(
            rows,
            min_records=max(min_records, 100),
            min_candidates=max(min_candidates, 20),
            min_target_dates=3,
        )
        self._apply_source_blockers(calibrated, source_blockers)
        self._apply_source_blockers(calibrated, feature_coverage_blockers)
        deployment_verdict = dict(calibrated.get("deployment_verdict", {}) or {})
        deployment_verdict["feature_schema_version"] = FEATURE_SCHEMA_VERSION
        deployment_verdict["accepted_feature_schema_version"] = FEATURE_SCHEMA_VERSION
        deployment_verdict["accepted_model_id"] = calibrated.get("method", "chronological_market_forecast_blend")
        deployment_verdict["validated_source_families"] = source_families
        deployment_verdict["validated_min_probability_gap"] = round(float(min_edge_gap), 4)
        deployment_verdict["validated_forecast_sources"] = forecast_sources
        deployment_verdict["validated_station_bias_status_counts"] = dict(station_bias_status_counts)
        deployment_verdict["validated_high_resolution_status_counts"] = dict(high_resolution_status_counts)
        calibrated["deployment_verdict"] = deployment_verdict

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "market_vertical": "weather",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "record_count": len(rows),
            "candidate_count": len(candidates),
            "target_date_count": calibrated.get("target_date_count"),
            "target_dates": calibrated.get("target_dates", []),
            "forecast_sources": forecast_sources,
            "validated_source_families": source_families,
            "validated_min_probability_gap": round(float(min_edge_gap), 4),
            "feature_coverage": {
                "station_bias_status_counts": dict(station_bias_status_counts),
                "high_resolution_manifest_status_counts": dict(high_resolution_status_counts),
            },
            "candidate_win_rate": round(candidate_wins / len(candidates), 4) if candidates else None,
            "candidate_roi_per_1usd": round(candidate_roi, 4),
            "candidate_pnl_per_1usd_staked": round(candidate_pnl, 4),
            "model_brier": model_brier,
            "market_brier": market_brier,
            "model_log_loss": model_log_loss,
            "market_log_loss": market_log_loss,
            "by_metric": self._group_summary(rows, "metric"),
            "by_location": self._group_summary(rows, "location", limit=20),
            "skip_reasons": dict(self.skip_reasons),
            "raw_heuristic_verdict": {
                "accepted_for_live_weather_trading": not raw_blockers,
                "blockers": raw_blockers,
                "required_evidence": [
                    f">= {min_records} resolved records",
                    f">= {min_candidates} candidate edges",
                    "model Brier and log loss beat market-implied probabilities",
                    "positive candidate ROI after price-history entry assumptions",
                ],
            },
            "calibrated_alpha": calibrated,
            "deployment_verdict": deployment_verdict,
            "top_candidates": [
                row.to_dict()
                for row in sorted(candidates, key=lambda item: abs(item.edge), reverse=True)[:20]
            ],
        }

    @staticmethod
    def _forecast_source_blockers(forecast_sources: List[str]) -> List[str]:
        if "open_meteo_historical_forecast" in forecast_sources:
            return ["historical_forecast_source_not_asof_safe"]
        return []

    def _feature_coverage_blockers(
        self,
        *,
        rows: List[WeatherAlphaRecord],
        station_bias_status_counts: Counter,
        high_resolution_status_counts: Counter,
    ) -> List[str]:
        blockers: List[str] = []
        record_count = len(rows)
        if bool(getattr(self.config, "weather_require_station_bias_validation", False)):
            validated = int(station_bias_status_counts.get("validated", 0) or 0)
            manual = int(station_bias_status_counts.get("manual_override", 0) or 0)
            if validated + manual < record_count:
                blockers.append("station_bias_alpha_coverage_incomplete")
        if bool(getattr(self.config, "weather_require_high_resolution_confirmation", False)):
            live_safe = int(high_resolution_status_counts.get("live_safe", 0) or 0)
            # Each row can carry multiple high-resolution sources. Require at
            # least one live-safe high-resolution source per resolved record.
            if live_safe < record_count:
                blockers.append("high_resolution_alpha_coverage_incomplete")
        return blockers

    @staticmethod
    def _forecast_source_family(forecast_source: str) -> str:
        source = str(forecast_source or "").lower()
        if source.startswith("open_meteo"):
            return "open_meteo"
        if source.startswith("nws"):
            return "nws"
        if "metar" in source:
            return "metar"
        return source or "unknown"

    @staticmethod
    def _apply_source_blockers(report: Dict[str, Any], blockers: List[str]) -> None:
        if not blockers:
            return
        verdict = report.setdefault("deployment_verdict", {})
        existing = [str(item) for item in verdict.get("blockers", [])]
        for blocker in blockers:
            if blocker not in existing:
                existing.append(blocker)
        verdict["blockers"] = existing
        verdict["accepted_for_live_weather_trading"] = False

    def write_artifacts(self, records: List[WeatherAlphaRecord], report: Dict[str, Any]) -> None:
        records_path = self.output_dir / "weather_alpha_records.jsonl"
        report_path = self.output_dir / "latest_weather_alpha_report.json"
        md_path = self.output_dir / "latest_weather_alpha_report.md"
        records_path.write_text(
            "\n".join(json.dumps(row.to_dict(), sort_keys=True) for row in records) + ("\n" if records else ""),
            encoding="utf-8",
        )
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        md_path.write_text(self._format_markdown(report), encoding="utf-8")

    @classmethod
    def parse_yes_resolution(cls, market: Dict[str, Any]) -> Optional[bool]:
        outcomes = cls._json_field(market.get("outcomes"), [])
        prices = cls._json_field(market.get("outcomePrices"), [])
        if len(outcomes) != 2 or len(prices) != 2:
            return None
        yes_idx = None
        no_idx = None
        for idx, outcome in enumerate(outcomes):
            if str(outcome).strip().lower() == "yes":
                yes_idx = idx
            if str(outcome).strip().lower() == "no":
                no_idx = idx
        if yes_idx is None or no_idx is None:
            return None
        try:
            yes_price = float(prices[yes_idx])
            no_price = float(prices[no_idx])
        except (TypeError, ValueError):
            return None
        if not cls._is_closed_or_resolved(market):
            return None
        if yes_price >= 0.999 and no_price <= 0.001:
            return True
        if yes_price <= 0.001 and no_price >= 0.999:
            return False
        return None

    @classmethod
    def _is_closed_or_resolved(cls, market: Dict[str, Any]) -> bool:
        if cls._to_bool(market.get("closed")):
            return True
        if market.get("active") is not None and not cls._to_bool(market.get("active"), True):
            return True
        for key in ("resolved", "finalized", "settled"):
            if cls._to_bool(market.get(key)):
                return True
        status = str(
            market.get("resolutionStatus")
            or market.get("resolution_status")
            or market.get("status")
            or ""
        ).strip().lower()
        return status in {"resolved", "finalized", "settled", "closed"}

    @staticmethod
    def _to_bool(raw: Any, default: bool = False) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "closed", "active"}

    def _record_from_inputs(
        self,
        market: CLIMarket,
        parsed: WeatherMarketParse,
        metrics: Dict[str, Any],
        yes_price: float,
        yes_resolved: bool,
        probability: float,
        lead_days: int,
        asof_time: datetime,
        price_source: str,
        forecast_source: str,
        clob_price_age_hours: float = 0.0,
    ) -> WeatherAlphaRecord:
        edge = probability - yes_price
        recommended_side = "YES" if edge >= 0 else "NO"
        side_price = yes_price if recommended_side == "YES" else max(0.001, 1.0 - yes_price)
        selected_win = yes_resolved if recommended_side == "YES" else not yes_resolved
        pnl = ((1.0 - side_price) / side_price) if selected_win else -1.0
        resolution = self.signals.station_mapper.resolve(
            market_id=str(market.condition_id),
            location=parsed.location,
            market_text=market.question,
        )
        station_bias = self.station_bias_resolver.snapshot(resolution)
        high_resolution_sources = self.high_resolution_builder.build_manifests(
            resolution=resolution,
            target_date=parsed.target_date,
            metric=parsed.metric,
            end_date=market.end_date,
            source_ids=getattr(self.config, "weather_high_resolution_sources", None),
            generated_at=asof_time,
        )
        return WeatherAlphaRecord(
            market_id=market.condition_id,
            question=market.question,
            slug=market.slug,
            end_date=market.end_date.isoformat() if market.end_date else "",
            target_date=parsed.target_date.isoformat() if parsed.target_date else "",
            location=parsed.location.name if parsed.location else "",
            metric=parsed.metric,
            operator=parsed.operator,
            threshold=parsed.threshold,
            upper_threshold=parsed.upper_threshold,
            lead_days=lead_days,
            asof_time=asof_time.isoformat(),
            yes_price=round(yes_price, 4),
            model_probability=round(probability, 4),
            edge=round(edge, 4),
            recommended_side=recommended_side,
            side_price=round(side_price, 4),
            yes_resolved=yes_resolved,
            selected_win=selected_win,
            pnl_per_usd=round(pnl, 4),
            price_source=price_source,
            forecast_source=forecast_source,
            forecast_metrics=metrics,
            clob_price_age_hours=round(float(clob_price_age_hours or 0.0), 4),
            station_mapping=resolution.to_dict(),
            source_statuses={
                "station_mapper": resolution.status,
                forecast_source: "research_only" if "historical" in forecast_source else "live_safe",
                "station_bias": station_bias.status,
                "high_resolution_manifests": "manifest_ready",
            },
            station_bias=station_bias.to_dict(),
            high_resolution_sources=high_resolution_sources,
            latency_signals={
                "price_source": price_source,
                "asof_time": asof_time.isoformat(),
                "clob_price_age_hours": round(float(clob_price_age_hours or 0.0), 4),
            },
        )

    def _market_from_gamma(self, raw: Dict[str, Any], event: Dict[str, Any]) -> Optional[CLIMarket]:
        token_ids = self._json_field(raw.get("clobTokenIds"), [])
        outcomes = self._json_field(raw.get("outcomes"), [])
        if len(token_ids) != 2 or len(outcomes) != 2:
            return None
        yes_idx = next((idx for idx, label in enumerate(outcomes) if str(label).lower() == "yes"), None)
        no_idx = next((idx for idx, label in enumerate(outcomes) if str(label).lower() == "no"), None)
        if yes_idx is None or no_idx is None:
            return None
        end_date = self._parse_datetime(raw.get("endDate") or event.get("endDate"))
        return CLIMarket(
            condition_id=str(raw.get("conditionId") or raw.get("id") or ""),
            question=str(raw.get("question") or event.get("title") or ""),
            symbol="WEATHER",
            yes_token_id=str(token_ids[yes_idx]),
            no_token_id=str(token_ids[no_idx]),
            yes_price=0.5,
            no_price=0.5,
            liquidity=self._safe_float(raw.get("liquidityNum", raw.get("liquidity", 0.0)), 0.0),
            volume_24h=self._safe_float(raw.get("volume24hr", event.get("volume24hr", 0.0)), 0.0),
            end_date=end_date,
            is_active=bool(raw.get("active", False)),
            market_type="neutral",
            event_slug=str(event.get("slug") or ""),
            spread=self._safe_float(raw.get("spread", 0.0), 0.0),
            slug=str(raw.get("slug") or event.get("slug") or ""),
            description=" ".join(
                part
                for part in (str(raw.get("description") or ""), str(event.get("description") or ""))
                if part
            ),
        )

    @staticmethod
    def _parse_skip_reason(parsed: WeatherMarketParse) -> str:
        if parsed.metric == "space_weather":
            return "unsupported_space_weather"
        if parsed.metric not in {"temperature_high", "temperature_low", "precipitation", "snowfall", "wind", "wind_gust"}:
            return "unsupported_metric"
        if not parsed.location:
            return "unparsed_location"
        if not parsed.operator or parsed.threshold is None:
            return "unparsed_resolution_rule"
        return ""

    @staticmethod
    def _weather_hourly_key(metric: str) -> str:
        return {
            "temperature_high": "temperature_2m",
            "temperature_low": "temperature_2m",
            "precipitation": "precipitation",
            "snowfall": "snowfall",
            "wind": "wind_speed_10m",
            "wind_gust": "wind_gusts_10m",
        }.get(metric, "")

    @staticmethod
    def _normalize_forecast_source(value: str) -> str:
        cleaned = str(value or "previous_runs").strip().lower().replace("-", "_")
        if cleaned in {"historical", "historical_forecast", "historical_forecasts"}:
            return "historical_forecast"
        return "previous_runs"

    @staticmethod
    def _forecast_source_label(source_name: str, lead_days: int) -> str:
        if source_name == "historical_forecast":
            return "open_meteo_historical_forecast"
        return f"open_meteo_previous_day{lead_days}"

    @staticmethod
    def _brier(rows: List[WeatherAlphaRecord], source: str) -> Optional[float]:
        if not rows:
            return None
        total = 0.0
        for row in rows:
            probability = row.model_probability if source == "model" else row.yes_price
            outcome = 1.0 if row.yes_resolved else 0.0
            total += (probability - outcome) ** 2
        return round(total / len(rows), 6)

    @staticmethod
    def _log_loss(rows: List[WeatherAlphaRecord], source: str) -> Optional[float]:
        if not rows:
            return None
        total = 0.0
        for row in rows:
            probability = row.model_probability if source == "model" else row.yes_price
            p = min(0.98, max(0.02, probability))
            total += -math.log(p if row.yes_resolved else 1.0 - p)
        return round(total / len(rows), 6)

    @staticmethod
    def _group_summary(rows: List[WeatherAlphaRecord], attr: str, limit: int = 10) -> Dict[str, Any]:
        grouped: Dict[str, List[WeatherAlphaRecord]] = defaultdict(list)
        for row in rows:
            grouped[str(getattr(row, attr))].append(row)
        summary = {}
        for key, group in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:limit]:
            summary[key] = {
                "records": len(group),
                "model_brier": WeatherAlphaBacktester._brier(group, "model"),
                "market_brier": WeatherAlphaBacktester._brier(group, "market"),
                "candidate_roi_per_1usd": round(
                    sum(row.pnl_per_usd for row in group if abs(row.edge) >= 0.08)
                    / max(1, len([row for row in group if abs(row.edge) >= 0.08])),
                    4,
                ),
            }
        return summary

    @staticmethod
    def _format_markdown(report: Dict[str, Any]) -> str:
        verdict = report.get("deployment_verdict", {})
        calibrated = report.get("calibrated_alpha", {}) if isinstance(report.get("calibrated_alpha"), dict) else {}
        holdout = calibrated.get("holdout_score", {}) if isinstance(calibrated.get("holdout_score"), dict) else {}
        lines = [
            "# Polymarket Weather Alpha Report",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Feature schema: `{report.get('feature_schema_version')}`",
            f"- Resolved records: `{report.get('record_count')}`",
            f"- Candidate edges: `{report.get('candidate_count')}`",
            f"- Target dates: `{calibrated.get('target_date_count')}`",
            f"- Model Brier: `{report.get('model_brier')}`",
            f"- Market Brier: `{report.get('market_brier')}`",
            f"- Candidate ROI per $1: `{report.get('candidate_roi_per_1usd')}`",
            f"- Holdout candidate ROI per $1: `{holdout.get('candidate_roi_per_1usd')}`",
            f"- Accepted for live weather trading: `{verdict.get('accepted_for_live_weather_trading')}`",
            "",
            "## Blockers",
        ]
        blockers = verdict.get("blockers") or []
        if not blockers:
            lines.append("- None")
        else:
            lines.extend(f"- `{blocker}`" for blocker in blockers)
        lines.extend(["", "## Top Candidates"])
        for row in report.get("top_candidates", [])[:10]:
            lines.append(
                f"- `{row.get('recommended_side')}` edge `{float(row.get('edge', 0.0)):+.2%}` "
                f"win=`{row.get('selected_win')}` pnl=`{row.get('pnl_per_usd')}` | "
                f"{row.get('question')}"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _json_field(value: Any, default: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default
        return value if value is not None else default

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if math.isfinite(parsed) else default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest Polymarket weather forecast edge")
    parser.add_argument("--max-events", type=int, default=80)
    parser.add_argument("--max-markets", type=int, default=250)
    parser.add_argument("--min-volume", type=float, default=0.0)
    parser.add_argument("--lead-days", type=int, default=1)
    parser.add_argument("--past-days", type=int, default=7)
    parser.add_argument("--min-edge-gap", type=float, default=0.08)
    parser.add_argument("--min-records", type=int, default=30)
    parser.add_argument("--min-candidates", type=int, default=5)
    parser.add_argument(
        "--forecast-source",
        choices=["previous_runs", "historical_forecast"],
        default="previous_runs",
        help="Forecast data source for backtest features",
    )
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--no-prices", action="store_true", help="Skip CLOB price history; useful only for parser debugging")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = PolymarketCLIConfig(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        min_volume_24h_usd=0.0,
    )
    backtester = WeatherAlphaBacktester(
        config=config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    report = backtester.run(
        max_events=args.max_events,
        max_markets=args.max_markets,
        min_volume=args.min_volume,
        lead_days=args.lead_days,
        past_days=args.past_days,
        min_edge_gap=args.min_edge_gap,
        min_records=args.min_records,
        min_candidates=args.min_candidates,
        fetch_prices=not args.no_prices,
        forecast_source=args.forecast_source,
    )
    verdict = report.get("deployment_verdict", {})
    cprint("Weather alpha report written", "green")
    cprint(f"  Records: {report.get('record_count')}", "white")
    cprint(f"  Candidates: {report.get('candidate_count')}", "white")
    cprint(f"  Accepted live gate: {verdict.get('accepted_for_live_weather_trading')}", "white")
    if verdict.get("blockers"):
        cprint(f"  Blockers: {', '.join(verdict.get('blockers', []))}", "yellow")
    cprint(f"  Output: {backtester.output_dir}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
