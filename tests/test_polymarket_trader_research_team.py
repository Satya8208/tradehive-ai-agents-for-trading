import json
from datetime import datetime, timedelta

from src.agents.polymarket_trader.backtest_scorer import BacktestResult, ReplayResult
from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.models import CLIMarket
from src.agents.polymarket_trader.performance_tracker import PerformanceTracker
from src.agents.polymarket_trader.research_team import QuantResearchTeam


def _result(
    *,
    filtered_trades,
    wins,
    losses,
    pnl,
    deployed,
    win_rate,
    roi,
    score,
    by_source=None,
    by_symbol=None,
):
    return BacktestResult(
        total_trades=26,
        filtered_trades=filtered_trades,
        wins=wins,
        losses=losses,
        total_pnl=pnl,
        total_deployed=deployed,
        win_rate=win_rate,
        roi=roi,
        score=score,
        by_source=by_source or {},
        by_symbol=by_symbol or {},
        by_timeframe={},
    )


def _replay(candidate: BacktestResult, accepted: bool = False) -> ReplayResult:
    baseline = _result(
        filtered_trades=8,
        wins=4,
        losses=4,
        pnl=20.0,
        deployed=200.0,
        win_rate=0.5,
        roi=0.1,
        score=60.0,
    )
    return ReplayResult(
        candidate=candidate,
        baseline=baseline,
        train=candidate,
        holdout=_result(
            filtered_trades=0,
            wins=0,
            losses=0,
            pnl=0.0,
            deployed=0.0,
            win_rate=0.0,
            roi=0.0,
            score=0.0,
        ),
        baseline_holdout=_result(
            filtered_trades=1,
            wins=0,
            losses=1,
            pnl=-5.0,
            deployed=10.0,
            win_rate=0.0,
            roi=-0.5,
            score=-5.0,
        ),
        accepted=accepted,
        holdout_ratio=0.2,
        split_markets=10,
        train_markets=8,
        holdout_markets=2,
        generalization_gap=12.0,
        notes=["holdout filtered_trades 0 < minimum 5"],
    )


class _FakeScorer:
    def score(self, params):
        symbols = tuple(params.allowed_symbols)
        if symbols == ("ETH",) and params.allow_arb and params.allow_swarm:
            return _result(
                filtered_trades=9,
                wins=5,
                losses=4,
                pnl=82.8,
                deployed=265.03,
                win_rate=0.556,
                roi=0.312,
                score=78.12,
                by_source={"swarm": {"count": 7, "pnl": 81.0}},
                by_symbol={"ETH": {"count": 9, "pnl": 82.8}},
            )
        if symbols == ("BTC",) and params.allow_arb and params.allow_swarm:
            return _result(
                filtered_trades=2,
                wins=0,
                losses=2,
                pnl=-20.27,
                deployed=31.45,
                win_rate=0.0,
                roi=-0.645,
                score=-12.9,
                by_symbol={"BTC": {"count": 2, "pnl": -20.27}},
            )
        if symbols == ("ETH", "BTC"):
            return _result(
                filtered_trades=11,
                wins=5,
                losses=6,
                pnl=62.53,
                deployed=296.48,
                win_rate=0.455,
                roi=0.211,
                score=66.55,
                by_symbol={"ETH": {"count": 9, "pnl": 82.8}, "BTC": {"count": 2, "pnl": -20.27}},
            )
        if symbols == ("ETH",) and params.allow_swarm and not params.allow_arb:
            return _result(
                filtered_trades=7,
                wins=6,
                losses=1,
                pnl=81.0,
                deployed=180.0,
                win_rate=0.857,
                roi=0.45,
                score=95.0,
                by_source={"swarm": {"count": 7, "pnl": 81.0}},
                by_symbol={"ETH": {"count": 7, "pnl": 81.0}},
            )
        if symbols == ("BTC",) and params.allow_swarm and not params.allow_arb:
            return _result(
                filtered_trades=2,
                wins=0,
                losses=2,
                pnl=-12.0,
                deployed=18.0,
                win_rate=0.0,
                roi=-0.667,
                score=-8.0,
                by_source={"swarm": {"count": 2, "pnl": -12.0}},
                by_symbol={"BTC": {"count": 2, "pnl": -12.0}},
            )
        return _result(
            filtered_trades=9,
            wins=5,
            losses=4,
            pnl=82.8,
            deployed=265.03,
            win_rate=0.556,
            roi=0.312,
            score=78.12,
        )

    def score_replay(self, params):
        return _replay(self.score(params), accepted=False)


class _FakePerformanceTracker:
    def __init__(self, config):
        self.config = config

    def generate_report(self):
        return {
            "closed_trades": 35,
            "open_trades": 42,
            "win_rate": 0.057,
            "total_pnl": -192.96,
            "avg_win": 22.73,
            "avg_loss": -7.22,
            "profit_factor": 0.19,
            "max_drawdown": 192.96,
            "consensus_accuracy": 0.114,
            "brier_score": 0.2869,
            "mean_absolute_error": 0.4974,
            "confidence_diagnostics": {
                "verdict": "HIGH_CONFIDENCE_ANTI_SIGNAL",
                "high_confidence_threshold": 0.5,
                "severe_confidence_threshold": 0.7,
                "best_cap": {
                    "threshold": 0.3,
                    "count": 5,
                    "win_rate": 0.2,
                    "total_pnl": -18.59,
                    "avg_predicted_probability": 0.211,
                    "overconfidence_gap": 0.011,
                },
                "best_floor": {
                    "threshold": 0.7,
                    "count": 6,
                    "win_rate": 0.0,
                    "total_pnl": -62.82,
                    "avg_predicted_probability": 0.785,
                    "overconfidence_gap": 0.785,
                },
                "gate_verdict": {
                    "status": "NO_PROMOTABLE_CONFIDENCE_GATE",
                    "reason_codes": [
                        "best_cap_still_negative_or_thin",
                        "high_confidence_floor_negative",
                        "confidence_monotonicity_broken",
                    ],
                },
                "cap_sweep": [
                    {"threshold": 0.3, "count": 5, "win_rate": 0.2, "total_pnl": -18.59, "avg_predicted_probability": 0.211, "overconfidence_gap": 0.011},
                    {"threshold": 0.4, "count": 14, "win_rate": 0.143, "total_pnl": -41.47, "avg_predicted_probability": 0.319, "overconfidence_gap": 0.176},
                    {"threshold": 0.5, "count": 24, "win_rate": 0.083, "total_pnl": -104.75, "avg_predicted_probability": 0.408, "overconfidence_gap": 0.325},
                ],
                "floor_sweep": [
                    {"threshold": 0.5, "count": 13, "win_rate": 0.0, "total_pnl": -106.51, "avg_predicted_probability": 0.672, "overconfidence_gap": 0.672},
                    {"threshold": 0.6, "count": 9, "win_rate": 0.0, "total_pnl": -78.98, "avg_predicted_probability": 0.735, "overconfidence_gap": 0.735},
                    {"threshold": 0.7, "count": 6, "win_rate": 0.0, "total_pnl": -62.82, "avg_predicted_probability": 0.785, "overconfidence_gap": 0.785},
                ],
                "high_confidence": {
                    "count": 13,
                    "wins": 0,
                    "win_rate": 0.0,
                    "total_pnl": -106.51,
                    "avg_predicted_probability": 0.672,
                    "overconfidence_gap": 0.672,
                },
                "severe_confidence": {
                    "count": 6,
                    "wins": 0,
                    "win_rate": 0.0,
                    "total_pnl": -62.82,
                    "avg_predicted_probability": 0.785,
                    "overconfidence_gap": 0.785,
                },
                "low_confidence": {
                    "count": 22,
                    "wins": 2,
                    "win_rate": 0.091,
                    "total_pnl": -86.45,
                    "avg_predicted_probability": 0.345,
                    "overconfidence_gap": 0.254,
                },
                "confidence_monotonicity_broken": True,
            },
            "edge_quality_diagnostics": {
                "verdict": "ONLY_LOW_SAMPLE_EDGE_PATCH",
                "min_trade_count": 5,
                "best_cap": {
                    "threshold": 10.0,
                    "count": 12,
                    "win_rate": 0.0,
                    "total_pnl": -36.55,
                    "avg_edge_at_entry": 6.48,
                    "avg_predicted_probability": 0.529,
                },
                "best_floor": {
                    "threshold": 30.0,
                    "count": 7,
                    "win_rate": 0.286,
                    "total_pnl": -10.0,
                    "avg_edge_at_entry": 40.41,
                    "avg_predicted_probability": 0.318,
                },
                "best_low_sample_floor": {
                    "threshold": 40.0,
                    "count": 2,
                    "win_rate": 0.5,
                    "total_pnl": 5.32,
                    "avg_edge_at_entry": 46.25,
                    "avg_predicted_probability": 0.373,
                },
                "low_edge": {
                    "count": 12,
                    "win_rate": 0.0,
                    "total_pnl": -36.55,
                    "avg_edge_at_entry": 6.48,
                    "avg_predicted_probability": 0.529,
                },
                "high_edge": {
                    "count": 11,
                    "win_rate": 0.182,
                    "total_pnl": -61.59,
                    "avg_edge_at_entry": 34.48,
                    "avg_predicted_probability": 0.402,
                },
                "high_edge_beats_low_edge": False,
                "gate_verdict": {
                    "status": "NO_PROMOTABLE_EDGE_GATE",
                    "reason_codes": [
                        "best_sampled_edge_floor_still_negative_or_flat",
                        "best_sampled_edge_cap_still_negative_or_flat",
                        "only_low_sample_positive_edge_floor",
                    ],
                },
                "cap_sweep": [
                    {"threshold": 10.0, "count": 12, "win_rate": 0.0, "total_pnl": -36.55, "avg_edge_at_entry": 6.48, "avg_predicted_probability": 0.529},
                    {"threshold": 20.0, "count": 24, "win_rate": 0.0, "total_pnl": -131.37, "avg_edge_at_entry": 11.21, "avg_predicted_probability": 0.463},
                    {"threshold": 40.0, "count": 33, "win_rate": 0.03, "total_pnl": -198.28, "avg_edge_at_entry": 16.85, "avg_predicted_probability": 0.439},
                ],
                "floor_sweep": [
                    {"threshold": 20.0, "count": 11, "win_rate": 0.182, "total_pnl": -61.59, "avg_edge_at_entry": 34.48, "avg_predicted_probability": 0.402},
                    {"threshold": 30.0, "count": 7, "win_rate": 0.286, "total_pnl": -10.0, "avg_edge_at_entry": 40.41, "avg_predicted_probability": 0.318},
                    {"threshold": 40.0, "count": 2, "win_rate": 0.5, "total_pnl": 5.32, "avg_edge_at_entry": 46.25, "avg_predicted_probability": 0.373},
                ],
            },
            "edge_timeframe_diagnostics": {
                "verdict": "ONLY_LOW_SAMPLE_TIMEFRAME_EDGE_PATCH",
                "min_trade_count": 5,
                "gate_verdict": {
                    "status": "NO_PROMOTABLE_TIMEFRAME_EDGE_POCKET",
                    "reason_codes": [
                        "best_sampled_timeframe_edge_pocket_still_negative_or_flat",
                        "only_low_sample_positive_timeframe_edge_pocket",
                        "only_positive_timeframe_edge_pocket_is_ultra_short",
                    ],
                },
                "best_sampled_pocket": {
                    "timeframe": "weekly",
                    "edge_mode": "cap",
                    "edge_filter": "cap<=10",
                    "threshold": 10.0,
                    "count": 5,
                    "win_rate": 0.0,
                    "total_pnl": -9.06,
                    "avg_edge_at_entry": 6.1,
                    "avg_predicted_probability": 0.28,
                },
                "best_low_sample_pocket": {
                    "timeframe": "ultra_short",
                    "edge_mode": "floor",
                    "edge_filter": "floor>=40",
                    "threshold": 40.0,
                    "count": 2,
                    "win_rate": 0.5,
                    "total_pnl": 5.32,
                    "avg_edge_at_entry": 46.25,
                    "avg_predicted_probability": 0.373,
                },
                "top_rows": [
                    {"timeframe": "ultra_short", "edge_mode": "floor", "edge_filter": "floor>=40", "threshold": 40.0, "count": 2, "win_rate": 0.5, "total_pnl": 5.32, "avg_edge_at_entry": 46.25, "avg_predicted_probability": 0.373},
                    {"timeframe": "weekly", "edge_mode": "cap", "edge_filter": "cap<=10", "threshold": 10.0, "count": 5, "win_rate": 0.0, "total_pnl": -9.06, "avg_edge_at_entry": 6.1, "avg_predicted_probability": 0.28},
                    {"timeframe": "intraday", "edge_mode": "floor", "edge_filter": "floor>=30", "threshold": 30.0, "count": 4, "win_rate": 0.25, "total_pnl": -7.42, "avg_edge_at_entry": 31.4, "avg_predicted_probability": 0.35},
                ],
                "positive_sampled_pocket_count": 0,
                "positive_low_sample_pocket_count": 1,
            },
            "market_archetype_diagnostics": {
                "verdict": "ONLY_LOW_SAMPLE_MARKET_ARCHETYPE_PATCH",
                "min_trade_count": 5,
                "gate_verdict": {
                    "status": "NO_PROMOTABLE_MARKET_ARCHETYPE_POCKET",
                    "reason_codes": [
                        "best_sampled_market_archetype_pocket_still_negative_or_flat",
                        "only_low_sample_positive_market_archetype_pocket",
                        "only_positive_market_archetype_pockets_are_no_side",
                    ],
                },
                "best_sampled_pocket": {
                    "timeframe": "weekly",
                    "market_type": "bullish",
                    "direction": "NO",
                    "count": 5,
                    "win_rate": 0.0,
                    "total_pnl": -9.06,
                    "avg_predicted_probability": 0.334,
                },
                "best_low_sample_pocket": {
                    "timeframe": "intraday",
                    "market_type": "bullish",
                    "direction": "NO",
                    "count": 2,
                    "win_rate": 0.5,
                    "total_pnl": 7.46,
                    "avg_predicted_probability": 0.31,
                },
                "top_rows": [
                    {"timeframe": "intraday", "market_type": "bullish", "direction": "NO", "count": 2, "win_rate": 0.5, "total_pnl": 7.46, "avg_predicted_probability": 0.31},
                    {"timeframe": "ultra_short", "market_type": "binary_updown", "direction": "NO", "count": 2, "win_rate": 0.5, "total_pnl": 5.32, "avg_predicted_probability": 0.373},
                    {"timeframe": "weekly", "market_type": "bullish", "direction": "NO", "count": 5, "win_rate": 0.0, "total_pnl": -9.06, "avg_predicted_probability": 0.334},
                ],
                "positive_sampled_pocket_count": 0,
                "positive_low_sample_pocket_count": 2,
            },
            "entry_price_diagnostics": {
                "verdict": "ONLY_LOW_SAMPLE_ENTRY_PRICE_PATCH",
                "min_trade_count": 5,
                "gate_verdict": {
                    "status": "NO_PROMOTABLE_ENTRY_PRICE_POCKET",
                    "reason_codes": [
                        "best_sampled_entry_price_pocket_still_negative_or_flat",
                        "only_low_sample_positive_entry_price_pocket",
                        "only_positive_entry_price_pockets_are_cheap_bullish_no",
                    ],
                },
                "best_sampled_pocket": {
                    "price_band": "0.10-0.20",
                    "market_type": "bullish",
                    "direction": "NO",
                    "timeframe_scope": "ALL",
                    "count": 5,
                    "win_rate": 0.0,
                    "total_pnl": -9.06,
                    "avg_entry_price": 0.145,
                    "avg_edge": 5.72,
                },
                "best_low_sample_pocket": {
                    "price_band": "<=0.10",
                    "market_type": "bullish",
                    "direction": "NO",
                    "timeframe_scope": "ALL",
                    "count": 3,
                    "win_rate": 0.667,
                    "total_pnl": 5.72,
                    "avg_entry_price": 0.059,
                    "avg_edge": 28.43,
                },
                "cheap_tail_all": {
                    "price_band": "<=0.10",
                    "market_type": "ALL",
                    "direction": "ALL",
                    "timeframe_scope": "ALL",
                    "count": 3,
                    "win_rate": 0.667,
                    "total_pnl": 5.72,
                    "avg_entry_price": 0.059,
                    "avg_edge": 28.43,
                },
                "cheap_tail_bullish_no": {
                    "price_band": "<=0.10",
                    "market_type": "bullish",
                    "direction": "NO",
                    "timeframe_scope": "ALL",
                    "count": 3,
                    "win_rate": 0.667,
                    "total_pnl": 5.72,
                    "avg_entry_price": 0.059,
                    "avg_edge": 28.43,
                },
                "cheap_tail_bullish_no_fast": {
                    "price_band": "<=0.10",
                    "market_type": "bullish",
                    "direction": "NO",
                    "timeframe_scope": "intraday+ultra_short",
                    "count": 2,
                    "win_rate": 0.5,
                    "total_pnl": 7.46,
                    "avg_entry_price": 0.057,
                    "avg_edge": 39.05,
                },
                "best_low_sample_concentration": {
                    "count": 3,
                    "unique_markets": 2,
                    "largest_win_pnl": 29.61,
                    "largest_loss_pnl": -22.15,
                    "total_pnl": 5.72,
                    "largest_win_share_of_total_pnl": 5.176,
                    "residual_pnl_without_largest_win": -23.89,
                    "survives_without_largest_win": False,
                },
                "cheap_tail_bullish_no_fast_concentration": {
                    "count": 2,
                    "unique_markets": 1,
                    "largest_win_pnl": 29.61,
                    "largest_loss_pnl": -22.15,
                    "total_pnl": 7.46,
                    "largest_win_share_of_total_pnl": 3.969,
                    "residual_pnl_without_largest_win": -22.15,
                    "survives_without_largest_win": False,
                },
                "top_rows": [
                    {"price_band": "<=0.10", "market_type": "bullish", "direction": "NO", "timeframe_scope": "ALL", "count": 3, "win_rate": 0.667, "total_pnl": 5.72, "avg_entry_price": 0.059, "avg_edge": 28.43},
                    {"price_band": "0.10-0.20", "market_type": "bullish", "direction": "NO", "timeframe_scope": "ALL", "count": 5, "win_rate": 0.0, "total_pnl": -9.06, "avg_entry_price": 0.145, "avg_edge": 5.72},
                    {"price_band": "0.20-0.30", "market_type": "bullish", "direction": "NO", "timeframe_scope": "ALL", "count": 1, "win_rate": 0.0, "total_pnl": -5.16, "avg_entry_price": 0.25, "avg_edge": 12.5},
                ],
                "positive_sampled_pocket_count": 0,
                "positive_low_sample_pocket_count": 1,
            },
            "direction_diagnostics": {
                "verdict": "YES_DIRECTION_ANTI_SIGNAL",
                "gate_verdict": {
                    "status": "NO_PROMOTABLE_DIRECTION_GATE",
                    "reason_codes": ["yes_direction_losing", "best_direction_still_negative", "yes_worse_than_no"],
                },
                "pocket_verdict": {
                    "status": "NO_PROMOTABLE_DIRECTION_TIMEFRAME_POCKET",
                    "reason_codes": ["best_pocket_low_sample", "only_positive_pocket_is_no_ultra_short"],
                },
                "by_direction": {
                    "YES": {
                        "count": 13,
                        "wins": 0,
                        "win_rate": 0.0,
                        "total_pnl": -106.51,
                        "avg_predicted_probability": 0.672,
                    },
                    "NO": {
                        "count": 22,
                        "wins": 2,
                        "win_rate": 0.091,
                        "total_pnl": -86.45,
                        "avg_predicted_probability": 0.345,
                    },
                },
                "by_direction_timeframe": {
                    "NO:ultra_short": {
                        "direction": "NO",
                        "timeframe": "ultra_short",
                        "count": 2,
                        "wins": 1,
                        "win_rate": 0.5,
                        "total_pnl": 5.32,
                        "avg_predicted_probability": 0.373,
                    }
                },
                "best_direction": {
                    "direction": "NO",
                    "count": 22,
                    "wins": 2,
                    "win_rate": 0.091,
                    "total_pnl": -86.45,
                    "avg_predicted_probability": 0.345,
                },
                "best_direction_timeframe": {
                    "direction": "NO",
                    "timeframe": "ultra_short",
                    "count": 2,
                    "wins": 1,
                    "win_rate": 0.5,
                    "total_pnl": 5.32,
                    "avg_predicted_probability": 0.373,
                },
                "worst_direction_timeframe": {
                    "direction": "YES",
                    "timeframe": "daily",
                    "count": 8,
                    "wins": 0,
                    "win_rate": 0.0,
                    "total_pnl": -64.77,
                    "avg_predicted_probability": 0.59,
                    "drag_share_of_negative_loss": 0.336,
                },
                "top_negative_direction_timeframes": [
                    {
                        "direction": "YES",
                        "timeframe": "daily",
                        "count": 8,
                        "wins": 0,
                        "win_rate": 0.0,
                        "total_pnl": -64.77,
                        "avg_predicted_probability": 0.59,
                        "drag_share_of_negative_loss": 0.336,
                    },
                    {
                        "direction": "NO",
                        "timeframe": "intraday",
                        "count": 12,
                        "wins": 1,
                        "win_rate": 0.083,
                        "total_pnl": -53.25,
                        "avg_predicted_probability": 0.387,
                        "drag_share_of_negative_loss": 0.276,
                    },
                    {
                        "direction": "NO",
                        "timeframe": "daily",
                        "count": 3,
                        "wins": 0,
                        "win_rate": 0.0,
                        "total_pnl": -29.47,
                        "avg_predicted_probability": 0.23,
                        "drag_share_of_negative_loss": 0.153,
                    },
                ],
                "top_two_directional_drag_share": 0.612,
                "exclusion_rescue": {
                    "status": "NO_SIMPLE_EXCLUSION_RESCUE",
                    "reason_codes": [
                        "residual_negative_after_all_simple_cuts",
                        "worst_pocket_not_dominant_enough",
                        "best_residual_still_negative",
                    ],
                    "scenarios": [
                        {
                            "label": "drop_worst_pocket",
                            "excluded_keys": ["YES:daily"],
                            "removed_count": 8,
                            "removed_pnl": -64.77,
                            "residual_pnl": -128.19,
                        },
                        {
                            "label": "drop_top2_pockets",
                            "excluded_keys": ["NO:intraday", "YES:daily"],
                            "removed_count": 20,
                            "removed_pnl": -118.02,
                            "residual_pnl": -74.94,
                        },
                        {
                            "label": "drop_top3_pockets",
                            "excluded_keys": ["NO:daily", "NO:intraday", "YES:daily"],
                            "removed_count": 23,
                            "removed_pnl": -147.49,
                            "residual_pnl": -45.47,
                        },
                        {
                            "label": "drop_all_yes",
                            "excluded_keys": ["YES:daily", "YES:intraday", "YES:weekly"],
                            "removed_count": 13,
                            "removed_pnl": -106.51,
                            "residual_pnl": -86.45,
                        },
                    ],
                },
            },
            "policy_rescue_diagnostics": {
                "verdict": "ONLY_LOW_SAMPLE_COMPOSITE_PATCH",
                "min_trade_count": 5,
                "gate_verdict": {
                    "status": "NO_PROMOTABLE_COMPOSITE_POLICY",
                    "reason_codes": [
                        "best_sampled_policy_still_negative_or_flat",
                        "only_low_sample_positive_composite_policy",
                    ],
                },
                "best_sampled_policy": {
                    "direction": "NO",
                    "timeframe": "intraday",
                    "confidence_filter": "cap<=40%",
                    "active_filters": ["direction=NO", "timeframe=intraday", "confidence<=40%"],
                    "count": 7,
                    "wins": 1,
                    "win_rate": 0.143,
                    "total_pnl": -21.33,
                    "avg_predicted_probability": 0.352,
                },
                "best_low_sample_policy": {
                    "direction": "NO",
                    "timeframe": "ultra_short",
                    "confidence_filter": "cap<=40%",
                    "active_filters": ["direction=NO", "timeframe=ultra_short", "confidence<=40%"],
                    "count": 2,
                    "wins": 1,
                    "win_rate": 0.5,
                    "total_pnl": 5.32,
                    "avg_predicted_probability": 0.373,
                },
                "top_rows": [
                    {
                        "direction": "NO",
                        "timeframe": "ultra_short",
                        "confidence_filter": "cap<=40%",
                        "active_filters": ["direction=NO", "timeframe=ultra_short", "confidence<=40%"],
                        "count": 2,
                        "wins": 1,
                        "win_rate": 0.5,
                        "total_pnl": 5.32,
                        "avg_predicted_probability": 0.373,
                    },
                    {
                        "direction": "NO",
                        "timeframe": "intraday",
                        "confidence_filter": "cap<=40%",
                        "active_filters": ["direction=NO", "timeframe=intraday", "confidence<=40%"],
                        "count": 7,
                        "wins": 1,
                        "win_rate": 0.143,
                        "total_pnl": -21.33,
                        "avg_predicted_probability": 0.352,
                    },
                    {
                        "direction": "YES",
                        "timeframe": "daily",
                        "confidence_filter": "floor>=50%",
                        "active_filters": ["direction=YES", "timeframe=daily", "confidence>=50%"],
                        "count": 8,
                        "wins": 0,
                        "win_rate": 0.0,
                        "total_pnl": -64.77,
                        "avg_predicted_probability": 0.59,
                    },
                ],
                "positive_sampled_policy_count": 0,
                "positive_low_sample_policy_count": 1,
            },
            "by_source": {
                "swarm": {"count": 30, "pnl": -136.75, "win_rate": 0.067},
                "arbitrage": {"count": 5, "pnl": -56.21, "win_rate": 0.0},
            },
            "by_timeframe": {
                "daily": {"count": 11, "pnl": -94.24, "win_rate": 0.0},
                "weekly": {"count": 7, "pnl": -37.52, "win_rate": 0.0},
                "intraday": {"count": 15, "pnl": -66.51, "win_rate": 0.067},
                "ultra_short": {"count": 2, "pnl": 5.32, "win_rate": 0.5},
            },
            "replay": {
                "accepted": False,
                "gate_feasible": False,
                "holdout_total_trades": 3,
                "trailing_holdout_probe": {
                    "diagnostic_only": True,
                    "shipping_gate_unchanged": True,
                    "min_filtered_trades": 1,
                    "min_holdout_trades": 1,
                    "any_filtered_holdout": False,
                    "best_filtered_holdout_trades": 0,
                    "best_holdout_ratio": None,
                    "ratios": [
                        {"holdout_ratio": 0.2, "raw_holdout_trades": 3, "filtered_holdout_trades": 0},
                        {"holdout_ratio": 0.3, "raw_holdout_trades": 6, "filtered_holdout_trades": 0},
                        {"holdout_ratio": 0.4, "raw_holdout_trades": 7, "filtered_holdout_trades": 0},
                        {"holdout_ratio": 0.5, "raw_holdout_trades": 8, "filtered_holdout_trades": 0},
                    ],
                },
                "candidate": {"score": -7.68},
                "holdout": {"score": 0.0},
                "baseline_holdout": {"score": 0.0},
                "cohort_diagnostics": {
                    "all": {
                        "total_trades": 35,
                        "unique_markets": 13,
                        "entry_span_start": "2026-03-24T08:34:28",
                        "entry_span_end": "2026-03-24T23:07:35",
                        "symbols": {"ETH": 35},
                    },
                    "holdout": {
                        "total_trades": 3,
                        "unique_markets": 3,
                        "exclusion_reasons": {
                            "expiry_too_far": 1,
                            "edge_below_threshold": 1,
                            "arb_edge_below_threshold": 1,
                        },
                    },
                },
            },
        }


def _fake_swarm_health(_config):
    return {
        "ready": False,
        "status": "degraded",
        "available_models": 0,
        "unavailable_models": 3,
        "configured_models": [
            {"provider": "claude", "model_name": "claude-sonnet-4-6", "status": "provider_unavailable"},
            {"provider": "deepseek", "model_name": "deepseek-reasoner", "status": "provider_unavailable"},
            {"provider": "xai", "model_name": "grok-4-fast-reasoning", "status": "provider_unavailable"},
        ],
    }


def _market(symbol, question, hours_remaining, market_type="neutral"):
    return CLIMarket(
        condition_id=f"{symbol}-{question[:8]}",
        question=question,
        symbol=symbol,
        yes_token_id=f"{symbol}-yes",
        no_token_id=f"{symbol}-no",
        yes_price=0.52,
        no_price=0.48,
        liquidity=25000.0,
        volume_24h=8000.0,
        end_date=datetime.utcnow() + timedelta(hours=hours_remaining),
        is_active=True,
        market_type=market_type,
        price_target=3000.0 if symbol == "ETH" else 100000.0,
    )


class _FakeScanner:
    def __init__(self, config):
        self.config = config
        self.last_scan_telemetry = {}

    def scan_markets(self, force_refresh=False):
        if self.config.min_volume_24h_usd > 0:
            self.last_scan_telemetry = {
                "query_count": 21,
                "raw_records": 1008,
                "parsed": 935,
                "filtered": 1008,
                "tradeable": 0,
                "no_markets": True,
                "exclusion_reasons": {
                    "low_volume_24h": 408,
                    "expiry_too_far": 264,
                },
            }
            return []

        markets = [
            _market("ETH", "Will the price of Ethereum be above $2,500 on April 23?", 12, "bullish"),
            _market("BTC", "Will Bitcoin dip to $55,000 by December 31, 2026?", 240, "bearish"),
        ]
        self.last_scan_telemetry = {
            "query_count": 21,
            "raw_records": 1008,
            "parsed": 935,
            "filtered": 963,
            "tradeable": len(markets),
            "no_markets": False,
            "exclusion_reasons": {
                "inactive_market": 40,
            },
        }
        return markets


def test_edge_quality_diagnostics_keeps_sampled_and_low_sample_floors_separate():
    scored_predictions = []

    for _ in range(5):
        scored_predictions.append(
            {
                "edge_at_entry": 10.0,
                "outcome": "loss",
                "net_pnl": -1.0,
                "consensus_probability": 0.52,
            }
        )

    for index in range(5):
        scored_predictions.append(
            {
                "edge_at_entry": 30.0,
                "outcome": "win" if index < 2 else "loss",
                "net_pnl": -3.0,
                "consensus_probability": 0.32,
            }
        )

    for index in range(2):
        scored_predictions.append(
            {
                "edge_at_entry": 40.0,
                "outcome": "win" if index == 0 else "loss",
                "net_pnl": 2.5,
                "consensus_probability": 0.37,
            }
        )

    diagnostics = PerformanceTracker._build_edge_quality_diagnostics(scored_predictions)

    assert diagnostics["best_floor"]["threshold"] == 30.0
    assert diagnostics["best_floor"]["count"] == 7
    assert diagnostics["best_floor"]["total_pnl"] == -10.0
    assert diagnostics["best_any_floor"]["threshold"] == 40.0
    assert diagnostics["best_any_floor"]["count"] == 2
    assert diagnostics["best_any_floor"]["total_pnl"] == 5.0
    assert diagnostics["best_low_sample_floor"]["threshold"] == 40.0
    assert diagnostics["best_low_sample_floor"]["count"] == 2
    assert diagnostics["best_low_sample_floor"]["total_pnl"] == 5.0
    assert diagnostics["gate_verdict"]["status"] == "NO_PROMOTABLE_EDGE_GATE"
    assert "only_low_sample_positive_edge_floor" in diagnostics["gate_verdict"]["reason_codes"]


def test_edge_timeframe_diagnostics_isolates_low_sample_ultra_short_patch():
    scored_predictions = []

    for _ in range(5):
        scored_predictions.append(
            {
                "timeframe": "weekly",
                "edge_at_entry": 10.0,
                "outcome": "loss",
                "net_pnl": -1.0,
                "consensus_probability": 0.28,
            }
        )

    for index in range(4):
        scored_predictions.append(
            {
                "timeframe": "intraday",
                "edge_at_entry": 30.0,
                "outcome": "win" if index == 0 else "loss",
                "net_pnl": -2.0,
                "consensus_probability": 0.35,
            }
        )

    for index in range(2):
        scored_predictions.append(
            {
                "timeframe": "ultra_short",
                "edge_at_entry": 40.0,
                "outcome": "win" if index == 0 else "loss",
                "net_pnl": 2.5,
                "consensus_probability": 0.37,
            }
        )

    diagnostics = PerformanceTracker._build_edge_timeframe_diagnostics(scored_predictions)

    assert diagnostics["verdict"] == "ONLY_LOW_SAMPLE_TIMEFRAME_EDGE_PATCH"
    assert diagnostics["best_sampled_pocket"]["timeframe"] == "weekly"
    assert diagnostics["best_sampled_pocket"]["threshold"] == 10.0
    assert diagnostics["best_sampled_pocket"]["count"] == 5
    assert diagnostics["best_sampled_pocket"]["total_pnl"] == -5.0
    assert diagnostics["best_low_sample_pocket"]["timeframe"] == "ultra_short"
    assert diagnostics["best_low_sample_pocket"]["edge_filter"] == "floor>=40"
    assert diagnostics["best_low_sample_pocket"]["count"] == 2
    assert diagnostics["best_low_sample_pocket"]["total_pnl"] == 5.0
    assert diagnostics["positive_sampled_pocket_count"] == 0
    assert diagnostics["positive_low_sample_pocket_count"] >= 1
    assert diagnostics["gate_verdict"]["status"] == "NO_PROMOTABLE_TIMEFRAME_EDGE_POCKET"
    assert "only_positive_timeframe_edge_pocket_is_ultra_short" in diagnostics["gate_verdict"]["reason_codes"]


def test_latest_cycle_interpretation_distinguishes_none_from_single_provider():
    none_case = QuantResearchTeam._build_latest_cycle_interpretation(
        fresh_enough_for_runtime_summary=True,
        latest_markets_found=1,
        latest_trades_executed=0,
        latest_successful_model_count=0,
        required_consensus_models=2,
        latest_abstain_reason="swarm_model_failures",
        latest_healthy_provider_set="none",
        runtime_provider_verdict={
            "status": "CURRENTLY_BLOCKED",
            "reason_codes": [
                "no_recent_consensus_ready_runs",
                "single_provider_control",
                "persistently_blocked_providers",
                "swarm_model_failures",
            ],
        },
    )
    single_provider_case = QuantResearchTeam._build_latest_cycle_interpretation(
        fresh_enough_for_runtime_summary=True,
        latest_markets_found=1,
        latest_trades_executed=0,
        latest_successful_model_count=1,
        required_consensus_models=2,
        latest_abstain_reason="insufficient_predictions_after_model_failures",
        latest_healthy_provider_set="xai",
        runtime_provider_verdict={
            "status": "CURRENTLY_BLOCKED",
            "reason_codes": [
                "no_recent_consensus_ready_runs",
                "single_provider_control",
                "persistently_blocked_providers",
                "insufficient_predictions_after_model_failures",
            ],
        },
    )

    assert none_case["status"] == "PROVIDER_BLOCKED_NO_TRADE"
    assert "no_healthy_provider_current_run" in none_case["reason_codes"]
    assert "single_provider_control_current_run" not in none_case["reason_codes"]
    assert "single_provider_control" not in none_case["reason_codes"]
    assert single_provider_case["status"] == "PROVIDER_BLOCKED_NO_TRADE"
    assert "single_provider_control_current_run" in single_provider_case["reason_codes"]
    assert "no_healthy_provider_current_run" not in single_provider_case["reason_codes"]


def test_market_archetype_diagnostics_surfaces_no_side_bullish_patch():
    scored_predictions = []

    for _ in range(5):
        scored_predictions.append(
            {
                "timeframe": "weekly",
                "market_type": "bullish",
                "consensus_prediction": "NO",
                "outcome": "loss",
                "net_pnl": -1.0,
                "consensus_probability": 0.33,
            }
        )

    for index in range(2):
        scored_predictions.append(
            {
                "timeframe": "intraday",
                "market_type": "bullish",
                "consensus_prediction": "NO",
                "outcome": "win" if index == 0 else "loss",
                "net_pnl": 3.73,
                "consensus_probability": 0.31,
            }
        )

    for index in range(2):
        scored_predictions.append(
            {
                "timeframe": "ultra_short",
                "market_type": "binary_updown",
                "consensus_prediction": "NO",
                "outcome": "win" if index == 0 else "loss",
                "net_pnl": 2.66,
                "consensus_probability": 0.37,
            }
        )

    diagnostics = PerformanceTracker._build_market_archetype_diagnostics(scored_predictions)

    assert diagnostics["verdict"] == "ONLY_LOW_SAMPLE_MARKET_ARCHETYPE_PATCH"
    assert diagnostics["best_sampled_pocket"]["timeframe"] == "weekly"
    assert diagnostics["best_sampled_pocket"]["market_type"] == "bullish"
    assert diagnostics["best_sampled_pocket"]["direction"] == "NO"
    assert diagnostics["best_sampled_pocket"]["count"] == 5
    assert diagnostics["best_sampled_pocket"]["total_pnl"] == -5.0
    assert diagnostics["best_low_sample_pocket"]["timeframe"] == "intraday"
    assert diagnostics["best_low_sample_pocket"]["market_type"] == "bullish"
    assert diagnostics["best_low_sample_pocket"]["direction"] == "NO"
    assert diagnostics["best_low_sample_pocket"]["count"] == 2
    assert diagnostics["best_low_sample_pocket"]["total_pnl"] == 7.46
    assert diagnostics["positive_sampled_pocket_count"] == 0
    assert diagnostics["positive_low_sample_pocket_count"] == 2
    assert diagnostics["gate_verdict"]["status"] == "NO_PROMOTABLE_MARKET_ARCHETYPE_POCKET"
    assert "only_positive_market_archetype_pockets_are_no_side" in diagnostics["gate_verdict"]["reason_codes"]


def test_entry_price_diagnostics_surfaces_cheap_bullish_no_patch():
    scored_predictions = []

    for price in (0.13, 0.14, 0.15, 0.16, 0.17):
        scored_predictions.append(
            {
                "market_id": f"weekly-{price}",
                "entry_price": price,
                "timeframe": "weekly",
                "market_type": "bullish",
                "consensus_prediction": "NO",
                "outcome": "loss",
                "net_pnl": -1.812,
                "edge_at_entry": 5.72,
            }
        )

    for price, pnl, outcome, timeframe in (
        (0.055, 4.0, "win", "intraday"),
        (0.06, 3.0, "win", "ultra_short"),
        (0.062, -1.28, "loss", "intraday"),
    ):
        scored_predictions.append(
            {
                "market_id": "intraday-2100",
                "entry_price": price,
                "timeframe": timeframe,
                "market_type": "bullish",
                "consensus_prediction": "NO",
                "outcome": outcome,
                "net_pnl": pnl,
                "edge_at_entry": 28.43,
            }
        )

    scored_predictions.append(
        {
            "market_id": "daily-2100",
            "entry_price": 0.25,
            "timeframe": "daily",
            "market_type": "bullish",
            "consensus_prediction": "NO",
            "outcome": "loss",
            "net_pnl": -5.16,
            "edge_at_entry": 12.5,
        }
    )

    diagnostics = PerformanceTracker._build_entry_price_diagnostics(scored_predictions)

    assert diagnostics["verdict"] == "ONLY_LOW_SAMPLE_ENTRY_PRICE_PATCH"
    assert diagnostics["best_sampled_pocket"]["price_band"] == "0.10-0.20"
    assert diagnostics["best_sampled_pocket"]["market_type"] == "bullish"
    assert diagnostics["best_sampled_pocket"]["direction"] == "NO"
    assert diagnostics["best_sampled_pocket"]["count"] == 5
    assert diagnostics["best_sampled_pocket"]["total_pnl"] == -9.06
    assert diagnostics["best_low_sample_pocket"]["price_band"] == "<=0.10"
    assert diagnostics["best_low_sample_pocket"]["market_type"] == "bullish"
    assert diagnostics["best_low_sample_pocket"]["direction"] == "NO"
    assert diagnostics["best_low_sample_pocket"]["count"] == 3
    assert diagnostics["best_low_sample_pocket"]["total_pnl"] == 5.72
    assert diagnostics["cheap_tail_all"]["count"] == 3
    assert diagnostics["cheap_tail_all"]["total_pnl"] == 5.72
    assert diagnostics["cheap_tail_bullish_no_fast"]["timeframe_scope"] == "intraday+ultra_short"
    assert diagnostics["best_low_sample_concentration"]["count"] == 3
    assert diagnostics["best_low_sample_concentration"]["unique_markets"] == 1
    assert diagnostics["best_low_sample_concentration"]["largest_win_pnl"] == 4.0
    assert diagnostics["best_low_sample_concentration"]["residual_pnl_without_largest_win"] == 1.72
    assert diagnostics["best_low_sample_concentration"]["survives_without_largest_win"] is True
    assert diagnostics["cheap_tail_bullish_no_fast_concentration"]["count"] == 3
    assert diagnostics["cheap_tail_bullish_no_fast_concentration"]["unique_markets"] == 1
    assert diagnostics["cheap_tail_bullish_no_fast_concentration"]["largest_win_share_of_total_pnl"] == 0.699
    assert diagnostics["positive_sampled_pocket_count"] == 0
    assert diagnostics["positive_low_sample_pocket_count"] == 1
    assert diagnostics["gate_verdict"]["status"] == "NO_PROMOTABLE_ENTRY_PRICE_POCKET"
    assert "only_positive_entry_price_pockets_are_cheap_bullish_no" in diagnostics["gate_verdict"]["reason_codes"]


def test_quant_research_team_writes_edge_report_and_priorities(tmp_path):
    config = get_polymarket_cli_config(_data_dir_override=tmp_path / "pm_research")
    older_runtime_dir = tmp_path / "polymarket_trader_candidate_soak_older"
    (older_runtime_dir / "predictions").mkdir(parents=True, exist_ok=True)
    (older_runtime_dir / "run_audit.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2029-12-31T23:00:00+00:00",
                "status": "complete",
                "markets_found": 2,
                "trades_executed": 0,
                "phase_progress": [
                    {"phase": "market_scan", "status": "completed", "elapsed_seconds": 10.0},
                    {"phase": "swarm_analysis", "status": "completed", "elapsed_seconds": 5.0},
                    {"phase": "cycle", "status": "complete", "elapsed_seconds": 20.0},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (older_runtime_dir / "predictions" / "prediction_older.json").write_text(
        json.dumps(
            {
                "successful_model_count": 2,
                "abstain_reason": "",
                "measurement_boundary": "swarm",
                "analysis_cohort": "swarm",
                "model_statuses": [
                    {"provider": "claude", "status": "ok"},
                    {"provider": "deepseek", "status": "ok"},
                    {"provider": "xai", "status": "ok"},
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "polymarket_trader_candidate_soak_recent"
    (runtime_dir / "predictions").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "run_audit.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2030-01-01T00:00:00+00:00",
                "status": "complete",
                "markets_found": 3,
                "trades_executed": 0,
                "scanner_telemetry": {
                    "query_count": 21,
                    "raw_records": 1008,
                    "parsed": 935,
                    "filtered": 963,
                    "tradeable": 3,
                    "no_markets": False,
                    "exclusion_reasons": {
                        "low_volume_24h": 408,
                        "low_liquidity": 276,
                        "symbol_filtered": 223,
                    },
                },
                "phase_progress": [
                    {"phase": "market_scan", "status": "completed", "elapsed_seconds": 12.5},
                    {"phase": "swarm_analysis", "status": "completed", "elapsed_seconds": 7.2},
                    {"phase": "cycle", "status": "complete", "elapsed_seconds": 25.0},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (runtime_dir / "predictions" / "prediction_recent.json").write_text(
        json.dumps(
            {
                "successful_model_count": 1,
                "abstain_reason": "swarm_model_failures",
                "current_price": 3012.5,
                "sigma_ratio": 1.7,
                "measurement_boundary": "degraded_swarm",
                "analysis_cohort": "single_model_control",
                "model_statuses": [
                    {"provider": "claude", "status": "exception", "error_code": "insufficient_credits"},
                    {"provider": "deepseek", "status": "exception", "error_code": "insufficient_balance"},
                    {"provider": "xai", "status": "ok"},
                ],
            }
        ),
        encoding="utf-8",
    )
    team = QuantResearchTeam(
        config=config,
        data_dirs=[str(config.data_dir)],
        output_dir=tmp_path / "pm_research" / "research_team",
        scorer=_FakeScorer(),
        scanner_factory=_FakeScanner,
        performance_tracker_cls=_FakePerformanceTracker,
        swarm_health_resolver=_fake_swarm_health,
    )

    report = team.run()

    assert report["edge_snapshot"]["summary"]["supported_symbols"] == ["ETH"]
    assert report["edge_snapshot"]["summary"]["best_variant_by_score"] == "no_replay_accepted_variant"
    assert report["edge_snapshot"]["summary"]["best_exploratory_variant_by_score"] == "eth_swarm_only"
    assert report["edge_snapshot"]["summary"]["best_research_candidate"]["label"].startswith("ETH:swarm_only")
    assert report["edge_snapshot"]["summary"]["best_low_sample_candidate"] == {}
    assert report["edge_snapshot"]["archive_context"]["enabled"] is True
    assert report["runtime_swarm_health"]["ready"] is False
    assert report["runtime_swarm_health"]["recent_runs_considered"] >= 2
    assert report["runtime_swarm_health"]["recent_ready_runs"] >= 1
    assert report["runtime_swarm_health"]["recent_degraded_runs"] >= 1
    assert report["runtime_swarm_health"]["recent_ready_runs"] + report["runtime_swarm_health"]["recent_degraded_runs"] == report["runtime_swarm_health"]["recent_runs_considered"]
    assert report["runtime_swarm_health"]["recent_runtime_blocked_streak_runs"] == 1
    assert report["runtime_swarm_health"]["recent_single_provider_control_streak_runs"] == 1
    assert report["runtime_swarm_health"]["runtime_freshness_verdict"] == "runtime_recent"
    assert report["runtime_swarm_health"]["latest_run_age_hours"] == 0.0
    assert report["runtime_swarm_health"]["runtime_freshness_threshold_hours"] == 6.0
    assert report["runtime_swarm_health"]["fresh_enough_for_runtime_summary"] is True
    assert report["runtime_swarm_health"]["total_runtime_dirs_scanned"] >= 2
    assert report["runtime_swarm_health"]["consensus_ready_runs_observed"] >= 1
    assert report["runtime_swarm_health"]["consensus_ready_history_verdict"] == "consensus_ready_seen_in_history"
    assert report["runtime_swarm_health"]["latest_consensus_ready_data_dir"].endswith("polymarket_trader_candidate_soak_older")
    assert report["runtime_swarm_health"]["latest_consensus_ready_run_age_hours"] == 0.0
    assert report["runtime_swarm_health"]["historical_runs_considered"] == 2
    assert report["runtime_swarm_health"]["historical_ready_runs"] == 1
    assert report["runtime_swarm_health"]["historical_degraded_runs"] == 1
    assert report["runtime_swarm_health"]["historical_provider_ok_rates"]["claude"] == 0.5
    assert report["runtime_swarm_health"]["historical_provider_ok_rates"]["deepseek"] == 0.5
    assert report["runtime_swarm_health"]["historical_provider_ok_rates"]["xai"] == 1.0
    assert report["runtime_swarm_health"]["historical_healthy_provider_sets"]["claude+deepseek+xai"] == 1
    assert report["runtime_swarm_health"]["historical_healthy_provider_sets"]["xai"] == 1
    assert report["runtime_swarm_health"]["historical_single_provider_only_runs"] == 1
    assert report["runtime_swarm_health"]["historical_single_provider_only_rate"] == 0.5
    assert report["runtime_swarm_health"]["historical_xai_only_runs"] == 1
    assert report["runtime_swarm_health"]["historical_xai_only_rate"] == 0.5
    assert report["runtime_swarm_health"]["historical_zero_healthy_provider_runs"] == 0
    assert report["runtime_swarm_health"]["historical_zero_healthy_provider_rate"] == 0.0
    assert report["runtime_swarm_health"]["historical_other_provider_mix_runs"] == 1
    assert report["runtime_swarm_health"]["historical_other_provider_mix_rate"] == 0.5
    assert report["runtime_swarm_health"]["historical_run_error_code_counts"]["insufficient_credits"] == 1
    assert report["runtime_swarm_health"]["historical_run_error_code_counts"]["insufficient_balance"] == 1
    assert report["runtime_swarm_health"]["most_common_historical_healthy_provider_set"] in {"claude+deepseek+xai", "xai"}
    assert report["runtime_swarm_health"]["runtime_provider_verdict"]["status"] == "MIXED_RECENT_HEALTH"
    assert report["runtime_swarm_health"]["latest_cycle_interpretation"]["status"] == "DEGRADED_SWARM_NO_TRADE"
    assert report["runtime_swarm_health"]["latest_run_status"] == "complete"
    assert report["runtime_swarm_health"]["latest_cycle_duration_seconds"] == 25.0
    assert report["runtime_swarm_health"]["latest_market_scan_seconds"] == 12.5
    assert report["runtime_swarm_health"]["latest_swarm_analysis_seconds"] == 7.2
    assert report["runtime_swarm_health"]["latest_markets_found"] == 3
    assert report["runtime_swarm_health"]["latest_trades_executed"] == 0
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["status"] == "TRADEABLE_MARKETS_FOUND_IN_LATEST_RUNTIME_SCAN"
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["query_count"] == 21
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["raw_records"] == 1008
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["parsed"] == 935
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["filtered"] == 963
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["tradeable"] == 3
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["top_exclusion_reasons"][0] == {
        "key": "low_volume_24h",
        "count": 408,
    }
    assert report["runtime_swarm_health"]["latest_runtime_scan_summary"]["top_exclusion_reasons"][1] == {
        "key": "low_liquidity",
        "count": 276,
    }
    assert report["runtime_swarm_health"]["recent_average_latest_successful_model_count"] >= 1.0
    assert report["runtime_swarm_health"]["latest_successful_model_count"] == 1
    assert report["runtime_swarm_health"]["latest_measurement_boundary"] == "degraded_swarm"
    assert report["runtime_swarm_health"]["latest_analysis_cohort"] == "single_model_control"
    assert report["runtime_swarm_health"]["latest_current_price_present"] is True
    assert report["runtime_swarm_health"]["latest_current_price"] == 3012.5
    assert report["runtime_swarm_health"]["latest_sigma_ratio"] == 1.7
    assert report["runtime_swarm_health"]["degraded_prediction_count"] == 1
    assert report["runtime_swarm_health"]["single_model_control_count"] == 1
    assert report["runtime_swarm_health"]["error_code_counts"]["insufficient_credits"] == 1
    assert report["runtime_swarm_health"]["error_code_counts"]["insufficient_balance"] == 1
    assert report["runtime_swarm_health"]["recent_run_error_code_counts"]["insufficient_credits"] == 1
    assert report["runtime_swarm_health"]["recent_run_error_code_counts"]["insufficient_balance"] == 1
    assert report["runtime_swarm_health"]["recent_runtime_dirs_considered"] == 2
    assert report["runtime_swarm_health"]["recent_prediction_runs_considered"] == 2
    assert report["runtime_swarm_health"]["recent_provider_ok_rates"]["claude"] == 0.5
    assert report["runtime_swarm_health"]["recent_provider_ok_rates"]["deepseek"] == 0.5
    assert report["runtime_swarm_health"]["recent_provider_ok_rates"]["xai"] == 1.0
    assert report["runtime_swarm_health"]["recent_primary_cause_counts"] == {
        "consensus_ready": 1,
        "single_provider_control": 1,
    }
    assert report["runtime_swarm_health"]["recent_primary_cause_counted_runs"] == 2
    assert report["runtime_swarm_health"]["most_common_recent_primary_cause"] == "consensus_ready"
    assert report["runtime_swarm_health"]["recent_healthy_provider_sets"]["claude+deepseek+xai"] == 1
    assert report["runtime_swarm_health"]["recent_healthy_provider_sets"]["xai"] == 1
    assert report["runtime_swarm_health"]["most_common_recent_healthy_provider_set"] in {"claude+deepseek+xai", "xai"}
    assert report["runtime_swarm_health"]["single_provider_only_runs"] == 1
    assert report["runtime_swarm_health"]["single_provider_only_rate"] == 0.5
    assert report["runtime_swarm_health"]["persistently_healthy_providers"] == ["xai"]
    assert report["runtime_swarm_health"]["persistently_blocked_providers"] == []
    assert sorted(report["runtime_swarm_health"]["intermittent_providers"]) == ["claude", "deepseek"]
    assert report["inventory_snapshot"]["strict"]["tradeable_markets"] == 0
    assert report["inventory_snapshot"]["broad"]["tradeable_markets"] == 2
    assert report["inventory_snapshot"]["refresh_mode"] == "live_scan"
    assert report["inventory_snapshot"]["source_generated_at"] == ""
    assert report["inventory_diagnostics"]["inventory_freshness_verdict"] == "live_fresh"
    assert report["inventory_diagnostics"]["inventory_snapshot_age_hours"] == 0.0
    assert report["inventory_diagnostics"]["inventory_freshness_threshold_hours"] == 4.0
    assert report["inventory_diagnostics"]["fresh_enough_for_research_summary"] is True
    assert report["inventory_diagnostics"]["strict_share_of_broad"] == 0.0
    assert report["inventory_diagnostics"]["broad_minus_strict_markets"] == 2
    assert report["inventory_diagnostics"]["symbol_expiry_mix_available"] is True
    assert report["inventory_diagnostics"]["inventory_thesis"] == "Market surface exists, but production filters eliminate all current candidates."
    assert report["inventory_diagnostics"]["strict_eth_short_horizon_markets"] == 0
    assert report["inventory_diagnostics"]["broad_eth_short_horizon_markets"] == 1
    assert report["inventory_diagnostics"]["broad_btc_long_dated_markets"] == 1
    assert report["inventory_diagnostics"]["broad_eth_long_dated_markets"] == 0
    assert report["inventory_diagnostics"]["thesis_surface_share_of_broad"] == 0.5
    assert report["inventory_diagnostics"]["strict_thesis_capture_rate"] == 0.0
    assert report["inventory_diagnostics"]["btc_long_dated_to_eth_short_ratio"] == 1.0
    assert report["inventory_diagnostics"]["top_strict_exclusion_reasons"][0]["key"] == "low_volume_24h"
    assert report["inventory_diagnostics"]["top_strict_exclusion_reasons"][0]["count"] == 408
    assert report["inventory_diagnostics"]["top_broad_exclusion_reasons"][0]["key"] == "inactive_market"
    assert report["inventory_diagnostics"]["dominant_broad_symbol"] in {"BTC", "ETH"}
    assert report["inventory_diagnostics"]["dominant_broad_symbol_share"] == 0.5
    assert report["inventory_diagnostics"]["dominant_broad_expiry_share"] == 0.5
    blocker_codes = [item["code"] for item in report["blockers"]]
    assert "no_holdout_support" in blocker_codes
    assert "negative_realized_book" in blocker_codes
    assert "strict_inventory_empty" in blocker_codes
    assert "positive_patch_non_independent" in blocker_codes
    assert "high_confidence_anti_signal" in blocker_codes
    assert "yes_direction_anti_signal" in blocker_codes
    assert report["deployment_verdict"]["status"] == "NO_GO"
    assert report["deployment_verdict"]["deployable_now"] is False
    assert report["deployment_verdict"]["current_scope"] == "research_only"
    assert report["deployment_verdict"]["deployment_target"] == "attended_micro_cap"
    assert report["deployment_verdict"]["approved_symbols"] == []
    assert report["deployment_verdict"]["btc_allowed"] is False
    assert report["deployment_verdict"]["arbitrage_policy"] == "structural_only"
    assert "no_holdout_support" in report["deployment_verdict"]["reason_codes"]
    assert "positive_patch_non_independent" in report["deployment_verdict"]["reason_codes"]
    assert "high_confidence_anti_signal" in report["deployment_verdict"]["reason_codes"]
    assert "yes_direction_anti_signal" in report["deployment_verdict"]["reason_codes"]
    assert "Find a positive ETH patch that survives without one outsized winner and spans more distinct markets before treating it as edge." in report["deployment_verdict"]["requirements"]
    assert "Recalibrate confidence so the >=50% cohort stops losing before using conviction as an edge amplifier." in report["deployment_verdict"]["requirements"]
    assert "Repair directional bias so YES-side calls stop behaving like anti-signal before trusting the swarm on binary direction." in report["deployment_verdict"]["requirements"]
    assert report["calibration_snapshot"]["verdict"] == "HIGH_CONFIDENCE_ANTI_SIGNAL"
    assert report["calibration_snapshot"]["high_confidence"]["count"] == 13
    assert report["calibration_snapshot"]["high_confidence"]["total_pnl"] == -106.51
    assert report["calibration_snapshot"]["gate_verdict"]["status"] == "NO_PROMOTABLE_CONFIDENCE_GATE"
    assert report["calibration_snapshot"]["best_cap"]["threshold"] == 0.3
    assert report["calibration_snapshot"]["best_cap"]["total_pnl"] == -18.59
    assert report["calibration_snapshot"]["best_floor"]["threshold"] == 0.7
    assert report["calibration_snapshot"]["best_floor"]["total_pnl"] == -62.82
    assert len(report["calibration_snapshot"]["cap_sweep"]) == 3
    assert len(report["calibration_snapshot"]["floor_sweep"]) == 3
    assert report["calibration_snapshot"]["confidence_monotonicity_broken"] is True
    assert report["edge_quality_snapshot"]["verdict"] == "ONLY_LOW_SAMPLE_EDGE_PATCH"
    assert report["edge_quality_snapshot"]["gate_verdict"]["status"] == "NO_PROMOTABLE_EDGE_GATE"
    assert report["edge_quality_snapshot"]["min_trade_count"] == 5
    assert report["edge_quality_snapshot"]["best_floor"]["threshold"] == 30.0
    assert report["edge_quality_snapshot"]["best_floor"]["count"] == 7
    assert report["edge_quality_snapshot"]["best_floor"]["total_pnl"] == -10.0
    assert report["edge_quality_snapshot"]["best_cap"]["threshold"] == 10.0
    assert report["edge_quality_snapshot"]["best_cap"]["total_pnl"] == -36.55
    assert report["edge_quality_snapshot"]["best_low_sample_floor"]["threshold"] == 40.0
    assert report["edge_quality_snapshot"]["best_low_sample_floor"]["total_pnl"] == 5.32
    assert report["edge_quality_snapshot"]["low_edge"]["count"] == 12
    assert report["edge_quality_snapshot"]["high_edge"]["count"] == 11
    assert report["edge_quality_snapshot"]["high_edge_beats_low_edge"] is False
    assert len(report["edge_quality_snapshot"]["cap_sweep"]) == 3
    assert len(report["edge_quality_snapshot"]["floor_sweep"]) == 3
    assert report["edge_timeframe_snapshot"]["verdict"] == "ONLY_LOW_SAMPLE_TIMEFRAME_EDGE_PATCH"
    assert report["edge_timeframe_snapshot"]["gate_verdict"]["status"] == "NO_PROMOTABLE_TIMEFRAME_EDGE_POCKET"
    assert report["edge_timeframe_snapshot"]["best_sampled_pocket"]["timeframe"] == "weekly"
    assert report["edge_timeframe_snapshot"]["best_sampled_pocket"]["edge_filter"] == "cap<=10"
    assert report["edge_timeframe_snapshot"]["best_sampled_pocket"]["total_pnl"] == -9.06
    assert report["edge_timeframe_snapshot"]["best_low_sample_pocket"]["timeframe"] == "ultra_short"
    assert report["edge_timeframe_snapshot"]["best_low_sample_pocket"]["edge_filter"] == "floor>=40"
    assert report["edge_timeframe_snapshot"]["best_low_sample_pocket"]["total_pnl"] == 5.32
    assert report["edge_timeframe_snapshot"]["positive_sampled_pocket_count"] == 0
    assert report["edge_timeframe_snapshot"]["positive_low_sample_pocket_count"] == 1
    assert report["market_archetype_snapshot"]["verdict"] == "ONLY_LOW_SAMPLE_MARKET_ARCHETYPE_PATCH"
    assert report["market_archetype_snapshot"]["gate_verdict"]["status"] == "NO_PROMOTABLE_MARKET_ARCHETYPE_POCKET"
    assert report["market_archetype_snapshot"]["best_sampled_pocket"]["timeframe"] == "weekly"
    assert report["market_archetype_snapshot"]["best_sampled_pocket"]["market_type"] == "bullish"
    assert report["market_archetype_snapshot"]["best_sampled_pocket"]["direction"] == "NO"
    assert report["market_archetype_snapshot"]["best_sampled_pocket"]["total_pnl"] == -9.06
    assert report["market_archetype_snapshot"]["best_low_sample_pocket"]["timeframe"] == "intraday"
    assert report["market_archetype_snapshot"]["best_low_sample_pocket"]["market_type"] == "bullish"
    assert report["market_archetype_snapshot"]["best_low_sample_pocket"]["direction"] == "NO"
    assert report["market_archetype_snapshot"]["best_low_sample_pocket"]["total_pnl"] == 7.46
    assert report["market_archetype_snapshot"]["positive_sampled_pocket_count"] == 0
    assert report["market_archetype_snapshot"]["positive_low_sample_pocket_count"] == 2
    assert report["entry_price_snapshot"]["verdict"] == "ONLY_LOW_SAMPLE_ENTRY_PRICE_PATCH"
    assert report["entry_price_snapshot"]["gate_verdict"]["status"] == "NO_PROMOTABLE_ENTRY_PRICE_POCKET"
    assert report["entry_price_snapshot"]["best_sampled_pocket"]["price_band"] == "0.10-0.20"
    assert report["entry_price_snapshot"]["best_sampled_pocket"]["market_type"] == "bullish"
    assert report["entry_price_snapshot"]["best_sampled_pocket"]["direction"] == "NO"
    assert report["entry_price_snapshot"]["best_sampled_pocket"]["total_pnl"] == -9.06
    assert report["entry_price_snapshot"]["best_low_sample_pocket"]["price_band"] == "<=0.10"
    assert report["entry_price_snapshot"]["best_low_sample_pocket"]["market_type"] == "bullish"
    assert report["entry_price_snapshot"]["best_low_sample_pocket"]["direction"] == "NO"
    assert report["entry_price_snapshot"]["best_low_sample_pocket"]["total_pnl"] == 5.72
    assert report["entry_price_snapshot"]["cheap_tail_all"]["count"] == 3
    assert report["entry_price_snapshot"]["cheap_tail_bullish_no"]["total_pnl"] == 5.72
    assert report["entry_price_snapshot"]["cheap_tail_bullish_no_fast"]["timeframe_scope"] == "intraday+ultra_short"
    assert report["entry_price_snapshot"]["best_low_sample_concentration"]["count"] == 3
    assert report["entry_price_snapshot"]["best_low_sample_concentration"]["unique_markets"] == 2
    assert report["entry_price_snapshot"]["best_low_sample_concentration"]["largest_win_pnl"] == 29.61
    assert report["entry_price_snapshot"]["best_low_sample_concentration"]["survives_without_largest_win"] is False
    assert report["entry_price_snapshot"]["cheap_tail_bullish_no_fast_concentration"]["count"] == 2
    assert report["entry_price_snapshot"]["cheap_tail_bullish_no_fast_concentration"]["unique_markets"] == 1
    assert report["entry_price_snapshot"]["cheap_tail_bullish_no_fast_concentration"]["largest_win_share_of_total_pnl"] == 3.969
    assert report["entry_price_snapshot"]["best_low_sample_independence_verdict"]["status"] == "NON_INDEPENDENT_PATCH"
    assert report["entry_price_snapshot"]["best_low_sample_independence_verdict"]["reason_codes"] == [
        "low_trade_count",
        "two_or_fewer_markets",
        "fails_without_top_win",
        "top_win_exceeds_total_patch_pnl",
    ]
    assert report["entry_price_snapshot"]["cheap_tail_bullish_no_fast_independence_verdict"]["status"] == "NON_INDEPENDENT_PATCH"
    assert report["entry_price_snapshot"]["cheap_tail_bullish_no_fast_independence_verdict"]["reason_codes"] == [
        "low_trade_count",
        "single_market_patch",
        "fails_without_top_win",
        "top_win_exceeds_total_patch_pnl",
    ]
    assert report["entry_price_snapshot"]["positive_sampled_pocket_count"] == 0
    assert report["entry_price_snapshot"]["positive_low_sample_pocket_count"] == 1
    assert report["surviving_patch_snapshot"]["status"] == "PATCH_FOUND"
    assert report["surviving_patch_snapshot"]["symbol"] == "ETH"
    assert report["surviving_patch_snapshot"]["research_bar"] == 5
    assert report["surviving_patch_snapshot"]["patch"]["price_band"] == "<=0.10"
    assert report["surviving_patch_snapshot"]["patch"]["market_type"] == "bullish"
    assert report["surviving_patch_snapshot"]["patch"]["direction"] == "NO"
    assert report["surviving_patch_snapshot"]["patch"]["total_pnl"] == 5.72
    assert report["surviving_patch_snapshot"]["concentration"]["unique_markets"] == 2
    assert report["surviving_patch_snapshot"]["concentration"]["residual_pnl_without_largest_win"] == -23.89
    assert report["surviving_patch_snapshot"]["independence_verdict"]["status"] == "NON_INDEPENDENT_PATCH"
    assert report["surviving_patch_snapshot"]["promotability"]["status"] == "RESEARCH_ONLY_NON_INDEPENDENT"
    assert report["surviving_patch_snapshot"]["promotability"]["reason_codes"] == [
        "low_trade_count",
        "two_or_fewer_markets",
        "fails_without_top_win",
        "top_win_exceeds_total_patch_pnl",
    ]
    assert report["active_edge_snapshot"]["status"] == "POSITIVE_CONFIG_UNCONFIRMED"
    assert report["active_edge_snapshot"]["best_active_configuration"]["label"] == "eth_swarm_only"
    assert report["active_edge_snapshot"]["best_active_configuration"]["filtered_trades"] == 7
    assert report["active_edge_snapshot"]["best_active_configuration"]["total_pnl"] == 81.0
    assert report["active_edge_snapshot"]["best_active_configuration"]["replay_accepted"] is False
    assert report["active_edge_snapshot"]["positive_active_configuration_count"] == 3
    assert report["active_edge_snapshot"]["replay_accepted_active_configuration_count"] == 0
    assert report["active_edge_snapshot"]["positive_replay_accepted_active_configuration_count"] == 0
    assert report["active_edge_snapshot"]["best_positive_active_configuration"]["label"] == "eth_swarm_only"
    assert report["active_edge_snapshot"]["best_positive_active_configuration"]["total_pnl"] == 81.0
    assert report["active_edge_snapshot"]["surviving_patch_found"] is True
    assert report["active_edge_snapshot"]["surviving_patch_promotability"]["status"] == "RESEARCH_ONLY_NON_INDEPENDENT"
    assert report["active_edge_snapshot"]["reason_codes"] == [
        "best_active_configuration_not_replay_accepted",
        "surviving_patch_is_slice_not_configuration",
        "surviving_patch_not_promotable",
    ]
    assert report["runtime_regime_snapshot"]["status"] == "LATEST_CYCLE_BLOCKED"
    assert report["runtime_regime_snapshot"]["latest_blocker_code"] == "cycle_blocked"
    assert report["runtime_regime_snapshot"]["latest_blocker"] == "DEGRADED_SWARM_NO_TRADE; reasons=['markets_found_but_swarm_degraded', 'swarm_model_failures']"
    assert report["runtime_regime_snapshot"]["chronic_blocker_code"] == "none"
    assert report["runtime_regime_snapshot"]["chronic_blocker"] == "none"
    assert report["runtime_regime_snapshot"]["recent_primary_cause_counts"] == {
        "consensus_ready": 1,
        "single_provider_control": 1,
    }
    assert report["runtime_regime_snapshot"]["most_common_recent_primary_cause"] == "consensus_ready"
    assert report["runtime_regime_snapshot"]["recent_runtime_dirs_considered"] == 2
    assert report["runtime_regime_snapshot"]["recent_prediction_runs_considered"] == 2
    assert report["direction_snapshot"]["verdict"] == "YES_DIRECTION_ANTI_SIGNAL"
    assert report["direction_snapshot"]["gate_verdict"]["status"] == "NO_PROMOTABLE_DIRECTION_GATE"
    assert report["direction_snapshot"]["yes"]["count"] == 13
    assert report["direction_snapshot"]["yes"]["total_pnl"] == -106.51
    assert report["direction_snapshot"]["no"]["count"] == 22
    assert report["direction_snapshot"]["no"]["total_pnl"] == -86.45
    assert report["direction_snapshot"]["best_direction"]["direction"] == "NO"
    assert report["direction_snapshot"]["best_direction"]["total_pnl"] == -86.45
    assert report["direction_snapshot"]["pocket_verdict"]["status"] == "NO_PROMOTABLE_DIRECTION_TIMEFRAME_POCKET"
    assert report["direction_snapshot"]["best_direction_timeframe"]["direction"] == "NO"
    assert report["direction_snapshot"]["best_direction_timeframe"]["timeframe"] == "ultra_short"
    assert report["direction_snapshot"]["best_direction_timeframe"]["count"] == 2
    assert report["direction_snapshot"]["best_direction_timeframe"]["total_pnl"] == 5.32
    assert report["direction_snapshot"]["worst_direction_timeframe"]["direction"] == "YES"
    assert report["direction_snapshot"]["worst_direction_timeframe"]["timeframe"] == "daily"
    assert report["direction_snapshot"]["worst_direction_timeframe"]["total_pnl"] == -64.77
    assert report["direction_snapshot"]["worst_direction_timeframe"]["drag_share_of_negative_loss"] == 0.336
    assert len(report["direction_snapshot"]["top_negative_direction_timeframes"]) == 3
    assert report["direction_snapshot"]["top_two_directional_drag_share"] == 0.612
    assert report["direction_snapshot"]["exclusion_rescue"]["status"] == "NO_SIMPLE_EXCLUSION_RESCUE"
    assert len(report["direction_snapshot"]["exclusion_rescue"]["scenarios"]) == 4
    assert report["direction_snapshot"]["exclusion_rescue"]["scenarios"][0]["label"] == "drop_worst_pocket"
    assert report["direction_snapshot"]["exclusion_rescue"]["scenarios"][0]["residual_pnl"] == -128.19
    assert report["direction_snapshot"]["exclusion_rescue"]["scenarios"][2]["label"] == "drop_top3_pockets"
    assert report["direction_snapshot"]["exclusion_rescue"]["scenarios"][2]["residual_pnl"] == -45.47
    assert report["policy_rescue_snapshot"]["verdict"] == "ONLY_LOW_SAMPLE_COMPOSITE_PATCH"
    assert report["policy_rescue_snapshot"]["gate_verdict"]["status"] == "NO_PROMOTABLE_COMPOSITE_POLICY"
    assert report["policy_rescue_snapshot"]["min_trade_count"] == 5
    assert report["policy_rescue_snapshot"]["best_sampled_policy"]["direction"] == "NO"
    assert report["policy_rescue_snapshot"]["best_sampled_policy"]["timeframe"] == "intraday"
    assert report["policy_rescue_snapshot"]["best_sampled_policy"]["confidence_filter"] == "cap<=40%"
    assert report["policy_rescue_snapshot"]["best_sampled_policy"]["count"] == 7
    assert report["policy_rescue_snapshot"]["best_sampled_policy"]["total_pnl"] == -21.33
    assert report["policy_rescue_snapshot"]["best_low_sample_policy"]["timeframe"] == "ultra_short"
    assert report["policy_rescue_snapshot"]["best_low_sample_policy"]["total_pnl"] == 5.32
    assert report["policy_rescue_snapshot"]["positive_sampled_policy_count"] == 0
    assert report["policy_rescue_snapshot"]["positive_low_sample_policy_count"] == 1
    assert len(report["policy_rescue_snapshot"]["top_rows"]) == 3
    assert report["risk_return_snapshot"]["expectancy_per_closed_trade"] == -5.51
    assert report["risk_return_snapshot"]["payoff_ratio"] == 3.15
    assert report["risk_return_snapshot"]["pnl_to_drawdown"] == -1.0
    assert report["expiry_policy_snapshot"]["scope"] == "ETH-only"
    assert report["expiry_policy_snapshot"]["comparison_basis"]["profile_label"] == "swarm_arb min=none"
    assert report["expiry_policy_snapshot"]["current_cap"]["cap_label"] == "<=24h"
    assert report["expiry_policy_snapshot"]["best_active_profile_cap"]["cap_label"] == "<=1h"
    assert report["expiry_policy_snapshot"]["best_active_profile_cap_with_min_sample"]["cap_label"] == "<=1h"
    assert report["expiry_policy_snapshot"]["best_exploratory_cap_any_profile"]["cap_label"] == "<=1h"
    assert report["expiry_policy_snapshot"]["best_active_profile_cap_delta_vs_current"]["pnl_delta"] == 0.0
    assert report["expiry_policy_snapshot"]["best_active_profile_cap_with_min_sample_delta_vs_current"]["filtered_trade_delta"] == 0
    assert report["expiry_policy_snapshot"]["active_profile_cap_verdict"]["status"] == "PROMOTABLE_WITH_SAMPLE"
    assert report["expiry_policy_snapshot"]["active_profile_cap_verdict"]["promotable_cap_label"] == "<=1h"
    assert report["expiry_policy_snapshot"]["rows"][0]["cap_label"] == "<=1h"
    assert "<=24h" in report["expiry_policy_snapshot"]["positive_active_profile_caps_with_min_sample"]
    assert report["symbol_verdicts"]["ETH"]["status"] == "RESEARCH_ONLY"
    assert report["symbol_verdicts"]["ETH"]["edge_status"] == "measured_positive_unconfirmed"
    assert report["symbol_verdicts"]["ETH"]["current_lane"]["filtered_trades"] == 9
    assert report["symbol_verdicts"]["ETH"]["best_measured_positive_lane"]["label"].startswith("ETH:")
    assert report["symbol_verdicts"]["ETH"]["best_low_sample_positive_lane"] == {}
    assert "no_replay_acceptance" in report["symbol_verdicts"]["ETH"]["reason_codes"]
    assert "positive_patch_non_independent" in report["symbol_verdicts"]["ETH"]["reason_codes"]
    assert "negative_realized_book" in report["symbol_verdicts"]["ETH"]["reason_codes"]
    assert report["symbol_verdicts"]["BTC"]["status"] == "RESEARCH_ONLY"
    assert report["symbol_verdicts"]["BTC"]["edge_status"] == "negative_or_flat_current_lane"
    assert report["symbol_verdicts"]["BTC"]["current_lane"]["filtered_trades"] == 2
    assert report["symbol_verdicts"]["BTC"]["best_measured_positive_lane"] == {}
    assert "btc_not_supported" in report["symbol_verdicts"]["BTC"]["reason_codes"]

    priority_codes = [item["code"] for item in report["priorities"]]
    assert "eth_first_until_btc_proves_itself" in priority_codes
    assert "paper_test_best_measured_variant" in priority_codes
    assert "restore_swarm_providers" in priority_codes
    assert "fix_runtime_swarm_health" in priority_codes
    assert "repair_confidence_calibration" in priority_codes
    assert "do_not_expect_confidence_gating_fix" in priority_codes
    assert "strip_yes_side_bias" in priority_codes
    assert "do_not_promote_direction_timeframe_patch" in priority_codes
    assert "do_not_expect_one_filter_fix" in priority_codes
    assert "split_inventory_policy" in priority_codes
    assert "keep_arb_structural_only" in priority_codes
    assert "do_not_generalize_ultra_short_blip" in priority_codes
    assert "do_not_promote_non_independent_tail_patch" in priority_codes
    assert "holdout_first" in priority_codes
    assert "fix_latest_runtime_inventory_block" not in priority_codes
    priority_by_code = {item["code"]: item for item in report["priorities"]}
    fix_runtime_priority = priority_by_code["fix_runtime_swarm_health"]
    assert "Historical runtime cohort: 1/2 runs were runtime-ready." in fix_runtime_priority["actions"]
    assert "Historical provider ok-rates: {'claude': 0.5, 'deepseek': 0.5, 'xai': 1.0}." in fix_runtime_priority["actions"]
    assert any("Historical healthy-provider sets:" in action for action in fix_runtime_priority["actions"])
    assert "Historical failure composition: xai-only=1 (50.0%), no-healthy-provider=0 (0.0%), other=1." in fix_runtime_priority["actions"]
    assert "Historical run-level error pattern: {'insufficient_credits': 1, 'insufficient_balance': 1}." in fix_runtime_priority["actions"]

    manifest_path = tmp_path / "pm_research" / "research_team" / "team_manifest.json"
    report_path = tmp_path / "pm_research" / "research_team" / "edge_report.json"
    markdown_path = tmp_path / "pm_research" / "research_team" / "edge_report.md"

    assert manifest_path.exists()
    assert report_path.exists()
    assert markdown_path.exists()

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Universe Scout" in markdown
    assert "Supported symbols today: `ETH`" in markdown
    assert "Best active configuration: `eth_swarm_only +81.00 (7 trades, replay=False, holdout=0)`" in markdown
    assert "Positive active configurations: `3`" in markdown
    assert "Best positive active configuration: `eth_swarm_only +81.00 (7 trades, replay=False, holdout=0)`" in markdown
    assert "Replay-accepted active configurations: `0`" in markdown
    assert "Current runtime blocker: `DEGRADED_SWARM_NO_TRADE; reasons=['markets_found_but_swarm_degraded', 'swarm_model_failures']`" in markdown
    assert "Runtime blocker regime: `LATEST_CYCLE_BLOCKED; latest=DEGRADED_SWARM_NO_TRADE; reasons=['markets_found_but_swarm_degraded', 'swarm_model_failures']; chronic=none; recent_mix=consensus_ready:1; single_provider_control:1; dirs=2; prediction_runs=2`" in markdown
    assert "Active edge read: `POSITIVE_CONFIG_UNCONFIRMED; reasons=['best_active_configuration_not_replay_accepted', 'surviving_patch_is_slice_not_configuration', 'surviving_patch_not_promotable']`" in markdown
    assert "Surviving ETH patch: `<=0.10 / bullish / NO: 3 trades, WR 66.7%, PnL $+5.72, avg px 0.059, avg edge 28.43`" in markdown
    assert "Surviving ETH patch stress test: `3 trades / 2 markets, top win $+29.61, largest loss $-22.15, residual ex-best $-23.89, top-win share 517.6%, survives ex-best False`" in markdown
    assert "Surviving ETH patch verdict: `NON_INDEPENDENT_PATCH; reasons=['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`" in markdown
    assert "Surviving ETH patch promotability: `RESEARCH_ONLY_NON_INDEPENDENT; reasons=['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`" in markdown
    assert "Deployment Verdict" in markdown
    assert "Status: `NO_GO`" in markdown
    assert "Deployable now: `False`" in markdown
    assert "Current scope: `research_only`" in markdown
    assert "Symbol Verdicts" in markdown
    assert "ETH: `RESEARCH_ONLY` / `measured_positive_unconfirmed`" in markdown
    assert "BTC: `RESEARCH_ONLY` / `negative_or_flat_current_lane`" in markdown
    assert "Deployment Requirements" in markdown
    assert "Earn filtered holdout support and a replay-accepted variant before deployment." in markdown
    assert "Best Measured Candidate" in markdown
    assert "Expiry Policy" in markdown
    assert "Active ETH profile basis: `swarm_arb min=none`" in markdown
    assert "Current ETH cap on active profile: `<=24h +82.80 (9 trades, replay=False)`" in markdown
    assert "Best active-profile ETH cap: `<=1h +82.80 (9 trades, replay=False)`" in markdown
    assert "Best active-profile cap delta vs current: `+0.00 PnL / +0 trades / +0.00 score`" in markdown
    assert "Best active-profile ETH cap with >= 5 trades: `<=1h +82.80 (9 trades, replay=False)`" in markdown
    assert "Best sampled active-profile cap delta vs current: `+0.00 PnL / +0 trades / +0.00 score`" in markdown
    assert "Best exploratory ETH cap across any profile: `<=1h +81.00 (7 trades, replay=False)`" in markdown
    assert "Active-profile cap verdict: `PROMOTABLE_WITH_SAMPLE; sampled=<=1h; exploratory=none; reasons=[]`" in markdown
    assert "Positive active-profile caps with >= 5 trades: `<=1h, <=4h, <=12h, <=24h, uncapped`" in markdown
    assert "Active-profile ETH cap sweep: `<=1h +82.80 (9 trades, replay=False);" in markdown
    assert "Swarm Health" in markdown
    assert "Runtime Swarm Health" in markdown
    assert "Runtime freshness verdict: `runtime_recent`" in markdown
    assert "Latest run age hours: `0.00h`" in markdown
    assert "Runtime fresh enough for summary: `True`" in markdown
    assert "Recent runtime dirs / prediction-bearing runs: `2` / `2`" in markdown
    assert "Runtime provider verdict: `MIXED_RECENT_HEALTH; healthy_set=" in markdown
    assert "Latest cycle interpretation: `DEGRADED_SWARM_NO_TRADE; reasons=" in markdown
    assert "Latest runtime scan verdict: `TRADEABLE_MARKETS_FOUND_IN_LATEST_RUNTIME_SCAN`" in markdown
    assert "Latest runtime scan query/raw/parsed/filtered/tradeable: `21 / 1008 / 935 / 963 / 3`" in markdown
    assert "Latest runtime scan top exclusions: `low_volume_24h: 408; low_liquidity: 276; symbol_filtered: 223`" in markdown
    assert "Runtime dirs scanned / consensus-ready observed: `2` / `1`" in markdown
    assert "Consensus-ready history verdict: `consensus_ready_seen_in_history`" in markdown
    assert "Latest consensus-ready run age hours: `0.00h`" in markdown
    assert "Latest consensus-ready data dir: `" in markdown
    assert "Historical runtime cohort (runs / ready / degraded): `2` / `1` / `1`" in markdown
    assert "Historical provider ok-rates: `{'claude': 0.5, 'deepseek': 0.5, 'xai': 1.0}`" in markdown
    assert "Historical healthy-provider sets: `" in markdown
    assert "Historical failure composition (xai-only / no-healthy / other): `1` / `0` / `1`" in markdown
    assert "Historical failure rates (xai-only / no-healthy): `50.0%` / `0.0%`" in markdown
    assert "claude+deepseek+xai': 1" in markdown
    assert "'xai': 1" in markdown
    assert "Historical run-level error codes: `{'insufficient_credits': 1, 'insufficient_balance': 1}`" in markdown
    assert "Most common historical healthy-provider set: `" in markdown
    assert "Recent blocked-run streak: `1`" in markdown
    assert "Historical runtime cohort: 1/2 runs were runtime-ready." in markdown
    assert "Historical provider ok-rates: {'claude': 0.5, 'deepseek': 0.5, 'xai': 1.0}." in markdown
    assert "Historical failure composition: xai-only=1 (50.0%), no-healthy-provider=0 (0.0%), other=1." in markdown
    assert "Historical run-level error pattern: {'insufficient_credits': 1, 'insufficient_balance': 1}." in markdown
    assert "Calibration Credibility" in markdown
    assert "Verdict: `HIGH_CONFIDENCE_ANTI_SIGNAL`" in markdown
    assert "High-confidence cohort: `>=50%: 13 trades, WR 0.0%, PnL $-106.51, avg p=0.672, gap=+0.672`" in markdown
    assert "Severe-confidence cohort: `>=70%: 6 trades, WR 0.0%, PnL $-62.82, avg p=0.785, gap=+0.785`" in markdown
    assert "Sub-50% cohort: `below threshold: 22 trades, WR 9.1%, PnL $-86.45, avg p=0.345, gap=+0.254`" in markdown
    assert "Confidence gate verdict: `NO_PROMOTABLE_CONFIDENCE_GATE; reasons=['best_cap_still_negative_or_thin', 'high_confidence_floor_negative', 'confidence_monotonicity_broken']`" in markdown
    assert "Best simple confidence cap: `<=30%: 5 trades, WR 20.0%, PnL $-18.59`" in markdown
    assert "Best simple confidence floor: `>=70%: 6 trades, WR 0.0%, PnL $-62.82`" in markdown
    assert "Confidence cap sweep: `<=30%: 5 trades, WR 20.0%, PnL $-18.59; <=40%: 14 trades, WR 14.3%, PnL $-41.47; <=50%: 24 trades, WR 8.3%, PnL $-104.75`" in markdown
    assert "Confidence floor sweep: `>=50%: 13 trades, WR 0.0%, PnL $-106.51; >=60%: 9 trades, WR 0.0%, PnL $-78.98; >=70%: 6 trades, WR 0.0%, PnL $-62.82`" in markdown
    assert "Confidence monotonicity broken: `True`" in markdown
    assert "Edge Quality" in markdown
    assert "Verdict: `ONLY_LOW_SAMPLE_EDGE_PATCH`" in markdown
    assert "Gate verdict: `NO_PROMOTABLE_EDGE_GATE; reasons=['best_sampled_edge_floor_still_negative_or_flat', 'best_sampled_edge_cap_still_negative_or_flat', 'only_low_sample_positive_edge_floor']`" in markdown
    assert "Sample bar: `5`" in markdown
    assert "Best sampled edge floor: `>=30: 7 trades, WR 28.6%, PnL $-10.00, avg edge 40.41`" in markdown
    assert "Best sampled edge cap: `<=10: 12 trades, WR 0.0%, PnL $-36.55, avg edge 6.48`" in markdown
    assert "Best low-sample edge floor: `>=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25`" in markdown
    assert "Low-edge cohort: `<=10: 12 trades, WR 0.0%, PnL $-36.55, avg edge 6.48`" in markdown
    assert "High-edge cohort: `>=20: 11 trades, WR 18.2%, PnL $-61.59, avg edge 34.48`" in markdown
    assert "Higher edge beats low edge: `False`" in markdown
    assert "Edge cap sweep: `<=10: 12 trades, WR 0.0%, PnL $-36.55, avg edge 6.48; <=20: 24 trades, WR 0.0%, PnL $-131.37, avg edge 11.21; <=40: 33 trades, WR 3.0%, PnL $-198.28, avg edge 16.85`" in markdown
    assert "Edge floor sweep: `>=20: 11 trades, WR 18.2%, PnL $-61.59, avg edge 34.48; >=30: 7 trades, WR 28.6%, PnL $-10.00, avg edge 40.41; >=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25`" in markdown
    assert "Timeframe + Edge Pockets" in markdown
    assert "Verdict: `ONLY_LOW_SAMPLE_TIMEFRAME_EDGE_PATCH`" in markdown
    assert "Gate verdict: `NO_PROMOTABLE_TIMEFRAME_EDGE_POCKET; reasons=['best_sampled_timeframe_edge_pocket_still_negative_or_flat', 'only_low_sample_positive_timeframe_edge_pocket', 'only_positive_timeframe_edge_pocket_is_ultra_short']`" in markdown
    assert "Best sampled timeframe-edge pocket: `weekly / cap<=10: 5 trades, WR 0.0%, PnL $-9.06, avg edge 6.10`" in markdown
    assert "Best low-sample timeframe-edge pocket: `ultra_short / floor>=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25`" in markdown
    assert "Positive sampled / low-sample timeframe-edge pockets: `0` / `1`" in markdown
    assert "Top timeframe-edge pockets: `ultra_short / floor>=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25; weekly / cap<=10: 5 trades, WR 0.0%, PnL $-9.06, avg edge 6.10; intraday / floor>=30: 4 trades, WR 25.0%, PnL $-7.42, avg edge 31.40`" in markdown
    assert "Market Archetype Pockets" in markdown
    assert "Verdict: `ONLY_LOW_SAMPLE_MARKET_ARCHETYPE_PATCH`" in markdown
    assert "Gate verdict: `NO_PROMOTABLE_MARKET_ARCHETYPE_POCKET; reasons=['best_sampled_market_archetype_pocket_still_negative_or_flat', 'only_low_sample_positive_market_archetype_pocket', 'only_positive_market_archetype_pockets_are_no_side']`" in markdown
    assert "Best sampled market-archetype pocket: `weekly / bullish / NO: 5 trades, WR 0.0%, PnL $-9.06`" in markdown
    assert "Best low-sample market-archetype pocket: `intraday / bullish / NO: 2 trades, WR 50.0%, PnL $+7.46`" in markdown
    assert "Positive sampled / low-sample market-archetype pockets: `0` / `2`" in markdown
    assert "Top market-archetype pockets: `intraday / bullish / NO: 2 trades, WR 50.0%, PnL $+7.46; ultra_short / binary_updown / NO: 2 trades, WR 50.0%, PnL $+5.32; weekly / bullish / NO: 5 trades, WR 0.0%, PnL $-9.06`" in markdown
    assert "Entry Price Pockets" in markdown
    assert "Verdict: `ONLY_LOW_SAMPLE_ENTRY_PRICE_PATCH`" in markdown
    assert "Gate verdict: `NO_PROMOTABLE_ENTRY_PRICE_POCKET; reasons=['best_sampled_entry_price_pocket_still_negative_or_flat', 'only_low_sample_positive_entry_price_pocket', 'only_positive_entry_price_pockets_are_cheap_bullish_no']`" in markdown
    assert "Best sampled entry-price pocket: `0.10-0.20 / bullish / NO: 5 trades, WR 0.0%, PnL $-9.06, avg px 0.145, avg edge 5.72`" in markdown
    assert "Best low-sample entry-price pocket: `<=0.10 / bullish / NO: 3 trades, WR 66.7%, PnL $+5.72, avg px 0.059, avg edge 28.43`" in markdown
    assert "Cheap-tail all cohort: `<=0.10 / ALL / ALL: 3 trades, WR 66.7%, PnL $+5.72, avg px 0.059, avg edge 28.43`" in markdown
    assert "Cheap-tail bullish-NO cohort: `<=0.10 / bullish / NO: 3 trades, WR 66.7%, PnL $+5.72, avg px 0.059, avg edge 28.43`" in markdown
    assert "Cheap-tail bullish-NO fast cohort: `<=0.10 / bullish / NO / intraday+ultra_short: 2 trades, WR 50.0%, PnL $+7.46, avg px 0.057, avg edge 39.05`" in markdown
    assert "Best low-sample patch concentration: `3 trades / 2 markets, top win $+29.61, largest loss $-22.15, residual ex-best $-23.89, top-win share 517.6%, survives ex-best False`" in markdown
    assert "Cheap-tail bullish-NO fast concentration: `2 trades / 1 markets, top win $+29.61, largest loss $-22.15, residual ex-best $-22.15, top-win share 396.9%, survives ex-best False`" in markdown
    assert "Low-sample patch independence verdict: `NON_INDEPENDENT_PATCH; reasons=['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`" in markdown
    assert "Cheap-tail fast-subset independence verdict: `NON_INDEPENDENT_PATCH; reasons=['low_trade_count', 'single_market_patch', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`" in markdown
    assert "Positive sampled / low-sample entry-price pockets: `0` / `1`" in markdown
    assert "Top entry-price pockets: `<=0.10 / bullish / NO: 3 trades, WR 66.7%, PnL $+5.72, avg px 0.059, avg edge 28.43; 0.10-0.20 / bullish / NO: 5 trades, WR 0.0%, PnL $-9.06, avg px 0.145, avg edge 5.72; 0.20-0.30 / bullish / NO: 1 trades, WR 0.0%, PnL $-5.16, avg px 0.250, avg edge 12.50`" in markdown
    assert "Directional Credibility" in markdown
    assert "Verdict: `YES_DIRECTION_ANTI_SIGNAL`" in markdown
    assert "Direction gate verdict: `NO_PROMOTABLE_DIRECTION_GATE; reasons=['yes_direction_losing', 'best_direction_still_negative', 'yes_worse_than_no']`" in markdown
    assert "YES cohort: `YES: 13 trades, WR 0.0%, PnL $-106.51, avg p=0.672`" in markdown
    assert "NO cohort: `NO: 22 trades, WR 9.1%, PnL $-86.45, avg p=0.345`" in markdown
    assert "Best direction gate: `NO: 22 trades, WR 9.1%, PnL $-86.45`" in markdown
    assert "Direction-timeframe pocket verdict: `NO_PROMOTABLE_DIRECTION_TIMEFRAME_POCKET; reasons=['best_pocket_low_sample', 'only_positive_pocket_is_no_ultra_short']`" in markdown
    assert "Composite Policy Rescue" in markdown
    assert "Verdict: `ONLY_LOW_SAMPLE_COMPOSITE_PATCH`" in markdown
    assert "Gate verdict: `NO_PROMOTABLE_COMPOSITE_POLICY; reasons=['best_sampled_policy_still_negative_or_flat', 'only_low_sample_positive_composite_policy']`" in markdown
    assert "Sample bar: `5`" in markdown
    assert "Best sampled composite policy: `NO / intraday / cap<=40%: 7 trades, WR 14.3%, PnL $-21.33`" in markdown
    assert "Best low-sample composite policy: `NO / ultra_short / cap<=40%: 2 trades, WR 50.0%, PnL $+5.32`" in markdown
    assert "Positive sampled / low-sample composite policies: `0` / `1`" in markdown
    assert "Top composite policies: `NO / ultra_short / cap<=40%: 2 trades, WR 50.0%, PnL $+5.32; NO / intraday / cap<=40%: 7 trades, WR 14.3%, PnL $-21.33; YES / daily / floor>=50%: 8 trades, WR 0.0%, PnL $-64.77`" in markdown
    assert "Best direction-timeframe pocket: `NO / ultra_short: 2 trades, WR 50.0%, PnL $+5.32`" in markdown
    assert "Worst direction-timeframe drag pocket: `YES / daily: 8 trades, WR 0.0%, PnL $-64.77, drag share 33.6%`" in markdown
    assert "Top directional drag pockets: `YES / daily: 8 trades, WR 0.0%, PnL $-64.77, drag share 33.6%; NO / intraday: 12 trades, WR 8.3%, PnL $-53.25, drag share 27.6%; NO / daily: 3 trades, WR 0.0%, PnL $-29.47, drag share 15.3%`" in markdown
    assert "Top-two directional drag share: `61.2%`" in markdown
    assert "Exclusion rescue verdict: `NO_SIMPLE_EXCLUSION_RESCUE; reasons=['residual_negative_after_all_simple_cuts', 'worst_pocket_not_dominant_enough', 'best_residual_still_negative']`" in markdown
    assert "Exclusion rescue scenarios: `drop_worst_pocket: removed 8 trades / $-64.77, residual $-128.19; drop_top2_pockets: removed 20 trades / $-118.02, residual $-74.94; drop_top3_pockets: removed 23 trades / $-147.49, residual $-45.47; drop_all_yes: removed 13 trades / $-106.51, residual $-86.45`" in markdown
    assert "Risk/Return" in markdown
    assert "Expectancy per closed trade: `$-5.51`" in markdown
    assert "Payoff ratio: `3.15`" in markdown
    assert "Replay Cohort" in markdown
    assert "Blockers" in markdown
    assert "There is no filtered holdout support for the current ETH configuration" in markdown
    assert "Holdout gate feasible today: `False`" in markdown
    assert "Recent runtime cohort (runs / ready / degraded):" in markdown
    assert "Latest cycle duration seconds: `25.0`" in markdown
    assert "Latest market scan / swarm analysis seconds: `12.5` / `7.2`" in markdown
    assert "Latest markets found / trades executed: `3` / `0`" in markdown
    assert "Inventory refresh mode: `live_scan`" in markdown
    assert "Inventory freshness verdict: `live_fresh`" in markdown
    assert "Inventory snapshot age hours: `0.00h`" in markdown
    assert "Inventory fresh enough for research summary: `True`" in markdown
    assert "Strict share of broad surface: `0.0%`" in markdown
    assert "Inventory funnel read: `Market surface exists, but production filters eliminate all current candidates.`" in markdown
    assert "Strict ETH short-horizon markets: `0`" in markdown
    assert "Broad ETH short-horizon markets: `1`" in markdown
    assert "Broad BTC long-dated markets: `1`" in markdown
    assert "Thesis surface share of broad: `50.0%`" in markdown
    assert "Strict thesis capture rate: `0.0%`" in markdown
    assert "BTC long-dated to ETH short-horizon ratio: `1.00x`" in markdown
    assert "Top strict exclusion reasons: `low_volume_24h 408" in markdown
    assert "Recent run-level error codes: `{'insufficient_credits': 1, 'insufficient_balance': 1}`" in markdown
    assert "Recent provider ok-rates: `{'claude': 0.5, 'deepseek': 0.5, 'xai': 1.0}`" in markdown
    assert "Persistently healthy / blocked providers: `['xai']` / `[]`" in markdown
    assert "Recent runtime primary-cause mix: `consensus_ready:1; single_provider_control:1`" in markdown
    assert "Most common recent primary cause: `consensus_ready`" in markdown
    assert "Recent healthy-provider sets:" in markdown
    assert "claude+deepseek+xai" in markdown
    assert "'xai': 1" in markdown
    assert "Single-provider-only runs: `1` (50.0%)" in markdown
    assert "Recent single-provider-control streak: `1`" in markdown
    assert "Positive timeframe lanes: `ultra_short +5.32 (2 trades)`" in markdown
    assert "PnL concentrated in one positive timeframe: `True`" in markdown
    assert "Do not generalize the lone positive timeframe without more samples" in markdown
    assert "Diagnostic widened holdout support: `False`" in markdown
    assert "20% raw=3 filtered=0; 30% raw=6 filtered=0; 40% raw=7 filtered=0; 50% raw=8 filtered=0" in markdown
    assert "Latest current price present: `True`" in markdown
    assert "Latest measurement boundary: `degraded_swarm`" in markdown


def test_build_latest_runtime_scan_summary_marks_no_tradeable_markets_when_filtered_empty():
    summary = QuantResearchTeam._build_latest_runtime_scan_summary(
        {
            "query_count": 21,
            "raw_records": 1050,
            "parsed": 987,
            "filtered": 1050,
            "tradeable": 0,
            "no_markets": True,
            "exclusion_reasons": {
                "low_volume_24h": 414,
                "low_liquidity": 276,
                "symbol_filtered": 223,
            },
        }
    )

    assert summary["status"] == "NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN"
    assert summary["reason_codes"] == ["low_volume_24h", "low_liquidity", "symbol_filtered"]
    assert summary["top_exclusion_reasons"][0] == {"key": "low_volume_24h", "count": 414}


def test_quant_research_team_can_skip_inventory_refresh(tmp_path):
    config = get_polymarket_cli_config(_data_dir_override=tmp_path / "pm_research_skip")

    def _scanner_should_not_run(_config):
        raise AssertionError("scanner should not run when inventory refresh is skipped")

    team = QuantResearchTeam(
        config=config,
        output_dir=tmp_path / "pm_research_skip" / "research_team",
        scorer=_FakeScorer(),
        scanner_factory=_scanner_should_not_run,
        performance_tracker_cls=_FakePerformanceTracker,
        swarm_health_resolver=_fake_swarm_health,
        skip_inventory=True,
    )

    report = team.run()

    assert report["inventory_snapshot"]["refresh_mode"] == "skipped_no_prior_snapshot"
    assert report["inventory_snapshot"]["source_generated_at"] == ""
    assert report["inventory_snapshot"]["strict"]["telemetry"]["skipped"] is True
    assert report["inventory_snapshot"]["broad"]["telemetry"]["skipped"] is True
    assert report["inventory_diagnostics"]["inventory_freshness_verdict"] == "no_inventory_snapshot"
    assert report["inventory_diagnostics"]["inventory_snapshot_age_hours"] is None
    assert report["inventory_diagnostics"]["fresh_enough_for_research_summary"] is False
    assert report["inventory_diagnostics"]["symbol_expiry_mix_available"] is False
    assert report["inventory_diagnostics"]["inventory_thesis"] == "No broad ETH/BTC market surface is currently visible."
    assert report["inventory_diagnostics"]["broad_eth_short_horizon_markets"] == 0
    assert report["inventory_diagnostics"]["broad_btc_long_dated_markets"] == 0
    assert report["inventory_diagnostics"]["strict_thesis_capture_rate"] is None
    assert report["inventory_diagnostics"]["btc_long_dated_to_eth_short_ratio"] is None
    assert report["expiry_policy_snapshot"]["current_cap"]["cap_label"] == "<=24h"
    assert report["expiry_policy_snapshot"]["best_active_profile_cap"]["cap_label"] == "<=1h"
    assert report["expiry_policy_snapshot"]["best_active_profile_cap_with_min_sample"]["cap_label"] == "<=1h"
    assert report["swarm_health"]["ready"] is False


def test_quant_research_team_skip_inventory_carries_forward_previous_snapshot(tmp_path):
    config = get_polymarket_cli_config(_data_dir_override=tmp_path / "pm_research_carry")
    output_dir = tmp_path / "pm_research_carry" / "research_team"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "edge_report.json").write_text(
        json.dumps(
            {
                "generated_at": "2030-01-01T00:00:00+00:00",
                "inventory_snapshot": {
                    "refresh_mode": "live_scan",
                    "source_generated_at": "",
                    "strict": {
                        "config": {"search_symbols": ["ETH"]},
                        "telemetry": {"query_count": 21},
                        "tradeable_markets": 1,
                        "by_symbol": {"ETH": 1},
                        "by_market_type": {},
                        "by_expiry_bucket": {},
                        "sample_questions": ["Will ETH be above $3,000 tomorrow?"],
                    },
                    "broad": {
                        "config": {"search_symbols": ["ETH", "BTC"]},
                        "telemetry": {"query_count": 21},
                        "tradeable_markets": 4,
                        "by_symbol": {"ETH": 3, "BTC": 1},
                        "by_market_type": {},
                        "by_expiry_bucket": {},
                        "sample_questions": ["Will ETH be above $3,000 tomorrow?"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def _scanner_should_not_run(_config):
        raise AssertionError("scanner should not run when inventory refresh is skipped")

    team = QuantResearchTeam(
        config=config,
        output_dir=output_dir,
        scorer=_FakeScorer(),
        scanner_factory=_scanner_should_not_run,
        performance_tracker_cls=_FakePerformanceTracker,
        swarm_health_resolver=_fake_swarm_health,
        skip_inventory=True,
    )

    report = team.run()

    assert report["inventory_snapshot"]["refresh_mode"] == "carried_forward"
    assert report["inventory_snapshot"]["source_generated_at"] == "2030-01-01T00:00:00+00:00"
    assert report["inventory_snapshot"]["strict"]["tradeable_markets"] == 1
    assert report["inventory_snapshot"]["broad"]["tradeable_markets"] == 4
    assert report["inventory_snapshot"]["strict"]["telemetry"]["skipped"] is True
    assert report["inventory_snapshot"]["strict"]["telemetry"]["carried_forward"] is True
    assert report["inventory_diagnostics"]["inventory_freshness_verdict"] == "carried_forward_recent"
    assert report["inventory_diagnostics"]["inventory_snapshot_age_hours"] == 0.0
    assert report["inventory_diagnostics"]["inventory_freshness_threshold_hours"] == 4.0
    assert report["inventory_diagnostics"]["fresh_enough_for_research_summary"] is True
    assert report["inventory_diagnostics"]["strict_share_of_broad"] == 0.25
    assert report["inventory_diagnostics"]["symbol_expiry_mix_available"] is False
    assert report["inventory_diagnostics"]["inventory_thesis"] == "Market surface exists, but strict production filters compress it sharply."
    assert report["inventory_diagnostics"]["strict_eth_short_horizon_markets"] == 0
    assert report["inventory_diagnostics"]["broad_eth_short_horizon_markets"] == 0
    assert report["inventory_diagnostics"]["broad_btc_long_dated_markets"] == 0
    assert report["inventory_diagnostics"]["strict_thesis_capture_rate"] is None
    assert report["inventory_diagnostics"]["btc_long_dated_to_eth_short_ratio"] is None
    assert report["expiry_policy_snapshot"]["best_active_profile_cap"]["cap_label"] == "<=1h"
    assert report["expiry_policy_snapshot"]["best_active_profile_cap_with_min_sample"]["cap_label"] == "<=1h"
