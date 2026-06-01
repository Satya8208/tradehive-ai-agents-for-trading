import csv
import json

from fastapi.testclient import TestClient

from src.agents.poker.auto_optimize import PokerAutoOptimizer
from src.agents.poker.poker_agent import GameFormat, GameMode, PokerAgent, parse_cards
from src.agents.poker.core.poker_types import Street
from src.agents.poker.live_advisor import LiveAdvisor
from src.agents.poker.poker_scorer import PokerParamSet, PokerScorer
from src.agents.poker.strategy.decision_engine import DecisionEngine
from src.agents.poker.strategy.postflop_engine import HandCategory, PostflopEngine
from src.agents.poker.strategy.preflop_engine import Position
from src.agents.poker.swarm_advisor import AdvisorOpinion, PokerSwarmAdvisor
from src.agents.poker.vision import VisionModelUnavailableError
from src.agents.poker.web_dashboard import api as poker_api
from src.agents.poker.web_dashboard.api import app


def test_poker_scorer_is_deterministic_and_reports_errors():
    scorer = PokerScorer(num_hands=200, num_sessions=2, base_seed=11)
    params = PokerParamSet()

    first = scorer.score(params)
    second = scorer.score(params)

    assert first.total_pnl == second.total_pnl
    assert first.score == second.score
    assert first.bb_per_100 == second.bb_per_100
    assert first.hand_errors == 0
    assert first.bb_per_100_ci_low <= first.bb_per_100_ci_high


def test_poker_auto_optimizer_writes_param_snapshot(tmp_path):
    results_path = tmp_path / "poker_results.tsv"

    optimizer = PokerAutoOptimizer(
        num_hands=150,
        num_sessions=2,
        results_path=str(results_path),
        min_hands_threshold=150,
        max_drawdown_threshold=1.0,
    )
    optimizer.run(max_rounds=1)

    with results_path.open() as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert len(rows) == 2
    assert "params_snapshot" in rows[0]
    snapshot = json.loads(rows[0]["params_snapshot"])
    assert "rfi_utg_pct" in snapshot


def test_live_advisor_tracks_state_and_decision():
    advisor = LiveAdvisor()
    advisor.cmd_new("AhKs BTN")
    advisor.cmd_flop("Qh7c2d")
    advisor.cmd_pot("12")
    advisor.cmd_stack("80")

    assert len(advisor.hole_cards) == 2
    assert len(advisor.board) == 3
    assert advisor.position == Position.BTN
    assert advisor.pot == 12.0
    assert advisor.effective_stack == 80.0

    decision = advisor.decision.get_decision(
        hole_cards=advisor.hole_cards,
        board=advisor.board,
        position=advisor.position,
        pot=advisor.pot,
        bet_to_call=4.0,
        street=Street.FLOP,
        in_position=True,
        villain_type=advisor.villain_type,
        effective_stack=advisor.effective_stack,
    )

    assert decision.action in {"fold", "call", "raise", "check", "bet", "check_raise", "all_in"}


def test_swarm_aggregate_majority_without_models():
    swarm = PokerSwarmAdvisor()
    opinions = [
        AdvisorOpinion("tight", "fold", "", 65, "Too weak", "mock-tight"),
        AdvisorOpinion("balanced", "call", "1x", 72, "Enough equity", "mock-balanced"),
        AdvisorOpinion("aggressive", "call", "1x", 81, "Pressure later", "mock-aggro"),
    ]

    decision = swarm._aggregate(opinions)

    assert decision.consensus_action == "call"
    assert decision.consensus_sizing == "1x"
    assert decision.agreement_ratio == 2 / 3


def test_postflop_engine_does_not_create_fake_draws_from_board_texture():
    engine = PostflopEngine()

    category, result = engine.analyze_hand_strength(
        parse_cards("AhKs"),
        parse_cards("Qh7c2d"),
    )

    assert category == HandCategory.TRASH
    assert result.description == "High Card, A"


def test_postflop_engine_detects_real_hero_draws():
    engine = PostflopEngine()

    category, _ = engine.analyze_hand_strength(
        parse_cards("9h8h"),
        parse_cards("7h6d2c"),
    )

    assert category == HandCategory.DRAW


def test_decision_engine_respects_equity_when_facing_bet():
    engine = DecisionEngine()

    decision = engine.get_decision(
        hole_cards=parse_cards("AhKs"),
        board=parse_cards("Qh7c2d"),
        position=Position.BTN,
        pot=12.0,
        bet_to_call=4.0,
        street=Street.FLOP,
        in_position=True,
        villain_type="reg",
        effective_stack=80.0,
    )

    assert decision.equity >= decision.pot_odds
    assert decision.action == "call"


def test_poker_agent_postflop_advice_matches_unified_engine():
    agent = PokerAgent(mode=GameMode.ADVISOR, game_format=GameFormat.CASH)
    agent.new_hand(parse_cards("AhKs"), Position.BTN)
    agent.set_board(parse_cards("Qh7c2d"))
    agent.set_pot(12.0, 4.0)

    result = agent.get_postflop_advice(in_position=True)

    assert result["decision"].action == "call"


def test_web_api_postflop_advice_serializes_unified_decision():
    client = TestClient(app)

    assert client.post(
        "/api/poker/new_hand",
        json={"hole_cards": "AhKs", "position": "btn"},
    ).status_code == 200
    assert client.post(
        "/api/poker/set_board",
        json={"cards": "Qh7c2d"},
    ).status_code == 200
    assert client.post(
        "/api/poker/set_pot",
        json={"pot_size": 12.0, "bet_to_call": 4.0, "effective_stack": 80.0},
    ).status_code == 200

    response = client.post("/api/poker/postflop_advice", json={"in_position": True})

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["action"] == "call"


def test_web_api_favicon_does_not_404():
    client = TestClient(app)

    response = client.get("/favicon.ico")

    assert response.status_code in {200, 204}


def test_web_api_stateless_analyze_ignores_legacy_session_state():
    client = TestClient(app)

    assert client.post(
        "/api/poker/new_hand",
        json={"session_id": "legacy-a", "hole_cards": "2c7d", "position": "sb"},
    ).status_code == 200
    assert client.post(
        "/api/poker/set_board",
        json={"session_id": "legacy-a", "cards": "AcKdQs"},
    ).status_code == 200

    response = client.post(
        "/api/poker/analyze",
        json={
            "hole_cards": "AhKs",
            "board": "Qh7c2d",
            "hero_position": "BTN",
            "villain_position": "BB",
            "pot_size": 12.0,
            "bet_to_call": 4.0,
            "effective_stack": 80.0,
            "street": "FLOP",
            "action_history": ["btn open 2.5bb", "bb call", "flop bet 33%"],
            "is_preflop_aggressor": True,
            "villain_type": "reg",
            "player_count": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["action"] == "call"
    assert body["spot_summary"]["hero_position"] == "BTN"
    assert body["spot_summary"]["villain_position"] == "BB"


def test_web_api_session_stats_isolated_by_session_id():
    client = TestClient(app)

    assert client.post("/api/poker/reset_session", json={"session_id": "iso-a"}).status_code == 200
    assert client.post("/api/poker/reset_session", json={"session_id": "iso-b"}).status_code == 200
    assert client.post("/api/poker/record_result", json={"session_id": "iso-a", "won": True, "amount": 12.5}).status_code == 200
    assert client.post("/api/poker/record_result", json={"session_id": "iso-b", "won": False, "amount": 7.0}).status_code == 200

    stats_a = client.get("/api/poker/session_stats", params={"session_id": "iso-a"})
    stats_b = client.get("/api/poker/session_stats", params={"session_id": "iso-b"})

    assert stats_a.status_code == 200
    assert stats_b.status_code == 200
    assert stats_a.json()["hands_won"] == 1
    assert stats_a.json()["total_profit"] == 12.5
    assert stats_b.json()["hands_won"] == 0
    assert stats_b.json()["total_profit"] == -7.0


def test_web_api_analyze_rejects_duplicate_cards():
    client = TestClient(app)

    response = client.post(
        "/api/poker/analyze",
        json={
            "hole_cards": "AhKs",
            "board": "Ah7c2d",
            "hero_position": "BTN",
            "villain_position": "BB",
            "pot_size": 10.0,
            "bet_to_call": 3.0,
            "effective_stack": 75.0,
        },
    )

    assert response.status_code == 400
    assert "Duplicate cards" in response.json()["detail"]


def test_web_api_analyze_requires_hero_position():
    client = TestClient(app)

    response = client.post(
        "/api/poker/analyze",
        json={
            "hole_cards": "AhKs",
            "board": "Qh7c2d",
            "pot_size": 10.0,
            "bet_to_call": 3.0,
            "effective_stack": 75.0,
        },
    )

    assert response.status_code == 400
    assert "Hero position is required" in response.json()["detail"]


def test_web_api_analyze_btn_vs_bb_is_in_position():
    client = TestClient(app)

    response = client.post(
        "/api/poker/analyze",
        json={
            "hole_cards": "AhKs",
            "board": "Qh7c2d",
            "hero_position": "BTN",
            "villain_position": "BB",
            "pot_size": 12.0,
            "bet_to_call": 4.0,
            "effective_stack": 80.0,
            "street": "FLOP",
            "action_history": ["btn open 2.5bb", "bb call", "flop bet 33%"],
            "is_preflop_aggressor": True,
            "villain_type": "reg",
            "player_count": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["spot_summary"]["in_position"] is True


def test_web_api_screenshot_analysis_matches_manual_spot(monkeypatch):
    client = TestClient(app)

    parsed_payload = {
        "source_hint": "online_table_ui",
        "hero_cards": ["Ah", "Ks"],
        "board": ["Qh", "7c", "2d"],
        "position": "BTN",
        "button_position": "BTN",
        "pot_size": 12.0,
        "bet_to_call": 4.0,
        "effective_stack": 80.0,
        "is_preflop_aggressor": True,
        "action_history": ["btn open 2.5bb", "bb call", "flop bet 33%"],
        "visible_opponents": [{"seat": "Villain 1", "position": "BB", "cards": [], "visibility": "unknown", "note": ""}],
        "warnings": [],
        "missing_fields": [],
        "parse_confidence": 0.91,
    }

    class StubParser:
        def analyze(self, image_data, image_type=None, source_hint="online_table_ui", layout_hint=None):
            assert image_data == "ZmFrZS1pbWFnZQ=="
            assert source_hint == "online_table_ui"
            assert layout_hint == "coinpoker"
            return parsed_payload

    monkeypatch.setattr(poker_api, "poker_screenshot_parser", None)
    monkeypatch.setattr(poker_api, "get_poker_screenshot_parser", lambda: StubParser())

    manual = client.post(
        "/api/poker/analyze",
        json={
            "hole_cards": "AhKs",
            "board": "Qh7c2d",
            "hero_position": "BTN",
            "villain_position": "BB",
            "pot_size": 12.0,
            "bet_to_call": 4.0,
            "effective_stack": 80.0,
            "street": "FLOP",
            "action_history": ["btn open 2.5bb", "bb call", "flop bet 33%"],
            "is_preflop_aggressor": True,
            "villain_type": "reg",
            "player_count": 2,
        },
    )
    screenshot = client.post(
        "/api/poker/analyze-screenshot",
        json={"image_data": "ZmFrZS1pbWFnZQ==", "image_type": "image/png", "layout_hint": "coinpoker"},
    )

    assert manual.status_code == 200
    assert screenshot.status_code == 200

    manual_body = manual.json()
    screenshot_body = screenshot.json()
    assert screenshot_body["decision"]["action"] == manual_body["decision"]["action"]
    assert screenshot_body["baseline_line"] == manual_body["baseline_line"]
    assert screenshot_body["parsed_spot"]["hero_position"] == "BTN"
    assert screenshot_body["visible_opponents"][0]["position"] == "BB"
    assert screenshot_body["layout_requested"] == "coinpoker"


def test_web_api_screenshot_returns_503_without_vision_model(monkeypatch):
    client = TestClient(app)

    def raise_unavailable():
        raise VisionModelUnavailableError("vision unavailable")

    monkeypatch.setattr(poker_api, "poker_screenshot_parser", None)
    monkeypatch.setattr(poker_api, "get_poker_screenshot_parser", raise_unavailable)

    response = client.post(
        "/api/poker/analyze-screenshot",
        json={"image_data": "ZmFrZS1pbWFnZQ==", "image_type": "image/png"},
    )

    assert response.status_code == 503
    assert "vision unavailable" in response.json()["detail"]


def test_web_api_reset_session_accepts_empty_body():
    client = TestClient(app)

    response = client.post("/api/poker/reset_session")

    assert response.status_code == 200
    assert response.json()["success"] is True
