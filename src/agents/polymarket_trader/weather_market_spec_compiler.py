"""
Compile canonical market specs for Polymarket weather contracts.

The spec compiler sits before alpha logic. It turns a free-form Polymarket
question plus token metadata into a typed, fail-closed contract description so
downstream research, replay, paper, and live gates reason over the same shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import CLIMarket
from .weather_contracts import WeatherMarketSpec
from .weather_market_type_classifier import WeatherMarketTypeClassifier


class WeatherMarketSpecCompiler:
    def __init__(self, classifier: Optional[WeatherMarketTypeClassifier] = None):
        self.classifier = classifier or WeatherMarketTypeClassifier()

    def compile(self, market: CLIMarket, *, now: Optional[datetime] = None) -> WeatherMarketSpec:
        classification = self.classifier.classify(market, now=now)
        blockers = list(classification.blockers)
        quality_flags = list(classification.quality_flags)

        condition_id = str(getattr(market, "condition_id", "") or "").strip()
        yes_token_id = str(getattr(market, "yes_token_id", "") or "").strip()
        no_token_id = str(getattr(market, "no_token_id", "") or "").strip()
        question = str(getattr(market, "question", "") or "").strip()

        if not condition_id:
            blockers.append("condition_id_missing")
        if not question:
            blockers.append("question_missing")
        if not yes_token_id or not no_token_id:
            blockers.append("yes_no_token_mapping_missing")
        if yes_token_id and no_token_id and yes_token_id == no_token_id:
            blockers.append("yes_no_token_mapping_ambiguous")
        if getattr(market, "end_date", None) is None:
            blockers.append("market_end_date_missing")

        yes_price = self._safe_price(getattr(market, "yes_price", None))
        no_price = self._safe_price(getattr(market, "no_price", None))
        if yes_price is None or no_price is None:
            blockers.append("market_price_missing")
        elif abs((yes_price + no_price) - 1.0) > 0.15:
            quality_flags.append("wide_or_inconsistent_yes_no_prices")

        if classification.region == "CONUS" and classification.station_id:
            settlement_source = "station_threshold_requires_official_resolution_check"
        elif classification.contract_type in {"hurricane_tropical", "space_weather"}:
            settlement_source = "specialized_official_source_required"
            quality_flags.append("specialized_settlement_source")
        else:
            settlement_source = "contract_text_unverified"

        return WeatherMarketSpec(
            market_id=condition_id,
            condition_id=condition_id,
            question=question,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            contract_type=classification.contract_type,
            metric=classification.metric,
            operator=classification.operator,
            threshold=classification.threshold,
            upper_threshold=classification.upper_threshold,
            threshold_unit=classification.threshold_unit,
            target_date=classification.target_date,
            location_name=classification.location_name,
            resolution_station=classification.station_id,
            station_type=classification.station_type,
            region=classification.region,
            horizon_bucket=classification.horizon_bucket,
            alpha_lanes=list(classification.alpha_lanes),
            source_applicability=list(classification.source_applicability),
            settlement_source=settlement_source,
            market_url=getattr(market, "market_url", ""),
            blockers=sorted(set(str(item) for item in blockers if str(item).strip())),
            quality_flags=sorted(set(str(item) for item in quality_flags if str(item).strip())),
        )

    @staticmethod
    def _safe_price(value) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed < 0.0 or parsed > 1.0:
            return None
        return parsed
