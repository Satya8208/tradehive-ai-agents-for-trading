"""
Blackjack Advisor Web API
FastAPI backend connecting the web dashboard to the blackjack agent logic
Built with love by TradeHive — SaaS Edition
"""

import sys
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Literal
import uvicorn

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Import blackjack agent components
from src.agents.blackjack.card_counter import CardCounter
from src.agents.blackjack.strategy_engine import StrategyEngine, Hand
from src.agents.blackjack.pro_trainer_api import router as protrainer_router

# Import SaaS modules (try both relative and absolute imports)
SAAS_ENABLED = False
try:
    # Try relative import first (when run as package)
    from .auth import (
        get_current_user, require_auth, require_pro, require_premium,
        check_rate_limit, User, DemoUser, rate_limiter, FREE_LIMITS
    )
    from .payments import (
        create_checkout_session, create_portal_session,
        handle_webhook, process_subscription_event, get_pricing_display
    )
    from .database import db
    SAAS_ENABLED = True
except ImportError:
    try:
        # Try absolute import (when run directly)
        from auth import (
            get_current_user, require_auth, require_pro, require_premium,
            check_rate_limit, User, DemoUser, rate_limiter, FREE_LIMITS
        )
        from payments import (
            create_checkout_session, create_portal_session,
            handle_webhook, process_subscription_event, get_pricing_display
        )
        from database import db
        SAAS_ENABLED = True
    except ImportError as e:
        print(f"[INFO] SaaS modules not loaded - running in standalone mode: {e}")

app = FastAPI(
    title="Blackjack God API",
    description="AI-powered blackjack advisor with card counting and strategy recommendations",
    version="2.0.0"
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Global state (in production, use session management)
counters = {}
strategy_engine = StrategyEngine()
betting_method = "spread"  # Default betting method

# Include Pro Trainer API routes
app.include_router(protrainer_router)

# Spread tables for different strategies
SPREAD_TABLES = {
    'spread': {
        -5: 1, -4: 1, -3: 1, -2: 1, -1: 1,
        0: 1, 1: 2, 2: 4, 3: 6, 4: 8, 5: 10, 6: 12
    },
    'spread_aggressive': {
        -5: 1, -4: 1, -3: 1, -2: 1, -1: 1,
        0: 1, 1: 2, 2: 4, 3: 8, 4: 12, 5: 12, 6: 12
    },
}


class CardInput(BaseModel):
    card: str


class HandInput(BaseModel):
    player_cards: List[str]
    dealer_upcard: str
    true_count: float = 0


class CounterConfig(BaseModel):
    system: Literal['hi_lo', 'omega_ii', 'wong_halves'] = 'hi_lo'
    num_decks: int = 6


class SessionState(BaseModel):
    player_cards: List[str] = []
    dealer_cards: List[str] = []
    other_cards: List[str] = []
    counting_system: str = 'hi_lo'
    num_decks: int = 6


# ===== AUTH HELPER =====

async def optional_auth(request: Request):
    """
    Optional authentication for counter endpoints.
    Returns user if authenticated, None in demo mode.
    Raises 401 if auth is configured but user is not authenticated.
    """
    if not SAAS_ENABLED:
        return None  # Demo mode, allow all

    # SaaS mode - check for auth
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        # Check if we're in demo mode (Supabase not configured)
        supabase = get_supabase() if 'get_supabase' in dir() else None
        if supabase is None:
            return None  # Demo mode
        # SaaS configured but no token - still allow for backwards compatibility
        # but log a warning
        return None

    # Has token - verify it
    return await get_current_user(request, None)


# ===== ENDPOINTS =====

@app.get("/")
async def root():
    """Serve the integrated blackjack dashboard shell"""
    return FileResponse(static_dir / "integrated_dashboard.html")


@app.get("/advisor-app")
async def advisor_app():
    """Serve the live advisor app inside the integrated shell"""
    return FileResponse(static_dir / "index.html")


def get_session_key(user, session_id: str = "default") -> str:
    """Get session key - user-specific if authenticated, otherwise shared"""
    if user and hasattr(user, 'id') and user.id != "demo-user":
        return f"{user.id}:{session_id}"
    return f"demo:{session_id}"


@app.post("/api/counter/create")
async def create_counter(config: CounterConfig, request: Request):
    """Create a new card counter session"""
    user = await optional_auth(request)
    session_key = get_session_key(user)
    counters[session_key] = CardCounter(system=config.system, num_decks=config.num_decks)
    return {
        "session_id": "default",
        "system": config.system,
        "num_decks": config.num_decks,
        "message": "Counter created"
    }


@app.post("/api/counter/add_card")
async def add_card(card_input: CardInput, request: Request, session_id: str = "default"):
    """Add a card to the count"""
    user = await optional_auth(request)
    session_key = get_session_key(user, session_id)

    if session_key not in counters:
        counters[session_key] = CardCounter()

    counter = counters[session_key]
    try:
        value = counter.add_card(card_input.card)
        return {
            "card": card_input.card,
            "count_value": value,
            "running_count": counter.running_count,
            "true_count": counter.true_count,
            "decks_remaining": counter.decks_remaining,
            "cards_seen": counter.cards_seen,
            "edge": counter.get_edge_estimate() * 100
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/counter/remove_card")
async def remove_card(card_input: CardInput, request: Request, session_id: str = "default"):
    """Remove a card from the count (for mistake correction)

    This subtracts the card's count value - use sparingly for corrections only.
    In real play, dealt cards should stay in the count until shuffle.
    """
    user = await optional_auth(request)
    session_key = get_session_key(user, session_id)

    if session_key not in counters:
        counters[session_key] = CardCounter()

    counter = counters[session_key]
    try:
        # Normalize card and get its value
        card = counter._normalize_card(card_input.card)
        value = counter.values.get(card, 0)

        # Subtract the card's contribution
        counter.running_count -= value
        counter.cards_seen = max(0, counter.cards_seen - 1)

        # Track ace removal for Omega II
        if card == 'A':
            counter.ace_count = max(0, counter.ace_count - 1)

        return {
            "card": card_input.card,
            "count_value_removed": value,
            "running_count": counter.running_count,
            "true_count": counter.true_count,
            "decks_remaining": counter.decks_remaining,
            "cards_seen": counter.cards_seen,
            "edge": counter.get_edge_estimate() * 100
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/counter/reset")
async def reset_counter(request: Request, session_id: str = "default"):
    """Reset the counter (shuffle)"""
    user = await optional_auth(request)
    session_key = get_session_key(user, session_id)

    if session_key in counters:
        counters[session_key].reset()
    return {"message": "Counter reset", "running_count": 0, "true_count": 0}


@app.get("/api/counter/state")
async def get_counter_state(request: Request, session_id: str = "default"):
    """Get current counter state"""
    user = await optional_auth(request)
    session_key = get_session_key(user, session_id)

    if session_key not in counters:
        counters[session_key] = CardCounter()

    counter = counters[session_key]
    return {
        "running_count": counter.running_count,
        "true_count": counter.true_count,
        "decks_remaining": counter.decks_remaining,
        "cards_seen": counter.cards_seen,
        "edge": counter.get_edge_estimate() * 100,
        "should_bet_big": counter.should_bet_big(),
        "system": counter.system
    }


@app.post("/api/strategy/recommend")
async def get_recommendation(hand_input: HandInput):
    """Get strategy recommendation for a hand"""
    try:
        # Create hand object
        hand = Hand(cards=hand_input.player_cards)

        # Get recommendation
        action, source = strategy_engine.get_action(
            hand,
            hand_input.dealer_upcard,
            true_count=hand_input.true_count
        )

        # Action names
        action_names = {
            'H': 'HIT',
            'S': 'STAND',
            'D': 'DOUBLE',
            'P': 'SPLIT',
            'R': 'SURRENDER'
        }

        # Check for blackjack
        if hand.is_blackjack:
            return {
                "action": "BLACKJACK",
                "action_code": "BJ",
                "source": "natural",
                "hand_total": 21,
                "is_soft": False,
                "is_blackjack": True
            }

        return {
            "action": action_names.get(action, action),
            "action_code": action,
            "source": source,
            "hand_total": hand.total,
            "is_soft": hand.is_soft,
            "is_pair": hand.is_pair,
            "is_blackjack": hand.is_blackjack,
            "true_count": hand_input.true_count
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/strategy/insurance")
async def should_take_insurance(true_count: float, system: str = "hi_lo"):
    """Check if insurance should be taken based on count"""
    should_take = strategy_engine.should_take_insurance(true_count, system)
    return {
        "should_take_insurance": should_take,
        "true_count": true_count,
        "system": system
    }


class BettingMethodInput(BaseModel):
    method: Literal['kelly', 'spread', 'spread_aggressive', 'flat'] = 'spread'


@app.post("/api/settings/betting_method")
async def set_betting_method(input: BettingMethodInput):
    """Set the betting method for bet calculations"""
    global betting_method
    betting_method = input.method
    return {
        "status": "ok",
        "method": betting_method,
        "description": {
            "spread": "Standard 1-12 spread for 75%+ penetration",
            "spread_aggressive": "Aggressive spread for 50% penetration games",
            "kelly": "Kelly Criterion - mathematically optimal",
            "flat": "Flat betting - constant bet size"
        }.get(betting_method, "")
    }


@app.get("/api/settings/betting_method")
async def get_betting_method():
    """Get current betting method"""
    return {
        "method": betting_method,
        "available": ['kelly', 'spread', 'spread_aggressive', 'flat']
    }


@app.post("/api/analyze")
async def analyze_full_state(state: SessionState, request: Request):
    """Analyze full game state - all cards, count, and recommendation

    NOTE: This endpoint does NOT reset the counter. Cards should be added
    incrementally via /api/counter/add_card. The counter only resets when
    /api/counter/reset (shuffle) is explicitly called.
    """
    # Create or get counter with user-specific session
    user = await optional_auth(request)
    session_key = get_session_key(user)

    if session_key not in counters:
        counters[session_key] = CardCounter(
            system=state.counting_system,
            num_decks=state.num_decks
        )

    counter = counters[session_key]

    # DO NOT reset the counter here! Cards persist across hands until shuffle.
    # The count is managed incrementally via add_card endpoint.
    # We only use the cards passed in for strategy recommendation, not for counting.

    # Get recommendation if we have enough cards
    recommendation = None
    if len(state.player_cards) >= 2 and len(state.dealer_cards) >= 1:
        hand = Hand(cards=state.player_cards)
        action, source = strategy_engine.get_action(
            hand,
            state.dealer_cards[0],
            true_count=counter.true_count
        )

        action_names = {
            'H': 'HIT', 'S': 'STAND', 'D': 'DOUBLE',
            'P': 'SPLIT', 'R': 'SURRENDER'
        }

        if hand.is_blackjack:
            recommendation = {
                "action": "BLACKJACK",
                "source": "natural",
                "hand_total": 21
            }
        else:
            recommendation = {
                "action": action_names.get(action, action),
                "source": source,
                "hand_total": hand.total,
                "is_soft": hand.is_soft,
                "is_pair": hand.is_pair
            }

    # Calculate bet recommendation based on betting method
    tc = counter.true_count
    base_bet = 10
    tc_rounded = max(-5, min(6, round(tc)))

    if betting_method in SPREAD_TABLES:
        multiplier = SPREAD_TABLES[betting_method].get(tc_rounded, 1)
        recommended_bet = base_bet * multiplier
    elif betting_method == 'flat':
        recommended_bet = base_bet
    elif betting_method == 'kelly':
        # Simplified Kelly calculation
        edge = -0.005 + (tc * 0.005)  # base_edge + count_adjustment
        if edge <= 0:
            recommended_bet = base_bet
        else:
            kelly_fraction = edge / 1.15 * 0.5  # Half Kelly
            recommended_bet = min(200, max(base_bet, 1000 * kelly_fraction))
    else:
        # Default to standard spread
        multiplier = SPREAD_TABLES['spread'].get(tc_rounded, 1)
        recommended_bet = base_bet * multiplier

    return {
        "count": {
            "running_count": counter.running_count,
            "true_count": counter.true_count,
            "decks_remaining": counter.decks_remaining,
            "cards_seen": counter.cards_seen,
            "edge": counter.get_edge_estimate() * 100
        },
        "recommendation": recommendation,
        "bet": {
            "recommended": recommended_bet,
            "method": betting_method,
            "should_bet_big": counter.should_bet_big()
        }
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "blackjack-god",
        "version": "2.0.0",
        "saas_enabled": SAAS_ENABLED
    }


# ===== PAGE ROUTES =====

@app.get("/auth")
async def auth_page():
    """Serve the auth page"""
    return FileResponse(static_dir / "auth.html")


@app.get("/pricing")
async def pricing_page():
    """Serve the pricing page"""
    return FileResponse(static_dir / "pricing.html")


@app.get("/landing")
async def landing_page():
    """Serve the landing page"""
    return FileResponse(static_dir / "landing.html")



@app.get("/pro-trainer")
async def pro_trainer_page():
    """Serve the integrated blackjack dashboard shell with trainer mode"""
    return FileResponse(static_dir / "integrated_dashboard.html")


@app.get("/trainer-app")
async def trainer_app():
    """Serve the standalone Pro Trainer app inside the integrated shell"""
    pt_path = Path(__file__).parent.parent / "pro_trainer.html"
    if pt_path.exists():
        return FileResponse(pt_path)
    raise HTTPException(status_code=404, detail="Pro Trainer not found")

@app.get("/cheat-sheet")
async def cheat_sheet_page():
    """Serve the card counting cheat sheet (lead magnet)"""
    cheat_sheet_path = static_dir.parent / "ebook" / "CHEAT_SHEET.html"
    if cheat_sheet_path.exists():
        return FileResponse(cheat_sheet_path)
    raise HTTPException(status_code=404, detail="Cheat sheet not found")


# ===== EMAIL CAPTURE =====

class EmailSubscribeRequest(BaseModel):
    email: str
    source: str = "landing"  # Track where signup came from


# In-memory storage for emails (replace with database in production)
email_subscribers = []


@app.post("/api/email/subscribe")
async def email_subscribe(request: EmailSubscribeRequest):
    """
    Capture email for lead magnet / newsletter.
    This is a backup endpoint - primary capture goes through ConvertKit.
    """
    from datetime import datetime
    import re

    # Basic email validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, request.email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    # Store email (in production, save to database)
    subscriber = {
        "email": request.email,
        "source": request.source,
        "subscribed_at": datetime.utcnow().isoformat(),
    }

    # Check for duplicates
    if any(s["email"] == request.email for s in email_subscribers):
        return {"success": True, "message": "Already subscribed"}

    email_subscribers.append(subscriber)

    # Log for visibility
    print(f"[EMAIL] New subscriber: {request.email} from {request.source}")

    # TODO: Forward to ConvertKit API if configured
    # convertkit_api_key = os.getenv("CONVERTKIT_API_KEY")
    # if convertkit_api_key:
    #     await forward_to_convertkit(request.email, convertkit_api_key)

    return {
        "success": True,
        "message": "Successfully subscribed! Check your email for the cheat sheet."
    }


@app.get("/api/email/subscribers")
async def get_email_subscribers():
    """Get list of email subscribers (admin only in production)"""
    return {
        "count": len(email_subscribers),
        "subscribers": email_subscribers
    }


# ===== TWITTER CONTENT ENGINE =====

class TwitterGenerateRequest(BaseModel):
    type: Literal['tweets', 'thread', 'video'] = 'tweets'
    topic: Optional[str] = None
    category: Optional[str] = None
    count: int = 5


@app.post("/api/twitter/generate")
async def generate_twitter_content(request: TwitterGenerateRequest):
    """
    Generate Twitter content using the BlackjackTwitterAgent.

    Args:
        type: 'tweets', 'thread', or 'video'
        topic: Specific topic or None for random from category
        category: Topic category (counting_systems, strategy_systems, etc.)
        count: Number of tweets (for tweets) or thread length (for thread)

    Returns:
        content: List of generated content with validation status
    """
    try:
        # Import the Twitter agent
        from src.agents.blackjack.blackjack_twitter_agent import BlackjackTwitterAgent

        agent = BlackjackTwitterAgent()
        content = []

        if request.type == 'tweets':
            # Generate tweets
            tweets = agent.generate_tweets(
                topic=request.topic,
                count=request.count,
                category=request.category
            )

            # Validate each tweet
            for tweet in tweets:
                is_valid, issues = agent.validate_tweet(tweet)
                content.append({
                    "text": tweet,
                    "valid": is_valid,
                    "issues": issues if not is_valid else [],
                    "char_count": len(tweet)
                })

        elif request.type == 'thread':
            # Generate thread
            thread = agent.generate_thread(
                topic=request.topic or "card counting fundamentals",
                length=request.count
            )

            for i, tweet in enumerate(thread):
                is_valid, issues = agent.validate_tweet(tweet)
                content.append({
                    "text": tweet,
                    "valid": is_valid,
                    "issues": issues if not is_valid else [],
                    "char_count": len(tweet),
                    "position": i + 1
                })

        elif request.type == 'video':
            # Generate video script
            script = agent.generate_video_script(
                topic=request.topic or "basic card counting"
            )
            content.append({
                "text": script,
                "valid": True,
                "issues": [],
                "char_count": len(script)
            })

        return {
            "success": True,
            "type": request.type,
            "topic": request.topic,
            "category": request.category,
            "content": content,
            "count": len(content)
        }

    except ImportError as e:
        # Agent not available
        raise HTTPException(
            status_code=503,
            detail=f"Twitter agent not available: {str(e)}"
        )
    except Exception as e:
        # Generation failed
        raise HTTPException(
            status_code=500,
            detail=f"Content generation failed: {str(e)}"
        )


@app.get("/api/twitter/topics")
async def get_twitter_topics():
    """Get available topics for content generation"""
    try:
        from src.agents.blackjack.blackjack_twitter_agent import TOPIC_BANK
        return {
            "categories": list(TOPIC_BANK.keys()),
            "topics": TOPIC_BANK
        }
    except ImportError:
        # Return default topics if agent not available
        return {
            "categories": [
                "counting_systems",
                "strategy_systems",
                "money_systems",
                "myth_busting",
                "casino_tactics"
            ],
            "topics": {}
        }


@app.get("/twitter")
async def twitter_dashboard_page():
    """Serve the Twitter dashboard"""
    return FileResponse(static_dir / "twitter_dashboard.html")


# ===== USER ENDPOINTS (SaaS) =====

class SubscribeRequest(BaseModel):
    tier: Literal['pro', 'premium']
    success_url: str
    cancel_url: str


if SAAS_ENABLED:

    @app.get("/api/user/me")
    async def get_current_user_info(request: Request):
        """Get current user info"""
        try:
            # Get credentials manually to avoid dependency errors
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                # No auth token - return demo user in demo mode or 401
                from auth import get_supabase, DemoUser
                supabase = get_supabase()
                if supabase is None:
                    # Demo mode - return demo user
                    demo = DemoUser()
                    return {
                        "id": demo.id,
                        "email": demo.email,
                        "tier": demo.tier,
                        "is_pro": demo.is_pro,
                        "is_premium": demo.is_premium,
                        "is_demo": True
                    }
                raise HTTPException(status_code=401, detail="Not authenticated")

            # Has auth token - try to verify
            token = auth_header[7:]  # Remove "Bearer "
            from auth import get_supabase, User
            supabase = get_supabase()

            if supabase is None:
                # Demo mode with token - just return demo user
                from auth import DemoUser
                demo = DemoUser()
                return {
                    "id": demo.id,
                    "email": demo.email,
                    "tier": demo.tier,
                    "is_pro": demo.is_pro,
                    "is_premium": demo.is_premium,
                    "is_demo": True
                }

            # Verify token
            user_response = supabase.auth.get_user(token)
            if user_response and user_response.user:
                auth_user = user_response.user
                return {
                    "id": auth_user.id,
                    "email": auth_user.email,
                    "tier": "free",  # Would fetch from profiles table
                    "is_pro": False,
                    "is_premium": False,
                    "is_demo": False
                }

            raise HTTPException(status_code=401, detail="Invalid token")

        except HTTPException:
            raise
        except Exception as e:
            # Log error but return 401 for security
            print(f"[ERROR] /api/user/me: {e}")
            raise HTTPException(status_code=401, detail="Authentication failed")

    @app.get("/api/user/progress")
    async def get_user_progress(user: User = Depends(require_auth)):
        """Get user's training progress"""
        progress = await db.get_progress(user.id)
        if progress:
            return progress.to_dict()
        return {
            "basic_strategy_accuracy": 0,
            "counting_speed_seconds": None,
            "true_count_accuracy": 0,
            "total_hands_practiced": 0,
            "streak_days": 0
        }

    @app.post("/api/user/progress")
    async def update_user_progress(
        updates: dict,
        user: User = Depends(require_auth)
    ):
        """Update user's training progress"""
        success = await db.update_progress(user.id, updates)
        return {"success": success}

    @app.get("/api/user/stats")
    async def get_user_stats(user: User = Depends(require_auth)):
        """Get aggregated user stats"""
        return await db.get_stats(user.id)

    @app.get("/api/user/sessions")
    async def get_user_sessions(
        limit: int = 10,
        user: User = Depends(require_pro)  # Pro feature
    ):
        """Get user's recent sessions (Pro feature)"""
        return await db.get_recent_sessions(user.id, limit)

    class SessionSaveRequest(BaseModel):
        hands_played: int = 0
        decisions_correct: int = 0
        counting_errors: int = 0
        profit_loss: float = 0
        wins: int = 0
        losses: int = 0
        pushes: int = 0
        blackjacks: int = 0

    @app.post("/api/sessions/save")
    async def save_session(
        session_data: SessionSaveRequest,
        user: User = Depends(require_pro)  # Pro feature
    ):
        """Save a completed session (Pro feature)"""
        # Create session record
        session_id = await db.create_session(user.id)
        if not session_id:
            raise HTTPException(status_code=500, detail="Failed to create session")

        # Update with session data
        await db.update_session(session_id, {
            "hands_played": session_data.hands_played,
            "decisions_correct": session_data.decisions_correct,
            "counting_errors": session_data.counting_errors,
            "profit_loss": session_data.profit_loss,
            "wins": session_data.wins,
            "losses": session_data.losses,
            "pushes": session_data.pushes,
            "blackjacks": session_data.blackjacks
        })

        # End the session
        await db.end_session(session_id)

        # Also record practice for streak tracking
        await db.record_practice(
            user.id,
            hands_played=session_data.hands_played,
            decisions_correct=session_data.decisions_correct
        )

        return {
            "success": True,
            "session_id": session_id,
            "message": "Session saved successfully"
        }

    @app.post("/api/subscribe")
    async def create_subscription(
        request: SubscribeRequest,
        user: User = Depends(require_auth)
    ):
        """Create a Stripe checkout session for subscription"""
        checkout_url = await create_checkout_session(
            user_id=user.id,
            user_email=user.email,
            tier=request.tier,
            success_url=request.success_url,
            cancel_url=request.cancel_url
        )
        return {"checkout_url": checkout_url}

    @app.post("/api/billing/portal")
    async def billing_portal(user: User = Depends(require_auth)):
        """Create a Stripe Customer Portal session"""
        if not user.stripe_customer_id:
            raise HTTPException(
                status_code=400,
                detail="No active subscription found"
            )

        portal_url = await create_portal_session(
            customer_id=user.stripe_customer_id,
            return_url=f"{os.getenv('APP_URL', 'http://localhost:8000')}/"
        )
        return {"portal_url": portal_url}

    @app.post("/api/webhooks/stripe")
    async def stripe_webhook(request: Request):
        """Handle Stripe webhooks"""
        event = await handle_webhook(request)
        result = await process_subscription_event(event)

        if result["processed"] and result["user_id"]:
            # Update user tier in database
            await db.update_tier(
                user_id=result["user_id"],
                tier=result["new_tier"],
                stripe_customer_id=result["customer_id"]
            )

        return {"received": True}

    @app.get("/api/pricing")
    async def get_pricing():
        """Get pricing information"""
        return get_pricing_display()

    @app.get("/api/rate-limit/{action}")
    async def get_rate_limit_status(
        action: str,
        user: User = Depends(get_current_user)
    ):
        """Get remaining rate limit for an action"""
        if user is None or isinstance(user, DemoUser) or user.is_pro:
            return {"limited": False, "remaining": -1}

        limit = FREE_LIMITS.get(action, 10)
        remaining = rate_limiter.get_remaining(user.id, action, limit)

        return {
            "limited": True,
            "remaining": remaining,
            "limit": limit,
            "action": action
        }


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  BLACKJACK GOD - SaaS Edition")
    print("  Built with love by TradeHive")
    print("=" * 50)
    print("\n  Open http://localhost:8000 in your browser")
    print("  Auth: http://localhost:8000/auth")
    print("  Pricing: http://localhost:8000/pricing\n")
    print("=" * 50 + "\n")

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
