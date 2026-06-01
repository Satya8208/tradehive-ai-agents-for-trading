"""
🥜 Nirvana Nuts Dashboard API
FastAPI backend for the growth engine
"""

import sys
import base64
import re
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Literal
import uvicorn

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.nirvana_nuts_agent import NirvanaNutsAgent
from src.agents.poker.poker_agent import PokerAgent, parse_cards
from src.agents.poker.core.hand_evaluator import Card
from src.agents.poker.core.board_analyzer import BoardAnalyzer, BoardTexture as AnalyzerTexture
from src.agents.poker.core.poker_types import Position, Street
from src.agents.poker.strategy.decision_engine import DecisionEngine
from src.agents.poker.strategy.postflop_engine import PostflopEngine, HandCategory
from src.agents.poker.ai.solver_lite import SolverLite, BoardTexture as SolverTexture, HandStrength
from src.agents.poker.vision import (
    PokerScreenshotParser,
    ScreenshotParserError,
    VisionModelUnavailableError,
)
from src.agents.blackjack.pro_trainer import ProTrainer
from src.agents.blackjack.casino_profiles import CASINO_PROFILES
from src.dashboard.backend.operator_store import JsonListStore

app = FastAPI(
    title="TradeHive AI Agents API",
    description="Unified API for TradeHive Agents (Nirvana Nuts + Poker God)",
    version="1.1.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize agents
agent = None  # Nirvana Nuts
poker_agent = None # Poker God
decision_engine = None
poker_screenshot_parser = None
board_analyzer = BoardAnalyzer()
postflop_engine = PostflopEngine()
solver_lite = SolverLite()
operator_data_dir = PROJECT_ROOT / "src" / "data" / "operator"
review_queue_store = JsonListStore(operator_data_dir / "poker_review_queue.json")

def get_agent():
    global agent
    if agent is None:
        agent = NirvanaNutsAgent()
    return agent

def get_poker_agent():
    global poker_agent
    if poker_agent is None:
        poker_agent = PokerAgent()
    return poker_agent


def get_decision_engine():
    global decision_engine
    if decision_engine is None:
        decision_engine = DecisionEngine()
    return decision_engine


def get_poker_screenshot_parser():
    global poker_screenshot_parser
    if poker_screenshot_parser is None:
        poker_screenshot_parser = PokerScreenshotParser()
    return poker_screenshot_parser


# Request/Response Models
class ReplyRequest(BaseModel):
    tweet: str

class PokerAdviceRequest(BaseModel):
    hole_cards: str  # "AhKh"
    board: str = ""  # "Kd 7c 2h"
    pot_size: float = 0.0
    bet_facing: float = 0.0
    position: str = "BTN"
    villain_range: Optional[str] = None


class BlackjackCoachSummaryRequest(BaseModel):
    counting_system: str = "hi_lo"


class BlackjackSessionPlanRequest(BaseModel):
    counting_system: str = "hi_lo"
    profile_name: Optional[str] = None
    custom_profile: Optional[Dict[str, Any]] = None


class BlackjackSessionReviewRequest(BaseModel):
    counting_system: str = "hi_lo"
    hands: int
    hours: float
    wagered: float
    pnl: float
    min_bet: float
    max_bet: float


class PokerSpotRequest(BaseModel):
    hole_cards: str
    board: str = ""
    position: str = "BTN"
    villain_type: str = "reg"
    villain_position: Optional[str] = None
    pot_size: float = 1.5
    bet_to_call: float = 0.0
    effective_stack: float = 100.0
    is_preflop_aggressor: bool = True
    action_history: List[str] = []


class PokerReviewQueueRequest(BaseModel):
    label: Optional[str] = None
    note: Optional[str] = None
    spot: Dict[str, Any]
    decision: Optional[Dict[str, Any]] = None


class PokerScreenshotAnalyzeRequest(BaseModel):
    image_data: str
    image_type: Optional[str] = None
    source_hint: Literal["online_table_ui"] = "online_table_ui"


def parse_position(value: Optional[str], default: Position = Position.BTN) -> Position:
    if not value:
        return default
    try:
        return Position[value.upper()]
    except KeyError:
        return default


def street_from_board(board: List[Card]) -> Street:
    street_map = {0: Street.PREFLOP, 3: Street.FLOP, 4: Street.TURN, 5: Street.RIVER}
    if len(board) not in street_map:
        raise HTTPException(status_code=400, detail="Board must contain 0, 3, 4, or 5 cards")
    return street_map[len(board)]


def infer_in_position(hero_position: Position, villain_position: Optional[Position]) -> bool:
    if villain_position is not None:
        return hero_position.value > villain_position.value
    return hero_position in {Position.BTN, Position.CO, Position.HJ}


def build_poker_validation(spot: PokerSpotRequest, street: Street, villain_position: Optional[Position]) -> Dict[str, Any]:
    warnings = []
    completeness = 1.0

    if spot.villain_type == "reg":
        warnings.append("Villain type is still the default (reg).")
        completeness -= 0.1

    if villain_position is None:
        warnings.append("Villain position is unknown, so in-position assumptions are estimated.")
        completeness -= 0.1

    if street != Street.PREFLOP and spot.bet_to_call == 0 and spot.pot_size <= 1.5:
        warnings.append("Pot size looks close to default and may not reflect the live hand yet.")
        completeness -= 0.15

    if street != Street.PREFLOP and not spot.action_history:
        warnings.append("Action history is empty, so line-specific advice is less reliable.")
        completeness -= 0.1

    if spot.effective_stack <= 0:
        warnings.append("Effective stack is invalid.")
        completeness -= 0.5

    completeness = max(0.0, round(completeness, 2))
    if completeness >= 0.85:
        status = "validated"
    elif completeness >= 0.55:
        status = "provisional"
    else:
        status = "unvalidated"

    return {
        "status": status,
        "completeness": completeness,
        "warnings": warnings,
        "source": "deterministic_decision_engine",
    }


def serialize_decision(decision, validation: Dict[str, Any], street: Street) -> Dict[str, Any]:
    return {
        "street": street.value,
        "action": decision.action,
        "sizing_fraction": decision.sizing_fraction,
        "sizing_bb": decision.sizing_bb,
        "frequency": decision.frequency,
        "equity": decision.equity,
        "pot_odds": decision.pot_odds,
        "ev": decision.ev,
        "reasoning": decision.reasoning,
        "hand_strength": decision.hand_strength,
        "alternative": decision.alternative,
        "alt_freq": decision.alt_freq,
        "barrel_plan": decision.barrel_plan,
        "exploit_note": decision.exploit_note,
        "validation": validation,
    }


def normalize_action(action: Optional[str]) -> Optional[str]:
    if not action:
        return None
    action = action.lower()
    if action in {"bet", "raise", "check_raise"}:
        return "aggressive"
    if action in {"check", "call"}:
        return "passive"
    if action == "fold":
        return "fold"
    return action


def map_solver_texture(analysis_texture: AnalyzerTexture) -> SolverTexture:
    texture_map = {
        AnalyzerTexture.DRY: SolverTexture.DRY_UNPAIRED,
        AnalyzerTexture.SEMI_DRY: SolverTexture.DRY_UNPAIRED,
        AnalyzerTexture.SEMI_WET: SolverTexture.TWO_TONE_LOW,
        AnalyzerTexture.WET: SolverTexture.DYNAMIC,
        AnalyzerTexture.MONOTONE: SolverTexture.MONOTONE,
        AnalyzerTexture.PAIRED: SolverTexture.DRY_PAIRED,
        AnalyzerTexture.DOUBLE_PAIRED: SolverTexture.DRY_PAIRED,
        AnalyzerTexture.TRIPS: SolverTexture.DRY_PAIRED,
    }
    return texture_map.get(analysis_texture, SolverTexture.DYNAMIC)


def map_solver_strength(hand_category: HandCategory) -> HandStrength:
    strength_map = {
        HandCategory.NUTS: HandStrength.NUTS,
        HandCategory.VERY_STRONG: HandStrength.VERY_STRONG,
        HandCategory.STRONG: HandStrength.TOP_PAIR_GOOD,
        HandCategory.MEDIUM: HandStrength.MIDDLE_PAIR,
        HandCategory.WEAK: HandStrength.WEAK_PAIR,
        HandCategory.DRAW: HandStrength.DRAW_STRONG,
        HandCategory.TRASH: HandStrength.AIR,
    }
    return strength_map.get(hand_category, HandStrength.AIR)


def build_poker_review_payload(
    request: PokerSpotRequest,
    hole_cards: List[Card],
    board: List[Card],
    street: Street,
    in_position: bool,
    decision_payload: Dict[str, Any],
) -> Dict[str, Any]:
    review_focus = []

    if street == Street.PREFLOP or len(board) < 3:
        return {
            "summary": "Preflop spot. Deterministic recommendation is primary; solver-lite review starts on the flop.",
            "agreement": "n_a",
            "review_focus": ["Confirm opener/3-bet positions and real raise size before trusting a mixed preflop frequency."],
            "solver_line": None,
            "board_texture": None,
            "hand_classification": "preflop",
            "board_description": None,
        }

    board_analysis = board_analyzer.analyze(board)
    hand_category, hand_result = postflop_engine.analyze_hand_strength(hole_cards, board)
    solver_texture = map_solver_texture(board_analysis.texture)
    solver_strength = map_solver_strength(hand_category)

    if street == Street.RIVER:
        solver_solution = solver_lite.get_river_value_solution(solver_strength, in_position)
    elif request.bet_to_call > 0:
        solver_solution = solver_lite.get_facing_bet_solution(
            solver_strength,
            bet_size=request.bet_to_call,
            pot_size=max(request.pot_size, 0.01),
        )
    else:
        solver_solution = solver_lite.get_cbet_solution(
            solver_texture,
            in_position=in_position,
            hand_strength=solver_strength,
        )

    deterministic_bucket = normalize_action(decision_payload.get("action"))
    solver_bucket = normalize_action(solver_solution.action)
    agreement = "aligned" if deterministic_bucket == solver_bucket else "diverges"

    if agreement == "diverges":
        review_focus.append("Deterministic engine and solver-lite prefer different action families. Replay this hand before using it as a study template.")

    if board_analysis.texture in {AnalyzerTexture.WET, AnalyzerTexture.MONOTONE}:
        review_focus.append("Board is volatile. Prioritize future-card pressure and avoid autopiloting one-street logic.")
    if hand_category == HandCategory.DRAW:
        review_focus.append("Draw-heavy hand class. Make sure real fold equity and implied odds justify aggression.")
    if request.bet_to_call > request.pot_size:
        review_focus.append("Facing an overbet. Villain range should be polarized; check that villain profile is accurate.")
    if not request.action_history:
        review_focus.append("Action history is missing. Enter the betting line next time so turn/river advice is state-complete.")

    if not review_focus:
        review_focus.append("Spot is internally consistent. Use this as a clean replay example.")

    return {
        "summary": f"{hand_result.description} on a {board_analysis.description.lower()} board.",
        "agreement": agreement,
        "review_focus": review_focus,
        "solver_line": {
            "action": solver_solution.action.lower(),
            "frequency": solver_solution.frequency,
            "sizing": solver_solution.sizing,
            "ev": solver_solution.ev,
            "reasoning": solver_solution.reasoning,
            "texture": solver_texture.value,
            "strength_bucket": solver_strength.value,
        },
        "board_texture": board_analysis.texture.value,
        "hand_classification": hand_category.value,
        "board_description": board_analysis.description,
    }


def analyze_poker_request(request: PokerSpotRequest) -> Dict[str, Any]:
    try:
        hole_cards = parse_cards(request.hole_cards)
        if len(hole_cards) != 2:
            raise HTTPException(status_code=400, detail="Hole cards must contain exactly 2 cards")

        board = parse_cards(request.board) if request.board else []
        hero_position = parse_position(request.position, Position.BTN)
        villain_position = parse_position(request.villain_position, None) if request.villain_position else None
        street = street_from_board(board)
        in_position = infer_in_position(hero_position, villain_position)

        engine = get_decision_engine()
        decision = engine.get_decision(
            hole_cards=hole_cards,
            board=board,
            position=hero_position,
            pot=request.pot_size,
            bet_to_call=request.bet_to_call,
            street=street,
            in_position=in_position,
            villain_type=request.villain_type,
            villain_position=villain_position,
            effective_stack=request.effective_stack,
            is_preflop_aggressor=request.is_preflop_aggressor,
        )

        validation = build_poker_validation(request, street, villain_position)
        decision_payload = serialize_decision(decision, validation, street)
        return {
            "spot": {
                "hole_cards": request.hole_cards,
                "board": request.board,
                "position": hero_position.name,
                "villain_type": request.villain_type,
                "villain_position": villain_position.name if villain_position else None,
                "pot_size": request.pot_size,
                "bet_to_call": request.bet_to_call,
                "effective_stack": request.effective_stack,
                "is_preflop_aggressor": request.is_preflop_aggressor,
                "in_position": in_position,
                "street": street.value,
                "action_history": request.action_history,
            },
            "decision": decision_payload,
            "review": build_poker_review_payload(
                request=request,
                hole_cards=hole_cards,
                board=board,
                street=street,
                in_position=in_position,
                decision_payload=decision_payload,
            ),
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def ensure_unique_cards(groups: Dict[str, List[Card]]) -> None:
    seen: Dict[str, str] = {}
    for label, cards in groups.items():
        for card in cards:
            card_key = str(card)
            previous = seen.get(card_key)
            if previous:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate card detected in screenshot parse: {card_key} appears in both {previous} and {label}",
                )
            seen[card_key] = label


def build_blocked_screenshot_response(
    parsed_spot: Dict[str, Any],
    visible_opponents: List[Dict[str, Any]],
    parse_confidence: float,
    missing_fields: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    return {
        "decision_status": "blocked",
        "parsed_spot": parsed_spot,
        "spot": parsed_spot,
        "visible_opponents": visible_opponents,
        "parse_confidence": parse_confidence,
        "missing_fields": list(dict.fromkeys(missing_fields)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def build_screenshot_analysis_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    warnings = list(parsed.get("warnings") or [])
    missing_fields = list(parsed.get("missing_fields") or [])
    visible_opponents = parsed.get("visible_opponents") or []
    parse_confidence = float(parsed.get("parse_confidence") or 0.0)

    parsed_spot: Dict[str, Any] = {
        "hole_cards": " ".join(parsed.get("hero_cards") or []),
        "board": " ".join(parsed.get("board") or []),
        "position": parsed.get("position"),
        "villain_type": "reg",
        "villain_position": None,
        "pot_size": parsed.get("pot_size"),
        "bet_to_call": parsed.get("bet_to_call"),
        "effective_stack": parsed.get("effective_stack"),
        "is_preflop_aggressor": parsed.get("is_preflop_aggressor"),
        "action_history": parsed.get("action_history") or [],
        "button_position": parsed.get("button_position"),
        "source_hint": parsed.get("source_hint", "online_table_ui"),
    }

    if parse_confidence < 0.35:
        warnings.append("Screenshot confidence is too low to trust a live decision.")
        return build_blocked_screenshot_response(parsed_spot, visible_opponents, parse_confidence, missing_fields, warnings)

    try:
        hero_cards = parse_cards(parsed_spot["hole_cards"]) if parsed_spot["hole_cards"] else []
        board_cards = parse_cards(parsed_spot["board"]) if parsed_spot["board"] else []
    except ValueError as exc:
        warnings.append(f"Card parsing failed: {exc}")
        return build_blocked_screenshot_response(parsed_spot, visible_opponents, parse_confidence, missing_fields, warnings)

    if len(hero_cards) != 2:
        warnings.append("Hero must have exactly 2 visible cards before the advisor can act.")
        return build_blocked_screenshot_response(parsed_spot, visible_opponents, parse_confidence, missing_fields, warnings)

    if len(board_cards) not in {0, 3, 4, 5}:
        warnings.append("Board must show 0, 3, 4, or 5 cards.")
        return build_blocked_screenshot_response(parsed_spot, visible_opponents, parse_confidence, missing_fields, warnings)

    unique_groups = {"hero hand": hero_cards, "board": board_cards}
    for idx, opponent in enumerate(visible_opponents, start=1):
        cards = opponent.get("cards") or []
        if not cards:
            continue
        try:
            unique_groups[f"opponent {idx}"] = parse_cards(" ".join(cards))
        except ValueError as exc:
            warnings.append(f"Visible opponent cards were invalid: {exc}")
            return build_blocked_screenshot_response(parsed_spot, visible_opponents, parse_confidence, missing_fields, warnings)
    ensure_unique_cards(unique_groups)

    if not parsed_spot["position"]:
        parsed_spot["position"] = "BTN"
        warnings.append("Hero position was unreadable. Defaulted to BTN.")

    if parsed_spot["bet_to_call"] is None:
        parsed_spot["bet_to_call"] = 0.0
        warnings.append("Bet to call was unreadable. Defaulted to 0.")

    if parsed_spot["pot_size"] is None:
        if not board_cards and parsed_spot["bet_to_call"] == 0 and not parsed_spot["action_history"]:
            parsed_spot["pot_size"] = 1.5
            warnings.append("Pot size was unreadable in a likely unopened preflop spot. Defaulted to 1.5bb.")
        else:
            warnings.append("Pot size is required for this spot, and it was not readable.")
            return build_blocked_screenshot_response(parsed_spot, visible_opponents, parse_confidence, missing_fields, warnings)

    if parsed_spot["effective_stack"] is None:
        warnings.append("Effective stack was unreadable, so the screenshot result is blocked.")
        return build_blocked_screenshot_response(parsed_spot, visible_opponents, parse_confidence, missing_fields, warnings)

    if parsed_spot["is_preflop_aggressor"] is None:
        parsed_spot["is_preflop_aggressor"] = True
        warnings.append("Preflop aggressor was unreadable. Defaulted to hero.")

    positioned_opponents = [opp for opp in visible_opponents if opp.get("position")]
    if len(positioned_opponents) == 1:
        parsed_spot["villain_position"] = positioned_opponents[0]["position"]
    elif len(positioned_opponents) > 1:
        warnings.append("Multiple visible opponents were detected, so villain position stays unknown.")

    warnings.append("Villain type defaulted to reg for screenshot mode.")

    request = PokerSpotRequest(
        hole_cards=parsed_spot["hole_cards"],
        board=parsed_spot["board"],
        position=parsed_spot["position"],
        villain_type=parsed_spot["villain_type"],
        villain_position=parsed_spot["villain_position"],
        pot_size=float(parsed_spot["pot_size"]),
        bet_to_call=float(parsed_spot["bet_to_call"]),
        effective_stack=float(parsed_spot["effective_stack"]),
        is_preflop_aggressor=bool(parsed_spot["is_preflop_aggressor"]),
        action_history=parsed_spot["action_history"],
    )

    analysis = analyze_poker_request(request)
    decision_status = "validated"
    if warnings or missing_fields or analysis["decision"]["validation"]["status"] != "validated":
        decision_status = "provisional"

    return {
        "decision_status": decision_status,
        "parsed_spot": {**parsed_spot, **analysis["spot"]},
        "spot": {**parsed_spot, **analysis["spot"]},
        "visible_opponents": visible_opponents,
        "parse_confidence": parse_confidence,
        "missing_fields": list(dict.fromkeys(missing_fields)),
        "warnings": list(dict.fromkeys(warnings)),
        "decision": analysis["decision"],
        "review": analysis["review"],
    }

class ImageReplyRequest(BaseModel):
    image_data: str  # Base64 encoded image (can include data:image/... prefix)
    caption: str = ""  # Optional caption text

class ReplyOption(BaseModel):
    mode: str
    reply: str
    char_count: int

class AnalysisResult(BaseModel):
    tone: str
    assumptions: str
    angle: str
    recommended_mode: str
    why: str
    engagement_potential: str

class ReplyResponse(BaseModel):
    analysis: AnalysisResult
    replies: List[ReplyOption]

class ImageAnalysisResult(BaseModel):
    image_type: str
    visible_text: str
    description: str
    actual_message: str
    tone: str
    hook: str

class ImageReplyResponse(BaseModel):
    image_analysis: ImageAnalysisResult
    analysis: AnalysisResult
    replies: List[ReplyOption]

class TweetRequest(BaseModel):
    topic: Optional[str] = None
    count: int = 5

class TweetResponse(BaseModel):
    topic: str
    tweets: List[dict]

class ThreadRequest(BaseModel):
    topic: str
    length: int = 5
    thesis: Optional[str] = None

class ThreadResponse(BaseModel):
    topic: str
    tweets: List[dict]


# Endpoints
@app.get("/")
async def root():
    return {"message": "🥜 Nirvana Nuts Growth Engine API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/operator/status")
async def operator_status():
    return {
        "status": "ready",
        "timestamp": datetime.now().isoformat(),
        "blackjack_profiles": len(CASINO_PROFILES),
        "poker_review_queue_items": len(review_queue_store.load()),
        "data_paths": {
            "operator": str(operator_data_dir),
            "blackjack": str(PROJECT_ROOT / "src" / "data" / "blackjack_agent"),
            "poker": str(PROJECT_ROOT / "src" / "data" / "poker_agent"),
        },
    }


@app.get("/api/blackjack/profiles")
async def blackjack_profiles():
    return [
        {"name": name, **profile}
        for name, profile in CASINO_PROFILES.items()
    ]


@app.get("/api/blackjack/coach-summary")
async def blackjack_coach_summary(counting_system: str = "hi_lo"):
    trainer = ProTrainer(counting_system=counting_system)
    return trainer.get_readiness_report()


@app.post("/api/blackjack/session-plan")
async def blackjack_session_plan(request: BlackjackSessionPlanRequest):
    trainer = ProTrainer(counting_system=request.counting_system)
    try:
        return trainer.build_session_plan(
            profile_name=request.profile_name,
            custom_profile=request.custom_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/blackjack/review-session")
async def blackjack_review_session(request: BlackjackSessionReviewRequest):
    trainer = ProTrainer(counting_system=request.counting_system)
    return trainer.analyze_session(
        hands=request.hands,
        hours=request.hours,
        wagered=request.wagered,
        pnl=request.pnl,
        min_bet=request.min_bet,
        max_bet=request.max_bet,
        save=True,
    )


@app.post("/api/replies", response_model=ReplyResponse)
async def generate_replies(request: ReplyRequest):
    """Generate reply options for a tweet"""
    try:
        agent = get_agent()

        # Get analysis
        analysis = agent.analyze_tweet(request.tweet)

        # Generate replies for each mode
        modes = ["savage", "funny", "philosophical", "controversial", "nuclear"]
        replies = []

        for mode in modes:
            reply_text = agent.generate_reply(request.tweet, mode, analysis)
            replies.append({
                "mode": mode,
                "reply": reply_text,
                "char_count": len(reply_text)
            })

        return {
            "analysis": {
                "tone": analysis.get("tone", "unknown"),
                "assumptions": analysis.get("assumptions", "unknown"),
                "angle": analysis.get("angle", "unknown"),
                "recommended_mode": analysis.get("recommended_mode", "savage"),
                "why": analysis.get("why", ""),
                "engagement_potential": analysis.get("engagement_potential", "medium")
            },
            "replies": replies
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/image-replies", response_model=ImageReplyResponse)
async def generate_image_replies(request: ImageReplyRequest):
    """Generate reply options for an image tweet"""
    try:
        agent = get_agent()
        print(f"[API] Processing image reply request with caption: {request.caption[:50]}..." if request.caption else "[API] Processing image reply (no caption)")

        # Parse the base64 image data
        image_data = request.image_data
        image_media_type = "image/png"  # Default

        # Handle data URL format (data:image/png;base64,...)
        if image_data.startswith("data:"):
            # Extract media type and base64 data
            match = re.match(r"data:(image/[^;]+);base64,(.+)", image_data)
            if match:
                image_media_type = match.group(1)
                image_data = match.group(2)
            else:
                # Try simpler format
                if ";base64," in image_data:
                    image_data = image_data.split(";base64,")[1]

        # Generate replies using the agent
        replies, analysis, image_analysis = agent.generate_replies_for_image(
            image_data=image_data,
            caption=request.caption,
            image_media_type=image_media_type
        )

        return {
            "image_analysis": {
                "image_type": image_analysis.get("image_type", "unknown"),
                "visible_text": image_analysis.get("visible_text", ""),
                "description": image_analysis.get("description", ""),
                "actual_message": image_analysis.get("actual_message", image_analysis.get("context", "")),
                "tone": image_analysis.get("tone", "unknown"),
                "hook": image_analysis.get("hook", "")
            },
            "analysis": {
                "tone": analysis.get("tone", "unknown"),
                "assumptions": analysis.get("assumptions", "unknown"),
                "angle": analysis.get("angle", "unknown"),
                "recommended_mode": analysis.get("recommended_mode", "savage"),
                "why": analysis.get("why", ""),
                "engagement_potential": analysis.get("engagement_potential", "medium")
            },
            "replies": [
                {"mode": r["mode"], "reply": r["reply"], "char_count": len(r["reply"])}
                for r in replies
            ]
        }
    except Exception as e:
        print(f"[API] Error generating image replies: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tweets", response_model=TweetResponse)
async def generate_tweets(request: TweetRequest):
    """Generate original tweet ideas"""
    try:
        agent = get_agent()
        print(f"[API] Generating {request.count} tweets on topic: {request.topic}")

        tweets = agent.generate_tweets(request.topic, request.count)

        if not tweets:
            print("[API] Warning: No tweets generated, returning empty list")
            tweets = []

        topic_used = request.topic or "random topic"

        result = {
            "topic": topic_used,
            "tweets": [{"text": t, "char_count": len(t)} for t in tweets if t]
        }
        print(f"[API] Returning {len(result['tweets'])} tweets")
        return result

    except Exception as e:
        print(f"[API] Error generating tweets: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thread", response_model=ThreadResponse)
async def generate_thread(request: ThreadRequest):
    """Generate a Twitter thread"""
    try:
        agent = get_agent()
        print(f"[API] Generating {request.length}-tweet thread on: {request.topic}")

        thread = agent.generate_thread(request.topic, request.length, request.thesis)

        if not thread:
            print("[API] Warning: No thread generated")
            thread = []

        roles = ["HOOK"] + ["BODY"] * (len(thread) - 2) + ["CLOSER"] if len(thread) > 1 else ["HOOK"]

        result = {
            "topic": request.topic,
            "tweets": [
                {"text": t, "char_count": len(t), "role": roles[i] if i < len(roles) else "BODY"}
                for i, t in enumerate(thread) if t
            ]
        }
        print(f"[API] Returning {len(result['tweets'])} thread tweets")
        return result

    except Exception as e:
        print(f"[API] Error generating thread: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/poker/advice")
async def get_poker_advice(request: PokerAdviceRequest):
    """Get God Mode poker advice"""
    try:
        god = get_poker_agent()
        
        # Parse inputs
        cards = []
        if request.hole_cards:
            # Simple parser or use agent's internal
            # Assuming parse_cards is available or we implement simple logic
            # god.parse_cards is not exposed, let's just assume string passed to new_hand? 
            # No, new_hand expects List[Card].
            # We need to parse.
            from src.agents.poker.poker_agent import parse_cards
            cards = parse_cards(request.hole_cards)
            
        board = []
        if request.board:
            from src.agents.poker.poker_agent import parse_cards
            board = parse_cards(request.board)
            
        pos_enum = Position.BTN
        try:
            pos_enum = Position[request.position.upper()]
        except:
            pass
            
        # Update State
        god.new_hand(cards, pos_enum)
        god.set_board(board)
        god.set_pot(request.pot_size, request.bet_facing)
        
        if request.villain_range:
            god.set_villain_range(request.villain_range)
            
        # Get advice
        advice = god.get_postflop_advice()
        
        # Format response
        if advice:
            return {
                "decision": advice['decision'].action.value,
                "sizing": advice['decision'].sizing_fraction,
                "reasoning": advice['decision'].reasoning,
                "equity": advice.get('equity', {}).get('equity', 0),
                "hand_class": advice['hand_category'].value
            }
        return {"error": "Could not generate advice"}

    except Exception as e:
        print(f"[API] Poker Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/poker/advisor/analyze")
async def analyze_poker_spot(request: PokerSpotRequest):
    return analyze_poker_request(request)


@app.post("/api/poker/advisor/analyze-screenshot")
async def analyze_poker_screenshot(request: PokerScreenshotAnalyzeRequest):
    try:
        parser = get_poker_screenshot_parser()
        parsed = parser.analyze(
            image_data=request.image_data,
            image_type=request.image_type,
            source_hint=request.source_hint,
        )
        return build_screenshot_analysis_payload(parsed)
    except VisionModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ScreenshotParserError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/poker/review-queue")
async def get_poker_review_queue():
    return {"items": review_queue_store.load()}


@app.post("/api/poker/review-queue")
async def add_poker_review_item(request: PokerReviewQueueRequest):
    entry = review_queue_store.add(
        {
            "label": request.label or "Marked hand",
            "note": request.note or "",
            "spot": request.spot,
            "decision": request.decision or {},
        }
    )
    return entry


@app.get("/api/poker/review-queue/{item_id}")
async def get_poker_review_item(item_id: str):
    item = review_queue_store.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    spot_data = item.get("spot") or {}
    review = None

    try:
        request = PokerSpotRequest(
            hole_cards=spot_data.get("hole_cards", ""),
            board=spot_data.get("board", ""),
            position=spot_data.get("position", "BTN"),
            villain_type=spot_data.get("villain_type", "reg"),
            villain_position=spot_data.get("villain_position"),
            pot_size=float(spot_data.get("pot_size", 1.5)),
            bet_to_call=float(spot_data.get("bet_to_call", 0.0)),
            effective_stack=float(spot_data.get("effective_stack", 100.0)),
            is_preflop_aggressor=bool(spot_data.get("is_preflop_aggressor", True)),
            action_history=spot_data.get("action_history", []) or [],
        )
        hole_cards = parse_cards(request.hole_cards)
        board = parse_cards(request.board) if request.board else []
        hero_position = parse_position(request.position, Position.BTN)
        villain_position = parse_position(request.villain_position, None) if request.villain_position else None
        street = street_from_board(board)
        in_position = infer_in_position(hero_position, villain_position)
        review = build_poker_review_payload(
            request=request,
            hole_cards=hole_cards,
            board=board,
            street=street,
            in_position=in_position,
            decision_payload=item.get("decision") or {},
        )
    except Exception as exc:
        review = {"summary": f"Replay payload could not be rebuilt: {exc}", "agreement": "n_a", "review_focus": [], "solver_line": None}

    return {"item": item, "review": review}


@app.delete("/api/poker/review-queue/{item_id}")
async def delete_poker_review_item(item_id: str):
    removed = review_queue_store.remove(item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Review item not found")
    return {"status": "deleted", "id": item_id}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
