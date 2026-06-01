"""
Performance Tracker for Polymarket CLI Agents
"""

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from termcolor import cprint

from .backtest_scorer import BacktestScorer, ParamSet
from .config import PolymarketCLIConfig, get_config


class PerformanceTracker:
    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()
        self.perf_dir = self.config.data_dir / "performance"
        self.perf_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self) -> Dict[str, Any]:
        trades = self._load_all_trades()
        predictions = self._load_all_predictions()
        if not trades:
            cprint("No trade data found for performance analysis", "yellow")
            return {}

        entries = [t for t in trades if not str(t.get("side", "")).startswith("CLOSE")]
        closes = [t for t in trades if str(t.get("side", "")).startswith("CLOSE")]
        journal = self._build_trade_journal(entries, closes, predictions)
        calibration = self._build_calibration(journal)
        model_accuracy = self._build_model_accuracy(journal)
        summary = self._build_summary(journal, calibration, model_accuracy)
        replay = self._build_replay_summary()
        if replay is not None:
            summary["replay"] = replay

        self._write_trade_journal(journal)
        self._write_calibration(calibration)
        self._write_model_accuracy(model_accuracy)
        if replay is not None:
            self._write_replay_summary(replay)
        self._write_summary(summary)
        self._print_summary(summary, calibration, model_accuracy)
        return summary

    def _load_all_trades(self) -> List[Dict]:
        trades = []
        trades_dir = self.config.trades_dir
        if not trades_dir.exists():
            return trades
        for f in sorted(trades_dir.glob("trades_*.jsonl")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            trades.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            except OSError:
                pass
        return trades

    def _load_all_predictions(self) -> List[Dict]:
        predictions = []
        pred_dir = self.config.predictions_dir
        if not pred_dir.exists():
            return predictions
        for f in sorted(pred_dir.glob("prediction_*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                    if isinstance(payload, dict):
                        payload["_prediction_file"] = str(f)
                        payload["_prediction_timestamp"] = self._parse_timestamp(payload.get("timestamp"))
                        predictions.append(payload)
            except (json.JSONDecodeError, OSError):
                pass
        return predictions

    def _build_trade_journal(self, entries: List[Dict], closes: List[Dict], predictions: List[Dict]) -> List[Dict]:
        entries_by_market = defaultdict(list)
        closes_by_market = defaultdict(list)
        for item in entries:
            mid = str(item.get("market_id", "")).strip()
            if mid:
                entries_by_market[mid].append(item)
        for item in closes:
            mid = str(item.get("market_id", "")).strip()
            if mid:
                closes_by_market[mid].append(item)

        prediction_index = self._index_predictions(predictions)
        journal = []
        for market_id in sorted(entries_by_market.keys()):
            market_entries = sorted(entries_by_market[market_id], key=self._trade_sort_key)
            market_closes = sorted(closes_by_market.get(market_id, []), key=self._trade_sort_key)
            close_cursor = 0
            for entry in market_entries:
                close, close_cursor = self._match_close(entry, market_closes, close_cursor)
                linked_prediction = self._select_prediction_for_entry(entry, prediction_index.get(market_id, []))
                journal.append(self._build_journal_row(entry, close, linked_prediction))
        journal.sort(key=lambda row: self._parse_timestamp(row.get("entry_time")) or datetime.min)
        return journal

    def _build_journal_row(self, entry: Dict, close: Optional[Dict], linked_prediction: Optional[Dict]) -> Dict:
        entry_price = self._safe_float(entry.get("price"))
        size_usd = self._safe_float(entry.get("size_usd"))
        entry_side = self._normalize_side(entry.get("side"))
        entry_ts = self._parse_timestamp(entry.get("timestamp"))
        confidence = self._safe_float(entry.get("confidence"), 0.5) or 0.5

        close_price = None
        close_ts = None
        pnl = None
        outcome = "open"
        is_closed = False
        if close and entry_price and entry_price > 0 and size_usd and size_usd > 0:
            close_price = self._safe_float(close.get("price"))
            close_ts = self._parse_timestamp(close.get("timestamp"))
            fees = (self._safe_float(entry.get("fees"), 0.0) or 0.0) + (self._safe_float(close.get("fees"), 0.0) or 0.0)
            if close_price is not None:
                pnl = (size_usd / entry_price) * (close_price - entry_price) - fees
                outcome = "win" if pnl > 0 else ("loss" if pnl < 0 else "flat")
                is_closed = True

        actual_side = ""
        if outcome == "win":
            actual_side = entry_side
        elif outcome == "loss":
            actual_side = self._opposite_side(entry_side)
        elif outcome == "flat":
            actual_side = "FLAT"

        prediction_timestamp = ""
        prediction_age_minutes = None
        consensus_prediction = None
        consensus_probability = None
        consensus_confidence = None
        prediction_match = None
        prediction_model_count = 0
        prediction_linked = linked_prediction is not None
        prediction_successful_model_count = 0
        prediction_runtime_ready = False
        prediction_measurement_boundary = ""
        prediction_analysis_cohort = ""
        if linked_prediction is not None:
            consensus_prediction = str(linked_prediction.get("consensus_prediction", "")).upper()
            consensus_probability = self._safe_float(linked_prediction.get("consensus_probability"))
            consensus_confidence = self._safe_float(linked_prediction.get("consensus_confidence"))
            pred_ts = self._parse_timestamp(linked_prediction.get("timestamp"))
            if pred_ts:
                prediction_timestamp = pred_ts.isoformat()
                if entry_ts:
                    prediction_age_minutes = round(max(0.0, (entry_ts - pred_ts).total_seconds() / 60.0), 2)
            prediction_model_count = len(linked_prediction.get("predictions", []) or [])
            prediction_successful_model_count = self._safe_int(
                linked_prediction.get("successful_model_count"),
                prediction_model_count,
            )
            prediction_runtime_ready = bool(
                linked_prediction.get(
                    "runtime_ready",
                    prediction_successful_model_count >= max(1, int(getattr(self.config, "min_consensus_count", 2))),
                )
            )
            prediction_measurement_boundary = str(
                linked_prediction.get("measurement_boundary", "swarm" if prediction_runtime_ready else "degraded_swarm")
                or ""
            )
            prediction_analysis_cohort = str(linked_prediction.get("analysis_cohort", "swarm") or "")
            if consensus_prediction in {"YES", "NO"} and actual_side in {"YES", "NO"}:
                prediction_match = consensus_prediction == actual_side

        return {
            "trade_id": entry.get("trade_id", ""),
            "entry_trade_id": entry.get("trade_id", ""),
            "close_trade_id": close.get("trade_id", "") if close else "",
            "market_id": entry.get("market_id", ""),
            "question": entry.get("question", "")[:80],
            "symbol": entry.get("symbol", ""),
            "side": entry_side or str(entry.get("side", "")),
            "close_side": self._normalize_side(close.get("side")) if close else "",
            "actual_side": actual_side,
            "source": entry.get("source", ""),
            "entry_time": entry_ts.isoformat() if entry_ts else str(entry.get("timestamp", "")),
            "exit_time": close_ts.isoformat() if close_ts else "",
            "entry_price": entry_price,
            "exit_price": close_price,
            "size_usd": size_usd,
            "fees": round((self._safe_float(entry.get("fees"), 0.0) or 0.0) + (self._safe_float(close.get("fees"), 0.0) if close else 0.0), 4),
            "net_pnl": pnl,
            "outcome": outcome,
            "is_closed": is_closed,
            "edge_at_entry": self._parse_edge_from_reason(entry.get("reason", "")),
            "swarm_probability": self._parse_prob_from_reason(entry.get("reason", "")),
            "confidence": confidence,
            "consensus_prediction": consensus_prediction,
            "consensus_probability": consensus_probability,
            "consensus_confidence": consensus_confidence,
            "prediction_timestamp": prediction_timestamp,
            "prediction_age_minutes": prediction_age_minutes,
            "prediction_match": prediction_match,
            "prediction_model_count": prediction_model_count,
            "prediction_successful_model_count": prediction_successful_model_count,
            "prediction_runtime_ready": prediction_runtime_ready,
            "prediction_measurement_boundary": prediction_measurement_boundary,
            "prediction_analysis_cohort": prediction_analysis_cohort,
            "prediction_linked": prediction_linked,
            "timeframe": self._classify_timeframe(self._safe_float(entry.get("time_remaining_hours")), self._safe_int(entry.get("duration_minutes"))),
            "market_type": entry.get("market_type", ""),
            "_entry_ts": entry_ts,
            "_close_ts": close_ts,
            "_linked_prediction": linked_prediction,
        }

    def _index_predictions(self, predictions: List[Dict]) -> Dict[str, List[Dict]]:
        grouped = defaultdict(list)
        for pred in predictions:
            mid = str(pred.get("market_id", "")).strip()
            if mid:
                grouped[mid].append(pred)
        for mid in list(grouped.keys()):
            grouped[mid] = sorted(grouped[mid], key=lambda pred: (pred.get("_prediction_timestamp") or datetime.min, str(pred.get("_prediction_file", ""))))
        return grouped

    def _select_prediction_for_entry(self, entry: Dict, market_predictions: List[Dict]) -> Optional[Dict]:
        if not market_predictions:
            return None
        entry_ts = self._parse_timestamp(entry.get("timestamp"))
        if entry_ts is None:
            return market_predictions[-1]
        best = None
        best_ts = None
        fallback = None
        for pred in market_predictions:
            pred_ts = pred.get("_prediction_timestamp") or self._parse_timestamp(pred.get("timestamp"))
            if pred_ts is None:
                continue
            fallback = pred
            if pred_ts <= entry_ts and (best_ts is None or pred_ts >= best_ts):
                best = pred
                best_ts = pred_ts
        return best or fallback or market_predictions[-1]

    def _match_close(self, entry: Dict, closes: List[Dict], start_index: int) -> Tuple[Optional[Dict], int]:
        entry_side = self._normalize_side(entry.get("side"))
        entry_ts = self._parse_timestamp(entry.get("timestamp"))
        for idx in range(start_index, len(closes)):
            close = closes[idx]
            close_side = self._normalize_side(close.get("side"))
            if entry_side and close_side and close_side != f"CLOSE_{entry_side}":
                continue
            close_ts = self._parse_timestamp(close.get("timestamp"))
            if entry_ts and close_ts and close_ts < entry_ts:
                continue
            return close, idx + 1
        return None, start_index

    def _build_calibration(self, journal: List[Dict]) -> List[Dict]:
        buckets = [f"{i * 10}-{(i + 1) * 10}%" for i in range(10)]
        specs = [
            ("overall", lambda t: "all"),
            ("source", lambda t: t.get("source", "unknown") or "unknown"),
            ("symbol", lambda t: t.get("symbol", "OTHER") or "OTHER"),
            ("timeframe", lambda t: t.get("timeframe", "unknown") or "unknown"),
        ]
        rows = []
        for group_type, selector in specs:
            grouped = defaultdict(lambda: defaultdict(lambda: {"count": 0, "wins": 0, "prob_sum": 0.0, "brier_sum": 0.0}))
            for trade in journal:
                if not trade.get("is_closed"):
                    continue
                prob = trade.get("consensus_probability")
                if prob is None or trade.get("outcome") not in {"win", "loss"}:
                    continue
                if trade.get("prediction_measurement_boundary") == "degraded_swarm":
                    continue
                group_value = selector(trade)
                bucket = buckets[min(int(float(prob) * 10), 9)]
                stats = grouped[group_value][bucket]
                stats["count"] += 1
                stats["wins"] += 1 if trade["outcome"] == "win" else 0
                stats["prob_sum"] += float(prob)
                label = 1.0 if trade["outcome"] == "win" else 0.0
                stats["brier_sum"] += (float(prob) - label) ** 2
            for group_value in sorted(grouped.keys()):
                for bucket in buckets:
                    stats = grouped[group_value].get(bucket)
                    if not stats or stats["count"] <= 0:
                        continue
                    count = stats["count"]
                    rows.append({
                        "group_type": group_type,
                        "group_value": group_value,
                        "probability_bucket": bucket,
                        "trade_count": count,
                        "wins": stats["wins"],
                        "losses": count - stats["wins"],
                        "actual_win_rate": round(stats["wins"] / count, 3),
                        "avg_predicted_probability": round(stats["prob_sum"] / count, 3),
                        "brier_score": round(stats["brier_sum"] / count, 4),
                    })
        return rows

    def _build_model_accuracy(self, journal: List[Dict]) -> List[Dict]:
        model_stats = defaultdict(lambda: {"total": 0, "correct": 0, "avg_confidence": 0.0, "avg_probability": 0.0, "yes_predictions": 0, "no_predictions": 0, "linked_trades": 0})
        for trade in journal:
            linked_prediction = trade.get("_linked_prediction")
            if not trade.get("is_closed") or linked_prediction is None:
                continue
            if trade.get("prediction_measurement_boundary") == "degraded_swarm":
                continue
            actual_side = trade.get("actual_side")
            if actual_side not in {"YES", "NO"}:
                continue
            for model_pred in linked_prediction.get("predictions", []) or []:
                predicted_side = str(model_pred.get("prediction", "")).strip().upper()
                if predicted_side not in {"YES", "NO"}:
                    continue
                key = f"{model_pred.get('model_provider', 'unknown')}/{model_pred.get('model_name', 'unknown')}"
                stats = model_stats[key]
                stats["total"] += 1
                stats["avg_confidence"] += self._safe_float(model_pred.get("confidence"))
                stats["avg_probability"] += self._safe_float(model_pred.get("probability_estimate"))
                stats["yes_predictions"] += 1 if predicted_side == "YES" else 0
                stats["no_predictions"] += 1 if predicted_side == "NO" else 0
                stats["linked_trades"] += 1
                if predicted_side == actual_side:
                    stats["correct"] += 1
        rows = []
        for model_key, stats in sorted(model_stats.items()):
            total = stats["total"] or 1
            rows.append({
                "model": model_key,
                "total_predictions": stats["total"],
                "correct": stats["correct"],
                "accuracy": round(stats["correct"] / total, 3),
                "avg_confidence": round(stats["avg_confidence"] / total, 3),
                "avg_probability_estimate": round(stats["avg_probability"] / total, 3),
                "yes_predictions": stats["yes_predictions"],
                "no_predictions": stats["no_predictions"],
                "linked_trades": stats["linked_trades"],
            })
        return rows

    def _build_summary(self, journal: List[Dict], calibration: List[Dict], model_accuracy: List[Dict]) -> Dict[str, Any]:
        closed = [t for t in journal if t["is_closed"] and t["net_pnl"] is not None]
        open_trades = [t for t in journal if not t["is_closed"]]
        if not closed:
            return {
                "total_trades": len(journal),
                "closed_trades": 0,
                "open_trades": len(open_trades),
                "generated_at": datetime.utcnow().isoformat(),
            }

        wins = [t for t in closed if t["outcome"] == "win"]
        losses = [t for t in closed if t["outcome"] == "loss"]
        total_pnl = sum(t["net_pnl"] for t in closed)
        total_fees = sum(t["fees"] for t in closed)
        avg_win = sum(t["net_pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["net_pnl"] for t in losses) / len(losses) if losses else 0
        win_rate = len(wins) / len(closed) if closed else 0
        loss_sum = sum(t["net_pnl"] for t in losses)
        profit_factor = abs(sum(t["net_pnl"] for t in wins) / loss_sum) if losses and loss_sum != 0 else float("inf")

        cumulative = 0
        peak = 0
        max_drawdown = 0
        for t in sorted(closed, key=lambda x: self._parse_timestamp(x["entry_time"]) or datetime.min):
            cumulative += t["net_pnl"]
            peak = max(peak, cumulative)
            max_drawdown = max(max_drawdown, peak - cumulative)

        source_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        symbol_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        tf_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        linked_closed = [t for t in closed if t.get("prediction_linked")]
        healthy_linked_closed = [t for t in linked_closed if t.get("prediction_measurement_boundary") != "degraded_swarm"]
        degraded_linked_closed = [t for t in linked_closed if t.get("prediction_measurement_boundary") == "degraded_swarm"]
        single_model_control = [t for t in linked_closed if t.get("prediction_analysis_cohort") == "single_model_control"]
        scored_predictions = [
            t for t in healthy_linked_closed
            if t.get("prediction_match") is not None and t.get("consensus_probability") is not None
        ]
        consensus_correct = [t for t in scored_predictions if t.get("prediction_match")]
        abstains = [t for t in healthy_linked_closed if t.get("consensus_prediction") == "ABSTAIN"]
        brier_total = sum((float(t["consensus_probability"]) - (1.0 if t["outcome"] == "win" else 0.0)) ** 2 for t in scored_predictions)
        abs_error_total = sum(abs(float(t["consensus_probability"]) - (1.0 if t["outcome"] == "win" else 0.0)) for t in scored_predictions)
        confidence_diagnostics = self._build_confidence_diagnostics(scored_predictions)
        edge_quality_diagnostics = self._build_edge_quality_diagnostics(scored_predictions)
        edge_timeframe_diagnostics = self._build_edge_timeframe_diagnostics(scored_predictions)
        market_archetype_diagnostics = self._build_market_archetype_diagnostics(scored_predictions)
        entry_price_diagnostics = self._build_entry_price_diagnostics(scored_predictions)
        direction_diagnostics = self._build_direction_diagnostics(scored_predictions)
        policy_rescue_diagnostics = self._build_policy_rescue_diagnostics(scored_predictions)
        for t in closed:
            src = t.get("source", "unknown")
            sym = t.get("symbol", "OTHER")
            tf = t.get("timeframe", "unknown")
            source_stats[src]["count"] += 1
            source_stats[src]["pnl"] += t["net_pnl"]
            source_stats[src]["wins"] += 1 if t["outcome"] == "win" else 0
            symbol_stats[sym]["count"] += 1
            symbol_stats[sym]["pnl"] += t["net_pnl"]
            symbol_stats[sym]["wins"] += 1 if t["outcome"] == "win" else 0
            tf_stats[tf]["count"] += 1
            tf_stats[tf]["pnl"] += t["net_pnl"]
            tf_stats[tf]["wins"] += 1 if t["outcome"] == "win" else 0

        model_accuracy_total = sum(row["total_predictions"] for row in model_accuracy)
        model_accuracy_correct = sum(row["correct"] for row in model_accuracy)
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "total_trades": len(journal),
            "closed_trades": len(closed),
            "open_trades": len(open_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 2),
            "total_fees": round(total_fees, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
            "max_drawdown": round(max_drawdown, 2),
            "prediction_coverage": round(len(linked_closed) / len(closed), 3) if closed else 0,
            "healthy_swarm_prediction_coverage": round(len(healthy_linked_closed) / len(closed), 3) if closed else 0,
            "degraded_swarm_linked_closed": len(degraded_linked_closed),
            "single_model_control_linked_closed": len(single_model_control),
            "consensus_accuracy": round(len(consensus_correct) / len(scored_predictions), 3) if scored_predictions else 0,
            "abstain_rate": round(len(abstains) / len(linked_closed), 3) if linked_closed else 0,
            "brier_score": round(brier_total / len(scored_predictions), 4) if scored_predictions else 0,
            "mean_absolute_error": round(abs_error_total / len(scored_predictions), 4) if scored_predictions else 0,
            "confidence_diagnostics": confidence_diagnostics,
            "edge_quality_diagnostics": edge_quality_diagnostics,
            "edge_timeframe_diagnostics": edge_timeframe_diagnostics,
            "market_archetype_diagnostics": market_archetype_diagnostics,
            "entry_price_diagnostics": entry_price_diagnostics,
            "direction_diagnostics": direction_diagnostics,
            "policy_rescue_diagnostics": policy_rescue_diagnostics,
            "model_accuracy_total_predictions": model_accuracy_total,
            "model_accuracy_correct": model_accuracy_correct,
            "model_accuracy_weighted_accuracy": round(model_accuracy_correct / model_accuracy_total, 3) if model_accuracy_total else 0,
            "by_source": {k: {"count": v["count"], "pnl": round(v["pnl"], 2), "win_rate": round(v["wins"] / v["count"], 3) if v["count"] else 0} for k, v in source_stats.items()},
            "by_timeframe": {k: {"count": v["count"], "pnl": round(v["pnl"], 2), "win_rate": round(v["wins"] / v["count"], 3) if v["count"] else 0} for k, v in tf_stats.items()},
            "by_symbol": {k: {"count": v["count"], "pnl": round(v["pnl"], 2), "win_rate": round(v["wins"] / v["count"], 3) if v["count"] else 0} for k, v in symbol_stats.items()},
            "calibration_buckets": len(calibration),
            "model_accuracy_models": len(model_accuracy),
        }

    @staticmethod
    def _build_confidence_diagnostics(scored_predictions: List[Dict]) -> Dict[str, Any]:
        high_threshold = 0.5
        severe_threshold = 0.7
        cap_thresholds = [0.3, 0.4, 0.5]
        floor_thresholds = [0.5, 0.6, 0.7]
        if not scored_predictions:
            return {
                "verdict": "NO_SCORABLE_PREDICTIONS",
                "high_confidence_threshold": high_threshold,
                "severe_confidence_threshold": severe_threshold,
                "best_cap": {},
                "best_floor": {},
                "gate_verdict": {
                    "status": "NO_SCORABLE_PREDICTIONS",
                    "reason_codes": ["no_scorable_predictions"],
                },
                "cap_sweep": [],
                "floor_sweep": [],
                "high_confidence": {"count": 0},
                "severe_confidence": {"count": 0},
                "low_confidence": {"count": 0},
                "confidence_monotonicity_broken": False,
            }

        def summarize(rows: List[Dict]) -> Dict[str, Any]:
            count = len(rows)
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            avg_probability = (
                sum(float(row.get("consensus_probability", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            actual_win_rate = (wins / count) if count > 0 else 0.0
            return {
                "count": count,
                "wins": wins,
                "win_rate": round(actual_win_rate, 3) if count > 0 else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_predicted_probability": round(avg_probability, 3) if count > 0 else 0.0,
                "overconfidence_gap": round(avg_probability - actual_win_rate, 3) if count > 0 else 0.0,
            }

        high_confidence = [
            row for row in scored_predictions
            if float(row.get("consensus_probability", 0.0) or 0.0) >= high_threshold
        ]
        severe_confidence = [
            row for row in scored_predictions
            if float(row.get("consensus_probability", 0.0) or 0.0) >= severe_threshold
        ]
        low_confidence = [
            row for row in scored_predictions
            if float(row.get("consensus_probability", 0.0) or 0.0) < high_threshold
        ]

        high_summary = summarize(high_confidence)
        severe_summary = summarize(severe_confidence)
        low_summary = summarize(low_confidence)
        cap_sweep = []
        for threshold in cap_thresholds:
            rows = [
                row for row in scored_predictions
                if float(row.get("consensus_probability", 0.0) or 0.0) <= threshold
            ]
            summary = summarize(rows)
            summary["threshold"] = threshold
            cap_sweep.append(summary)
        floor_sweep = []
        for threshold in floor_thresholds:
            rows = [
                row for row in scored_predictions
                if float(row.get("consensus_probability", 0.0) or 0.0) >= threshold
            ]
            summary = summarize(rows)
            summary["threshold"] = threshold
            floor_sweep.append(summary)
        confidence_monotonicity_broken = bool(
            high_summary.get("count", 0) > 0
            and low_summary.get("count", 0) > 0
            and float(high_summary.get("win_rate", 0.0) or 0.0) < float(low_summary.get("win_rate", 0.0) or 0.0)
        )

        best_cap = max(
            cap_sweep,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                -float(item.get("threshold", 0.0) or 0.0),
            ),
            default={},
        )
        best_floor = max(
            floor_sweep,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                -float(item.get("threshold", 0.0) or 0.0),
            ),
            default={},
        )

        verdict = "MIXED_CONFIDENCE_SIGNAL"
        if int(high_summary.get("count", 0) or 0) >= 5 and float(high_summary.get("win_rate", 0.0) or 0.0) <= 0.1 and float(high_summary.get("total_pnl", 0.0) or 0.0) < 0.0:
            verdict = "HIGH_CONFIDENCE_ANTI_SIGNAL"
        elif int(high_summary.get("count", 0) or 0) <= 0:
            verdict = "NO_HIGH_CONFIDENCE_SAMPLE"

        gate_reason_codes = []
        gate_status = "NO_PROMOTABLE_CONFIDENCE_GATE"
        if best_cap and int(best_cap.get("count", 0) or 0) >= 5 and float(best_cap.get("total_pnl", 0.0) or 0.0) > 0.0:
            gate_status = "PROMOTABLE_CONFIDENCE_CAP"
        else:
            gate_reason_codes.append("best_cap_still_negative_or_thin")
        if best_floor and int(best_floor.get("count", 0) or 0) > 0 and float(best_floor.get("total_pnl", 0.0) or 0.0) < 0.0:
            gate_reason_codes.append("high_confidence_floor_negative")
        if confidence_monotonicity_broken:
            gate_reason_codes.append("confidence_monotonicity_broken")

        return {
            "verdict": verdict,
            "high_confidence_threshold": high_threshold,
            "severe_confidence_threshold": severe_threshold,
            "best_cap": best_cap,
            "best_floor": best_floor,
            "gate_verdict": {
                "status": gate_status,
                "reason_codes": gate_reason_codes,
            },
            "cap_sweep": cap_sweep,
            "floor_sweep": floor_sweep,
            "high_confidence": high_summary,
            "severe_confidence": severe_summary,
            "low_confidence": low_summary,
            "confidence_monotonicity_broken": confidence_monotonicity_broken,
        }

    @staticmethod
    def _build_edge_quality_diagnostics(scored_predictions: List[Dict]) -> Dict[str, Any]:
        floor_thresholds = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]
        cap_thresholds = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]
        min_trade_count = 5
        edge_rows = [
            row for row in scored_predictions
            if row.get("edge_at_entry") is not None
        ]
        if not edge_rows:
            return {
                "verdict": "NO_EDGE_SAMPLE",
                "min_trade_count": min_trade_count,
                "best_cap": {},
                "best_floor": {},
                "best_low_sample_floor": {},
                "gate_verdict": {
                    "status": "NO_EDGE_SAMPLE",
                    "reason_codes": ["no_edge_scored_predictions"],
                },
                "cap_sweep": [],
                "floor_sweep": [],
                "high_edge_beats_low_edge": False,
            }

        def summarize(rows: List[Dict]) -> Dict[str, Any]:
            count = len(rows)
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            avg_edge = (
                sum(float(row.get("edge_at_entry", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            avg_probability = (
                sum(float(row.get("consensus_probability", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            return {
                "count": count,
                "wins": wins,
                "win_rate": round((wins / count), 3) if count > 0 else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_edge_at_entry": round(avg_edge, 2) if count > 0 else 0.0,
                "avg_predicted_probability": round(avg_probability, 3) if count > 0 else 0.0,
            }

        floor_sweep = []
        for threshold in floor_thresholds:
            rows = [
                row for row in edge_rows
                if float(row.get("edge_at_entry", 0.0) or 0.0) >= threshold
            ]
            summary = summarize(rows)
            summary["threshold"] = threshold
            floor_sweep.append(summary)

        cap_sweep = []
        for threshold in cap_thresholds:
            rows = [
                row for row in edge_rows
                if float(row.get("edge_at_entry", 0.0) or 0.0) <= threshold
            ]
            summary = summarize(rows)
            summary["threshold"] = threshold
            cap_sweep.append(summary)

        best_any_floor = max(
            floor_sweep,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                float(item.get("threshold", 0.0) or 0.0),
            ),
            default={},
        )
        sampled_floors = [
            row for row in floor_sweep
            if int(row.get("count", 0) or 0) >= min_trade_count
        ]
        # Keep sampled and low-sample floors separate so the report does not
        # promote a tiny positive patch as the best production-ready gate.
        best_floor = max(
            sampled_floors,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                float(item.get("threshold", 0.0) or 0.0),
            ),
            default={},
        )
        best_cap = max(
            cap_sweep,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                -float(item.get("threshold", 0.0) or 0.0),
            ),
            default={},
        )
        positive_low_sample_floors = [
            row for row in floor_sweep
            if 0 < int(row.get("count", 0) or 0) < min_trade_count
            and float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        best_low_sample_floor = max(
            positive_low_sample_floors,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                float(item.get("threshold", 0.0) or 0.0),
            ),
            default={},
        )

        low_edge_rows = [
            row for row in edge_rows
            if float(row.get("edge_at_entry", 0.0) or 0.0) <= 10.0
        ]
        high_edge_rows = [
            row for row in edge_rows
            if float(row.get("edge_at_entry", 0.0) or 0.0) >= 20.0
        ]
        low_edge_summary = summarize(low_edge_rows)
        high_edge_summary = summarize(high_edge_rows)
        high_edge_beats_low_edge = (
            int(high_edge_summary.get("count", 0) or 0) > 0
            and int(low_edge_summary.get("count", 0) or 0) > 0
            and float(high_edge_summary.get("total_pnl", 0.0) or 0.0) > float(low_edge_summary.get("total_pnl", 0.0) or 0.0)
        )

        gate_status = "NO_PROMOTABLE_EDGE_GATE"
        gate_reason_codes: List[str] = []
        if best_floor and int(best_floor.get("count", 0) or 0) >= min_trade_count and float(best_floor.get("total_pnl", 0.0) or 0.0) > 0.0:
            gate_status = "PROMOTABLE_EDGE_FLOOR"
        else:
            gate_reason_codes.append("best_sampled_edge_floor_still_negative_or_flat")
        if best_cap and int(best_cap.get("count", 0) or 0) >= min_trade_count and float(best_cap.get("total_pnl", 0.0) or 0.0) > 0.0:
            gate_reason_codes.append("positive_edge_cap_exists")
        else:
            gate_reason_codes.append("best_sampled_edge_cap_still_negative_or_flat")
        if best_low_sample_floor:
            gate_reason_codes.append("only_low_sample_positive_edge_floor")
        if high_edge_beats_low_edge:
            gate_reason_codes.append("higher_edge_cohorts_less_bad_but_not_good")

        verdict = (
            "ONLY_LOW_SAMPLE_EDGE_PATCH"
            if best_low_sample_floor and gate_status == "NO_PROMOTABLE_EDGE_GATE"
            else "NO_PROMOTABLE_EDGE_GATE"
            if gate_status == "NO_PROMOTABLE_EDGE_GATE"
            else "PROMOTABLE_EDGE_GATE"
        )

        return {
            "verdict": verdict,
            "min_trade_count": min_trade_count,
            "best_cap": best_cap,
            "best_any_floor": best_any_floor,
            "best_floor": best_floor,
            "best_low_sample_floor": best_low_sample_floor,
            "low_edge": low_edge_summary,
            "high_edge": high_edge_summary,
            "high_edge_beats_low_edge": high_edge_beats_low_edge,
            "gate_verdict": {
                "status": gate_status,
                "reason_codes": gate_reason_codes,
            },
            "cap_sweep": cap_sweep,
            "floor_sweep": floor_sweep,
        }

    @staticmethod
    def _build_edge_timeframe_diagnostics(scored_predictions: List[Dict]) -> Dict[str, Any]:
        min_trade_count = 5
        floor_thresholds = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]
        cap_thresholds = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]
        if not scored_predictions:
            return {
                "verdict": "NO_TIMEFRAME_EDGE_SAMPLE",
                "min_trade_count": min_trade_count,
                "gate_verdict": {
                    "status": "NO_TIMEFRAME_EDGE_SAMPLE",
                    "reason_codes": ["no_scorable_predictions"],
                },
                "best_sampled_pocket": {},
                "best_low_sample_pocket": {},
                "top_rows": [],
                "positive_sampled_pocket_count": 0,
                "positive_low_sample_pocket_count": 0,
            }

        def row_identifier(row: Dict[str, Any]) -> str:
            for key in ("trade_id", "entry_trade_id", "close_trade_id"):
                value = str(row.get(key, "") or "").strip()
                if value:
                    return value
            market_id = str(row.get("market_id", "") or "").strip()
            entry_time = str(row.get("entry_time", "") or "").strip()
            if market_id or entry_time:
                return f"{market_id}|{entry_time}"
            return str(id(row))

        def summarize(rows: List[Dict], *, timeframe: str, edge_mode: str, threshold: float) -> Dict[str, Any]:
            count = len(rows)
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            avg_edge = (
                sum(float(row.get("edge_at_entry", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            avg_probability = (
                sum(float(row.get("consensus_probability", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            comparator = ">=" if edge_mode == "floor" else "<="
            return {
                "timeframe": timeframe,
                "edge_mode": edge_mode,
                "threshold": threshold,
                "edge_filter": f"{edge_mode}{comparator}{threshold:g}",
                "pocket_signature": tuple(sorted(row_identifier(row) for row in rows)),
                "count": count,
                "wins": wins,
                "win_rate": round((wins / count), 3) if count > 0 else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_edge_at_entry": round(avg_edge, 2) if count > 0 else 0.0,
                "avg_predicted_probability": round(avg_probability, 3) if count > 0 else 0.0,
            }

        rows: List[Dict[str, Any]] = []
        timeframes = sorted({str(row.get("timeframe", "unknown") or "unknown") for row in scored_predictions})
        for timeframe in timeframes:
            timeframe_rows = [
                row for row in scored_predictions
                if str(row.get("timeframe", "unknown") or "unknown") == timeframe
            ]
            for threshold in floor_thresholds:
                filtered = [
                    row for row in timeframe_rows
                    if float(row.get("edge_at_entry", 0.0) or 0.0) >= threshold
                ]
                if filtered:
                    rows.append(
                        summarize(filtered, timeframe=timeframe, edge_mode="floor", threshold=threshold)
                    )
            for threshold in cap_thresholds:
                filtered = [
                    row for row in timeframe_rows
                    if float(row.get("edge_at_entry", 0.0) or 0.0) <= threshold
                ]
                if filtered:
                    rows.append(
                        summarize(filtered, timeframe=timeframe, edge_mode="cap", threshold=threshold)
                    )

        def row_key(item: Dict[str, Any]) -> tuple:
            edge_mode = str(item.get("edge_mode", "") or "")
            threshold = float(item.get("threshold", 0.0) or 0.0)
            strictness = threshold if edge_mode == "floor" else -threshold
            return (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                strictness,
                str(item.get("timeframe", "") or ""),
            )

        rows.sort(key=row_key, reverse=True)
        deduped_rows: List[Dict[str, Any]] = []
        seen_signatures = set()
        for row in rows:
            signature = tuple(row.get("pocket_signature", ()) or ())
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped_rows.append(row)

        sampled_rows = [
            row for row in deduped_rows
            if int(row.get("count", 0) or 0) >= min_trade_count
        ]
        sampled_positive_rows = [
            row for row in sampled_rows
            if float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        low_sample_positive_rows = [
            row for row in deduped_rows
            if 0 < int(row.get("count", 0) or 0) < min_trade_count
            and float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]

        best_sampled_pocket = max(sampled_rows, key=row_key, default={})
        best_low_sample_pocket = max(low_sample_positive_rows, key=row_key, default={})

        gate_status = "NO_PROMOTABLE_TIMEFRAME_EDGE_POCKET"
        gate_reason_codes: List[str] = []
        if sampled_positive_rows:
            gate_status = "PROMOTABLE_TIMEFRAME_EDGE_POCKET_EXISTS"
        else:
            gate_reason_codes.append("best_sampled_timeframe_edge_pocket_still_negative_or_flat")
        if low_sample_positive_rows:
            gate_reason_codes.append("only_low_sample_positive_timeframe_edge_pocket")
            if any(str(row.get("timeframe", "") or "") == "ultra_short" for row in low_sample_positive_rows):
                gate_reason_codes.append("only_positive_timeframe_edge_pocket_is_ultra_short")
        else:
            gate_reason_codes.append("no_positive_low_sample_timeframe_edge_pocket")

        verdict = (
            "PROMOTABLE_TIMEFRAME_EDGE_POCKET_EXISTS"
            if sampled_positive_rows
            else "ONLY_LOW_SAMPLE_TIMEFRAME_EDGE_PATCH"
            if low_sample_positive_rows
            else "NO_PROMOTABLE_TIMEFRAME_EDGE_POCKET"
        )

        return {
            "verdict": verdict,
            "min_trade_count": min_trade_count,
            "gate_verdict": {
                "status": gate_status,
                "reason_codes": gate_reason_codes,
            },
            "best_sampled_pocket": best_sampled_pocket,
            "best_low_sample_pocket": best_low_sample_pocket,
            "top_rows": deduped_rows[:5],
            "positive_sampled_pocket_count": len(sampled_positive_rows),
            "positive_low_sample_pocket_count": len(low_sample_positive_rows),
        }

    @staticmethod
    def _build_market_archetype_diagnostics(scored_predictions: List[Dict]) -> Dict[str, Any]:
        min_trade_count = 5
        if not scored_predictions:
            return {
                "verdict": "NO_MARKET_ARCHETYPE_SAMPLE",
                "min_trade_count": min_trade_count,
                "gate_verdict": {
                    "status": "NO_MARKET_ARCHETYPE_SAMPLE",
                    "reason_codes": ["no_scorable_predictions"],
                },
                "best_sampled_pocket": {},
                "best_low_sample_pocket": {},
                "top_rows": [],
                "positive_sampled_pocket_count": 0,
                "positive_low_sample_pocket_count": 0,
            }

        def summarize(rows: List[Dict], *, timeframe: str, market_type: str, direction: str) -> Dict[str, Any]:
            count = len(rows)
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            avg_probability = (
                sum(float(row.get("consensus_probability", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            return {
                "timeframe": timeframe,
                "market_type": market_type,
                "direction": direction,
                "count": count,
                "wins": wins,
                "win_rate": round((wins / count), 3) if count > 0 else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_predicted_probability": round(avg_probability, 3) if count > 0 else 0.0,
            }

        rows: List[Dict[str, Any]] = []
        timeframes = sorted({str(row.get("timeframe", "unknown") or "unknown") for row in scored_predictions})
        market_types = sorted({str(row.get("market_type", "unknown") or "unknown") for row in scored_predictions})
        directions = sorted({str(row.get("consensus_prediction", "unknown") or "unknown").upper() for row in scored_predictions})
        for timeframe in timeframes:
            for market_type in market_types:
                for direction in directions:
                    filtered = [
                        row for row in scored_predictions
                        if str(row.get("timeframe", "unknown") or "unknown") == timeframe
                        and str(row.get("market_type", "unknown") or "unknown") == market_type
                        and str(row.get("consensus_prediction", "unknown") or "unknown").upper() == direction
                    ]
                    if filtered:
                        rows.append(
                            summarize(
                                filtered,
                                timeframe=timeframe,
                                market_type=market_type,
                                direction=direction,
                            )
                        )

        rows.sort(
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                str(item.get("direction", "") or ""),
                str(item.get("market_type", "") or ""),
                str(item.get("timeframe", "") or ""),
            ),
            reverse=True,
        )
        sampled_rows = [
            row for row in rows
            if int(row.get("count", 0) or 0) >= min_trade_count
        ]
        sampled_positive_rows = [
            row for row in sampled_rows
            if float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        low_sample_positive_rows = [
            row for row in rows
            if 0 < int(row.get("count", 0) or 0) < min_trade_count
            and float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        best_sampled_pocket = max(
            sampled_rows,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                str(item.get("direction", "") or ""),
                str(item.get("market_type", "") or ""),
                str(item.get("timeframe", "") or ""),
            ),
            default={},
        )
        best_low_sample_pocket = max(
            low_sample_positive_rows,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                str(item.get("direction", "") or ""),
                str(item.get("market_type", "") or ""),
                str(item.get("timeframe", "") or ""),
            ),
            default={},
        )

        gate_status = "NO_PROMOTABLE_MARKET_ARCHETYPE_POCKET"
        gate_reason_codes: List[str] = []
        if sampled_positive_rows:
            gate_status = "PROMOTABLE_MARKET_ARCHETYPE_POCKET_EXISTS"
        else:
            gate_reason_codes.append("best_sampled_market_archetype_pocket_still_negative_or_flat")
        if low_sample_positive_rows:
            gate_reason_codes.append("only_low_sample_positive_market_archetype_pocket")
            if all(str(row.get("direction", "") or "") == "NO" for row in low_sample_positive_rows):
                gate_reason_codes.append("only_positive_market_archetype_pockets_are_no_side")
        else:
            gate_reason_codes.append("no_positive_low_sample_market_archetype_pocket")

        verdict = (
            "PROMOTABLE_MARKET_ARCHETYPE_POCKET_EXISTS"
            if sampled_positive_rows
            else "ONLY_LOW_SAMPLE_MARKET_ARCHETYPE_PATCH"
            if low_sample_positive_rows
            else "NO_PROMOTABLE_MARKET_ARCHETYPE_POCKET"
        )

        return {
            "verdict": verdict,
            "min_trade_count": min_trade_count,
            "gate_verdict": {
                "status": gate_status,
                "reason_codes": gate_reason_codes,
            },
            "best_sampled_pocket": best_sampled_pocket,
            "best_low_sample_pocket": best_low_sample_pocket,
            "top_rows": rows[:5],
            "positive_sampled_pocket_count": len(sampled_positive_rows),
            "positive_low_sample_pocket_count": len(low_sample_positive_rows),
        }

    @staticmethod
    def _build_entry_price_diagnostics(scored_predictions: List[Dict]) -> Dict[str, Any]:
        min_trade_count = 5
        if not scored_predictions:
            return {
                "verdict": "NO_ENTRY_PRICE_SAMPLE",
                "min_trade_count": min_trade_count,
                "gate_verdict": {
                    "status": "NO_ENTRY_PRICE_SAMPLE",
                    "reason_codes": ["no_scorable_predictions"],
                },
                "best_sampled_pocket": {},
                "best_low_sample_pocket": {},
                "cheap_tail_all": {},
                "cheap_tail_bullish_no": {},
                "cheap_tail_bullish_no_fast": {},
                "top_rows": [],
                "positive_sampled_pocket_count": 0,
                "positive_low_sample_pocket_count": 0,
            }

        def price_band(value: float) -> str:
            if value <= 0.10:
                return "<=0.10"
            if value <= 0.20:
                return "0.10-0.20"
            if value <= 0.30:
                return "0.20-0.30"
            if value <= 0.40:
                return "0.30-0.40"
            return ">0.40"

        def summarize(
            rows: List[Dict],
            *,
            band: str,
            market_type: str,
            direction: str,
            timeframe_scope: str = "ALL",
        ) -> Dict[str, Any]:
            count = len(rows)
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            avg_entry_price = (
                sum(float(row.get("entry_price", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            avg_edge = (
                sum(float(row.get("edge_at_entry", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            return {
                "price_band": band,
                "market_type": market_type,
                "direction": direction,
                "timeframe_scope": timeframe_scope,
                "count": count,
                "wins": wins,
                "win_rate": round((wins / count), 3) if count > 0 else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_entry_price": round(avg_entry_price, 3) if count > 0 else 0.0,
                "avg_edge": round(avg_edge, 2) if count > 0 else 0.0,
            }

        def summarize_concentration(rows: List[Dict]) -> Dict[str, Any]:
            if not rows:
                return {}
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            largest_win = max(
                (float(row.get("net_pnl", 0.0) or 0.0) for row in rows),
                default=0.0,
            )
            largest_loss = min(
                (float(row.get("net_pnl", 0.0) or 0.0) for row in rows),
                default=0.0,
            )
            largest_win_share = (
                largest_win / total_pnl
                if total_pnl > 0.0 and largest_win > 0.0
                else None
            )
            unique_markets = len({
                str(row.get("market_id", "") or row.get("question", "") or "")
                for row in rows
                if str(row.get("market_id", "") or row.get("question", "") or "")
            })
            residual_without_largest_win = (
                total_pnl - largest_win
                if largest_win > 0.0
                else total_pnl
            )
            return {
                "count": len(rows),
                "unique_markets": unique_markets,
                "largest_win_pnl": round(largest_win, 2),
                "largest_loss_pnl": round(largest_loss, 2),
                "total_pnl": round(total_pnl, 2),
                "largest_win_share_of_total_pnl": round(largest_win_share, 3) if largest_win_share is not None else None,
                "residual_pnl_without_largest_win": round(residual_without_largest_win, 2),
                "survives_without_largest_win": residual_without_largest_win > 0.0,
            }

        def rows_matching(summary_row: Dict[str, Any]) -> List[Dict]:
            if not summary_row:
                return []
            timeframe_scope = str(summary_row.get("timeframe_scope", "ALL") or "ALL")
            return [
                row for row in scored_predictions
                if price_band(float(row.get("entry_price", 0.0) or 0.0)) == str(summary_row.get("price_band", "") or "")
                and str(row.get("market_type", "unknown") or "unknown") == str(summary_row.get("market_type", "") or "")
                and str(row.get("consensus_prediction", "unknown") or "unknown").upper() == str(summary_row.get("direction", "") or "")
                and (
                    timeframe_scope in {"", "ALL"}
                    or str(row.get("timeframe", "unknown") or "unknown") in set(timeframe_scope.split("+"))
                )
            ]

        rows: List[Dict[str, Any]] = []
        price_bands = sorted({price_band(float(row.get("entry_price", 0.0) or 0.0)) for row in scored_predictions})
        market_types = sorted({str(row.get("market_type", "unknown") or "unknown") for row in scored_predictions})
        directions = sorted({str(row.get("consensus_prediction", "unknown") or "unknown").upper() for row in scored_predictions})
        for band in price_bands:
            for market_type in market_types:
                for direction in directions:
                    filtered = [
                        row for row in scored_predictions
                        if price_band(float(row.get("entry_price", 0.0) or 0.0)) == band
                        and str(row.get("market_type", "unknown") or "unknown") == market_type
                        and str(row.get("consensus_prediction", "unknown") or "unknown").upper() == direction
                    ]
                    if filtered:
                        rows.append(
                            summarize(
                                filtered,
                                band=band,
                                market_type=market_type,
                                direction=direction,
                            )
                        )

        rows.sort(
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                -float(item.get("avg_entry_price", 0.0) or 0.0),
                str(item.get("direction", "") or ""),
                str(item.get("market_type", "") or ""),
                str(item.get("price_band", "") or ""),
            ),
            reverse=True,
        )
        sampled_rows = [
            row for row in rows
            if int(row.get("count", 0) or 0) >= min_trade_count
        ]
        sampled_positive_rows = [
            row for row in sampled_rows
            if float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        low_sample_positive_rows = [
            row for row in rows
            if 0 < int(row.get("count", 0) or 0) < min_trade_count
            and float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        best_sampled_pocket = max(
            sampled_rows,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                -float(item.get("avg_entry_price", 0.0) or 0.0),
                str(item.get("direction", "") or ""),
                str(item.get("market_type", "") or ""),
                str(item.get("price_band", "") or ""),
            ),
            default={},
        )
        best_low_sample_pocket = max(
            low_sample_positive_rows,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                -float(item.get("avg_entry_price", 0.0) or 0.0),
                str(item.get("direction", "") or ""),
                str(item.get("market_type", "") or ""),
                str(item.get("price_band", "") or ""),
            ),
            default={},
        )

        cheap_tail_all_rows = [
            row for row in scored_predictions
            if float(row.get("entry_price", 0.0) or 0.0) <= 0.10
        ]
        cheap_tail_bullish_no_rows = [
            row for row in cheap_tail_all_rows
            if str(row.get("market_type", "unknown") or "unknown") == "bullish"
            and str(row.get("consensus_prediction", "unknown") or "unknown").upper() == "NO"
        ]
        cheap_tail_bullish_no_fast_rows = [
            row for row in cheap_tail_bullish_no_rows
            if str(row.get("timeframe", "unknown") or "unknown") in {"intraday", "ultra_short"}
        ]
        cheap_tail_all = summarize(
            cheap_tail_all_rows,
            band="<=0.10",
            market_type="ALL",
            direction="ALL",
        ) if cheap_tail_all_rows else {}
        cheap_tail_bullish_no = summarize(
            cheap_tail_bullish_no_rows,
            band="<=0.10",
            market_type="bullish",
            direction="NO",
        ) if cheap_tail_bullish_no_rows else {}
        cheap_tail_bullish_no_fast = summarize(
            cheap_tail_bullish_no_fast_rows,
            band="<=0.10",
            market_type="bullish",
            direction="NO",
            timeframe_scope="intraday+ultra_short",
        ) if cheap_tail_bullish_no_fast_rows else {}
        best_low_sample_concentration = summarize_concentration(rows_matching(best_low_sample_pocket))
        cheap_tail_bullish_no_fast_concentration = summarize_concentration(cheap_tail_bullish_no_fast_rows)

        gate_status = "NO_PROMOTABLE_ENTRY_PRICE_POCKET"
        gate_reason_codes: List[str] = []
        if sampled_positive_rows:
            gate_status = "PROMOTABLE_ENTRY_PRICE_POCKET_EXISTS"
        else:
            gate_reason_codes.append("best_sampled_entry_price_pocket_still_negative_or_flat")
        if low_sample_positive_rows:
            gate_reason_codes.append("only_low_sample_positive_entry_price_pocket")
            if all(
                str(row.get("price_band", "") or "") == "<=0.10"
                and str(row.get("market_type", "") or "") == "bullish"
                and str(row.get("direction", "") or "") == "NO"
                for row in low_sample_positive_rows
            ):
                gate_reason_codes.append("only_positive_entry_price_pockets_are_cheap_bullish_no")
        else:
            gate_reason_codes.append("no_positive_low_sample_entry_price_pocket")

        verdict = (
            "PROMOTABLE_ENTRY_PRICE_POCKET_EXISTS"
            if sampled_positive_rows
            else "ONLY_LOW_SAMPLE_ENTRY_PRICE_PATCH"
            if low_sample_positive_rows
            else "NO_PROMOTABLE_ENTRY_PRICE_POCKET"
        )

        return {
            "verdict": verdict,
            "min_trade_count": min_trade_count,
            "gate_verdict": {
                "status": gate_status,
                "reason_codes": gate_reason_codes,
            },
            "best_sampled_pocket": best_sampled_pocket,
            "best_low_sample_pocket": best_low_sample_pocket,
            "cheap_tail_all": cheap_tail_all,
            "cheap_tail_bullish_no": cheap_tail_bullish_no,
            "cheap_tail_bullish_no_fast": cheap_tail_bullish_no_fast,
            "best_low_sample_concentration": best_low_sample_concentration,
            "cheap_tail_bullish_no_fast_concentration": cheap_tail_bullish_no_fast_concentration,
            "top_rows": rows[:5],
            "positive_sampled_pocket_count": len(sampled_positive_rows),
            "positive_low_sample_pocket_count": len(low_sample_positive_rows),
        }

    @staticmethod
    def _build_direction_diagnostics(scored_predictions: List[Dict]) -> Dict[str, Any]:
        if not scored_predictions:
            return {
                "verdict": "NO_DIRECTIONAL_SAMPLE",
                "gate_verdict": {"status": "NO_DIRECTIONAL_SAMPLE", "reason_codes": ["no_scorable_predictions"]},
                "by_direction": {},
                "best_direction": {},
            }

        def summarize(rows: List[Dict]) -> Dict[str, Any]:
            count = len(rows)
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            avg_probability = (
                sum(float(row.get("consensus_probability", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            return {
                "count": count,
                "wins": wins,
                "win_rate": round((wins / count), 3) if count > 0 else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_predicted_probability": round(avg_probability, 3) if count > 0 else 0.0,
            }

        by_direction: Dict[str, Dict[str, Any]] = {}
        for direction in ("YES", "NO", "ABSTAIN"):
            rows = [row for row in scored_predictions if str(row.get("consensus_prediction", "") or "").upper() == direction]
            if rows:
                by_direction[direction] = summarize(rows)
        by_direction_timeframe: Dict[str, Dict[str, Any]] = {}
        for direction in ("YES", "NO", "ABSTAIN"):
            for timeframe in sorted({str(row.get("timeframe", "unknown") or "unknown") for row in scored_predictions}):
                rows = [
                    row for row in scored_predictions
                    if str(row.get("consensus_prediction", "") or "").upper() == direction
                    and str(row.get("timeframe", "unknown") or "unknown") == timeframe
                ]
                if rows:
                    by_direction_timeframe[f"{direction}:{timeframe}"] = {
                        "direction": direction,
                        "timeframe": timeframe,
                        **summarize(rows),
                    }

        best_direction = max(
            (
                {"direction": direction, **stats}
                for direction, stats in by_direction.items()
            ),
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
            ),
            default={},
        )
        best_direction_timeframe = max(
            by_direction_timeframe.values(),
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
            ),
            default={},
        )
        negative_direction_timeframes = sorted(
            [
                item
                for item in by_direction_timeframe.values()
                if float(item.get("total_pnl", 0.0) or 0.0) < 0.0
            ],
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                -int(item.get("count", 0) or 0),
            ),
        )
        total_negative_directional_loss = sum(
            abs(float(item.get("total_pnl", 0.0) or 0.0))
            for item in negative_direction_timeframes
        )
        top_negative_direction_timeframes = []
        for item in negative_direction_timeframes[:3]:
            row = dict(item)
            pnl_abs = abs(float(row.get("total_pnl", 0.0) or 0.0))
            row["drag_share_of_negative_loss"] = (
                round(pnl_abs / total_negative_directional_loss, 3)
                if total_negative_directional_loss > 0.0
                else 0.0
            )
            top_negative_direction_timeframes.append(row)
        worst_direction_timeframe = top_negative_direction_timeframes[0] if top_negative_direction_timeframes else {}
        top_two_directional_drag_share = (
            round(sum(float(item.get("drag_share_of_negative_loss", 0.0) or 0.0) for item in top_negative_direction_timeframes[:2]), 3)
            if top_negative_direction_timeframes
            else 0.0
        )
        total_directional_pnl = round(sum(float(item.get("total_pnl", 0.0) or 0.0) for item in by_direction_timeframe.values()), 2)
        exclusion_scenarios = []
        ranked_keys = [
            f"{str(item.get('direction', '') or '')}:{str(item.get('timeframe', '') or '')}"
            for item in negative_direction_timeframes
        ]
        scenario_definitions = [
            ("drop_worst_pocket", set(ranked_keys[:1])),
            ("drop_top2_pockets", set(ranked_keys[:2])),
            ("drop_top3_pockets", set(ranked_keys[:3])),
            ("drop_all_yes", {key for key in by_direction_timeframe if key.startswith("YES:")}),
        ]
        for label, excluded_keys in scenario_definitions:
            removed_count = 0
            removed_pnl = 0.0
            for key, row in by_direction_timeframe.items():
                if key in excluded_keys:
                    removed_count += int(row.get("count", 0) or 0)
                    removed_pnl += float(row.get("total_pnl", 0.0) or 0.0)
            exclusion_scenarios.append(
                {
                    "label": label,
                    "excluded_keys": sorted(excluded_keys),
                    "removed_count": removed_count,
                    "removed_pnl": round(removed_pnl, 2),
                    "residual_pnl": round(total_directional_pnl - removed_pnl, 2),
                }
            )
        exclusion_rescue_status = "NO_SIMPLE_EXCLUSION_RESCUE"
        exclusion_rescue_reasons: List[str] = []
        if exclusion_scenarios and any(float(row.get("residual_pnl", 0.0) or 0.0) > 0.0 for row in exclusion_scenarios):
            exclusion_rescue_status = "PARTIAL_EXCLUSION_RESCUE_EXISTS"
        else:
            exclusion_rescue_reasons.append("residual_negative_after_all_simple_cuts")
        if top_negative_direction_timeframes and float(top_negative_direction_timeframes[0].get("drag_share_of_negative_loss", 0.0) or 0.0) < 0.5:
            exclusion_rescue_reasons.append("worst_pocket_not_dominant_enough")
        if exclusion_scenarios:
            best_residual = max(float(row.get("residual_pnl", 0.0) or 0.0) for row in exclusion_scenarios)
            if best_residual <= 0.0:
                exclusion_rescue_reasons.append("best_residual_still_negative")

        verdict = "MIXED_DIRECTION_SIGNAL"
        reason_codes: List[str] = []
        yes_stats = by_direction.get("YES", {})
        no_stats = by_direction.get("NO", {})
        if yes_stats and int(yes_stats.get("count", 0) or 0) >= 5 and float(yes_stats.get("win_rate", 0.0) or 0.0) <= 0.05 and float(yes_stats.get("total_pnl", 0.0) or 0.0) < 0.0:
            verdict = "YES_DIRECTION_ANTI_SIGNAL"
            reason_codes.append("yes_direction_losing")
        if best_direction and float(best_direction.get("total_pnl", 0.0) or 0.0) <= 0.0:
            reason_codes.append("best_direction_still_negative")
        if yes_stats and no_stats and float(yes_stats.get("total_pnl", 0.0) or 0.0) < float(no_stats.get("total_pnl", 0.0) or 0.0):
            reason_codes.append("yes_worse_than_no")

        gate_status = "NO_PROMOTABLE_DIRECTION_GATE"
        if best_direction and int(best_direction.get("count", 0) or 0) >= 5 and float(best_direction.get("total_pnl", 0.0) or 0.0) > 0.0:
            gate_status = "PROMOTABLE_DIRECTION_GATE"
        pocket_reason_codes: List[str] = []
        pocket_status = "NO_PROMOTABLE_DIRECTION_TIMEFRAME_POCKET"
        if best_direction_timeframe:
            best_pocket_count = int(best_direction_timeframe.get("count", 0) or 0)
            best_pocket_pnl = float(best_direction_timeframe.get("total_pnl", 0.0) or 0.0)
            best_pocket_direction = str(best_direction_timeframe.get("direction", "") or "")
            best_pocket_timeframe = str(best_direction_timeframe.get("timeframe", "") or "")
            if best_pocket_count >= 5 and best_pocket_pnl > 0.0:
                pocket_status = "PROMOTABLE_DIRECTION_TIMEFRAME_POCKET"
            else:
                if best_pocket_pnl <= 0.0:
                    pocket_reason_codes.append("best_pocket_still_negative")
                if 0 < best_pocket_count < 5:
                    pocket_reason_codes.append("best_pocket_low_sample")
                if best_pocket_direction == "NO" and best_pocket_timeframe == "ultra_short":
                    pocket_reason_codes.append("only_positive_pocket_is_no_ultra_short")

        return {
            "verdict": verdict,
            "gate_verdict": {
                "status": gate_status,
                "reason_codes": reason_codes,
            },
            "by_direction": by_direction,
            "by_direction_timeframe": by_direction_timeframe,
            "best_direction": best_direction,
            "best_direction_timeframe": best_direction_timeframe,
            "worst_direction_timeframe": worst_direction_timeframe,
            "top_negative_direction_timeframes": top_negative_direction_timeframes,
            "top_two_directional_drag_share": top_two_directional_drag_share,
            "exclusion_rescue": {
                "status": exclusion_rescue_status,
                "reason_codes": exclusion_rescue_reasons,
                "scenarios": exclusion_scenarios,
            },
            "pocket_verdict": {
                "status": pocket_status,
                "reason_codes": pocket_reason_codes,
            },
        }

    @staticmethod
    def _build_policy_rescue_diagnostics(scored_predictions: List[Dict]) -> Dict[str, Any]:
        min_trade_count = 5
        if not scored_predictions:
            return {
                "verdict": "NO_COMPOSITE_POLICY_SAMPLE",
                "min_trade_count": min_trade_count,
                "gate_verdict": {
                    "status": "NO_COMPOSITE_POLICY_SAMPLE",
                    "reason_codes": ["no_scorable_predictions"],
                },
                "best_sampled_policy": {},
                "best_low_sample_policy": {},
                "top_rows": [],
                "positive_sampled_policy_count": 0,
                "positive_low_sample_policy_count": 0,
            }

        def summarize(rows: List[Dict], *, direction: str, timeframe: str, confidence_filter: str, active_filters: List[str]) -> Dict[str, Any]:
            count = len(rows)
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            total_pnl = sum(float(row.get("net_pnl", 0.0) or 0.0) for row in rows)
            avg_probability = (
                sum(float(row.get("consensus_probability", 0.0) or 0.0) for row in rows) / count
                if count > 0
                else 0.0
            )
            return {
                "direction": direction,
                "timeframe": timeframe,
                "confidence_filter": confidence_filter,
                "active_filters": active_filters,
                "count": count,
                "wins": wins,
                "win_rate": round((wins / count), 3) if count > 0 else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_predicted_probability": round(avg_probability, 3) if count > 0 else 0.0,
            }

        timeframes = sorted({str(row.get("timeframe", "unknown") or "unknown") for row in scored_predictions})
        direction_options = [("ALL", None), ("YES", "YES"), ("NO", "NO")]
        timeframe_options = [("ALL", None)] + [(tf, tf) for tf in timeframes]
        confidence_options = [
            ("ALL", None, None),
            ("cap<=30%", "cap", 0.3),
            ("cap<=40%", "cap", 0.4),
            ("cap<=50%", "cap", 0.5),
            ("floor>=50%", "floor", 0.5),
            ("floor>=60%", "floor", 0.6),
            ("floor>=70%", "floor", 0.7),
        ]

        rows: List[Dict[str, Any]] = []
        for direction_label, direction_value in direction_options:
            for timeframe_label, timeframe_value in timeframe_options:
                for confidence_label, confidence_mode, confidence_threshold in confidence_options:
                    active_filters: List[str] = []
                    filtered = scored_predictions
                    if direction_value is not None:
                        filtered = [
                            row for row in filtered
                            if str(row.get("consensus_prediction", "") or "").upper() == direction_value
                        ]
                        active_filters.append(f"direction={direction_value}")
                    if timeframe_value is not None:
                        filtered = [
                            row for row in filtered
                            if str(row.get("timeframe", "unknown") or "unknown") == timeframe_value
                        ]
                        active_filters.append(f"timeframe={timeframe_value}")
                    if confidence_mode == "cap" and confidence_threshold is not None:
                        filtered = [
                            row for row in filtered
                            if float(row.get("consensus_probability", 0.0) or 0.0) <= confidence_threshold
                        ]
                        active_filters.append(f"confidence<={int(confidence_threshold * 100)}%")
                    elif confidence_mode == "floor" and confidence_threshold is not None:
                        filtered = [
                            row for row in filtered
                            if float(row.get("consensus_probability", 0.0) or 0.0) >= confidence_threshold
                        ]
                        active_filters.append(f"confidence>={int(confidence_threshold * 100)}%")
                    if len(active_filters) < 2 or not filtered:
                        continue
                    rows.append(
                        summarize(
                            filtered,
                            direction=direction_label,
                            timeframe=timeframe_label,
                            confidence_filter=confidence_label,
                            active_filters=active_filters,
                        )
                    )

        rows.sort(
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
                -len(item.get("active_filters", []) or []),
            ),
            reverse=True,
        )
        sampled_positive_rows = [
            row for row in rows
            if int(row.get("count", 0) or 0) >= min_trade_count
            and float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        low_sample_positive_rows = [
            row for row in rows
            if 0 < int(row.get("count", 0) or 0) < min_trade_count
            and float(row.get("total_pnl", 0.0) or 0.0) > 0.0
        ]
        best_sampled_policy = max(
            (row for row in rows if int(row.get("count", 0) or 0) >= min_trade_count),
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
            ),
            default={},
        )
        best_low_sample_policy = max(
            low_sample_positive_rows,
            key=lambda item: (
                float(item.get("total_pnl", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("count", 0) or 0),
            ),
            default={},
        )

        gate_status = "NO_PROMOTABLE_COMPOSITE_POLICY"
        gate_reason_codes: List[str] = []
        if sampled_positive_rows:
            gate_status = "PROMOTABLE_COMPOSITE_POLICY_EXISTS"
        else:
            gate_reason_codes.append("best_sampled_policy_still_negative_or_flat")
        if low_sample_positive_rows:
            gate_reason_codes.append("only_low_sample_positive_composite_policy")
        else:
            gate_reason_codes.append("no_positive_low_sample_composite_policy")

        verdict = (
            "PROMOTABLE_COMPOSITE_POLICY_EXISTS"
            if sampled_positive_rows
            else "ONLY_LOW_SAMPLE_COMPOSITE_PATCH"
            if low_sample_positive_rows
            else "NO_PROMOTABLE_COMPOSITE_POLICY"
        )

        return {
            "verdict": verdict,
            "min_trade_count": min_trade_count,
            "gate_verdict": {
                "status": gate_status,
                "reason_codes": gate_reason_codes,
            },
            "best_sampled_policy": best_sampled_policy,
            "best_low_sample_policy": best_low_sample_policy,
            "top_rows": rows[:5],
            "positive_sampled_policy_count": len(sampled_positive_rows),
            "positive_low_sample_policy_count": len(low_sample_positive_rows),
        }

    def _build_replay_summary(self) -> Optional[Dict[str, Any]]:
        try:
            scorer = BacktestScorer(data_dirs=[str(self.config.data_dir)])
            params = ParamSet.from_config(self.config)
            replay_summary = scorer.score_replay(params).to_dict()
            replay_summary["trailing_holdout_probe"] = self._build_trailing_holdout_probe(
                scorer,
                params,
            )
            return replay_summary
        except Exception as exc:
            cprint(f"Failed to build replay summary: {exc}", "yellow")
            return None

    def _build_trailing_holdout_probe(
        self,
        scorer: BacktestScorer,
        params: ParamSet,
    ) -> Dict[str, Any]:
        """Diagnostic-only sweep to show whether any wider late cohort has support."""
        probe_rows = []
        ratios = (0.2, 0.3, 0.4, 0.5)
        for ratio in ratios:
            replay = scorer.score_replay(
                params,
                holdout_ratio=ratio,
                min_filtered_trades=1,
                min_holdout_trades=1,
            )
            probe_rows.append(
                {
                    "holdout_ratio": round(float(ratio), 2),
                    "raw_holdout_trades": int(replay.holdout_total_trades),
                    "filtered_holdout_trades": int(replay.holdout.filtered_trades),
                    "holdout_score": round(float(replay.holdout.score), 2),
                    "holdout_pnl": round(float(replay.holdout.total_pnl), 2),
                    "baseline_holdout_score": round(float(replay.baseline_holdout.score), 2),
                    "baseline_holdout_pnl": round(float(replay.baseline_holdout.total_pnl), 2),
                    "accepted": bool(replay.accepted),
                    "gate_feasible": bool(replay.gate_feasible),
                    "notes": list(replay.notes),
                }
            )

        best_row = max(
            probe_rows,
            key=lambda row: (
                int(row["filtered_holdout_trades"]),
                float(row["holdout_score"]),
                int(row["raw_holdout_trades"]),
            ),
            default=None,
        )
        any_filtered_holdout = any(int(row["filtered_holdout_trades"]) > 0 for row in probe_rows)
        return {
            "diagnostic_only": True,
            "shipping_gate_unchanged": True,
            "min_filtered_trades": 1,
            "min_holdout_trades": 1,
            "any_filtered_holdout": any_filtered_holdout,
            "best_filtered_holdout_trades": int(best_row["filtered_holdout_trades"]) if best_row else 0,
            "best_holdout_ratio": (
                float(best_row["holdout_ratio"])
                if best_row and int(best_row["filtered_holdout_trades"]) > 0
                else None
            ),
            "ratios": probe_rows,
        }

    def _write_trade_journal(self, journal: List[Dict]):
        if not journal:
            return
        path = self.perf_dir / "trade_journal.csv"
        fields = [
            "trade_id", "entry_trade_id", "close_trade_id", "market_id", "question", "symbol",
            "side", "close_side", "actual_side", "source", "entry_time", "exit_time",
            "entry_price", "exit_price", "size_usd", "fees", "net_pnl", "outcome",
            "is_closed", "edge_at_entry", "swarm_probability", "confidence",
            "consensus_prediction", "consensus_probability", "consensus_confidence",
            "prediction_timestamp", "prediction_age_minutes", "prediction_match",
            "prediction_model_count", "prediction_successful_model_count",
            "prediction_runtime_ready", "prediction_measurement_boundary",
            "prediction_analysis_cohort", "prediction_linked", "timeframe", "market_type",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(journal)
        cprint(f"Trade journal: {path} ({len(journal)} trades)", "green")

    def _write_calibration(self, calibration: List[Dict]):
        if not calibration:
            return
        path = self.perf_dir / "calibration.csv"
        fields = [
            "group_type", "group_value", "probability_bucket", "trade_count", "wins",
            "losses", "actual_win_rate", "avg_predicted_probability", "brier_score",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(calibration)
        cprint(f"Calibration:   {path} ({len(calibration)} buckets)", "green")

    def _write_model_accuracy(self, model_accuracy: List[Dict]):
        if not model_accuracy:
            return
        path = self.perf_dir / "model_accuracy.csv"
        fields = [
            "model", "total_predictions", "correct", "accuracy", "avg_confidence",
            "avg_probability_estimate", "yes_predictions", "no_predictions", "linked_trades",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(model_accuracy)
        cprint(f"Model accuracy: {path} ({len(model_accuracy)} models)", "green")

    def _write_replay_summary(self, replay_summary: Dict[str, Any]):
        path = self.perf_dir / "replay_summary.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(replay_summary, f, indent=2)
        cprint(f"Replay summary: {path}", "green")

    def _write_summary(self, summary: Dict):
        path = self.perf_dir / "summary.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        cprint(f"Summary:       {path}", "green")

    def _print_summary(self, summary: Dict, calibration: List[Dict], model_accuracy: List[Dict]):
        cprint("\n" + "=" * 60, "cyan")
        cprint("PERFORMANCE REPORT", "cyan", attrs=["bold"])
        cprint("=" * 60, "cyan")
        print(f"Total trades: {summary.get('total_trades', 0)} (closed: {summary.get('closed_trades', 0)}, open: {summary.get('open_trades', 0)})")
        if summary.get("closed_trades", 0) > 0:
            print(f"Win rate:     {summary.get('win_rate', 0):.1%} ({summary.get('wins', 0)}W / {summary.get('losses', 0)}L)")
            print(f"Total P&L:    ${summary.get('total_pnl', 0):+.2f}")
            print(f"Total fees:   ${summary.get('total_fees', 0):.2f}")
            print(f"Avg win:      ${summary.get('avg_win', 0):+.2f}")
            print(f"Avg loss:     ${summary.get('avg_loss', 0):+.2f}")
            print(f"Profit factor: {summary.get('profit_factor', 0)}")
            print(f"Max drawdown: ${summary.get('max_drawdown', 0):.2f}")
            for label, stats in (("Source", summary.get("by_source", {})), ("Timeframe", summary.get("by_timeframe", {}))):
                if stats:
                    print(f"\nBy {label}:")
                    for key, row in stats.items():
                        print(f"  {key:12s}: {row['count']:3d} trades, P&L ${row['pnl']:+.2f}, WR {row['win_rate']:.1%}")
        if calibration:
            print(f"\nCalibration (predicted prob vs actual win rate):")
            for row in calibration:
                bar = "#" * int(row["actual_win_rate"] * 20)
                print(f"  {row['group_type']}/{row['group_value']:<12s} {row['probability_bucket']:8s}: {row['actual_win_rate']:.0%} actual (n={row['trade_count']:3d}) {bar}")
        if model_accuracy:
            print(f"\nModel Accuracy:")
            for row in model_accuracy:
                print(f"  {row['model']:30s}: {row['accuracy']:.1%} (n={row['total_predictions']}, avg_conf={row['avg_confidence']:.2f})")
        if summary.get("replay"):
            replay = summary["replay"]
            print(
                "\nReplay Gate: "
                f"accepted={replay.get('accepted', False)} | "
                f"candidate_score={replay.get('candidate', {}).get('score', 0):.2f} | "
                f"holdout_score={replay.get('holdout', {}).get('score', 0):.2f} | "
                f"baseline_holdout={replay.get('baseline_holdout', {}).get('score', 0):.2f}"
            )
        cprint("=" * 60 + "\n", "cyan")

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _trade_sort_key(trade: Dict) -> Tuple[datetime, str, str]:
        ts = PerformanceTracker._parse_timestamp(trade.get("_entry_ts") or trade.get("entry_time") or trade.get("timestamp")) or datetime.min
        return ts, str(trade.get("market_id", "")), str(trade.get("trade_id", ""))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
            return default if parsed != parsed else parsed
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_side(value: Any) -> str:
        side = str(value or "").strip().upper()
        return side if side in {"YES", "NO"} or side.startswith("CLOSE_") else side

    @staticmethod
    def _opposite_side(side: str) -> str:
        if side == "YES":
            return "NO"
        if side == "NO":
            return "YES"
        return "FLAT"

    @staticmethod
    def _parse_edge_from_reason(reason: str) -> Optional[float]:
        import re
        match = re.search(r"([\d.]+)%\s*edge", reason, re.IGNORECASE)
        if match:
            return float(match.group(1))
        match = re.search(r"Edge:\s*([\d.]+)%", reason)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _parse_prob_from_reason(reason: str) -> Optional[float]:
        import re
        match = re.search(r"prob=([\d.]+)", reason)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _classify_timeframe(time_remaining_hours: Optional[float], duration_minutes: Optional[int]) -> str:
        if duration_minutes:
            if duration_minutes <= 30:
                return "ultra_short"
            if duration_minutes <= 240:
                return "intraday"
            if duration_minutes <= 1440:
                return "daily"
            return "weekly"
        if time_remaining_hours is not None:
            if time_remaining_hours <= 1:
                return "ultra_short"
            if time_remaining_hours <= 6:
                return "intraday"
            if time_remaining_hours <= 24:
                return "daily"
            return "weekly"
        return "unknown"


if __name__ == "__main__":
    PerformanceTracker().generate_report()
