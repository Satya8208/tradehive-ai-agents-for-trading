"""
Database Module for Blackjack God SaaS
Handles user profiles, progress tracking, and session history with Supabase
Built with love by TradeHive
"""

import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Import auth module for Supabase client (try both import styles)
try:
    from .auth import get_supabase_admin, get_supabase
except ImportError:
    from auth import get_supabase_admin, get_supabase


class UserProfile:
    """User profile data"""
    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id")
        self.email = data.get("email")
        self.tier = data.get("tier", "free")
        self.stripe_customer_id = data.get("stripe_customer_id")
        self.created_at = data.get("created_at")


class TrainingProgress:
    """Training progress data"""
    def __init__(self, data: Dict[str, Any]):
        self.user_id = data.get("user_id")
        self.basic_strategy_accuracy = data.get("basic_strategy_accuracy", 0)
        self.counting_speed_seconds = data.get("counting_speed_seconds")
        self.true_count_accuracy = data.get("true_count_accuracy", 0)
        self.total_hands_practiced = data.get("total_hands_practiced", 0)
        self.streak_days = data.get("streak_days", 0)
        self.last_practice = data.get("last_practice")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "basic_strategy_accuracy": self.basic_strategy_accuracy,
            "counting_speed_seconds": self.counting_speed_seconds,
            "true_count_accuracy": self.true_count_accuracy,
            "total_hands_practiced": self.total_hands_practiced,
            "streak_days": self.streak_days,
            "last_practice": self.last_practice
        }


class Database:
    """Database operations for Blackjack God SaaS"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_admin() or get_supabase()
        return self._client

    # ===== User Profiles =====

    async def create_profile(self, user_id: str, email: str) -> Optional[UserProfile]:
        """Create a new user profile"""
        if not self.client:
            return None

        try:
            result = self.client.table("profiles").insert({
                "id": user_id,
                "email": email,
                "tier": "free",
                "created_at": datetime.utcnow().isoformat()
            }).execute()

            if result.data:
                return UserProfile(result.data[0])
        except Exception as e:
            print(f"Create profile error: {e}")
        return None

    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile by ID"""
        if not self.client:
            return None

        try:
            result = self.client.table("profiles").select("*").eq(
                "id", user_id
            ).single().execute()

            if result.data:
                return UserProfile(result.data)
        except Exception as e:
            print(f"Get profile error: {e}")
        return None

    async def update_tier(
        self,
        user_id: str,
        tier: str,
        stripe_customer_id: Optional[str] = None
    ) -> bool:
        """Update user subscription tier"""
        if not self.client:
            return False

        try:
            update_data = {"tier": tier}
            if stripe_customer_id:
                update_data["stripe_customer_id"] = stripe_customer_id

            self.client.table("profiles").update(update_data).eq(
                "id", user_id
            ).execute()
            return True
        except Exception as e:
            print(f"Update tier error: {e}")
        return False

    # ===== Training Progress =====

    async def get_progress(self, user_id: str) -> Optional[TrainingProgress]:
        """Get user's training progress"""
        if not self.client:
            return None

        try:
            result = self.client.table("training_progress").select("*").eq(
                "user_id", user_id
            ).single().execute()

            if result.data:
                return TrainingProgress(result.data)
        except Exception as e:
            # No progress yet - return empty
            pass

        return TrainingProgress({"user_id": user_id})

    async def update_progress(
        self,
        user_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update training progress"""
        if not self.client:
            return False

        try:
            # Check if exists
            existing = self.client.table("training_progress").select("id").eq(
                "user_id", user_id
            ).execute()

            updates["updated_at"] = datetime.utcnow().isoformat()

            if existing.data:
                # Update existing
                self.client.table("training_progress").update(updates).eq(
                    "user_id", user_id
                ).execute()
            else:
                # Insert new
                updates["user_id"] = user_id
                self.client.table("training_progress").insert(updates).execute()

            return True
        except Exception as e:
            print(f"Update progress error: {e}")
        return False

    async def record_practice(
        self,
        user_id: str,
        hands_played: int = 1,
        decisions_correct: int = 0,
        counting_errors: int = 0
    ) -> bool:
        """Record a practice session and update streak"""
        if not self.client:
            return False

        try:
            progress = await self.get_progress(user_id)

            # Calculate streak
            streak = progress.streak_days if progress else 0
            last_practice = progress.last_practice if progress else None

            today = datetime.utcnow().date()
            if last_practice:
                last_date = datetime.fromisoformat(last_practice).date()
                if last_date == today:
                    # Same day, don't increment streak
                    pass
                elif last_date == today - timedelta(days=1):
                    # Yesterday, increment streak
                    streak += 1
                else:
                    # Streak broken
                    streak = 1
            else:
                streak = 1

            # Update totals
            total_hands = (progress.total_hands_practiced if progress else 0) + hands_played

            await self.update_progress(user_id, {
                "total_hands_practiced": total_hands,
                "streak_days": streak,
                "last_practice": datetime.utcnow().isoformat()
            })

            return True
        except Exception as e:
            print(f"Record practice error: {e}")
        return False

    # ===== Session History =====

    async def create_session(self, user_id: str) -> Optional[str]:
        """Create a new game session, return session ID"""
        if not self.client:
            return None

        try:
            import uuid
            session_id = str(uuid.uuid4())

            self.client.table("sessions").insert({
                "id": session_id,
                "user_id": user_id,
                "started_at": datetime.utcnow().isoformat(),
                "hands_played": 0,
                "decisions_correct": 0,
                "counting_errors": 0,
                "profit_loss": 0
            }).execute()

            return session_id
        except Exception as e:
            print(f"Create session error: {e}")
        return None

    async def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update session data"""
        if not self.client:
            return False

        try:
            self.client.table("sessions").update(updates).eq(
                "id", session_id
            ).execute()
            return True
        except Exception as e:
            print(f"Update session error: {e}")
        return False

    async def end_session(self, session_id: str) -> bool:
        """End a game session"""
        return await self.update_session(session_id, {
            "ended_at": datetime.utcnow().isoformat()
        })

    async def get_recent_sessions(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get user's recent sessions"""
        if not self.client:
            return []

        try:
            result = self.client.table("sessions").select("*").eq(
                "user_id", user_id
            ).order("started_at", desc=True).limit(limit).execute()

            return result.data or []
        except Exception as e:
            print(f"Get sessions error: {e}")
        return []

    async def get_stats(self, user_id: str) -> Dict[str, Any]:
        """Get aggregated stats for user"""
        sessions = await self.get_recent_sessions(user_id, limit=100)
        progress = await self.get_progress(user_id)

        total_hands = sum(s.get("hands_played", 0) for s in sessions)
        total_correct = sum(s.get("decisions_correct", 0) for s in sessions)
        total_pnl = sum(s.get("profit_loss", 0) for s in sessions)

        return {
            "total_sessions": len(sessions),
            "total_hands": total_hands,
            "accuracy": (total_correct / total_hands * 100) if total_hands > 0 else 0,
            "total_pnl": total_pnl,
            "streak_days": progress.streak_days if progress else 0,
            "basic_strategy_accuracy": progress.basic_strategy_accuracy if progress else 0,
            "counting_speed": progress.counting_speed_seconds if progress else None
        }


# Global database instance
db = Database()
