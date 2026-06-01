"""
Pro Trainer API — FastAPI endpoints for the Pro Trainer dashboard
Wraps ProTrainer drill logic over REST for the HTML dashboard.

Usage:
    The endpoints are mounted in api.py under /api/protrainer/
"""

import random
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException

from .pro_trainer import ProTrainer, DEVIATION_NAMES, ACTION_NAMES, DATA_DIR
from .card_counter import CardCounter, HI_LO_VALUES, OMEGA_II_VALUES, WONG_HALVES_VALUES
from .strategy_engine import ILLUSTRIOUS_18, StrategyEngine, BasicStrategy, Hand as StratHand
from .batch_simulator import HeadlessBetCalculator
from .casino_profiles import CASINO_PROFILES

router = APIRouter(prefix="/api/protrainer", tags=["pro_trainer"])


# ─────────────────────────────────────────────────────────────────
# In-Memory Drill Session State
# ─────────────────────────────────────────────────────────────────

@dataclass
class DeviationDrillState:
    questions: List[Dict] = field(default_factory=list)
    current_index: int = 0
    correct: int = 0
    total: int = 0
    mistakes: List[str] = field(default_factory=list)
    system: str = "hi_lo"
    current_question: Optional[Dict] = None


@dataclass
class CountingDrillState:
    rounds: List[Dict] = field(default_factory=list)
    current_round: int = 0
    correct: int = 0
    total: int = 0
    times: List[float] = field(default_factory=list)
    running_count: float = 0.0
    system: str = "hi_lo"
    delay: float = 2.0
    max_rounds: int = 8
    _deck_cards: List[str] = field(default_factory=list)


@dataclass
class BetSizingDrillState:
    scenarios: List[Dict] = field(default_factory=list)
    current_index: int = 0
    correct: int = 0
    total: int = 0
    system: str = "hi_lo"


_deviation_sessions: Dict[str, DeviationDrillState] = {}
_counting_sessions: Dict[str, CountingDrillState] = {}
_betsizing_sessions: Dict[str, BetSizingDrillState] = {}


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _get_pt(system: str = "hi_lo") -> ProTrainer:
    return ProTrainer(counting_system=system)


def _load_best_optimization(tsv_path: Path) -> Optional[Dict]:
    if not tsv_path.exists():
        return None
    best_score = float('-inf')
    best_row = None
    try:
        with open(tsv_path) as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                if row.get('status') in ('keep', 'baseline'):
                    score = float(row.get('score', 0))
                    if score > best_score:
                        best_score = score
                        best_row = row
    except (IOError, csv.Error):
        return None
    if not best_row:
        return None
    result = {
        'score': float(best_row.get('score', 0)),
        'hourly_rate': float(best_row.get('hourly_rate', 0)),
        'win_rate': float(best_row.get('win_rate', 0)),
    }
    params_json = best_row.get('params_snapshot') or best_row.get('params_changed', '{}')
    try:
        params = json.loads(params_json)
        for k, v in params.items():
            if isinstance(v, dict) and 'new' in v:
                result[k] = v['new']
            else:
                result[k] = v
    except (json.JSONDecodeError, TypeError):
        pass
    return result


def _make_hand(total: int, is_soft: bool) -> List[str]:
    if is_soft:
        other = total - 11
        return ['A', str(max(2, min(9, other)))]
    elif total <= 11:
        return [str(max(2, total - 2)), '2']
    else:
        high = min(10, total - 2)
        low = total - high
        if low > 10:
            return ['10', str(total - 10)]
        return [str(high) if high <= 9 else '10', str(max(2, low))]


# ─────────────────────────────────────────────────────────────────
# Deviation Drill Endpoints
# ─────────────────────────────────────────────────────────────────

@router.post("/drill/deviation/start")
def deviation_start(system: str = "hi_lo", num_questions: int = 20, session_id: str = "default") -> Dict:
    """Start a new deviation drill session"""
    pt = _get_pt(system)
    state = DeviationDrillState(system=system)
    state.questions = _generate_deviation_questions(num_questions, system)
    state.current_index = 0
    state.total = len(state.questions)
    _deviation_sessions[session_id] = state
    q = state.questions[0]
    state.current_question = q
    return {
        "session_id": session_id,
        "question_num": 1,
        "total_questions": state.total,
        "question": q,
        "correct": 0,
        "running_score": "0/0 (0%)"
    }


def _generate_deviation_questions(num_q: int, system: str) -> List[Dict]:
    """Generate deviation drill questions"""
    questions = []
    dev_keys = [k for k in ILLUSTRIOUS_18.keys() if k[0] != 'insurance']
    insurance_key = ('insurance', 'A', False, False)
    basic = BasicStrategy()

    for _ in range(num_q):
        test_deviation = random.random() < 0.70

        if random.random() < 0.15 and test_deviation:
            action, threshold = ILLUSTRIOUS_18[insurance_key]
            if test_deviation:
                tc = round(threshold + random.uniform(0, 3), 1)
                correct_action = 'Y'
            else:
                tc = round(threshold - random.uniform(1, 4), 1)
                correct_action = 'N'
            questions.append({
                "type": "insurance",
                "tc": tc,
                "correct_action": correct_action,
                "threshold": threshold,
            })
            continue

        key = random.choice(dev_keys)
        dev_action, threshold = ILLUSTRIOUS_18[key]
        hand_total, dealer, is_soft, is_pair = key

        if test_deviation:
            if threshold < 0:
                tc = round(threshold - random.uniform(0, 2), 1)
            else:
                tc = round(threshold + random.uniform(0, 3), 1)
            expected = dev_action
        else:
            if threshold < 0:
                tc = round(threshold + random.uniform(1, 4), 1)
            else:
                tc = round(threshold - random.uniform(1, 4), 1)
            expected = 'H'  # default

        if is_pair:
            cards = [str(hand_total), str(hand_total)]
        else:
            cards = _make_hand(hand_total, is_soft)

        if not test_deviation:
            strat_hand = StratHand(cards=cards)
            expected = basic.get_action(strat_hand, dealer, True, is_pair, True)

        name = DEVIATION_NAMES.get(key, f"{hand_total} vs {dealer}")
        questions.append({
            "type": "deviation",
            "name": name,
            "hand_total": hand_total,
            "dealer": dealer,
            "is_pair": is_pair,
            "pair_tag": " (PAIR)" if is_pair else "",
            "tc": tc,
            "correct_action": expected,
            "threshold": threshold,
            "cards": cards,
        })

    return questions


@router.post("/drill/deviation/answer")
def deviation_answer(answer: str, session_id: str = "default") -> Dict:
    """Submit an answer to the current deviation question"""
    if session_id not in _deviation_sessions:
        raise HTTPException(status_code=404, detail="No active drill session. Start a new session first.")

    state = _deviation_sessions[session_id]
    q = state.current_question

    correct = q["correct_action"].upper() == answer.upper()
    if correct:
        state.correct += 1
    else:
        action_name = ACTION_NAMES.get(q["correct_action"], q["correct_action"])
        mistakes_str = f"{q.get('name', 'Insurance')} at TC {q['tc']:+.1f}: said {answer}, correct {action_name}"
        state.mistakes.append(mistakes_str)

    state.current_index += 1
    is_complete = state.current_index >= state.total

    if is_complete:
        pct = state.correct / state.total * 100 if state.total > 0 else 0
        color = "green" if pct >= 90 else "yellow" if pct >= 70 else "red"
        feedback = "Casino ready for deviations!" if pct >= 95 else \
                   "Good progress — drill daily until 95%+" if pct >= 80 else \
                   "Need more practice — focus on the top 6 deviations first"

        pt = _get_pt(state.system)
        pt._record_drill("deviation", state.correct, state.total)

        return {
            "correct": correct,
            "expected": q["correct_action"],
            "expected_name": ACTION_NAMES.get(q["correct_action"], q["correct_action"]),
            "question_num": state.current_index,
            "is_complete": True,
            "final_score": f"{state.correct}/{state.total} ({pct:.0f}%)",
            "final_color": color,
            "feedback": feedback,
            "mistakes": state.mistakes[:5],
        }

    next_q = state.questions[state.current_index]
    state.current_question = next_q
    pct = state.correct / state.current_index * 100 if state.current_index > 0 else 0

    return {
        "correct": correct,
        "expected": q["correct_action"],
        "expected_name": ACTION_NAMES.get(q["correct_action"], q["correct_action"]),
        "question_num": state.current_index,
        "total_questions": state.total,
        "is_complete": False,
        "running_score": f"{state.correct}/{state.current_index} ({pct:.0f}%)",
        "question": next_q,
        "mistakes": state.mistakes[-3:] if state.mistakes else [],
    }


# ─────────────────────────────────────────────────────────────────
# Speed Counting Drill Endpoints
# ─────────────────────────────────────────────────────────────────

@router.post("/drill/counting/start")
def counting_start(system: str = "hi_lo", num_rounds: int = 8, speed: float = 2.0, session_id: str = "default") -> Dict:
    """Start a speed counting drill session"""
    values = CardCounter.SYSTEMS[system]
    state = CountingDrillState(system=system, max_rounds=num_rounds, delay=speed)
    state.running_count = 0.0

    # Pre-generate deck
    all_cards = [c for c in ['2','3','4','5','6','7','8','9','10','J','Q','K','A'] for _ in range(24)]
    random.shuffle(all_cards)
    state._deck_cards = all_cards

    for round_num in range(num_rounds):
        num_players = random.choice([5, 6])
        num_cards = num_players * 2 + 1
        cards = []
        for _ in range(num_cards):
            if not state._deck_cards:
                all_cards = [c for c in ['2','3','4','5','6','7','8','9','10','J','Q','K','A'] for _ in range(24)]
                random.shuffle(all_cards)
                state._deck_cards = all_cards
            card = state._deck_cards.pop()
            cards.append(card)
            state.running_count += values.get(card, 0)

        round_count_before = state.running_count
        is_shuffle = False
        if random.random() < 0.1:
            state.running_count = 0.0
            is_shuffle = True

        player_labels = [f"P{i+1}" for i in range(num_players)]
        state.rounds.append({
            "round_num": round_num + 1,
            "cards": cards,
            "num_players": num_players,
            "player_labels": player_labels,
            "expected_count": round_count_before if not is_shuffle else 0.0,
            "is_shuffle": is_shuffle,
        })

    state.current_round = 0
    _counting_sessions[session_id] = state

    return {
        "session_id": session_id,
        "round_num": 1,
        "total_rounds": num_rounds,
        "round": state.rounds[0],
        "speed": speed,
    }


@router.post("/drill/counting/submit")
def counting_submit(user_count: float, session_id: str = "default") -> Dict:
    """Submit running count for current round"""
    if session_id not in _counting_sessions:
        raise HTTPException(status_code=404, detail="No active counting session.")

    state = _counting_sessions[session_id]
    round_data = state.rounds[state.current_round]
    expected = round_data["expected_count"]
    tolerance = 0.5 if state.system == 'wong_halves' else 0

    correct = abs(user_count - expected) <= tolerance
    if correct:
        state.correct += 1

    state.total += 1
    state.current_round += 1
    is_complete = state.current_round >= state.max_rounds

    if is_complete:
        pct = state.correct / state.total * 100 if state.total > 0 else 0
        avg_time = sum(state.times) / len(state.times) if state.times else 0
        color = "green" if pct >= 85 else "yellow" if pct >= 65 else "red"
        feedback = "Table-ready counting speed!" if pct >= 90 else \
                   "Accuracy good — work on speed" if pct >= 75 else \
                   "Keep drilling — accuracy first, then speed"

        pt = _get_pt(state.system)
        pt._record_drill("full_table_counting", state.correct, state.total, {"avg_time_sec": round(avg_time, 1)})

        return {
            "correct": correct,
            "user_count": user_count,
            "expected_count": expected,
            "is_complete": True,
            "final_score": f"{state.correct}/{state.total} ({pct:.0f}%)",
            "final_color": color,
            "avg_time": round(avg_time, 1),
            "feedback": feedback,
        }

    next_round = state.rounds[state.current_round]
    return {
        "correct": correct,
        "user_count": user_count,
        "expected_count": expected,
        "round_num": state.current_round + 1,
        "total_rounds": state.max_rounds,
        "is_complete": False,
        "running_score": f"{state.correct}/{state.total}",
        "round": next_round,
    }


# ─────────────────────────────────────────────────────────────────
# Bet Sizing Drill Endpoints
# ─────────────────────────────────────────────────────────────────

@router.post("/drill/betsizing/start")
def betsizing_start(system: str = "hi_lo", num_questions: int = 10, session_id: str = "default") -> Dict:
    """Start a bet sizing drill session"""
    state = BetSizingDrillState(system=system)
    methods = ['spread', 'spread_aggressive', 'kelly']
    min_bets = [5, 10, 15, 25]
    bankrolls = [1000, 2000, 5000, 10000, 20000]

    for _ in range(num_questions):
        tc = round(random.uniform(-3, 6), 1)
        bankroll = random.choice(bankrolls)
        min_bet = random.choice(min_bets)
        max_bet = min_bet * random.choice([10, 15, 20])
        method = random.choice(methods)

        calc = HeadlessBetCalculator(
            min_bet=min_bet, max_bet=max_bet, bankroll=bankroll,
            kelly_fraction=0.5, spread_ratio=12.0, method=method,
        )
        correct_bet = calc.get_bet(tc)

        state.scenarios.append({
            "tc": tc,
            "bankroll": bankroll,
            "min_bet": min_bet,
            "max_bet": max_bet,
            "method": method,
            "correct_bet": round(correct_bet),
            "tolerance": max(5, correct_bet * 0.10),
        })

    state.current_index = 0
    _betsizing_sessions[session_id] = state

    return {
        "session_id": session_id,
        "question_num": 1,
        "total_questions": num_questions,
        "scenario": state.scenarios[0],
        "correct": 0,
        "running_score": "0/0 (0%)",
    }


@router.post("/drill/betsizing/submit")
def betsizing_submit(user_bet: float, session_id: str = "default") -> Dict:
    """Submit bet sizing answer"""
    if session_id not in _betsizing_sessions:
        raise HTTPException(status_code=404, detail="No active bet sizing session.")

    state = _betsizing_sessions[session_id]
    scenario = state.scenarios[state.current_index]

    correct_bet = scenario["correct_bet"]
    tolerance = scenario["tolerance"]
    correct = abs(user_bet - correct_bet) <= tolerance

    if correct:
        state.correct += 1

    state.total += 1
    state.current_index += 1
    is_complete = state.current_index >= len(state.scenarios)

    if is_complete:
        pct = state.correct / state.total * 100 if state.total > 0 else 0
        color = "green" if pct >= 80 else "yellow" if pct >= 60 else "red"

        pt = _get_pt(state.system)
        pt._record_drill("bet_sizing", state.correct, state.total)

        return {
            "correct": correct,
            "user_bet": user_bet,
            "correct_bet": correct_bet,
            "is_complete": True,
            "final_score": f"{state.correct}/{state.total} ({pct:.0f}%)",
            "final_color": color,
        }

    next_scenario = state.scenarios[state.current_index]
    pct = state.correct / (state.current_index) * 100 if state.current_index > 0 else 0

    return {
        "correct": correct,
        "user_bet": user_bet,
        "correct_bet": correct_bet,
        "question_num": state.current_index + 1,
        "total_questions": len(state.scenarios),
        "is_complete": False,
        "running_score": f"{state.correct}/{state.current_index} ({pct:.0f}%)",
        "scenario": next_scenario,
    }


# ─────────────────────────────────────────────────────────────────
# Session Planner
# ─────────────────────────────────────────────────────────────────

@router.get("/session_plan")
def get_session_plan(profile_name: str = "evo_live") -> Dict:
    """Get session plan for a casino profile"""
    if profile_name not in CASINO_PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown profile: {profile_name}")

    profile = CASINO_PROFILES[profile_name]
    pt = _get_pt("hi_lo")
    best_params = _load_best_optimization(DATA_DIR / "optimization_results.tsv")

    return {
        "profile_name": profile_name,
        "profile": profile,
        "counting_system": best_params.get("counting_system", "hi_lo") if best_params else "hi_lo",
        "betting_method": best_params.get("betting_method", "spread") if best_params else "spread",
        "spread_ratio": float(best_params.get("spread_ratio", 12.0)) if best_params else 12.0,
        "bet_ramp_tc": float(best_params.get("bet_ramp_tc", 1.0)) if best_params else 1.0,
        "wong_out_tc": float(best_params.get("wong_out_tc", -2.0)) if best_params else -2.0,
        "wong_in_tc": float(best_params.get("wong_in_tc", 1.0)) if best_params else 1.0,
        "kelly_fraction": float(best_params.get("kelly_fraction", 0.5)) if best_params else 0.5,
        "expected_hourly_rate": float(best_params.get("hourly_rate", 0.0)) if best_params else 0.0,
        "has_optimization": best_params is not None,
    }


@router.get("/casino_profiles")
def get_casino_profiles() -> Dict:
    """Get all available casino profiles"""
    return {
        "profiles": {
            name: {
                "description": p["description"],
                "num_decks": p["num_decks"],
                "penetration": p.get("penetration", 0.50),
                "dealer_hits_soft_17": p.get("dealer_hits_soft_17", False),
                "blackjack_pays": p.get("blackjack_pays", 1.5),
                "late_surrender": p.get("late_surrender", False),
                "double_after_split": p.get("double_after_split", True),
            }
            for name, p in CASINO_PROFILES.items()
        }
    }


# ─────────────────────────────────────────────────────────────────
# Post-Session Analysis
# ─────────────────────────────────────────────────────────────────

@router.post("/analyze_session")
def analyze_session(
    hands: int,
    hours: float,
    wagered: float,
    pnl: float,
    min_bet: float,
    max_bet: float,
    save: bool = True,
    system: str = "hi_lo",
) -> Dict:
    """Analyze a session's results"""
    pt = _get_pt(system)
    return pt.analyze_session(
        hands=hands, hours=hours, wagered=wagered, pnl=pnl,
        min_bet=min_bet, max_bet=max_bet, save=save,
    )


# ─────────────────────────────────────────────────────────────────
# Progress & Readiness
# ─────────────────────────────────────────────────────────────────

@router.get("/progress")
def get_progress(system: str = "hi_lo") -> Dict:
    """Get training progress"""
    pt = _get_pt(system)
    return pt.get_progress_summary()


@router.get("/readiness")
def get_readiness(system: str = "hi_lo") -> Dict:
    """Get readiness report"""
    pt = _get_pt(system)
    return pt.get_readiness_report()


@router.get("/settings")
def get_settings() -> Dict:
    """Get available settings"""
    return {
        "counting_systems": [
            {"id": "hi_lo", "name": "Hi-Lo", "level": 1, "difficulty": "Easy", "description": "Simple +1/-1 system, great for beginners"},
            {"id": "omega_ii", "name": "Omega II", "level": 2, "difficulty": "Medium", "description": "Multi-level system with ace side-count"},
            {"id": "wong_halves", "name": "Wong Halves", "level": 3, "difficulty": "Hard", "description": "Fractional values for maximum accuracy"},
        ],
        "casino_profiles": list(CASINO_PROFILES.keys()),
        "betting_methods": ["spread", "spread_aggressive", "kelly", "flat"],
    }


@router.get("/illustrious_18")
def get_illustrious_18() -> Dict:
    """Get the Illustrious 18 deviation list"""
    result = []
    for key, (action, threshold) in ILLUSTRIOUS_18.items():
        hand_total, dealer, is_soft, is_pair = key
        name = DEVIATION_NAMES.get(key, f"{hand_total} vs {dealer}")
        result.append({
            "hand": name,
            "dealer": dealer,
            "is_pair": is_pair,
            "action": ACTION_NAMES.get(action, action),
            "action_code": action,
            "threshold": threshold,
            "tc_condition": f"TC >= {threshold:+.0f}" if threshold >= 0 else f"TC <= {threshold:+.0f}",
        })
    return {"deviations": result}
