"""
🎰 Poker God API
Dedicated backend for the Poker Agent
Runs on Port 8001
"""

import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.poker.poker_agent import PokerAgent
from src.agents.poker.core.poker_types import Position

app = FastAPI(
    title="Poker God API",
    description="Dedicated backend for Poker God Agent",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize agent
poker_agent = None

def get_poker_agent():
    global poker_agent
    if poker_agent is None:
        poker_agent = PokerAgent()
    return poker_agent

class PokerAdviceRequest(BaseModel):
    hole_cards: str
    board: str = ""
    pot_size: float = 0.0
    bet_facing: float = 0.0
    position: str = "BTN"
    villain_range: Optional[str] = None

@app.get("/")
async def root():
    return {"status": "Poker God is Online 🎰"}

@app.post("/api/poker/advice")
async def get_poker_advice(request: PokerAdviceRequest):
    try:
        god = get_poker_agent()
        
        # Parse inputs
        from src.agents.poker.poker_agent import parse_cards
        cards = parse_cards(request.hole_cards)
        
        board = []
        if request.board:
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
        print(f"[POKER API] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
