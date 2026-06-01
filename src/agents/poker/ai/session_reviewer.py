"""
📝 Session Reviewer - AI-Powered Session Analysis
Deep analysis of poker sessions with LLM commentary
Built with love by TradeHive
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path


@dataclass
class HandRecord:
    """Record of a single hand"""
    hand_id: int
    hole_cards: str
    board: str
    position: str
    action_sequence: List[str]
    pot_size: float
    result: str  # 'won', 'lost', 'folded'
    amount: float
    villain_type: str = ""
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "hand_id": self.hand_id,
            "hole_cards": self.hole_cards,
            "board": self.board,
            "position": self.position,
            "actions": self.action_sequence,
            "pot": self.pot_size,
            "result": self.result,
            "amount": self.amount,
            "villain": self.villain_type,
            "notes": self.notes
        }

    def summary(self) -> str:
        """One-line summary"""
        return f"#{self.hand_id}: {self.hole_cards} {self.position} | {self.board or 'preflop'} | {self.result} ${self.amount:+.1f}"


@dataclass
class SessionRecord:
    """Complete session record"""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    game_type: str = "NLHE"
    stakes: str = "1/2"
    hands: List[HandRecord] = field(default_factory=list)

    # Aggregate stats
    total_hands: int = 0
    total_winnings: float = 0
    vpip_count: int = 0
    pfr_count: int = 0
    three_bet_count: int = 0
    showdown_count: int = 0
    showdown_wins: int = 0

    def add_hand(self, hand: HandRecord):
        """Add a hand to the session"""
        self.hands.append(hand)
        self.total_hands += 1
        self.total_winnings += hand.amount

        # Update stats (simplified)
        if hand.result != "folded":
            self.vpip_count += 1

    @property
    def win_rate(self) -> float:
        """BB/100 win rate"""
        if self.total_hands == 0:
            return 0
        bb = 2  # Big blind (assume 1/2)
        return (self.total_winnings / bb) / self.total_hands * 100

    @property
    def vpip(self) -> float:
        """VPIP percentage"""
        return self.vpip_count / self.total_hands * 100 if self.total_hands > 0 else 0

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "game_type": self.game_type,
            "stakes": self.stakes,
            "stats": {
                "total_hands": self.total_hands,
                "total_winnings": self.total_winnings,
                "win_rate_bb100": self.win_rate,
                "vpip": self.vpip,
            },
            "hands": [h.to_dict() for h in self.hands]
        }


class SessionReviewer:
    """
    📝 AI-Powered Session Reviewer

    Features:
    - Track hands during live play
    - AI analysis of key decision points
    - Leak detection from patterns
    - Session summaries with improvement points
    - Hand export for further study
    """

    def __init__(self, ai_brain=None):
        """
        Initialize reviewer

        Args:
            ai_brain: AIBrain instance for LLM analysis
        """
        self.ai_brain = ai_brain
        self.current_session: Optional[SessionRecord] = None
        self.data_dir = Path(__file__).parent.parent / "data" / "sessions"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def start_session(self, game_type: str = "NLHE", stakes: str = "1/2") -> SessionRecord:
        """Start a new session"""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_session = SessionRecord(
            session_id=session_id,
            start_time=datetime.now(),
            game_type=game_type,
            stakes=stakes
        )
        return self.current_session

    def record_hand(self,
                    hole_cards: str,
                    board: str,
                    position: str,
                    actions: List[str],
                    pot_size: float,
                    result: str,
                    amount: float,
                    villain_type: str = "",
                    notes: str = "") -> HandRecord:
        """Record a hand to current session"""
        if not self.current_session:
            self.start_session()

        hand = HandRecord(
            hand_id=self.current_session.total_hands + 1,
            hole_cards=hole_cards,
            board=board,
            position=position,
            action_sequence=actions,
            pot_size=pot_size,
            result=result,
            amount=amount,
            villain_type=villain_type,
            notes=notes
        )

        self.current_session.add_hand(hand)
        return hand

    def end_session(self) -> SessionRecord:
        """End current session"""
        if self.current_session:
            self.current_session.end_time = datetime.now()
            self._save_session()
        return self.current_session

    def _save_session(self):
        """Save session to file"""
        if not self.current_session:
            return

        filepath = self.data_dir / f"session_{self.current_session.session_id}.json"
        with open(filepath, 'w') as f:
            json.dump(self.current_session.to_dict(), f, indent=2)

    def get_session_summary(self) -> str:
        """Get text summary of current session"""
        if not self.current_session:
            return "No active session"

        s = self.current_session
        duration = (datetime.now() - s.start_time).seconds / 60

        summary = f"""
📊 SESSION SUMMARY
==================
Duration: {duration:.0f} minutes
Hands: {s.total_hands}
Net Result: ${s.total_winnings:+.2f}
Win Rate: {s.win_rate:+.1f} BB/100

Key Stats:
- VPIP: {s.vpip:.1f}%
- Showdowns: {s.showdown_count}
- Showdown Win%: {s.showdown_wins/s.showdown_count*100:.0f}% if s.showdown_count > 0 else "N/A"

Notable Hands:
"""
        # Add top 5 biggest pots
        sorted_hands = sorted(s.hands, key=lambda h: abs(h.amount), reverse=True)[:5]
        for h in sorted_hands:
            summary += f"  {h.summary()}\n"

        return summary

    def get_ai_review(self) -> str:
        """Get AI-powered review of session"""
        if not self.ai_brain:
            return "AI Brain not available. Initialize SessionReviewer with AIBrain instance."

        if not self.current_session or self.current_session.total_hands == 0:
            return "No hands to review"

        # Get AI review
        response = self.ai_brain.review_session(
            hands=[h.to_dict() for h in self.current_session.hands[-20:]],  # Last 20 hands
            stats={
                "total_hands": self.current_session.total_hands,
                "win_rate": self.current_session.win_rate,
                "vpip": self.current_session.vpip,
                "net_result": self.current_session.total_winnings
            }
        )

        if response.success:
            return response.content
        else:
            return f"AI review failed: {response.error}"

    def analyze_hand(self, hand_id: int) -> str:
        """Get AI analysis of specific hand"""
        if not self.ai_brain:
            return "AI Brain not available"

        if not self.current_session:
            return "No active session"

        # Find hand
        hand = None
        for h in self.current_session.hands:
            if h.hand_id == hand_id:
                hand = h
                break

        if not hand:
            return f"Hand #{hand_id} not found"

        # Build hand history text
        hh = f"""
Hand #{hand.hand_id}
Hole Cards: {hand.hole_cards}
Position: {hand.position}
Board: {hand.board}
Actions: {' -> '.join(hand.actions)}
Pot: ${hand.pot_size}
Result: {hand.result} ${hand.amount:+.2f}
Villain: {hand.villain_type or 'Unknown'}
Notes: {hand.notes or 'None'}
"""

        response = self.ai_brain.analyze_hand(hh)

        if response.success:
            return response.content
        else:
            return f"Analysis failed: {response.error}"

    def find_leaks(self) -> str:
        """Analyze session for common leaks"""
        if not self.current_session or self.current_session.total_hands < 10:
            return "Need at least 10 hands to detect patterns"

        leaks = []
        s = self.current_session

        # Check VPIP
        if s.vpip > 35:
            leaks.append(f"⚠️ HIGH VPIP ({s.vpip:.0f}%): Playing too many hands. Tighten up preflop.")
        elif s.vpip < 18:
            leaks.append(f"⚠️ LOW VPIP ({s.vpip:.0f}%): Playing too tight. Missing value opportunities.")

        # Check showdown stats
        if s.showdown_count > 0:
            sd_win = s.showdown_wins / s.showdown_count
            if sd_win < 0.45:
                leaks.append(f"⚠️ LOW SHOWDOWN WIN ({sd_win*100:.0f}%): Possibly overvaluing hands or calling too light.")

        # Check for tilt pattern (multiple big losses in a row)
        losses_in_row = 0
        max_losses_in_row = 0
        for h in s.hands:
            if h.amount < -5:  # Significant loss
                losses_in_row += 1
                max_losses_in_row = max(max_losses_in_row, losses_in_row)
            else:
                losses_in_row = 0

        if max_losses_in_row >= 4:
            leaks.append(f"⚠️ POSSIBLE TILT: {max_losses_in_row} big losses in a row detected. Take a break if tilted.")

        # Check position profitability
        position_results = {}
        for h in s.hands:
            if h.position not in position_results:
                position_results[h.position] = []
            position_results[h.position].append(h.amount)

        for pos, amounts in position_results.items():
            avg = sum(amounts) / len(amounts)
            if pos in ["BTN", "CO"] and avg < 0:
                leaks.append(f"⚠️ LOSING IN POSITION ({pos}): Should be profitable from late position.")

        if not leaks:
            return "✅ No major leaks detected! Keep up the solid play."

        return "LEAK ANALYSIS\n" + "\n".join(leaks)

    def export_hands(self, filepath: str = None) -> str:
        """Export hands to file for external analysis"""
        if not self.current_session:
            return "No session to export"

        if not filepath:
            filepath = self.data_dir / f"export_{self.current_session.session_id}.txt"

        with open(filepath, 'w') as f:
            for hand in self.current_session.hands:
                f.write(f"--- Hand #{hand.hand_id} ---\n")
                f.write(f"Cards: {hand.hole_cards} | Board: {hand.board}\n")
                f.write(f"Position: {hand.position} | Pot: ${hand.pot_size}\n")
                f.write(f"Actions: {' -> '.join(hand.action_sequence)}\n")
                f.write(f"Result: {hand.result} ${hand.amount:+.2f}\n")
                f.write("\n")

        return f"Exported {len(self.current_session.hands)} hands to {filepath}"


# === Quick Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n📝 Testing Session Reviewer...\n", "cyan", attrs=["bold"])

    reviewer = SessionReviewer()

    # Start session
    reviewer.start_session("NLHE", "1/2")

    # Record some hands
    reviewer.record_hand(
        hole_cards="AhKh",
        board="Qh Jc 2d Th",
        position="BTN",
        actions=["raise 6", "call", "bet 12", "call", "check", "bet 35", "call"],
        pot_size=82,
        result="won",
        amount=82,
        notes="Nut flush on turn"
    )

    reviewer.record_hand(
        hole_cards="9d9c",
        board="Kc 8s 2h 7d 4c",
        position="CO",
        actions=["raise 6", "call", "cbet 8", "fold"],
        pot_size=20,
        result="folded",
        amount=-6,
        notes="Gave up on cbet"
    )

    reviewer.record_hand(
        hole_cards="QsJd",
        board="Qc 7h 3s Kd 2s",
        position="MP",
        actions=["raise 6", "call", "bet 8", "call", "check", "check", "bet 20", "call"],
        pot_size=56,
        result="lost",
        amount=-34,
        notes="Lost to AQ"
    )

    # Get summary
    cprint(reviewer.get_session_summary(), "white")

    # Find leaks
    cprint("\n" + reviewer.find_leaks(), "yellow")

    # End session
    reviewer.end_session()
    cprint("\n✅ Session saved!", "green")
