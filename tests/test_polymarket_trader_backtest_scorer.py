import json
from datetime import datetime, timedelta

from src.agents.polymarket_trader.backtest_scorer import BacktestScorer, ParamSet


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _make_entry(idx, timestamp, source, reason, confidence):
    market_id = f"m-replay-{idx:02d}"
    return {
        "trade_id": f"entry-{idx:02d}",
        "market_id": market_id,
        "token_id": f"token-{idx:02d}",
        "side": "YES",
        "size_usd": 10.0,
        "price": 0.5,
        "status": "paper_filled",
        "execution_mode": "paper",
        "timestamp": timestamp.isoformat(),
        "order_id": None,
        "fees": 0.1,
        "source": source,
        "reason": reason,
        "confidence": confidence,
        "symbol": "ETH",
        "question": f"Will ETH move {idx}?",
        "duration_minutes": 60,
        "time_remaining_hours": 10.0,
        "market_type": "bullish",
    }


def _make_close(idx, timestamp, price):
    return {
        "trade_id": f"close-{idx:02d}",
        "market_id": f"m-replay-{idx:02d}",
        "token_id": f"token-{idx:02d}",
        "side": "CLOSE_YES",
        "size_usd": 10.0,
        "price": price,
        "status": "closed",
        "execution_mode": "paper",
        "timestamp": timestamp.isoformat(),
        "order_id": None,
        "fees": 0.0,
    }


def test_score_replay_holds_out_by_market_and_accepts_cleaner_filter(tmp_path):
    data_dir = tmp_path / "pm_replay"
    trades_dir = data_dir / "trades"
    trades_dir.mkdir(parents=True)

    start = datetime(2026, 1, 1, 0, 0, 0)
    rows = []
    for idx in range(30):
        ts = start + timedelta(minutes=idx)
        if idx % 2 == 0:
            rows.append(
                _make_entry(
                    idx,
                    ts,
                    "swarm",
                    "Swarm: YES (100% agree, prob=0.78) | Edge: 18.0% YES | Kelly: $10.00",
                    0.84,
                )
            )
            rows.append(_make_close(idx, ts + timedelta(hours=1), 0.8))
        else:
            rows.append(
                _make_entry(
                    idx,
                    ts,
                    "arbitrage",
                    "Arb: range_sum - 30.0% edge",
                    1.0,
                )
            )
            rows.append(_make_close(idx, ts + timedelta(hours=1), 0.2))

    _write_jsonl(trades_dir / "trades_20260101.jsonl", rows)

    scorer = BacktestScorer(data_dirs=[str(data_dir)])
    baseline = scorer.score(ParamSet())
    candidate = scorer.score(ParamSet(allow_arb=False))
    replay = scorer.score_replay(ParamSet(allow_arb=False), holdout_ratio=0.5)

    assert baseline.filtered_trades == 30
    assert candidate.filtered_trades == 15
    assert candidate.score > baseline.score
    assert replay.split_markets == 30
    assert replay.train_markets == 15
    assert replay.holdout_markets == 15
    assert replay.candidate.filtered_trades == 15
    assert replay.holdout.filtered_trades < replay.baseline_holdout.filtered_trades
    assert replay.holdout.score > replay.baseline_holdout.score
    assert replay.accepted is True
    assert replay.generalization_gap >= 0
    assert replay.cohort_diagnostics["all"]["unique_markets"] == 30
    assert replay.cohort_diagnostics["holdout"]["total_trades"] == 15
    assert replay.cohort_diagnostics["holdout"]["exclusion_reasons"]["source_arbitrage_disabled"] > 0
    assert replay.holdout_total_trades == 15
    assert replay.gate_feasible is True


def test_score_respects_expiry_filters(tmp_path):
    data_dir = tmp_path / "pm_replay_expiry"
    trades_dir = data_dir / "trades"
    trades_dir.mkdir(parents=True)

    start = datetime(2026, 1, 1, 0, 0, 0)
    rows = [
        _make_entry(
            0,
            start,
            "swarm",
            "Swarm: YES (100% agree, prob=0.78) | Edge: 18.0% YES | Kelly: $10.00",
            0.84,
        ),
        _make_close(0, start + timedelta(hours=1), 0.8),
        _make_entry(
            1,
            start + timedelta(minutes=1),
            "swarm",
            "Swarm: YES (100% agree, prob=0.78) | Edge: 18.0% YES | Kelly: $10.00",
            0.84,
        ),
        _make_close(1, start + timedelta(hours=1, minutes=1), 0.8),
    ]
    rows[0]["time_remaining_hours"] = 2.0
    rows[2]["time_remaining_hours"] = 10.0
    _write_jsonl(trades_dir / "trades_20260101.jsonl", rows)

    scorer = BacktestScorer(data_dirs=[str(data_dir)])
    short_only = scorer.score(ParamSet(min_expiry_hours=0.0, max_expiry_hours=4.0))
    longer_only = scorer.score(ParamSet(min_expiry_hours=4.0, max_expiry_hours=24.0))

    assert short_only.filtered_trades == 1
    assert longer_only.filtered_trades == 1
