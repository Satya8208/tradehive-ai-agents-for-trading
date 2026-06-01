"""Stateless NLH cash-game analysis helpers for the standalone poker dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.agents.poker.core.board_analyzer import BoardAnalyzer
from src.agents.poker.core.hand_evaluator import Card
from src.agents.poker.core.odds_calculator import OddsCalculator
from src.agents.poker.core.poker_types import Position, Street
from src.agents.poker.core.range_manager import Range
from src.agents.poker.poker_agent import parse_cards
from src.agents.poker.strategy.decision_engine import (
    POSITION_RANGE_WIDTH,
    VILLAIN_RANGES,
    Decision,
    DecisionEngine,
)
from src.agents.poker.strategy.postflop_engine import HandCategory, PostflopEngine


POSITION_ALIASES = {
    "utg": Position.UTG,
    "utg1": Position.UTG1,
    "utg+1": Position.UTG1,
    "utg2": Position.UTG2,
    "utg+2": Position.UTG2,
    "mp": Position.MP,
    "mp2": Position.MP2,
    "hj": Position.HJ,
    "co": Position.CO,
    "btn": Position.BTN,
    "button": Position.BTN,
    "dealer": Position.BTN,
    "sb": Position.SB,
    "bb": Position.BB,
}

POSTFLOP_POSITION_ORDER = {
    Position.SB: 0,
    Position.BB: 1,
    Position.UTG: 2,
    Position.UTG1: 3,
    Position.UTG2: 4,
    Position.MP: 5,
    Position.MP2: 6,
    Position.HJ: 7,
    Position.CO: 8,
    Position.BTN: 9,
}

STREET_MAP = {
    0: Street.PREFLOP,
    3: Street.FLOP,
    4: Street.TURN,
    5: Street.RIVER,
}

SUPPORTED_VILLAIN_TYPES = {"reg", "fish", "tag", "lag", "nit"}

decision_engine = DecisionEngine()
postflop_engine = PostflopEngine()
board_analyzer = BoardAnalyzer()
odds_calculator = OddsCalculator()
class SpotValidationError(ValueError):
    """Raised when the requested poker spot is structurally invalid."""


@dataclass
class SpotContext:
    hole_cards: List[Card]
    board: List[Card]
    street: Street
    hero_position: Position
    villain_position: Optional[Position]
    in_position: bool
    villain_type: str
    villain_stats: Dict[str, Optional[float]]
    pot_size: float
    bet_to_call: float
    effective_stack: float
    is_preflop_aggressor: bool
    action_history: List[str]
    player_count: int
    assumptions: List[str]
    requested_villain_range: Optional[str]
    node: str


def _parse_action_history(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _parse_float(value: Any) -> Optional[float]:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_stats(value: Any) -> Dict[str, Optional[float]]:
    if not isinstance(value, dict):
        return {}
    return {
        "vpip": _parse_float(value.get("vpip")),
        "pfr": _parse_float(value.get("pfr")),
        "three_bet": _parse_float(value.get("three_bet")),
        "fold_to_cbet": _parse_float(value.get("fold_to_cbet")),
        "aggression": _parse_float(value.get("aggression")),
    }


def _parse_position(value: Any, default: Optional[Position] = None) -> Optional[Position]:
    if value in {None, ""}:
        return default
    key = str(value).strip().lower()
    if key in POSITION_ALIASES:
        return POSITION_ALIASES[key]
    try:
        return Position[str(value).strip().upper()]
    except KeyError:
        return default


def _infer_villain_type(
    explicit_type: Optional[str],
    villain_stats: Dict[str, Optional[float]],
    assumptions: List[str],
) -> str:
    explicit = (explicit_type or "").strip().lower()
    if explicit in SUPPORTED_VILLAIN_TYPES and explicit != "reg":
        return explicit

    vpip = villain_stats.get("vpip")
    pfr = villain_stats.get("pfr")
    three_bet = villain_stats.get("three_bet")
    aggression = villain_stats.get("aggression")

    if vpip is None and pfr is None and three_bet is None and aggression is None:
        assumptions.append("Villain type defaulted to reg because no reads or HUD stats were provided.")
        return "reg"

    if vpip is not None and vpip >= 38 and (pfr is None or pfr <= 26):
        inferred = "fish"
    elif vpip is not None and vpip <= 18 and (pfr is None or pfr <= 15):
        inferred = "nit"
    elif vpip is not None and vpip >= 28 and (pfr is not None and pfr >= 22):
        inferred = "lag"
    elif vpip is not None and pfr is not None and 18 <= vpip <= 28 and 15 <= pfr <= 23:
        inferred = "tag"
    else:
        inferred = "reg"

    assumptions.append(f"Villain type inferred as {inferred} from HUD-style stats.")
    return inferred


def _street_from_board(board: List[Card], requested_street: Optional[str] = None) -> Street:
    if len(board) not in STREET_MAP:
        raise SpotValidationError("Board must contain 0, 3, 4, or 5 cards.")
    derived = STREET_MAP[len(board)]
    if not requested_street:
        return derived
    try:
        requested = Street[str(requested_street).strip().upper()]
    except KeyError as exc:
        raise SpotValidationError(f"Unsupported street value: {requested_street}") from exc
    if requested != derived:
        raise SpotValidationError("Street does not match the number of board cards.")
    return derived


def _infer_in_position(hero_position: Position, villain_position: Optional[Position], assumptions: List[str]) -> bool:
    if villain_position is not None:
        return POSTFLOP_POSITION_ORDER[hero_position] > POSTFLOP_POSITION_ORDER[villain_position]
    assumptions.append("Villain position was missing, so in-position status was inferred from hero position only.")
    return hero_position in {Position.HJ, Position.CO, Position.BTN}


def _derive_node(street: Street, action_history: List[str], bet_to_call: float, requested_facing: Optional[str]) -> str:
    joined = " ".join(action_history).lower()
    facing = (requested_facing or "").strip().lower()
    if "4bet" in joined or facing == "4bet":
        return "4bet_pot"
    if "3bet" in joined or facing == "3bet":
        return "3bet_pot"
    if street == Street.PREFLOP and bet_to_call > 0:
        return "raised_pot"
    return "srp"


def _default_villain_range(villain_type: str, villain_position: Optional[Position]) -> Tuple[str, str]:
    if villain_position in POSITION_RANGE_WIDTH:
        return POSITION_RANGE_WIDTH[villain_position], f"{villain_position.name} pooled opening/continuing range"
    return VILLAIN_RANGES.get(villain_type, VILLAIN_RANGES["reg"]), f"{villain_type} pooled population range"


def _build_range_summary(context: SpotContext) -> Dict[str, Any]:
    if context.requested_villain_range:
        try:
            requested = Range.from_notation(context.requested_villain_range)
            percent = round(len(requested.hands) / 1326 * 100, 1)
            summary = f"Custom villain range supplied ({percent}% / {len(requested.hands)} combos)."
        except Exception:
            percent = None
            summary = "Custom villain range supplied, but combo count could not be parsed."
        return {
            "label": "Custom range",
            "summary": summary,
            "notation": context.requested_villain_range,
            "combos": None if percent is None else len(requested.hands),
            "percent": percent,
            "node": context.node,
        }

    notation, label = _default_villain_range(context.villain_type, context.villain_position)
    combos = None
    percent = None
    try:
        range_obj = Range.from_notation(notation)
        combos = len(range_obj.hands)
        percent = round(combos / 1326 * 100, 1)
    except Exception:
        pass

    return {
        "label": label,
        "summary": f"Using a {context.villain_type} population range for a {context.node.replace('_', ' ')} node.",
        "notation": notation,
        "combos": combos,
        "percent": percent,
        "node": context.node,
    }


def _size_label(decision: Decision) -> Optional[str]:
    if decision.sizing_bb is not None:
        return f"{decision.sizing_bb:.1f}bb"
    if decision.sizing_fraction is not None:
        return f"{round(decision.sizing_fraction * 100)}% pot"
    return None


def _build_baseline_line(context: SpotContext, decision: Decision) -> str:
    size = _size_label(decision)
    parts = [
        context.street.value.upper(),
        context.node.replace("_", " ").upper(),
        f"{context.hero_position.name} vs {context.villain_position.name if context.villain_position else 'UNKNOWN'}",
        decision.action.upper(),
    ]
    if size:
        parts.append(size)
    if decision.frequency < 0.99:
        parts.append(f"{round(decision.frequency * 100)}% freq")
    return " | ".join(parts)


def _apply_exploit_adjustment(context: SpotContext, decision: Decision) -> Tuple[str, Optional[str], Optional[float]]:
    note = None
    action = decision.action
    sizing_fraction = decision.sizing_fraction

    if context.villain_type == "fish" and action in {"bet", "raise"}:
        if sizing_fraction is not None and sizing_fraction < 0.66:
            sizing_fraction = 0.66
            note = "Fish profile detected: size up value bets and raises instead of using small balanced sizings."
        else:
            note = "Fish profile detected: keep the line value-heavy and avoid fancy bluffs."
    elif context.villain_type == "nit" and action in {"call", "check"} and context.bet_to_call > 0:
        note = "Nit profile detected: continue only because the price and range interaction still clear the threshold."
    elif context.villain_type == "lag" and action == "fold" and context.bet_to_call <= max(context.pot_size * 0.33, 1.0):
        note = "LAG profile detected: folding is still preferred, but the bluffing frequency likely runs above population."
    elif context.villain_type == "tag":
        note = "TAG profile detected: baseline line stays close to population/GTO assumptions."

    return action, note, sizing_fraction


def _next_street_plan(context: SpotContext, decision: Decision, hand_category: Optional[HandCategory], board_texture: Optional[str]) -> str:
    if context.street == Street.RIVER:
        return "River is final street: commit only to the current action and review showdown blockers for similar spots."

    texture = board_texture or "dynamic"
    if decision.action in {"bet", "raise", "check_raise"}:
        if hand_category in {HandCategory.NUTS, HandCategory.VERY_STRONG, HandCategory.STRONG}:
            return f"Keep barreling clean runouts on this {texture} texture and slow down only when obvious draws complete."
        return f"Pressure good barrel cards on this {texture} board, but shut down when the range disadvantage swings hard."

    if decision.action == "call":
        return f"Realize equity first: continue on clean turns, and re-evaluate sharply if sizing balloons on this {texture} texture."

    if decision.action == "check":
        return f"Protect the checking range here, then react to turn size and runout quality instead of autopiloting a delayed stab."

    return "Take the low-variance line now and move to the next hand unless a strong exploit read appears."


def _confidence_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def _build_confidence(
    context: SpotContext,
    assumptions: List[str],
    parse_confidence: Optional[float] = None,
) -> Dict[str, Any]:
    score = 0.92
    reasons: List[str] = []

    if context.villain_position is None:
        score -= 0.12
        reasons.append("villain position missing")
    if not context.action_history and context.street != Street.PREFLOP:
        score -= 0.12
        reasons.append("postflop action history missing")
    if context.player_count > 2:
        score -= 0.12
        reasons.append("multiway support is pooled, not fully solved")
    if context.villain_type == "reg":
        score -= 0.05
        reasons.append("villain profile is population default")
    if context.effective_stack in {100.0, 75.0} and any("defaulted" in item.lower() for item in assumptions):
        score -= 0.08
        reasons.append("one or more key fields were defaulted")
    if parse_confidence is not None:
        score = (score * 0.6) + (parse_confidence * 0.4)
        reasons.append("screenshot parse confidence blended into final score")

    score = round(max(0.18, min(0.99, score)), 2)
    return {
        "score": score,
        "label": _confidence_label(score),
        "reasons": reasons,
    }


def _gto_metrics(pot_size: float, bet_to_call: float, sizing_fraction: Optional[float]) -> Dict[str, Optional[float]]:
    if pot_size <= 0:
        return {"mdf": None, "alpha": None, "bluff_freq": None}
    reference_bet = bet_to_call if bet_to_call > 0 else (pot_size * (sizing_fraction or 0.75))
    if reference_bet <= 0:
        return {"mdf": None, "alpha": None, "bluff_freq": None}
    mdf = pot_size / (pot_size + reference_bet)
    alpha = reference_bet / (pot_size + reference_bet)
    bluff_freq = reference_bet / ((2 * reference_bet) + pot_size)
    return {
        "mdf": round(mdf * 100, 1),
        "alpha": round(alpha * 100, 1),
        "bluff_freq": round(bluff_freq * 100, 1),
    }


def _build_context(payload: Dict[str, Any]) -> SpotContext:
    assumptions: List[str] = []
    hero_cards = parse_cards(payload.get("hole_cards", ""))
    if len(hero_cards) != 2:
        raise SpotValidationError("Hole cards must contain exactly 2 cards.")

    board = parse_cards(payload.get("board", "")) if payload.get("board") else []
    all_cards = hero_cards + board
    if len(set(all_cards)) != len(all_cards):
        raise SpotValidationError("Duplicate cards detected across hole cards and board.")
    street = _street_from_board(board, payload.get("street"))
    hero_position = _parse_position(payload.get("hero_position") or payload.get("position"))
    if hero_position is None:
        raise SpotValidationError("Hero position is required for a live NLH decision.")
    villain_position = _parse_position(payload.get("villain_position"))
    in_position = _infer_in_position(hero_position, villain_position, assumptions)

    action_history = _parse_action_history(payload.get("action_history"))
    villain_stats = _normalize_stats(payload.get("villain_stats"))
    villain_type = _infer_villain_type(payload.get("villain_type"), villain_stats, assumptions)

    pot_size = _parse_float(payload.get("pot_size"))
    if pot_size is None:
        pot_size = 1.5
        assumptions.append("Pot size defaulted to 1.5bb.")

    bet_to_call = _parse_float(payload.get("bet_to_call"))
    if bet_to_call is None:
        bet_to_call = 0.0
        assumptions.append("Bet to call defaulted to 0bb.")

    effective_stack = _parse_float(payload.get("effective_stack"))
    if effective_stack is None:
        effective_stack = 100.0
        assumptions.append("Effective stack defaulted to 100bb.")

    player_count = int(payload.get("player_count") or 2)
    if player_count < 2:
        player_count = 2
        assumptions.append("Player count was invalid and reset to heads-up.")

    is_preflop_aggressor = payload.get("is_preflop_aggressor")
    if is_preflop_aggressor is None:
        is_preflop_aggressor = True
        assumptions.append("Preflop aggressor defaulted to hero.")

    requested_villain_range = str(payload.get("villain_range") or "").strip() or None
    node = _derive_node(street, action_history, bet_to_call, payload.get("facing"))

    return SpotContext(
        hole_cards=hero_cards,
        board=board,
        street=street,
        hero_position=hero_position,
        villain_position=villain_position,
        in_position=in_position,
        villain_type=villain_type,
        villain_stats=villain_stats,
        pot_size=pot_size,
        bet_to_call=bet_to_call,
        effective_stack=effective_stack,
        is_preflop_aggressor=bool(is_preflop_aggressor),
        action_history=action_history,
        player_count=player_count,
        assumptions=assumptions,
        requested_villain_range=requested_villain_range,
        node=node,
    )


def analyze_nlh_spot(payload: Dict[str, Any]) -> Dict[str, Any]:
    context = _build_context(payload)
    baseline = decision_engine.get_decision(
        hole_cards=context.hole_cards,
        board=context.board,
        position=context.hero_position,
        pot=context.pot_size,
        bet_to_call=context.bet_to_call,
        street=context.street,
        in_position=context.in_position,
        villain_type=context.villain_type,
        villain_position=context.villain_position,
        effective_stack=context.effective_stack,
        is_preflop_aggressor=context.is_preflop_aggressor,
    )

    action, exploit_note, adjusted_sizing_fraction = _apply_exploit_adjustment(context, baseline)
    board_analysis = board_analyzer.analyze(context.board) if context.board else None
    hand_category = None
    hand_result = None
    if context.board:
        hand_category, hand_result = postflop_engine.analyze_hand_strength(context.hole_cards, context.board)

    if context.requested_villain_range:
        try:
            villain_range_obj = Range.from_notation(context.requested_villain_range)
            equity_result = decision_engine.equity_calc.hand_vs_range(
                context.hole_cards,
                villain_range_obj,
                context.board,
                iterations=1500,
            )
            equity = round(equity_result["equity"] * 100, 1)
            win_rate = round(equity_result["win_rate"] * 100, 1)
            tie_rate = round(equity_result["tie_rate"] * 100, 1)
        except Exception:
            equity = round(baseline.equity * 100, 1)
            win_rate = None
            tie_rate = None
            context.assumptions.append("Custom villain range could not be solved, so population equity was used instead.")
    else:
        equity = round(baseline.equity * 100, 1)
        win_rate = None
        tie_rate = None

    sizing_fraction = adjusted_sizing_fraction if adjusted_sizing_fraction is not None else baseline.sizing_fraction
    sizing_bb = baseline.sizing_bb
    size_label = f"{round(sizing_fraction * 100)}% pot" if sizing_fraction is not None else (f"{sizing_bb:.1f}bb" if sizing_bb is not None else None)
    alternative = baseline.alternative or ("check" if action in {"bet", "raise"} else "call")
    range_summary = _build_range_summary(context)
    confidence = _build_confidence(context, context.assumptions)

    decision_payload = {
        "action": action,
        "reasoning": baseline.reasoning,
        "sizing": sizing_bb,
        "sizing_fraction": sizing_fraction,
        "sizing_percent": None if sizing_fraction is None else int(round(sizing_fraction * 100)),
        "frequency": round(baseline.frequency * 100, 1),
        "equity": equity,
        "pot_odds": None if baseline.pot_odds is None else round(baseline.pot_odds * 100, 1),
        "ev": baseline.ev,
        "hand_strength": baseline.hand_strength,
        "alternative": alternative,
        "alt_frequency": round(baseline.alt_freq * 100, 1),
    }

    odds_result = None
    if context.bet_to_call > 0 and context.pot_size > 0:
        odds_result = odds_calculator.pot_odds(context.bet_to_call, context.pot_size)

    return {
        "success": True,
        "street": context.street.value.upper(),
        "position": context.hero_position.name,
        "facing": context.node.replace("_", " "),
        "decision": decision_payload,
        "sizing": {
            "bb": sizing_bb,
            "fraction": sizing_fraction,
            "label": size_label,
        },
        "confidence": confidence,
        "assumptions": context.assumptions,
        "baseline_line": _build_baseline_line(context, baseline),
        "exploit_adjustment": exploit_note,
        "alternative": {
            "action": alternative,
            "frequency": round(baseline.alt_freq * 100, 1),
        },
        "next_street_plan": _next_street_plan(
            context,
            Decision(
                action=action,
                sizing_fraction=sizing_fraction,
                sizing_bb=sizing_bb,
                frequency=baseline.frequency,
                equity=baseline.equity,
                pot_odds=baseline.pot_odds,
                ev=baseline.ev,
                reasoning=baseline.reasoning,
                hand_strength=baseline.hand_strength,
                alternative=baseline.alternative,
                alt_freq=baseline.alt_freq,
                barrel_plan=baseline.barrel_plan,
                exploit_note=exploit_note,
            ),
            hand_category,
            board_analysis.texture.value if board_analysis else None,
        ),
        "range_summary": range_summary,
        "spot_summary": {
            "hero_position": context.hero_position.name,
            "villain_position": context.villain_position.name if context.villain_position else None,
            "street": context.street.value,
            "node": context.node,
            "player_count": context.player_count,
            "in_position": context.in_position,
            "spr": round(context.effective_stack / max(context.pot_size, 0.1), 2),
            "pot_size": context.pot_size,
            "bet_to_call": context.bet_to_call,
            "effective_stack": context.effective_stack,
            "villain_type": context.villain_type,
            "action_history": context.action_history,
            "board_texture": board_analysis.texture.value if board_analysis else None,
            "summary": f"{context.street.value.upper()} {context.node.replace('_', ' ')} | {context.hero_position.name} vs {context.villain_position.name if context.villain_position else 'UNKNOWN'}",
        },
        "hand_category": None if hand_category is None else hand_category.value,
        "hand_description": None if hand_result is None else hand_result.description,
        "board_texture": None if board_analysis is None else board_analysis.texture.value,
        "equity": {
            "equity": equity,
            "win_rate": win_rate,
            "tie_rate": tie_rate,
        },
        "pot_odds": {
            "pot_odds": None if odds_result is None else round(odds_result.pot_odds * 100, 1),
            "ratio": None if odds_result is None else odds_result.pot_odds_ratio,
            "break_even": None if odds_result is None else round(odds_result.break_even_equity * 100, 1),
        },
        "gto_metrics": _gto_metrics(context.pot_size, context.bet_to_call, sizing_fraction),
    }


def build_analysis_from_screenshot(parsed: Dict[str, Any], layout_hint: Optional[str] = None) -> Dict[str, Any]:
    parse_assumptions = list(parsed.get("warnings") or [])
    parse_confidence = float(parsed.get("parse_confidence") or 0.0)
    hero_cards = parsed.get("hero_cards") or []
    board = parsed.get("board") or []
    if len(hero_cards) != 2:
        raise SpotValidationError("Screenshot parse must identify exactly 2 hero cards.")
    if len(board) not in {0, 3, 4, 5}:
        raise SpotValidationError("Screenshot parse returned an invalid board state.")

    visible_opponents = parsed.get("visible_opponents") or []
    villain_position = None
    positioned = [item.get("position") for item in visible_opponents if item.get("position")]
    if len(positioned) == 1:
        villain_position = positioned[0]
    elif len(positioned) > 1:
        parse_assumptions.append("Multiple positioned opponents were visible, so villain position stayed generic.")

    payload = {
        "hole_cards": " ".join(hero_cards),
        "board": " ".join(board),
        "hero_position": parsed.get("position") or parsed.get("button_position"),
        "villain_position": villain_position,
        "pot_size": parsed.get("pot_size") if parsed.get("pot_size") is not None else 1.5,
        "bet_to_call": parsed.get("bet_to_call") if parsed.get("bet_to_call") is not None else 0.0,
        "effective_stack": parsed.get("effective_stack") if parsed.get("effective_stack") is not None else 100.0,
        "action_history": parsed.get("action_history") or [],
        "is_preflop_aggressor": parsed.get("is_preflop_aggressor"),
        "villain_type": "reg",
        "player_count": 2,
    }

    if parsed.get("pot_size") is None:
        parse_assumptions.append("Pot size defaulted to 1.5bb from screenshot mode.")
    if parsed.get("bet_to_call") is None:
        parse_assumptions.append("Bet to call defaulted to 0bb from screenshot mode.")
    if parsed.get("effective_stack") is None:
        parse_assumptions.append("Effective stack defaulted to 100bb from screenshot mode.")
    if parsed.get("position") is None and parsed.get("button_position") is not None:
        parse_assumptions.append("Hero position was inferred from the detected button marker.")
    if payload["hero_position"] is None:
        raise SpotValidationError("Screenshot parse could not determine hero position well enough to advise safely.")
    if payload["is_preflop_aggressor"] is None:
        payload["is_preflop_aggressor"] = True
        parse_assumptions.append("Preflop aggressor defaulted to hero from screenshot mode.")

    missing_fields = parsed.get("missing_fields") or []
    parse_confidence = max(
        0.05,
        round(parse_confidence - (0.08 * len(missing_fields)) - (0.04 * len(parse_assumptions)), 2),
    )

    analysis = analyze_nlh_spot(payload)
    analysis["parsed_spot"] = {
        "hole_cards": payload["hole_cards"],
        "board": payload["board"],
        "hero_position": payload["hero_position"],
        "villain_position": payload["villain_position"],
        "pot_size": payload["pot_size"],
        "bet_to_call": payload["bet_to_call"],
        "effective_stack": payload["effective_stack"],
        "action_history": payload["action_history"],
        "is_preflop_aggressor": payload["is_preflop_aggressor"],
        "source_hint": parsed.get("source_hint", "online_table_ui"),
    }
    analysis["parse_confidence"] = parse_confidence
    analysis["parse_assumptions"] = parse_assumptions
    analysis["layout_detected"] = parsed.get("layout_detected")
    analysis["layout_requested"] = layout_hint
    analysis["visible_opponents"] = visible_opponents

    blended = _build_confidence(_build_context(payload), analysis["assumptions"], parse_confidence=parse_confidence)
    blended["reasons"] = list(dict.fromkeys((analysis["confidence"]["reasons"] or []) + blended["reasons"]))
    analysis["confidence"] = blended
    analysis["assumptions"] = list(dict.fromkeys(parse_assumptions + analysis["assumptions"]))
    return analysis
