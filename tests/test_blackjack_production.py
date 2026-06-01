import csv
import json
from pathlib import Path

from src.agents.blackjack.auto_optimize import BJAutoOptimizer
from src.agents.blackjack.bj_scorer import BJParamSet, BJScorer
from src.agents.blackjack.pro_trainer import ProTrainer


def test_bj_scorer_is_deterministic():
    scorer = BJScorer(num_hands=300, num_sessions=2, base_seed=17)
    params = BJParamSet()

    first = scorer.score(params)
    second = scorer.score(params)

    assert first.total_pnl == second.total_pnl
    assert first.score == second.score
    assert first.hourly_rate == second.hourly_rate
    assert first.hourly_rate_ci_low <= first.hourly_rate_ci_high
    assert 0 <= first.play_rate <= 1


def test_bj_auto_optimizer_writes_param_snapshot(tmp_path):
    results_path = tmp_path / "blackjack_results.tsv"

    optimizer = BJAutoOptimizer(
        num_hands=300,
        num_sessions=2,
        results_path=str(results_path),
        min_hands_threshold=200,
        max_drawdown_threshold=1.0,
        min_play_rate=0.0,
    )
    optimizer.run(max_rounds=1)

    with results_path.open() as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert len(rows) == 2
    assert "params_snapshot" in rows[0]
    snapshot = json.loads(rows[0]["params_snapshot"])
    assert snapshot["counting_system"] in {"hi_lo", "omega_ii", "wong_halves"}


def test_pro_trainer_prefers_param_snapshot(tmp_path):
    trainer = ProTrainer(counting_system="hi_lo")
    tsv_path = tmp_path / "optimization.tsv"

    with tsv_path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([
            "round", "score", "win_rate", "pnl", "hands",
            "roi", "profit_per_hand", "max_drawdown", "ruin_rate",
            "hourly_rate", "hourly_ci_low", "hourly_ci_high", "play_rate",
            "wonged_out", "status", "description", "params_changed",
            "params_snapshot",
        ])
        writer.writerow([
            0, "1.0", "0.40", "10", 1000, "0.01", "0.01", "0.10", "0.00",
            "5.0", "1.0", "9.0", "0.80", 10, "baseline", "initial", "{}",
            json.dumps({"counting_system": "hi_lo"}),
        ])
        writer.writerow([
            1, "9.0", "0.42", "50", 2000, "0.02", "0.02", "0.20", "0.00",
            "20.0", "5.0", "35.0", "0.85", 20, "keep", "improved", "{}",
            json.dumps({"counting_system": "omega_ii", "spread_ratio": 14.0}),
        ])

    best = trainer._load_best_optimization(tsv_path)

    assert best is not None
    assert best["counting_system"] == "omega_ii"
    assert best["spread_ratio"] == 14.0


def test_pro_trainer_readiness_and_session_analysis():
    trainer = ProTrainer(counting_system="hi_lo")
    trainer.progress = {
        "drills": {
            "deviation": [{"correct": 19, "total": 20}],
            "full_table_counting": [{"correct": 8, "total": 10, "avg_time_sec": 2.4}],
            "bet_sizing": [{"correct": 8, "total": 10}],
        },
        "sessions": [],
    }

    readiness = trainer.get_readiness_report()
    assert readiness["score"] > 80
    assert readiness["level"] in {"advanced", "table_ready"}
    assert readiness["certification"]["status"] in {"certified", "near_ready"}
    assert len(readiness["practice_blocks"]) >= 1

    analysis = trainer.analyze_session(
        hands=120,
        hours=2.0,
        wagered=2400,
        pnl=180,
        min_bet=25,
        max_bet=200,
        save=False,
    )
    assert "metrics" in analysis
    assert "benchmark" in analysis
    assert "discipline_score" in analysis
    assert len(analysis["next_drills"]) >= 1
    assert analysis["metrics"]["hourly_rate"] == 90.0
