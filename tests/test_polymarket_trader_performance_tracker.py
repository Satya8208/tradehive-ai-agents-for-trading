import csv
import json
from datetime import datetime, timedelta

from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.performance_tracker import PerformanceTracker


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_performance_tracker_links_predictions_and_writes_canonical_outputs(tmp_path):
    data_dir = tmp_path / "pm_eval"
    trades_dir = data_dir / "trades"
    preds_dir = data_dir / "predictions"
    trades_dir.mkdir(parents=True)
    preds_dir.mkdir(parents=True)

    entry_time = datetime(2026, 1, 1, 10, 10, 0)
    close_time = entry_time + timedelta(hours=1)
    market_id = "m-track-1"

    _write_jsonl(
        trades_dir / "trades_20260101.jsonl",
        [
            {
                "trade_id": "entry-1",
                "market_id": market_id,
                "token_id": "token-1",
                "side": "YES",
                "size_usd": 10.0,
                "price": 0.5,
                "status": "paper_filled",
                "execution_mode": "paper",
                "timestamp": entry_time.isoformat(),
                "order_id": None,
                "fees": 0.2,
                "source": "swarm",
                "reason": "Swarm: YES (100% agree, prob=0.78) | Edge: 18.0% YES | Kelly: $10.00",
                "confidence": 0.81,
                "symbol": "ETH",
                "question": "Will ETH break out?",
                "duration_minutes": 60,
                "time_remaining_hours": 10.0,
                "market_type": "bullish",
            },
            {
                "trade_id": "close-1",
                "market_id": market_id,
                "token_id": "token-1",
                "side": "CLOSE_YES",
                "size_usd": 10.0,
                "price": 0.8,
                "status": "closed",
                "execution_mode": "paper",
                "timestamp": close_time.isoformat(),
                "order_id": None,
                "fees": 0.05,
            },
        ],
    )

    _write_jsonl(
        preds_dir / "prediction_m-track-1_20260101_100500.json",
        [
            {
                "market_id": market_id,
                "timestamp": (entry_time - timedelta(minutes=5)).isoformat(),
                "consensus_prediction": "NO",
                "consensus_probability": 0.35,
                "consensus_confidence": 0.55,
                "yes_votes": 1,
                "no_votes": 2,
                "agreement_ratio": 0.67,
                "predictions": [],
                "market_question": "Will ETH break out?",
                "market_symbol": "ETH",
            }
        ],
    )

    _write_jsonl(
        preds_dir / "prediction_m-track-1_20260101_100700.json",
        [
            {
                "market_id": market_id,
                "timestamp": (entry_time - timedelta(minutes=3)).isoformat(),
                "consensus_prediction": "YES",
                "consensus_probability": 0.76,
                "consensus_confidence": 0.82,
                "successful_model_count": 2,
                "runtime_ready": True,
                "measurement_boundary": "swarm",
                "analysis_cohort": "swarm",
                "yes_votes": 2,
                "no_votes": 1,
                "agreement_ratio": 0.67,
                "predictions": [
                    {
                        "model_provider": "openai",
                        "model_name": "gpt-4o",
                        "prediction": "YES",
                        "probability_estimate": 0.77,
                        "confidence": 0.9,
                        "reasoning": "aligned",
                        "response_time": 1.0,
                    },
                    {
                        "model_provider": "openai",
                        "model_name": "gpt-4o",
                        "prediction": "NO",
                        "probability_estimate": 0.23,
                        "confidence": 0.7,
                        "reasoning": "dissent",
                        "response_time": 1.1,
                    },
                ],
                "market_question": "Will ETH break out?",
                "market_symbol": "ETH",
            }
        ],
    )

    tracker = PerformanceTracker(
        get_polymarket_cli_config(
            _data_dir_override=data_dir,
            max_expiry_hours=6.0,
            min_expiry_hours=0.0,
        )
    )
    summary = tracker.generate_report()

    assert summary["closed_trades"] == 1
    assert summary["prediction_coverage"] == 1.0
    assert summary["consensus_accuracy"] == 1.0
    assert summary["model_accuracy_weighted_accuracy"] == 0.5
    assert "replay" in summary
    assert summary["replay"]["accepted"] is False
    assert summary["replay"]["candidate"]["filtered_trades"] == 0
    assert summary["replay"]["trailing_holdout_probe"]["diagnostic_only"] is True
    assert summary["replay"]["trailing_holdout_probe"]["any_filtered_holdout"] is False
    assert [row["holdout_ratio"] for row in summary["replay"]["trailing_holdout_probe"]["ratios"]] == [0.2, 0.3, 0.4, 0.5]

    journal_path = data_dir / "performance" / "trade_journal.csv"
    rows = list(csv.DictReader(journal_path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 1
    row = rows[0]
    assert row["consensus_prediction"] == "YES"
    assert row["prediction_match"] == "True"
    assert row["actual_side"] == "YES"
    assert row["prediction_model_count"] == "2"
    assert row["prediction_successful_model_count"] == "2"
    assert row["prediction_runtime_ready"] == "True"
    assert row["prediction_measurement_boundary"] == "swarm"
    assert row["prediction_analysis_cohort"] == "swarm"
    assert abs(float(row["prediction_age_minutes"]) - 3.0) < 0.01

    calibration_path = data_dir / "performance" / "calibration.csv"
    calibration_rows = list(csv.DictReader(calibration_path.read_text(encoding="utf-8").splitlines()))
    assert {r["group_type"] for r in calibration_rows} == {"overall", "source", "symbol", "timeframe"}
    overall = next(r for r in calibration_rows if r["group_type"] == "overall")
    assert overall["group_value"] == "all"
    assert overall["actual_win_rate"] == "1.0"

    model_path = data_dir / "performance" / "model_accuracy.csv"
    model_rows = list(csv.DictReader(model_path.read_text(encoding="utf-8").splitlines()))
    assert len(model_rows) == 1
    assert model_rows[0]["model"] == "openai/gpt-4o"
    assert model_rows[0]["correct"] == "1"
    assert model_rows[0]["accuracy"] == "0.5"

    replay_path = data_dir / "performance" / "replay_summary.json"
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    assert replay_payload["trailing_holdout_probe"]["shipping_gate_unchanged"] is True
