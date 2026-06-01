"""
Backtest Scorer for AutoTrader

Replays historical trades against a parameter set to evaluate
strategy quality WITHOUT waiting for live market resolution.

Loads resolved trades (entries + outcomes), applies parameter
filters (edge threshold, kelly sizing, confidence), and scores
the result.
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ParamSet:
    """Parameter set to evaluate."""

    min_edge_threshold: float = 15.0
    min_edge_confidence: float = 0.50
    kelly_fraction: float = 0.25
    min_arb_edge_percent: float = 27.0
    max_position_usd: float = 30.0
    max_markets_to_analyze: int = 5
    min_arb_token_price: float = 0.03
    # Which sources to allow
    allow_swarm: bool = True
    allow_arb: bool = True
    # Filters
    min_expiry_hours: float = 4.0
    max_expiry_hours: float = 24.0
    # Symbol filters
    allowed_symbols: list = field(default_factory=lambda: ["ETH"])

    @classmethod
    def from_config(cls, config: Any) -> "ParamSet":
        symbols = [
            str(sym).strip().upper()
            for sym in getattr(config, "search_symbols", ["ETH"])
            if str(sym).strip()
        ] or ["ETH"]
        return cls(
            min_edge_threshold=float(getattr(config, "min_edge_threshold", cls.min_edge_threshold)),
            min_edge_confidence=float(getattr(config, "min_edge_confidence", cls.min_edge_confidence)),
            kelly_fraction=float(getattr(config, "kelly_fraction", cls.kelly_fraction)),
            min_arb_edge_percent=float(getattr(config, "min_arb_edge_percent", cls.min_arb_edge_percent)),
            max_position_usd=float(getattr(config, "max_position_usd", cls.max_position_usd)),
            max_markets_to_analyze=int(getattr(config, "max_markets_to_analyze", cls.max_markets_to_analyze)),
            min_arb_token_price=float(getattr(config, "min_arb_token_price", cls.min_arb_token_price)),
            min_expiry_hours=getattr(config, "min_expiry_hours", cls.min_expiry_hours),
            max_expiry_hours=getattr(config, "max_expiry_hours", cls.max_expiry_hours),
            allowed_symbols=symbols,
        )


@dataclass
class BacktestResult:
    """Result of scoring a parameter set against historical trades."""

    total_trades: int = 0
    filtered_trades: int = 0  # trades that pass the parameter filters
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_deployed: float = 0.0
    win_rate: float = 0.0
    roi: float = 0.0  # total_pnl / total_deployed
    score: float = 0.0  # composite metric
    by_source: Dict = field(default_factory=dict)
    by_symbol: Dict = field(default_factory=dict)
    by_timeframe: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "filtered_trades": self.filtered_trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": self.total_pnl,
            "total_deployed": self.total_deployed,
            "win_rate": self.win_rate,
            "roi": self.roi,
            "score": self.score,
            "by_source": self.by_source,
            "by_symbol": self.by_symbol,
            "by_timeframe": self.by_timeframe,
        }


@dataclass
class ReplayResult:
    """Holdout replay result with an acceptance-gate verdict."""

    candidate: BacktestResult
    baseline: BacktestResult
    train: BacktestResult
    holdout: BacktestResult
    baseline_holdout: BacktestResult
    accepted: bool
    holdout_ratio: float
    split_markets: int
    train_markets: int
    holdout_markets: int
    generalization_gap: float
    holdout_total_trades: int = 0
    gate_feasible: bool = False
    cohort_diagnostics: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "baseline": self.baseline.to_dict(),
            "train": self.train.to_dict(),
            "holdout": self.holdout.to_dict(),
            "baseline_holdout": self.baseline_holdout.to_dict(),
            "accepted": self.accepted,
            "holdout_ratio": self.holdout_ratio,
            "split_markets": self.split_markets,
            "train_markets": self.train_markets,
            "holdout_markets": self.holdout_markets,
            "holdout_total_trades": self.holdout_total_trades,
            "gate_feasible": self.gate_feasible,
            "generalization_gap": self.generalization_gap,
            "cohort_diagnostics": self.cohort_diagnostics,
            "notes": self.notes,
        }


class BacktestScorer:
    """
    Fast backtester that scores parameter sets against historical trades.

    Usage:
        scorer = BacktestScorer()
        result = scorer.score(ParamSet(min_edge_threshold=5.0))
        print(f"Score: {result.score}")
    """

    def __init__(self, data_dirs: Optional[List[str]] = None):
        if data_dirs is None:
            data_dirs = [
                "src/data/polymarket_cli",
                "src/data/polymarket_cli_weekly",
                "src/data/polymarket_cli_intraday",
                "src/data/polymarket_cli_daily",
                "src/data/polymarket_trader_daily",
                "src/data/polymarket_trader_weekly",
                "src/data/polymarket_trader_short",
            ]
        self.trades = self._load_resolved_trades(data_dirs)

    def _load_trade_rows(self, data_dirs: List[str]) -> Tuple[Dict[str, List[Dict]], Dict[str, List[Dict]]]:
        """Load raw entry and close rows, grouped by market_id."""
        entries_by_market: Dict[str, List[Dict]] = defaultdict(list)
        closes_by_market: Dict[str, List[Dict]] = defaultdict(list)

        for base_dir in data_dirs:
            trades_dir = Path(base_dir) / "trades"
            if not trades_dir.exists():
                continue

            for f in sorted(trades_dir.glob("trades_*.jsonl")):
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        for row_index, line in enumerate(fh):
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                trade = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            market_id = str(trade.get("market_id", "")).strip()
                            if not market_id:
                                continue

                            trade["_source_file"] = str(f)
                            trade["_source_index"] = row_index
                            if str(trade.get("side", "")).upper().startswith("CLOSE"):
                                closes_by_market[market_id].append(trade)
                            else:
                                entries_by_market[market_id].append(trade)
                except OSError:
                    continue

        return entries_by_market, closes_by_market

    def _load_resolved_trades(self, data_dirs: List[str]) -> List[Dict]:
        """Load all trades and match entries with closes."""
        entries_by_market, closes_by_market = self._load_trade_rows(data_dirs)

        resolved: List[Dict] = []
        for market_id, entries in entries_by_market.items():
            sorted_entries = sorted(entries, key=self._trade_sort_key)
            sorted_closes = sorted(closes_by_market.get(market_id, []), key=self._trade_sort_key)

            close_cursor = 0
            for entry in sorted_entries:
                close, close_cursor = self._match_close(entry, sorted_closes, close_cursor)
                if not close:
                    continue

                resolved_trade = self._resolve_trade_record(entry, close)
                if resolved_trade is not None:
                    resolved.append(resolved_trade)

        return resolved

    def _score_trade_subset(self, trades: List[Dict], params: ParamSet) -> BacktestResult:
        """Score a specific trade subset against a parameter set."""
        filtered, _ = self._filter_trade_subset(trades, params)
        result = BacktestResult(total_trades=len(trades))
        return self._build_result_from_filtered(result, filtered)

    def _filter_trade_subset(
        self,
        trades: List[Dict],
        params: ParamSet,
    ) -> Tuple[List[Tuple[Dict, float]], Dict[str, int]]:
        filtered: List[Tuple[Dict, float]] = []
        exclusion_reasons: Counter[str] = Counter()

        for trade in trades:
            source = str(trade.get("source", "") or "")
            if source == "swarm" and not params.allow_swarm:
                exclusion_reasons["source_swarm_disabled"] += 1
                continue
            if source == "arbitrage" and not params.allow_arb:
                exclusion_reasons["source_arbitrage_disabled"] += 1
                continue

            sym = str(trade.get("symbol", "OTHER") or "OTHER")
            if sym not in params.allowed_symbols and "OTHER" not in params.allowed_symbols:
                exclusion_reasons["symbol_filtered"] += 1
                continue

            hours_remaining = self._safe_float(trade.get("_hours_remaining"))
            if params.min_expiry_hours is not None:
                if hours_remaining is None or hours_remaining < float(params.min_expiry_hours):
                    exclusion_reasons["expiry_too_short"] += 1
                    continue
            if params.max_expiry_hours is not None:
                if hours_remaining is None or hours_remaining > float(params.max_expiry_hours):
                    exclusion_reasons["expiry_too_far"] += 1
                    continue

            edge = trade.get("_edge", 0)
            if source == "swarm" and edge < params.min_edge_threshold:
                exclusion_reasons["edge_below_threshold"] += 1
                continue
            if source == "arbitrage" and edge < params.min_arb_edge_percent:
                exclusion_reasons["arb_edge_below_threshold"] += 1
                continue

            conf = trade.get("_confidence", 0)
            if source == "swarm" and conf < params.min_edge_confidence:
                exclusion_reasons["confidence_below_threshold"] += 1
                continue

            size = trade.get("size_usd", 0)
            scale = params.max_position_usd / size if size > params.max_position_usd and size > 0 else 1.0
            filtered.append((trade, scale))

        return filtered, dict(exclusion_reasons)

    def _build_result_from_filtered(
        self,
        result: BacktestResult,
        filtered: List[Tuple[Dict, float]],
    ) -> BacktestResult:

        by_source = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        by_symbol = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        by_timeframe = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})

        for trade, scale in filtered:
            pnl = trade["_pnl"] * scale
            size = trade.get("size_usd", 0) * scale
            is_win = pnl > 0

            result.filtered_trades += 1
            result.total_pnl += pnl
            result.total_deployed += size
            if is_win:
                result.wins += 1
            else:
                result.losses += 1

            src = trade.get("source", "unknown")
            by_source[src]["count"] += 1
            by_source[src]["pnl"] += pnl
            if is_win:
                by_source[src]["wins"] += 1

            sym = trade.get("symbol", "OTHER")
            by_symbol[sym]["count"] += 1
            by_symbol[sym]["pnl"] += pnl
            if is_win:
                by_symbol[sym]["wins"] += 1

            tf = trade.get("_timeframe", "unknown")
            by_timeframe[tf]["count"] += 1
            by_timeframe[tf]["pnl"] += pnl
            if is_win:
                by_timeframe[tf]["wins"] += 1

        result.by_source = {
            k: {
                "count": v["count"],
                "pnl": round(v["pnl"], 2),
                "win_rate": round(v["wins"] / v["count"], 3) if v["count"] > 0 else 0,
            }
            for k, v in by_source.items()
        }
        result.by_symbol = {
            k: {
                "count": v["count"],
                "pnl": round(v["pnl"], 2),
                "win_rate": round(v["wins"] / v["count"], 3) if v["count"] > 0 else 0,
            }
            for k, v in by_symbol.items()
        }
        result.by_timeframe = {
            k: {
                "count": v["count"],
                "pnl": round(v["pnl"], 2),
                "win_rate": round(v["wins"] / v["count"], 3) if v["count"] > 0 else 0,
            }
            for k, v in by_timeframe.items()
        }

        if result.filtered_trades > 0:
            result.win_rate = result.wins / result.filtered_trades
        if result.total_deployed > 0:
            result.roi = result.total_pnl / result.total_deployed

        trade_penalty = min(result.filtered_trades / 10.0, 1.0)
        result.score = (result.win_rate * 100 + result.roi * 100) * trade_penalty
        return result

    def _build_subset_diagnostics(
        self,
        trades: List[Dict],
        filtered: List[Tuple[Dict, float]],
        exclusion_reasons: Dict[str, int],
    ) -> Dict[str, Any]:
        timestamps = [
            self._parse_timestamp(trade.get("_entry_ts") or trade.get("entry_time") or trade.get("timestamp"))
            for trade in trades
        ]
        timestamps = sorted(ts for ts in timestamps if ts is not None)
        sorted_trades = sorted(trades, key=self._trade_sort_key)

        return {
            "total_trades": len(trades),
            "filtered_trades": len(filtered),
            "unique_markets": len({str(trade.get("market_id", "") or "") for trade in trades if str(trade.get("market_id", "") or "").strip()}),
            "symbols": dict(Counter(str(trade.get("symbol", "OTHER") or "OTHER") for trade in trades)),
            "sources": dict(Counter(str(trade.get("source", "unknown") or "unknown") for trade in trades)),
            "timeframes": dict(Counter(str(trade.get("_timeframe", "unknown") or "unknown") for trade in trades)),
            "entry_span_start": timestamps[0].isoformat() if timestamps else "",
            "entry_span_end": timestamps[-1].isoformat() if timestamps else "",
            "sample_questions": [str(trade.get("question", "") or "") for trade in sorted_trades[:3]],
            "filtered_sample_questions": [str(trade.get("question", "") or "") for trade, _ in filtered[:3]],
            "exclusion_reasons": exclusion_reasons,
        }

    def score(self, params: ParamSet) -> BacktestResult:
        """Score a parameter set against historical resolved trades."""
        return self._score_trade_subset(self.trades, params)

    def score_replay(
        self,
        params: Optional[ParamSet] = None,
        holdout_ratio: float = 0.2,
        min_filtered_trades: int = 15,
        min_holdout_trades: int = 5,
    ) -> ReplayResult:
        """
        Score a parameter set against a chronological holdout split.

        The acceptance gate compares the candidate against a baseline on the
        holdout slice, and requires enough filtered trades to avoid tiny-sample
        overfitting.
        """
        params = params or ParamSet()
        baseline_params = ParamSet()
        candidate_filtered, candidate_exclusions = self._filter_trade_subset(self.trades, params)
        baseline_filtered, baseline_exclusions = self._filter_trade_subset(self.trades, baseline_params)
        candidate = self._build_result_from_filtered(BacktestResult(total_trades=len(self.trades)), candidate_filtered)
        baseline = self._build_result_from_filtered(BacktestResult(total_trades=len(self.trades)), baseline_filtered)

        train_trades, holdout_trades, split_markets, train_markets, holdout_markets = (
            self._split_replay_trades(holdout_ratio)
        )
        train_filtered, train_exclusions = self._filter_trade_subset(train_trades, params)
        holdout_filtered, holdout_exclusions = self._filter_trade_subset(holdout_trades, params)
        baseline_holdout_filtered, baseline_holdout_exclusions = self._filter_trade_subset(holdout_trades, baseline_params)
        train = self._build_result_from_filtered(BacktestResult(total_trades=len(train_trades)), train_filtered)
        holdout = self._build_result_from_filtered(BacktestResult(total_trades=len(holdout_trades)), holdout_filtered)
        baseline_holdout = self._build_result_from_filtered(
            BacktestResult(total_trades=len(holdout_trades)),
            baseline_holdout_filtered,
        )

        notes: List[str] = []
        accepted = True
        gate_feasible = len(holdout_trades) >= min_holdout_trades

        if candidate.filtered_trades < min_filtered_trades:
            accepted = False
            notes.append(
                f"filtered_trades {candidate.filtered_trades} < minimum {min_filtered_trades}"
            )
        if not gate_feasible:
            accepted = False
            notes.append(
                f"raw holdout trades {len(holdout_trades)} < minimum {min_holdout_trades}"
            )
        if holdout.filtered_trades < min_holdout_trades:
            accepted = False
            notes.append(
                f"holdout filtered_trades {holdout.filtered_trades} < minimum {min_holdout_trades}"
            )
        if holdout.score < baseline_holdout.score:
            accepted = False
            notes.append(
                f"holdout score {holdout.score:.2f} < baseline {baseline_holdout.score:.2f}"
            )
        if holdout.total_pnl < baseline_holdout.total_pnl:
            accepted = False
            notes.append(
                f"holdout pnl {holdout.total_pnl:+.2f} < baseline {baseline_holdout.total_pnl:+.2f}"
            )

        generalization_gap = max(0.0, train.score - holdout.score)
        if train.score > 0 and holdout.score < train.score * 0.75:
            notes.append(
                f"holdout score {holdout.score:.2f} trails train score {train.score:.2f}"
            )

        return ReplayResult(
            candidate=candidate,
            baseline=baseline,
            train=train,
            holdout=holdout,
            baseline_holdout=baseline_holdout,
            accepted=accepted,
            holdout_ratio=holdout_ratio,
            split_markets=split_markets,
            train_markets=train_markets,
            holdout_markets=holdout_markets,
            holdout_total_trades=len(holdout_trades),
            gate_feasible=gate_feasible,
            generalization_gap=generalization_gap,
            cohort_diagnostics={
                "all": self._build_subset_diagnostics(self.trades, candidate_filtered, candidate_exclusions),
                "baseline_all": self._build_subset_diagnostics(self.trades, baseline_filtered, baseline_exclusions),
                "train": self._build_subset_diagnostics(train_trades, train_filtered, train_exclusions),
                "holdout": self._build_subset_diagnostics(holdout_trades, holdout_filtered, holdout_exclusions),
                "baseline_holdout": self._build_subset_diagnostics(
                    holdout_trades,
                    baseline_holdout_filtered,
                    baseline_holdout_exclusions,
                ),
            },
            notes=notes,
        )

    def score_prompts(self, benchmark_path: str = None) -> Dict:
        """
        Deep scoring mode: runs current swarm prompts against benchmark markets
        with known outcomes. Costs API calls but tests prompt quality directly.

        Returns dict with accuracy, correct predictions, and details.
        """
        if benchmark_path is None:
            benchmark_path = str(Path(__file__).parent / "benchmark_markets.json")

        with open(benchmark_path, encoding="utf-8") as f:
            benchmarks = json.load(f)

        from .swarm_analyzer import CLISwarmAnalyzer
        from .config import PolymarketCLIConfig
        from .models import CLIMarket

        config = PolymarketCLIConfig()
        swarm = CLISwarmAnalyzer(config)

        correct = 0
        total = 0
        details = []

        for bm in benchmarks:
            market = CLIMarket(
                condition_id=f"benchmark_{total}",
                question=bm["question"],
                symbol=bm.get("symbol", ""),
                yes_token_id="",
                no_token_id="",
                yes_price=bm.get("market_price_yes", 0.5),
                no_price=1.0 - bm.get("market_price_yes", 0.5),
                liquidity=50000,
                volume_24h=10000,
                market_type=bm.get("market_type", "neutral"),
            )

            consensus = swarm.analyze_market(market)

            yes_resolved = bm.get("yes_resolved", False)
            predicted_yes = consensus.consensus_prediction == "YES"

            is_correct = predicted_yes == yes_resolved
            if is_correct:
                correct += 1
            total += 1

            details.append(
                {
                    "question": bm["question"][:50],
                    "actual": "YES" if yes_resolved else "NO",
                    "predicted": consensus.consensus_prediction,
                    "probability": consensus.consensus_probability,
                    "confidence": consensus.consensus_confidence,
                    "correct": is_correct,
                }
            )

        accuracy = correct / total if total > 0 else 0
        return {
            "accuracy": accuracy,
            "correct": correct,
            "total": total,
            "details": details,
            "score": accuracy * 100,
        }

    def _split_replay_trades(
        self, holdout_ratio: float
    ) -> Tuple[List[Dict], List[Dict], int, int, int]:
        """Split resolved trades into train and holdout sets by market_id."""
        if not self.trades:
            return [], [], 0, 0, 0

        ratio = holdout_ratio
        if ratio is None:
            ratio = 0.2
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            ratio = 0.2
        ratio = max(0.1, min(0.5, ratio))

        market_groups: Dict[str, List[Dict]] = defaultdict(list)
        for trade in self.trades:
            market_groups[str(trade.get("market_id", ""))].append(trade)

        market_order: List[Tuple[datetime, str]] = []
        for market_id, trades in market_groups.items():
            first_ts = min(
                (self._parse_timestamp(t.get("_entry_ts") or t.get("entry_time") or t.get("timestamp"))
                 for t in trades),
                default=None,
            )
            market_order.append((first_ts or datetime.min, market_id))

        market_order.sort(key=lambda item: (item[0], item[1]))
        if len(market_order) == 1:
            train_ids: set[str] = set()
            holdout_ids: set[str] = {market_order[0][1]}
        else:
            holdout_count = max(1, int(round(len(market_order) * ratio)))
            holdout_count = min(len(market_order) - 1, holdout_count)
            split_index = len(market_order) - holdout_count
            train_ids = {mid for _, mid in market_order[:split_index]}
            holdout_ids = {mid for _, mid in market_order[split_index:]}

        train_trades = [t for t in self.trades if t.get("market_id") in train_ids]
        holdout_trades = [t for t in self.trades if t.get("market_id") in holdout_ids]
        return (
            train_trades,
            holdout_trades,
            len(market_order),
            len(train_ids),
            len(holdout_ids),
        )

    def _resolve_trade_record(self, entry: Dict, close: Dict) -> Optional[Dict]:
        entry_price = self._safe_float(entry.get("price"))
        close_price = self._safe_float(close.get("price"))
        size_usd = self._safe_float(entry.get("size_usd"))
        if entry_price is None or entry_price <= 0:
            return None
        if close_price is None or close_price <= 0:
            return None
        if size_usd is None or size_usd <= 0:
            return None

        fees = self._safe_float(entry.get("fees"), 0.0) or 0.0
        close_fees = self._safe_float(close.get("fees"), 0.0) or 0.0
        shares = size_usd / entry_price
        pnl = shares * (close_price - entry_price) - fees - close_fees

        outcome = "win" if pnl > 0 else "loss"
        if abs(pnl) < 1e-9:
            outcome = "flat"

        entry_ts = self._parse_timestamp(entry.get("timestamp"))
        close_ts = self._parse_timestamp(close.get("timestamp"))
        entry_side = self._normalize_side(entry.get("side"))
        close_side = self._normalize_side(close.get("side"))
        edge = self._parse_edge(entry.get("reason", ""))
        confidence = self._safe_float(entry.get("confidence"), 0.5) or 0.5
        timeframe = self._classify_timeframe(
            self._safe_float(entry.get("time_remaining_hours")),
            self._safe_int(entry.get("duration_minutes")),
        )
        hours_remaining = self._safe_float(entry.get("time_remaining_hours"))
        actual_side = ""
        if outcome == "win":
            actual_side = entry_side
        elif outcome == "loss":
            actual_side = self._opposite_side(entry_side)
        else:
            actual_side = "FLAT"

        return {
            "trade_id": entry.get("trade_id", ""),
            "entry_trade_id": entry.get("trade_id", ""),
            "close_trade_id": close.get("trade_id", ""),
            "market_id": entry.get("market_id", ""),
            "question": entry.get("question", "")[:80],
            "symbol": entry.get("symbol", ""),
            "side": entry_side or str(entry.get("side", "")),
            "close_side": close_side,
            "actual_side": actual_side,
            "source": entry.get("source", ""),
            "entry_time": entry_ts.isoformat() if entry_ts else str(entry.get("timestamp", "")),
            "exit_time": close_ts.isoformat() if close_ts else str(close.get("timestamp", "")),
            "entry_price": entry_price,
            "exit_price": close_price,
            "size_usd": size_usd,
            "fees": round(fees + close_fees, 4),
            "net_pnl": pnl,
            "outcome": outcome,
            "is_closed": True,
            "_pnl": pnl,
            "_outcome": outcome,
            "_edge": edge,
            "_confidence": confidence,
            "_timeframe": timeframe,
            "_hours_remaining": hours_remaining,
            "edge_at_entry": edge,
            "swarm_probability": self._parse_prob_from_reason(entry.get("reason", "")),
            "confidence": confidence,
            "timeframe": timeframe,
            "market_type": entry.get("market_type", ""),
            "_entry_ts": entry_ts,
            "_close_ts": close_ts,
            "_entry": entry,
            "_close": close,
        }

    def _match_close(
        self,
        entry: Dict,
        closes: List[Dict],
        start_index: int,
    ) -> Tuple[Optional[Dict], int]:
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

    @staticmethod
    def _trade_sort_key(trade: Dict) -> Tuple[datetime, str, str]:
        ts = (
            BacktestScorer._parse_timestamp(trade.get("_entry_ts") or trade.get("entry_time") or trade.get("timestamp"))
            or datetime.min
        )
        market_id = str(trade.get("market_id", ""))
        trade_id = str(trade.get("trade_id", ""))
        return ts, market_id, trade_id

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
            if parsed != parsed:
                return default
            return parsed
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

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
    def _normalize_side(value: Any) -> str:
        side = str(value or "").strip().upper()
        if side in {"YES", "NO"}:
            return side
        if side.startswith("CLOSE_"):
            return side
        return side

    @staticmethod
    def _opposite_side(side: str) -> str:
        if side == "YES":
            return "NO"
        if side == "NO":
            return "YES"
        return "FLAT"

    @staticmethod
    def _parse_edge(reason: str) -> float:
        """Extract edge percentage from trade reason."""
        import re

        match = re.search(r"([\d.]+)%\s*(?:edge|YES|NO)", reason, re.IGNORECASE)
        if match:
            return float(match.group(1))
        match = re.search(r"Edge:\s*([\d.]+)%", reason)
        if match:
            return float(match.group(1))
        return 0.0

    @staticmethod
    def _parse_prob_from_reason(reason: str) -> float:
        """Extract swarm probability from trade reason string."""
        import re

        match = re.search(r"prob=([\d.]+)", reason)
        if match:
            return float(match.group(1))
        return 0.0

    @staticmethod
    def _classify_timeframe(hours: Optional[float], minutes: Optional[int]) -> str:
        """Classify trade into timeframe bucket."""
        if minutes:
            if minutes <= 30:
                return "ultra_short"
            if minutes <= 240:
                return "intraday"
            if minutes <= 1440:
                return "daily"
            return "weekly"
        if hours is not None:
            if hours <= 1:
                return "ultra_short"
            if hours <= 6:
                return "intraday"
            if hours <= 24:
                return "daily"
            return "weekly"
        return "unknown"


if __name__ == "__main__":
    scorer = BacktestScorer()
    print(f"Loaded {len(scorer.trades)} resolved trades")

    baseline = scorer.score(ParamSet())
    print(f"\nBASELINE (current params):")
    print(f"  Trades: {baseline.filtered_trades}/{baseline.total_trades}")
    print(f"  Win rate: {baseline.win_rate:.1%} ({baseline.wins}W/{baseline.losses}L)")
    print(f"  P&L: ${baseline.total_pnl:+.2f} on ${baseline.total_deployed:.0f}")
    print(f"  ROI: {baseline.roi:.1%}")
    print(f"  Score: {baseline.score:.2f}")

    replay = scorer.score_replay(ParamSet())
    print(f"\nREPLAY GATE:")
    print(f"  Accepted: {replay.accepted}")
    print(f"  Holdout score: {replay.holdout.score:.2f}")
    print(f"  Baseline holdout score: {replay.baseline_holdout.score:.2f}")

    print("\nEDGE THRESHOLD SWEEP:")
    for thresh in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]:
        r = scorer.score(ParamSet(min_edge_threshold=thresh))
        print(
            f"  {thresh:5.1f}%: {r.filtered_trades:3d} trades | "
            f"{r.win_rate:.1%} WR | ${r.total_pnl:+8.2f} | score={r.score:.1f}"
        )

    print("\nARB-ONLY vs SWARM-ONLY vs BOTH:")
    for label, sw, arb in [("arb-only", False, True), ("swarm-only", True, False), ("both", True, True)]:
        r = scorer.score(ParamSet(allow_swarm=sw, allow_arb=arb))
        print(
            f"  {label:12s}: {r.filtered_trades:3d} trades | "
            f"{r.win_rate:.1%} WR | ${r.total_pnl:+8.2f} | score={r.score:.1f}"
        )

    print("\nSYMBOL FILTER:")
    for syms in [["ETH"], ["BTC"], ["ETH", "BTC"], ["ETH", "BTC", "SOL", "XRP", "DOGE"]]:
        r = scorer.score(ParamSet(allowed_symbols=syms))
        label = "+".join(syms)
        print(
            f"  {label:20s}: {r.filtered_trades:3d} trades | "
            f"{r.win_rate:.1%} WR | ${r.total_pnl:+8.2f} | score={r.score:.1f}"
        )
