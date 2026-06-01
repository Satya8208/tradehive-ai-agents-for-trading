"""
Calibration and holdout evaluation for Polymarket weather alpha records.

The ingestion layer builds real resolved records. This layer decides whether a
forecast signal survives a simple chronological holdout test against the market
price baseline.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from termcolor import cprint


@dataclass(frozen=True)
class WeatherAlphaPolicy:
    forecast_weight: float
    min_edge_gap: float


class WeatherAlphaCalibrationEvaluator:
    """Search a simple market/forecast blend and verify on chronological holdout."""

    WEIGHTS = tuple(round(i / 20.0, 2) for i in range(0, 21))
    EDGE_GAPS = (0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20)

    def evaluate(
        self,
        rows: Iterable[Any],
        min_records: int = 100,
        min_candidates: int = 20,
        min_target_dates: int = 3,
        holdout_ratio: float = 0.35,
    ) -> Dict[str, Any]:
        records = [row for row in rows if self._is_valid_row(row)]
        records.sort(key=lambda row: (self._text(row, "target_date"), self._text(row, "market_id")))
        train, holdout, target_dates = self._split_chronological(records, holdout_ratio)

        baseline_all = self.score_policy(records, WeatherAlphaPolicy(0.0, 0.0))
        raw_all = self.score_policy(records, WeatherAlphaPolicy(1.0, 0.08))
        best_policy, train_score = self._fit_policy(train, min_candidates=max(1, min_candidates // 2))
        holdout_score = self.score_policy(holdout, best_policy) if best_policy else self._empty_score()
        train_market = self.score_policy(train, WeatherAlphaPolicy(0.0, best_policy.min_edge_gap if best_policy else 0.0))
        holdout_market = self.score_policy(holdout, WeatherAlphaPolicy(0.0, best_policy.min_edge_gap if best_policy else 0.0))

        blockers = self._build_blockers(
            records=records,
            target_dates=target_dates,
            train=train,
            holdout=holdout,
            train_score=train_score,
            holdout_score=holdout_score,
            train_market=train_market,
            holdout_market=holdout_market,
            min_records=min_records,
            min_candidates=min_candidates,
            min_target_dates=min_target_dates,
        )

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "method": "chronological_market_forecast_blend",
            "record_count": len(records),
            "target_date_count": len(target_dates),
            "target_dates": target_dates,
            "train_records": len(train),
            "holdout_records": len(holdout),
            "best_policy": {
                "forecast_weight": best_policy.forecast_weight if best_policy else None,
                "market_weight": round(1.0 - best_policy.forecast_weight, 2) if best_policy else None,
                "min_edge_gap": best_policy.min_edge_gap if best_policy else None,
            },
            "baseline_market_all": baseline_all,
            "raw_forecast_all": raw_all,
            "train_score": train_score,
            "train_market_at_policy_gap": train_market,
            "holdout_score": holdout_score,
            "holdout_market_at_policy_gap": holdout_market,
            "deployment_verdict": {
                "accepted_for_live_weather_trading": not blockers,
                "blockers": blockers,
                "required_evidence": [
                    f">= {min_records} resolved records",
                    f">= {min_target_dates} target dates",
                    f">= {min_candidates} holdout candidate edges",
                    "train and holdout Brier/log loss better than market baseline",
                    "positive train and holdout candidate ROI",
                ],
            },
        }

    def score_policy(self, rows: Iterable[Any], policy: WeatherAlphaPolicy) -> Dict[str, Any]:
        records = [row for row in rows if self._is_valid_row(row)]
        if not records:
            return self._empty_score()

        scored = [self._score_row(row, policy) for row in records]
        candidates = [row for row in scored if abs(row["edge"]) >= policy.min_edge_gap]
        wins = sum(1 for row in candidates if row["selected_win"])
        candidate_pnl = sum(float(row["pnl_per_usd"]) for row in candidates)
        return {
            "records": len(records),
            "candidate_count": len(candidates),
            "candidate_win_rate": round(wins / len(candidates), 4) if candidates else None,
            "candidate_roi_per_1usd": round(candidate_pnl / len(candidates), 4) if candidates else 0.0,
            "candidate_pnl_per_1usd_staked": round(candidate_pnl, 4),
            "brier": self._brier(scored),
            "log_loss": self._log_loss(scored),
            "top_candidates": sorted(candidates, key=lambda row: abs(row["edge"]), reverse=True)[:10],
        }

    def _fit_policy(
        self,
        train: List[Any],
        min_candidates: int,
    ) -> Tuple[Optional[WeatherAlphaPolicy], Dict[str, Any]]:
        if not train:
            return None, self._empty_score()

        market_score = self.score_policy(train, WeatherAlphaPolicy(0.0, 0.0))
        best_policy: Optional[WeatherAlphaPolicy] = None
        best_score: Optional[Dict[str, Any]] = None
        best_rank: Optional[Tuple[float, float, float, float]] = None

        for weight in self.WEIGHTS:
            for edge_gap in self.EDGE_GAPS:
                policy = WeatherAlphaPolicy(weight, edge_gap)
                score = self.score_policy(train, policy)
                if score["candidate_count"] < min_candidates:
                    continue
                brier_advantage = float(market_score["brier"] or 0.0) - float(score["brier"] or 0.0)
                log_advantage = float(market_score["log_loss"] or 0.0) - float(score["log_loss"] or 0.0)
                rank = (
                    1.0 if brier_advantage > 0 and log_advantage > 0 else 0.0,
                    brier_advantage + log_advantage,
                    float(score["candidate_roi_per_1usd"]),
                    -abs(weight - 0.5),
                )
                if best_rank is None or rank > best_rank:
                    best_policy = policy
                    best_score = score
                    best_rank = rank

        if best_policy is None:
            best_policy = WeatherAlphaPolicy(0.0, 0.0)
            best_score = market_score
        return best_policy, best_score or self._empty_score()

    def _build_blockers(
        self,
        records: List[Any],
        target_dates: List[str],
        train: List[Any],
        holdout: List[Any],
        train_score: Dict[str, Any],
        holdout_score: Dict[str, Any],
        train_market: Dict[str, Any],
        holdout_market: Dict[str, Any],
        min_records: int,
        min_candidates: int,
        min_target_dates: int,
    ) -> List[str]:
        blockers: List[str] = []
        if len(records) < min_records:
            blockers.append(f"need_at_least_{min_records}_records")
        if len(target_dates) < min_target_dates:
            blockers.append(f"need_at_least_{min_target_dates}_target_dates")
        if not train or not holdout:
            blockers.append("chronological_holdout_unavailable")
        if holdout_score.get("candidate_count", 0) < min_candidates:
            blockers.append(f"need_at_least_{min_candidates}_holdout_candidate_edges")
        if not self._beats_market(train_score, train_market, "brier"):
            blockers.append("train_brier_not_better_than_market")
        if not self._beats_market(train_score, train_market, "log_loss"):
            blockers.append("train_log_loss_not_better_than_market")
        if not self._beats_market(holdout_score, holdout_market, "brier"):
            blockers.append("holdout_brier_not_better_than_market")
        if not self._beats_market(holdout_score, holdout_market, "log_loss"):
            blockers.append("holdout_log_loss_not_better_than_market")
        if float(train_score.get("candidate_roi_per_1usd", 0.0) or 0.0) <= 0:
            blockers.append("train_candidate_roi_not_positive")
        if float(holdout_score.get("candidate_roi_per_1usd", 0.0) or 0.0) <= 0:
            blockers.append("holdout_candidate_roi_not_positive")
        return blockers

    @staticmethod
    def _beats_market(score: Dict[str, Any], market_score: Dict[str, Any], key: str) -> bool:
        value = score.get(key)
        market_value = market_score.get(key)
        return value is not None and market_value is not None and float(value) < float(market_value)

    def _score_row(self, row: Any, policy: WeatherAlphaPolicy) -> Dict[str, Any]:
        market_probability = self._float(row, "yes_price")
        forecast_probability = self._float(row, "model_probability")
        probability = self._clip(
            market_probability + policy.forecast_weight * (forecast_probability - market_probability)
        )
        edge = probability - market_probability
        side = "YES" if edge >= 0 else "NO"
        side_price = market_probability if side == "YES" else max(0.001, 1.0 - market_probability)
        yes_resolved = self._bool(row, "yes_resolved")
        selected_win = yes_resolved if side == "YES" else not yes_resolved
        pnl = ((1.0 - side_price) / side_price) if selected_win else -1.0
        return {
            "market_id": self._text(row, "market_id"),
            "question": self._text(row, "question"),
            "target_date": self._text(row, "target_date"),
            "metric": self._text(row, "metric"),
            "location": self._text(row, "location"),
            "yes_price": round(market_probability, 4),
            "forecast_probability": round(forecast_probability, 4),
            "probability": round(probability, 4),
            "edge": round(edge, 4),
            "recommended_side": side,
            "side_price": round(side_price, 4),
            "yes_resolved": yes_resolved,
            "selected_win": selected_win,
            "pnl_per_usd": round(pnl, 4),
        }

    @staticmethod
    def _split_chronological(rows: List[Any], holdout_ratio: float) -> Tuple[List[Any], List[Any], List[str]]:
        target_dates = sorted({WeatherAlphaCalibrationEvaluator._text(row, "target_date") for row in rows})
        if len(target_dates) < 2:
            return rows, [], target_dates
        ratio = max(0.05, min(0.8, holdout_ratio))
        holdout_dates = max(1, int(math.floor(len(target_dates) * ratio)))
        holdout_dates = min(holdout_dates, len(target_dates) - 1)
        split_dates = set(target_dates[-holdout_dates:])
        train = [row for row in rows if WeatherAlphaCalibrationEvaluator._text(row, "target_date") not in split_dates]
        holdout = [row for row in rows if WeatherAlphaCalibrationEvaluator._text(row, "target_date") in split_dates]
        return train, holdout, target_dates

    @staticmethod
    def _brier(scored_rows: List[Dict[str, Any]]) -> Optional[float]:
        if not scored_rows:
            return None
        total = 0.0
        for row in scored_rows:
            outcome = 1.0 if row["yes_resolved"] else 0.0
            total += (float(row["probability"]) - outcome) ** 2
        return round(total / len(scored_rows), 6)

    @staticmethod
    def _log_loss(scored_rows: List[Dict[str, Any]]) -> Optional[float]:
        if not scored_rows:
            return None
        total = 0.0
        for row in scored_rows:
            p = WeatherAlphaCalibrationEvaluator._clip(float(row["probability"]))
            total += -math.log(p if row["yes_resolved"] else 1.0 - p)
        return round(total / len(scored_rows), 6)

    @staticmethod
    def _empty_score() -> Dict[str, Any]:
        return {
            "records": 0,
            "candidate_count": 0,
            "candidate_win_rate": None,
            "candidate_roi_per_1usd": 0.0,
            "candidate_pnl_per_1usd_staked": 0.0,
            "brier": None,
            "log_loss": None,
            "top_candidates": [],
        }

    @staticmethod
    def _is_valid_row(row: Any) -> bool:
        try:
            yes_price = WeatherAlphaCalibrationEvaluator._float(row, "yes_price")
            model_probability = WeatherAlphaCalibrationEvaluator._float(row, "model_probability")
        except (TypeError, ValueError):
            return False
        return math.isfinite(yes_price) and math.isfinite(model_probability)

    @staticmethod
    def _clip(value: float) -> float:
        return max(0.02, min(0.98, float(value)))

    @staticmethod
    def _float(row: Any, key: str) -> float:
        value = row.get(key) if isinstance(row, dict) else getattr(row, key)
        return float(value)

    @staticmethod
    def _bool(row: Any, key: str) -> bool:
        value = row.get(key) if isinstance(row, dict) else getattr(row, key)
        return bool(value)

    @staticmethod
    def _text(row: Any, key: str) -> str:
        value = row.get(key, "") if isinstance(row, dict) else getattr(row, key, "")
        return str(value or "")


def load_records(path: Path) -> List[Dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate calibrated weather alpha records")
    parser.add_argument("records", type=str, help="Path to weather_alpha_records.jsonl")
    parser.add_argument("--output", type=str, default=None, help="Optional JSON report output path")
    parser.add_argument("--min-records", type=int, default=100)
    parser.add_argument("--min-candidates", type=int, default=20)
    parser.add_argument("--min-target-dates", type=int, default=3)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    evaluator = WeatherAlphaCalibrationEvaluator()
    report = evaluator.evaluate(
        load_records(Path(args.records)),
        min_records=args.min_records,
        min_candidates=args.min_candidates,
        min_target_dates=args.min_target_dates,
    )
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    cprint("Weather alpha calibration evaluated", "green")
    cprint(f"  Records: {report.get('record_count')}", "white")
    cprint(f"  Target dates: {report.get('target_date_count')}", "white")
    cprint(f"  Accepted: {report.get('deployment_verdict', {}).get('accepted_for_live_weather_trading')}", "white")
    blockers = report.get("deployment_verdict", {}).get("blockers", [])
    if blockers:
        cprint(f"  Blockers: {', '.join(blockers)}", "yellow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
