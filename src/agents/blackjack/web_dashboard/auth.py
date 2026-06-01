"""
Supabase Authentication Module for Blackjack God SaaS
Handles user authentication, session management, and tier checking
Built with love by TradeHive
"""

import os
from functools import wraps
from typing import Optional, Dict, Any
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Initialize Supabase client lazily
_supabase_client = None
_supabase_admin = None

def get_supabase():
    """Get Supabase client for frontend operations"""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase import create_client, Client
            if SUPABASE_URL and SUPABASE_ANON_KEY:
                _supabase_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            else:
                print("[INFO] Supabase not configured - running in demo mode")
                return None
        except ImportError:
            print("[INFO] Supabase library not installed - pip install supabase")
            return None
    return _supabase_client

def get_supabase_admin():
    """Get Supabase admin client for server-side operations"""
    global _supabase_admin
    if _supabase_admin is None:
        try:
            from supabase import create_client, Client
            if SUPABASE_URL and SUPABASE_SERVICE_KEY:
                _supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            else:
                return None
        except ImportError:
            return None
    return _supabase_admin


# Security scheme
security = HTTPBearer(auto_error=False)


class User:
    """User model with tier information"""
    def __init__(self, id: str, email: str, tier: str = "free", **kwargs):
        self.id = id
        self.email = email
        self.tier = tier
        self.stripe_customer_id = kwargs.get("stripe_customer_id")
        self.created_at = kwargs.get("created_at")

    @property
    def is_pro(self) -> bool:
        return self.tier in ["pro", "premium"]

    @property
    def is_premium(self) -> bool:
        return self.tier == "premium"

    def can_access(self, feature: str) -> bool:
        """Check if user can access a feature based on tier"""
        feature_tiers = {
            # Free features
            "basic_strategy": ["free", "pro", "premium"],
            "hilo_counting": ["free", "pro", "premium"],  # Limited for free

            # Pro features
            "advisor_mode": ["pro", "premium"],
            "session_tracking": ["pro", "premium"],
            "deviations": ["pro", "premium"],
            "unlimited_practice": ["pro", "premium"],

            # Premium features
            "advanced_systems": ["premium"],
            "analytics": ["premium"],
            "all_features": ["premium"],
        }

        allowed_tiers = feature_tiers.get(feature, ["premium"])
        return self.tier in allowed_tiers


class DemoUser(User):
    """Demo user for when auth is not configured"""
    def __init__(self):
        super().__init__(
            id="demo-user",
            email="demo@blackjackgod.com",
            tier="premium"  # Full access in demo mode
        )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[User]:
    """
    Get current authenticated user from JWT token.
    Returns DemoUser if auth is not configured.
    """
    supabase = get_supabase()

    # Demo mode if Supabase not configured
    if supabase is None:
        return DemoUser()

    # No token provided
    if credentials is None:
        return None

    try:
        token = credentials.credentials

        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)

        if user_response and user_response.user:
            auth_user = user_response.user

            # Get user profile with tier info
            profile = supabase.table("profiles").select("*").eq(
                "id", auth_user.id
            ).single().execute()

            tier = "free"
            stripe_customer_id = None

            if profile.data:
                tier = profile.data.get("tier", "free")
                stripe_customer_id = profile.data.get("stripe_customer_id")

            return User(
                id=auth_user.id,
                email=auth_user.email,
                tier=tier,
                stripe_customer_id=stripe_customer_id,
                created_at=auth_user.created_at
            )
    except Exception as e:
        print(f"Auth error: {e}")
        return None

    return None


async def require_auth(
    user: Optional[User] = Depends(get_current_user)
) -> User:
    """Dependency that requires authentication"""
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user


async def require_pro(
    user: User = Depends(require_auth)
) -> User:
    """Dependency that requires Pro tier or higher"""
    if not user.is_pro:
        raise HTTPException(
            status_code=403,
            detail="Pro subscription required for this feature"
        )
    return user


async def require_premium(
    user: User = Depends(require_auth)
) -> User:
    """Dependency that requires Premium tier"""
    if not user.is_premium:
        raise HTTPException(
            status_code=403,
            detail="Premium subscription required for this feature"
        )
    return user


def check_feature(feature: str):
    """
    Decorator factory to check feature access.
    Usage: @check_feature("advisor_mode")
    """
    async def dependency(user: User = Depends(require_auth)) -> User:
        if not user.can_access(feature):
            raise HTTPException(
                status_code=403,
                detail=f"Your subscription does not include access to {feature}"
            )
        return user
    return dependency


# Rate limiting for free tier
class RateLimiter:
    """Simple in-memory rate limiter for free tier"""
    def __init__(self):
        self.counts: Dict[str, Dict[str, int]] = {}

    def check_limit(self, user_id: str, action: str, limit: int) -> bool:
        """Check if user is within rate limit for action"""
        import datetime
        today = datetime.date.today().isoformat()

        if user_id not in self.counts:
            self.counts[user_id] = {}

        key = f"{action}:{today}"
        current = self.counts[user_id].get(key, 0)

        if current >= limit:
            return False

        self.counts[user_id][key] = current + 1
        return True

    def get_remaining(self, user_id: str, action: str, limit: int) -> int:
        """Get remaining uses for today"""
        import datetime
        today = datetime.date.today().isoformat()

        if user_id not in self.counts:
            return limit

        key = f"{action}:{today}"
        current = self.counts[user_id].get(key, 0)
        return max(0, limit - current)


# Global rate limiter instance
rate_limiter = RateLimiter()

# Free tier limits
FREE_LIMITS = {
    "counting_practice": 10,  # 10 practice sessions per day
    "strategy_lookups": 50,   # 50 strategy lookups per day
}


async def check_rate_limit(
    action: str,
    user: User = Depends(get_current_user)
) -> bool:
    """Check rate limit for free tier users"""
    # Demo and paid users have no limits
    if user is None or isinstance(user, DemoUser) or user.is_pro:
        return True

    limit = FREE_LIMITS.get(action, 10)
    if not rate_limiter.check_limit(user.id, action, limit):
        remaining = rate_limiter.get_remaining(user.id, action, limit)
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"Daily limit reached for {action}",
                "limit": limit,
                "remaining": remaining,
                "upgrade_url": "/pricing"
            }
        )
    return True
