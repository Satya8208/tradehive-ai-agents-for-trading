"""
Known/near-known observation-lag alpha for weather markets.

This module produces research candidates only. It never enables live execution.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from .models import CLIMarket
from .weather_market_tape import WeatherMarketTapeSnapshot
from .weather_market_type_classifier import LANE_OBSERVATION_LAG, WeatherMarketTypeClassifier
from .weather_orderbook_simulator import WeatherOrderbookFillSimulator
from .weather_station_observation_state import WeatherStationObservationState
from .weather_threshold_state import WeatherThresholdStateEvaluator


KNOWN_OUTCOME_ALPHA_SCHEMA_VERSION = "weather_known_outcome_alpha_v1"
KNOWN_OUTCOME_ALPHA_CODE = "OBSERVATION_LAG_STATION_THRESHOLD_V1"


@dataclass(frozen=True)
class WeatherKnownOutcomeCandidate:
    market_id: str
    alpha_code: str
    status: str
    side: str
    p_yes: Optional[float]
    executable_price: Optional[float]
    edge_after_cost: Optional[float]
    schema_version: str = KNOWN_OUTCOME_ALPHA_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    executable_price_source: str = ""
    fill_status: str = ""
    max_fillable_usd: Optional[float] = None
    selected_win_probability: Optional[float] = None
    p_yes_source: str = ""
    probability_role: str = ""
    fill_simulation: Dict[str, Any] = field(default_factory=dict)
    threshold_state: Dict[str, Any] = field(default_factory=dict)
    classification: Dict[str, Any] = field(default_factory=dict)
    station_state: Dict[str, Any] = field(default_factory=dict)
    proof: list[str] = field(default_factory=list)
    disproof: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherKnownOutcomeAlpha:
    def __init__(
        self,
        classifier: Optional[WeatherMarketTypeClassifier] = None,
        threshold_evaluator: Optional[WeatherThresholdStateEvaluator] = None,
        min_edge_after_cost: float = 0.06,
        fee_slippage_buffer: float = 0.02,
        target_fill_usd: float = 5.0,
        min_fillable_usd: float = 1.0,
        require_full_fill: bool = False,
    ):
        self.classifier = classifier or WeatherMarketTypeClassifier()
        self.threshold_evaluator = threshold_evaluator or WeatherThresholdStateEvaluator()
        self.min_edge_after_cost = float(min_edge_after_cost)
        self.fee_slippage_buffer = float(fee_slippage_buffer)
        self.target_fill_usd = float(target_fill_usd)
        self.min_fillable_usd = max(0.0, float(min_fillable_usd))
        self.require_full_fill = bool(require_full_fill)
        self.fill_simulator = WeatherOrderbookFillSimulator(
            default_request_size_usd=max(0.01, self.target_fill_usd),
            allow_best_ask_without_depth=not self.require_full_fill,
        )

    def evaluate(
        self,
        market: CLIMarket,
        station_state: WeatherStationObservationState | Dict[str, Any],
        *,
        tape: Optional[WeatherMarketTapeSnapshot | Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> WeatherKnownOutcomeCandidate:
        now = now or datetime.utcnow()
        classification = self.classifier.classify(market, now=now)
        state = station_state.to_dict() if hasattr(station_state, "to_dict") else dict(station_state or {})
        threshold_state = self.threshold_evaluator.evaluate(
            metric=classification.metric,
            operator=classification.operator,
            threshold=classification.threshold,
            upper_threshold=classification.upper_threshold,
            station_state=state,
            market_end=getattr(market, "end_date", None),
            now=now,
        )
        blockers = list(classification.blockers) + list(threshold_state.blockers)
        flags = ["known_outcome_alpha_research_only"]
        flags.extend(classification.quality_flags)
        flags.extend(threshold_state.quality_flags)

        if LANE_OBSERVATION_LAG not in classification.alpha_lanes:
            blockers.append("market_not_routed_to_observation_lag")
        if threshold_state.p_yes is None:
            blockers.append("known_outcome_probability_missing")
        elif threshold_state.probability_role != "settlement_fact":
            blockers.append(f"known_outcome_probability_not_settlement_fact:{threshold_state.p_yes_source}")

        side = threshold_state.recommended_side
        executable_price, executable_source = self._executable_price_and_source(side, tape)
        fill = self.fill_simulator.simulate(
            tape,
            side,
            requested_size_usd=self.target_fill_usd,
            limit_price=executable_price,
        ) if side else None
        fill_dict = fill.to_dict() if fill is not None else {}
        if fill is not None:
            flags.extend(fill.quality_flags)
            if fill.full_fill and fill.average_price is not None and executable_source == "orderbook_best_ask":
                executable_price = fill.average_price
                executable_source = "orderbook_depth_simulation"
            elif self.require_full_fill:
                blockers.extend(fill.blockers or ["fill_not_full"])
            if float(fill_dict.get("filled_notional_usd") or 0.0) < self.min_fillable_usd:
                blockers.append("executable_fill_below_minimum")
        if executable_price is None:
            blockers.append("executable_price_missing")
        elif executable_source not in {"orderbook_best_ask", "orderbook_depth_simulation"}:
            blockers.append(f"executable_price_not_orderbook:{executable_source or 'missing'}")

        edge_after_cost = None
        win_probability = None
        if (
            threshold_state.p_yes is not None
            and threshold_state.probability_role == "settlement_fact"
            and executable_price is not None
            and side
        ):
            win_probability = threshold_state.p_yes if side == "YES" else 1.0 - threshold_state.p_yes
            edge_after_cost = win_probability - executable_price - self.fee_slippage_buffer
            if edge_after_cost < self.min_edge_after_cost:
                blockers.append("known_outcome_edge_below_cost_buffer")

        status = "candidate" if not blockers else "blocked"
        if status == "candidate":
            flags.append("known_or_near_known_executable_edge")
        proof = self._proof_lines(
            side=side,
            p_yes=threshold_state.p_yes,
            threshold_state=threshold_state.to_dict(),
            classification=classification.to_dict(),
            station_state=state,
        )
        disproof = self._disproof_lines(blockers, fill_dict, executable_source)

        return WeatherKnownOutcomeCandidate(
            market_id=str(getattr(market, "condition_id", "") or ""),
            alpha_code=KNOWN_OUTCOME_ALPHA_CODE,
            status=status,
            side=side,
            p_yes=threshold_state.p_yes,
            executable_price=round(executable_price, 6) if executable_price is not None else None,
            edge_after_cost=round(edge_after_cost, 6) if edge_after_cost is not None else None,
            executable_price_source=executable_source,
            fill_status=str(fill_dict.get("status") or ""),
            max_fillable_usd=round(float(fill_dict.get("total_depth_usd_at_limit") or 0.0), 6) if fill_dict else None,
            selected_win_probability=round(win_probability, 6) if win_probability is not None else None,
            p_yes_source=threshold_state.p_yes_source,
            probability_role=threshold_state.probability_role,
            fill_simulation=fill_dict,
            threshold_state=threshold_state.to_dict(),
            classification=classification.to_dict(),
            station_state=state,
            proof=proof,
            disproof=disproof,
            blockers=sorted(set(blockers)),
            quality_flags=sorted(set(flags)),
        )

    @staticmethod
    def _executable_price_and_source(
        side: str,
        tape: Optional[WeatherMarketTapeSnapshot | Dict[str, Any]],
    ) -> tuple[Optional[float], str]:
        if not side:
            return None, ""
        tape_dict = tape.to_dict() if hasattr(tape, "to_dict") else dict(tape or {})
        key = "executable_yes_price" if side == "YES" else "executable_no_price"
        source_key = "executable_yes_price_source" if side == "YES" else "executable_no_price_source"
        try:
            parsed = float(tape_dict.get(key))
        except (TypeError, ValueError):
            return None, str(tape_dict.get(source_key) or "")
        if not math.isfinite(parsed) or parsed <= 0:
            return None, str(tape_dict.get(source_key) or "")
        return parsed, str(tape_dict.get(source_key) or "")

    @staticmethod
    def _proof_lines(
        *,
        side: str,
        p_yes: Optional[float],
        threshold_state: Dict[str, Any],
        classification: Dict[str, Any],
        station_state: Dict[str, Any],
    ) -> list[str]:
        if p_yes is None or not side:
            return []
        metric = str(classification.get("metric") or "")
        operator = str(classification.get("operator") or "")
        threshold = classification.get("threshold")
        upper = classification.get("upper_threshold")
        observed = threshold_state.get("observed_value")
        station = str(station_state.get("station_id") or classification.get("station_id") or "")
        target = f"{operator} {threshold}"
        if operator == "between" and upper is not None:
            target = f"between {threshold} and {upper}"
        return [
            f"Station {station} observed {metric}={observed}, tested against market threshold {target}.",
            "Threshold evaluator assigned "
            f"p_yes={p_yes} from {threshold_state.get('p_yes_source')} "
            f"({threshold_state.get('probability_role')}); selected paper side is {side}.",
        ]

    @staticmethod
    def _disproof_lines(blockers: list[str], fill_dict: Dict[str, Any], executable_source: str) -> list[str]:
        lines = [f"Blocked by {blocker}." for blocker in sorted(set(blockers))]
        fill_status = str(fill_dict.get("status") or "")
        if fill_status and fill_status != "full":
            lines.append(f"Depth simulation did not fully fill target size: {fill_status}.")
        if executable_source and executable_source not in {"orderbook_best_ask", "orderbook_depth_simulation"}:
            lines.append(f"Executable price source was not accepted orderbook depth: {executable_source}.")
        return lines
