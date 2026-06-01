"""
Standalone Poker Advisor API.

The live dashboard now uses a stateless NLH analysis path for real-time advice,
while legacy helper endpoints stay available behind scoped in-memory sessions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.poker_types import Position
from src.agents.poker.poker_agent import GameFormat, GameMode, PokerAgent, parse_cards
from src.agents.poker.strategy.preflop_engine import FacingAction
from src.agents.poker.vision import (
    PokerScreenshotParser,
    ScreenshotParserError,
    VisionModelUnavailableError,
)

from .advisor_service import (
    SpotValidationError,
    analyze_nlh_spot,
    build_analysis_from_screenshot,
)


app = FastAPI(
    title="Poker Advisor API",
    description="Real-time poker strategy advice powered by TradeHive's Poker God Agent",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=static_dir), name="static")


POSITION_MAP = {
    "utg": Position.UTG,
    "utg1": Position.UTG1,
    "utg2": Position.UTG2,
    "mp": Position.MP,
    "mp2": Position.MP2,
    "hj": Position.HJ,
    "co": Position.CO,
    "btn": Position.BTN,
    "sb": Position.SB,
    "bb": Position.BB,
}

FACING_MAP = {
    "unopened": FacingAction.UNOPENED,
    "limped": FacingAction.LIMPED,
    "raised": FacingAction.RAISED,
    "facing_raise": FacingAction.RAISED,
    "3bet": FacingAction.THREE_BET,
    "facing_3bet": FacingAction.THREE_BET,
    "4bet": FacingAction.FOUR_BET,
    "facing_4bet": FacingAction.FOUR_BET,
    "5bet": FacingAction.FIVE_BET,
    "all_in": FacingAction.ALL_IN,
}


class DashboardSessionManager:
    """Small in-memory scoped session store for compatibility endpoints."""

    def __init__(self) -> None:
        self._agents: Dict[str, PokerAgent] = {}

    def get(self, session_id: Optional[str] = None) -> PokerAgent:
        key = (session_id or "default").strip() or "default"
        if key not in self._agents:
            self._agents[key] = PokerAgent(mode=GameMode.ADVISOR, game_format=GameFormat.CASH)
        return self._agents[key]

    def reset(self, session_id: Optional[str] = None) -> None:
        key = (session_id or "default").strip() or "default"
        self._agents[key] = PokerAgent(mode=GameMode.ADVISOR, game_format=GameFormat.CASH)


session_manager = DashboardSessionManager()
poker_screenshot_parser: Optional[PokerScreenshotParser] = None


def get_poker_screenshot_parser() -> PokerScreenshotParser:
    global poker_screenshot_parser
    if poker_screenshot_parser is None:
        poker_screenshot_parser = PokerScreenshotParser()
    return poker_screenshot_parser


class SessionScopedRequest(BaseModel):
    session_id: Optional[str] = None


class NewHandInput(SessionScopedRequest):
    hole_cards: str
    position: str = "btn"


class BoardInput(SessionScopedRequest):
    cards: str


class PotInput(SessionScopedRequest):
    pot_size: float
    bet_to_call: float = 0
    effective_stack: float = 100


class RangeInput(SessionScopedRequest):
    notation: str


class PreflopRequest(SessionScopedRequest):
    facing: str = "unopened"
    raiser_position: Optional[str] = None


class PostflopRequest(SessionScopedRequest):
    in_position: bool = True


class EquityRequest(SessionScopedRequest):
    villain_range: str = ""
    iterations: int = 5000


class GTORequest(SessionScopedRequest):
    bet_size: Optional[float] = None


class AnalyzeRequest(BaseModel):
    hole_cards: str
    board: str = ""
    hero_position: Optional[str] = None
    position: Optional[str] = None
    villain_position: Optional[str] = None
    pot_size: float = 1.5
    bet_to_call: float = 0
    effective_stack: float = 100
    street: Optional[str] = None
    action_history: Any = Field(default_factory=list)
    is_preflop_aggressor: Optional[bool] = None
    villain_type: str = "reg"
    villain_stats: Dict[str, Optional[float]] = Field(default_factory=dict)
    player_count: int = 2
    facing: Optional[str] = None
    villain_range: str = ""


class ScreenshotInput(BaseModel):
    image_data: str
    image_type: str = "image/png"
    layout_hint: Optional[str] = None


class ResultInput(SessionScopedRequest):
    won: bool
    amount: float


def get_position(pos_str: Optional[str], default: Position = Position.BTN) -> Position:
    if not pos_str:
        return default
    return POSITION_MAP.get(pos_str.lower(), default)


def get_facing_action(facing_str: Optional[str]) -> FacingAction:
    if not facing_str:
        return FacingAction.UNOPENED
    return FACING_MAP.get(facing_str.lower(), FacingAction.UNOPENED)


def serialize_decision(decision) -> Dict[str, Any]:
    if decision is None:
        return {}
    result = {
        "action": decision.action.value if hasattr(decision.action, "value") else str(decision.action),
        "reasoning": getattr(decision, "reasoning", ""),
    }
    if hasattr(decision, "sizing") and decision.sizing is not None:
        result["sizing"] = decision.sizing
    if hasattr(decision, "frequency"):
        result["frequency"] = decision.frequency
    if hasattr(decision, "range_strength"):
        result["range_strength"] = decision.range_strength
    if hasattr(decision, "alternative") and decision.alternative:
        alt = decision.alternative
        result["alternative"] = alt.value if hasattr(alt, "value") else str(alt)
        result["alt_frequency"] = getattr(decision, "alt_frequency", getattr(decision, "alt_freq", 0))
    if hasattr(decision, "sizing_fraction") and decision.sizing_fraction is not None:
        result["sizing_fraction"] = decision.sizing_fraction
        result["sizing_percent"] = int(round(decision.sizing_fraction * 100))
    return result


@app.get("/")
async def root():
    return FileResponse(static_dir / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    icon_path = static_dir / "favicon.ico"
    if icon_path.exists():
        return FileResponse(icon_path)
    return Response(status_code=204)


@app.post("/api/poker/new_hand")
async def new_hand(input: NewHandInput):
    try:
        agent = session_manager.get(input.session_id)
        cards = parse_cards(input.hole_cards)
        position = get_position(input.position)
        agent.new_hand(cards, position)
        return {
            "success": True,
            "hole_cards": input.hole_cards,
            "position": position.name,
            "message": f"New hand started: {input.hole_cards} from {position.name}",
            "session_id": input.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/set_board")
async def set_board(input: BoardInput):
    try:
        agent = session_manager.get(input.session_id)
        if input.cards.strip():
            cards = parse_cards(input.cards)
            agent.set_board(cards)
            street = {3: "FLOP", 4: "TURN", 5: "RIVER"}.get(len(cards), "PREFLOP")
        else:
            agent.hand_state.board = []
            street = "PREFLOP"
        return {
            "success": True,
            "board": input.cards,
            "street": street,
            "num_cards": len(agent.hand_state.board),
            "session_id": input.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/set_pot")
async def set_pot(input: PotInput):
    try:
        agent = session_manager.get(input.session_id)
        agent.set_pot(input.pot_size, input.bet_to_call)
        agent.hand_state.effective_stack = input.effective_stack
        return {
            "success": True,
            "pot_size": input.pot_size,
            "bet_to_call": input.bet_to_call,
            "effective_stack": input.effective_stack,
            "session_id": input.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/set_villain_range")
async def set_villain_range(input: RangeInput):
    try:
        agent = session_manager.get(input.session_id)
        agent.set_villain_range(input.notation)
        range_obj = agent.hand_state.villain_range
        range_percent = len(range_obj.hands) / 1326 * 100 if range_obj else 0
        return {
            "success": True,
            "notation": input.notation,
            "range_percent": round(range_percent, 1),
            "num_combos": len(range_obj.hands) if range_obj else 0,
            "session_id": input.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/preflop_advice")
async def get_preflop_advice(request: PreflopRequest):
    try:
        agent = session_manager.get(request.session_id)
        facing = get_facing_action(request.facing)
        raiser_pos = get_position(request.raiser_position) if request.raiser_position else None
        decision = agent.get_preflop_advice(facing, raiser_pos)
        return {
            "success": True,
            "decision": serialize_decision(decision),
            "position": agent.hand_state.position.name,
            "facing": facing.value,
            "session_id": request.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/postflop_advice")
async def get_postflop_advice(request: PostflopRequest):
    try:
        agent = session_manager.get(request.session_id)
        result = agent.get_postflop_advice(in_position=request.in_position)
        if result is None:
            return {"success": False, "error": "Need hole cards and board to analyze"}
        response = {
            "success": True,
            "decision": serialize_decision(result["decision"]),
            "hand_category": result["hand_category"].value if result.get("hand_category") else None,
            "hand_description": result["hand_result"].description if result.get("hand_result") else None,
            "board_texture": result["board_analysis"].texture.value if result.get("board_analysis") else None,
            "session_id": request.session_id or "default",
        }
        if result.get("equity"):
            response["equity"] = {
                "equity": round(result["equity"]["equity"] * 100, 1),
                "win_rate": round(result["equity"]["win_rate"] * 100, 1),
                "tie_rate": round(result["equity"]["tie_rate"] * 100, 1),
            }
        if result.get("board_analysis") and result["board_analysis"].draws:
            response["draws"] = [item.draw_type.value for item in result["board_analysis"].draws[:3]]
        return response
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/equity")
async def calculate_equity(request: EquityRequest):
    try:
        agent = session_manager.get(request.session_id)
        result = agent.get_equity(
            villain_range_str=request.villain_range if request.villain_range else None,
            iterations=request.iterations,
        )
        if "error" in result:
            return {"success": False, "error": result["error"]}
        return {
            "success": True,
            "equity": round(result["equity"] * 100, 1),
            "win_rate": round(result["win_rate"] * 100, 1),
            "tie_rate": round(result["tie_rate"] * 100, 1),
            "loss_rate": round(result["loss_rate"] * 100, 1),
            "session_id": request.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/poker/pot_odds")
async def get_pot_odds(session_id: Optional[str] = None):
    try:
        agent = session_manager.get(session_id)
        result = agent.get_pot_odds()
        if "error" in result:
            return {"success": False, "error": result["error"]}
        return {
            "success": True,
            "pot_odds": round(result["pot_odds"] * 100, 1),
            "pot_odds_ratio": result["ratio"],
            "break_even_equity": round(result["break_even_equity"] * 100, 1),
            "session_id": session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/gto_metrics")
async def get_gto_metrics(request: GTORequest):
    try:
        agent = session_manager.get(request.session_id)
        result = agent.get_gto_metrics(bet_size=request.bet_size)
        return {
            "success": True,
            "mdf": round(result["mdf"] * 100, 1),
            "alpha": round(result["alpha"] * 100, 1),
            "bluff_freq": round(result["bluff_freq"] * 100, 1),
            "session_id": request.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/poker/analyze")
async def analyze_full_state(request: AnalyzeRequest):
    try:
        return analyze_nlh_spot(request.model_dump())
    except SpotValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/poker/analyze-screenshot")
async def analyze_screenshot(request: ScreenshotInput):
    try:
        parser = get_poker_screenshot_parser()
        parsed = parser.analyze(
            image_data=request.image_data,
            image_type=request.image_type,
            source_hint="online_table_ui",
            layout_hint=request.layout_hint,
        )
        return build_analysis_from_screenshot(parsed, layout_hint=request.layout_hint)
    except VisionModelUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except (ScreenshotParserError, SpotValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/poker/record_result")
async def record_result(input: ResultInput):
    try:
        agent = session_manager.get(input.session_id)
        agent.record_result(input.won, input.amount)
        return {
            "success": True,
            "won": input.won,
            "amount": input.amount,
            "session_profit": agent.session_stats.total_profit,
            "session_id": input.session_id or "default",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/poker/session_stats")
async def get_session_stats(session_id: Optional[str] = None):
    agent = session_manager.get(session_id)
    stats = agent.session_stats
    return {
        "success": True,
        "hands_played": stats.hands_played,
        "hands_won": stats.hands_won,
        "win_rate": round(stats.win_rate * 100, 1),
        "total_profit": round(stats.total_profit, 2),
        "bb_per_100": round(stats.bb_per_100, 1),
        "biggest_pot_won": stats.biggest_pot_won,
        "biggest_pot_lost": stats.biggest_pot_lost,
        "vpip": stats.vpip,
        "pfr": stats.pfr,
        "three_bet": stats.three_bet,
        "session_id": session_id or "default",
    }


@app.post("/api/poker/reset_session")
async def reset_session(request: Optional[SessionScopedRequest] = None):
    session_id = None if request is None else request.session_id
    session_manager.reset(session_id)
    return {
        "success": True,
        "message": "Session reset",
        "session_id": session_id or "default",
    }


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "poker-advisor"}


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  POKER ADVISOR WEB DASHBOARD")
    print("  Built with love by TradeHive")
    print("=" * 50)
    print("\n  Open http://localhost:8001 in your browser\n")
    print("=" * 50 + "\n")
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=True)
