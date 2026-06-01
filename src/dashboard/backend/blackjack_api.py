"""
Blackjack Twitter Agent Dashboard API
The High Roller's Command Center
Runs on Port 8002
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

app = FastAPI(
    title="Blackjack Twitter API",
    description="The High Roller's Dashboard for Gambling Wisdom on Twitter",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class AnalyzeRequest(BaseModel):
    tweet: str

class RepliesRequest(BaseModel):
    tweet: str
    mode: Optional[str] = None  # Optional mode filter

class TweetsRequest(BaseModel):
    topic: Optional[str] = None
    count: int = 5

class ThreadRequest(BaseModel):
    topic: str
    length: int = 5
    thesis: Optional[str] = None

class AnalysisResponse(BaseModel):
    tone: str
    the_bet: str
    assumptions: Optional[str] = None
    angle: str
    recommended_mode: str
    why: str
    engagement_potential: str

class ReplyItem(BaseModel):
    mode: str
    reply: str
    char_count: int

class RepliesResponse(BaseModel):
    original_tweet: str
    analysis: AnalysisResponse
    replies: List[ReplyItem]

class TweetItem(BaseModel):
    text: str
    char_count: int

class TweetsResponse(BaseModel):
    topic: str
    tweets: List[TweetItem]

class ThreadResponse(BaseModel):
    topic: str
    thesis: Optional[str]
    tweets: List[TweetItem]

class ModeInfo(BaseModel):
    mode: str
    name: str
    description: str
    icon: str
    color: str
    pattern: str

class StatusResponse(BaseModel):
    status: str
    model: str
    modes_available: List[str]
    timestamp: str

# =============================================================================
# AGENT WRAPPER
# =============================================================================

_agent = None

def get_agent():
    """Lazy load the Blackjack agent"""
    global _agent
    if _agent is None:
        try:
            from src.agents.blackjack_agent import BlackjackAgent
            _agent = BlackjackAgent()
        except Exception as e:
            print(f"Warning: Could not load Blackjack agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load agent: {str(e)}")
    return _agent

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    return {
        "status": "Blackjack Twitter API Online",
        "message": "The house edge is ignorance. Your edge is wisdom.",
        "port": 8002
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/blackjack/status")
async def get_status() -> StatusResponse:
    """Get agent status and available modes"""
    try:
        agent = get_agent()
        return StatusResponse(
            status="online",
            model=agent.model.model_name if agent.model else "unknown",
            modes_available=["card_counter", "high_roller", "table_reader", "bankroll_manager", "the_dealer", "shark"],
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        return StatusResponse(
            status="offline",
            model="unknown",
            modes_available=[],
            timestamp=datetime.now().isoformat()
        )

@app.get("/api/blackjack/modes")
async def get_modes() -> List[ModeInfo]:
    """Get all available modes with descriptions"""
    return [
        ModeInfo(
            mode="card_counter",
            name="Card Counter",
            description="Mathematical precision. You see the odds others miss.",
            icon="calculator",
            color="#06b6d4",
            pattern="THE ODDS FLIP - Show real odds vs perceived odds"
        ),
        ModeInfo(
            mode="high_roller",
            name="High Roller",
            description="Confident boldness. Small bets, small life.",
            icon="trending-up",
            color="#eab308",
            pattern="THE BET REVEAL - Show hidden bets in behavior"
        ),
        ModeInfo(
            mode="table_reader",
            name="Table Reader",
            description="Psychological insight. Every action is a tell.",
            icon="eye",
            color="#a855f7",
            pattern="THE TABLE READ - Decode the psychology"
        ),
        ModeInfo(
            mode="bankroll_manager",
            name="Bankroll Manager",
            description="Strategic survival. Never go broke.",
            icon="shield",
            color="#10b981",
            pattern="THE POSITION SIZE - Apply bankroll management to life"
        ),
        ModeInfo(
            mode="the_dealer",
            name="The Dealer",
            description="Cool detachment. Seen it all from the other side.",
            icon="glasses",
            color="#94a3b8",
            pattern="THE DEALER'S VIEW - Wisdom from experience"
        ),
        ModeInfo(
            mode="shark",
            name="Shark",
            description="Aggressive precision. Blood in the water.",
            icon="target",
            color="#ef4444",
            pattern="THE EV CALCULATION - Calculate where others don't"
        ),
    ]

@app.post("/api/blackjack/analyze")
async def analyze_tweet(request: AnalyzeRequest) -> AnalysisResponse:
    """Analyze a tweet and get mode recommendation"""
    if not request.tweet.strip():
        raise HTTPException(status_code=400, detail="Tweet text is required")

    try:
        agent = get_agent()
        analysis = agent.analyze_tweet(request.tweet)

        return AnalysisResponse(
            tone=analysis.get("tone", "unknown"),
            the_bet=analysis.get("the_bet", "unknown"),
            assumptions=analysis.get("assumptions"),
            angle=analysis.get("angle", "gambling wisdom"),
            recommended_mode=analysis.get("recommended_mode", "card_counter"),
            why=analysis.get("why", ""),
            engagement_potential=analysis.get("engagement_potential", "medium")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/blackjack/replies")
async def generate_replies(request: RepliesRequest) -> RepliesResponse:
    """Generate replies across all modes (or a specific mode)"""
    if not request.tweet.strip():
        raise HTTPException(status_code=400, detail="Tweet text is required")

    try:
        agent = get_agent()

        # First analyze
        analysis = agent.analyze_tweet(request.tweet)

        # Generate replies
        replies = agent.generate_replies(request.tweet, request.mode)

        reply_items = [
            ReplyItem(
                mode=r["mode"],
                reply=r["reply"],
                char_count=len(r["reply"])
            )
            for r in replies
        ]

        return RepliesResponse(
            original_tweet=request.tweet,
            analysis=AnalysisResponse(
                tone=analysis.get("tone", "unknown"),
                the_bet=analysis.get("the_bet", "unknown"),
                assumptions=analysis.get("assumptions"),
                angle=analysis.get("angle", "gambling wisdom"),
                recommended_mode=analysis.get("recommended_mode", "card_counter"),
                why=analysis.get("why", ""),
                engagement_potential=analysis.get("engagement_potential", "medium")
            ),
            replies=reply_items
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/blackjack/tweets")
async def generate_tweets(request: TweetsRequest) -> TweetsResponse:
    """Generate original tweets on a topic"""
    try:
        agent = get_agent()
        tweets = agent.generate_tweets(request.topic, request.count)

        tweet_items = [
            TweetItem(text=t, char_count=len(t))
            for t in tweets
        ]

        return TweetsResponse(
            topic=request.topic or "random gambling wisdom",
            tweets=tweet_items
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/blackjack/thread")
async def generate_thread(request: ThreadRequest) -> ThreadResponse:
    """Generate a Twitter thread"""
    if not request.topic.strip():
        raise HTTPException(status_code=400, detail="Topic is required")

    try:
        agent = get_agent()
        thread = agent.generate_thread(request.topic, request.length, request.thesis)

        tweet_items = [
            TweetItem(text=t, char_count=len(t))
            for t in thread
        ]

        return ThreadResponse(
            topic=request.topic,
            thesis=request.thesis,
            tweets=tweet_items
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("   BLACKJACK TWITTER API")
    print("   The High Roller's Dashboard")
    print("   Starting on http://localhost:8002")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8002)
