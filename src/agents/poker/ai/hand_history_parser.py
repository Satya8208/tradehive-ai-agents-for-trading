"""
📜 Hand History Parser
Parses hand histories from PokerStars, GGPoker, and other major sites
Built with love by TradeHive
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import datetime


class PokerSite(Enum):
    """Supported poker sites"""
    POKERSTARS = "pokerstars"
    GGPOKER = "ggpoker"
    PARTYPOKER = "partypoker"
    IGNITION = "ignition"
    ACR = "acr"
    GENERIC = "generic"


class ActionType(Enum):
    """Action types"""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"
    POST_BLIND = "post"
    SHOW = "show"
    MUCK = "muck"


class Street(Enum):
    """Betting streets"""
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


@dataclass
class ParsedAction:
    """A single parsed action"""
    player: str
    action_type: ActionType
    amount: float = 0.0
    is_all_in: bool = False

    def __str__(self):
        if self.amount > 0:
            return f"{self.player} {self.action_type.value} ${self.amount:.2f}"
        return f"{self.player} {self.action_type.value}"


@dataclass
class ParsedHand:
    """A fully parsed hand"""
    hand_id: str
    site: PokerSite
    game_type: str = "NLHE"
    stakes: str = ""
    table_name: str = ""
    timestamp: Optional[datetime] = None

    # Seats
    players: Dict[str, float] = field(default_factory=dict)  # name -> stack
    button_seat: int = 0
    hero: str = ""
    hero_cards: str = ""

    # Board
    flop: str = ""
    turn: str = ""
    river: str = ""

    # Actions by street
    preflop_actions: List[ParsedAction] = field(default_factory=list)
    flop_actions: List[ParsedAction] = field(default_factory=list)
    turn_actions: List[ParsedAction] = field(default_factory=list)
    river_actions: List[ParsedAction] = field(default_factory=list)

    # Results
    pot_size: float = 0.0
    rake: float = 0.0
    winners: Dict[str, float] = field(default_factory=dict)
    shown_hands: Dict[str, str] = field(default_factory=dict)

    @property
    def board(self) -> str:
        """Get full board"""
        parts = []
        if self.flop:
            parts.append(self.flop)
        if self.turn:
            parts.append(self.turn)
        if self.river:
            parts.append(self.river)
        return " ".join(parts)

    @property
    def hero_won(self) -> bool:
        """Did hero win?"""
        return self.hero in self.winners

    @property
    def hero_profit(self) -> float:
        """Hero's profit/loss"""
        if not self.hero:
            return 0

        # Calculate amount invested
        invested = 0
        for actions in [self.preflop_actions, self.flop_actions,
                       self.turn_actions, self.river_actions]:
            for action in actions:
                if action.player == self.hero and action.amount > 0:
                    invested += action.amount

        won = self.winners.get(self.hero, 0)
        return won - invested

    def summary(self) -> str:
        """One-line summary"""
        result = "WON" if self.hero_won else "LOST"
        return f"#{self.hand_id}: {self.hero_cards} | {self.board} | {result} ${self.hero_profit:+.2f}"

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "hand_id": self.hand_id,
            "site": self.site.value,
            "hero": self.hero,
            "hero_cards": self.hero_cards,
            "board": self.board,
            "pot": self.pot_size,
            "hero_profit": self.hero_profit,
            "won": self.hero_won,
            "shown_hands": self.shown_hands
        }


class HandHistoryParser:
    """
    📜 Universal Hand History Parser

    Supports:
    - PokerStars format
    - GGPoker format
    - Generic formats

    Features:
    - Extract player stats from HH
    - Parse actions by street
    - Identify hero and results
    - Bulk import sessions
    """

    # Site detection patterns
    SITE_PATTERNS = {
        PokerSite.POKERSTARS: r"PokerStars (Hand|Game|Zoom)",
        PokerSite.GGPOKER: r"Poker Hand #|GGPoker",
        PokerSite.PARTYPOKER: r"PartyPoker|Party Poker",
        PokerSite.ACR: r"Americas Cardroom|Winning Poker Network",
    }

    def __init__(self):
        self.hands_parsed = 0
        self.errors = []

    def detect_site(self, text: str) -> PokerSite:
        """Detect which poker site the HH is from"""
        for site, pattern in self.SITE_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return site
        return PokerSite.GENERIC

    def parse(self, text: str) -> ParsedHand:
        """
        Parse a single hand history

        Args:
            text: Raw hand history text

        Returns:
            ParsedHand object
        """
        site = self.detect_site(text)

        if site == PokerSite.POKERSTARS:
            return self._parse_pokerstars(text)
        elif site == PokerSite.GGPOKER:
            return self._parse_ggpoker(text)
        else:
            return self._parse_generic(text)

    def parse_file(self, filepath: str) -> List[ParsedHand]:
        """Parse all hands from a file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        return self.parse_session(content)

    def parse_session(self, text: str) -> List[ParsedHand]:
        """Parse multiple hands from text"""
        hands = []

        # Split by hand boundaries
        site = self.detect_site(text)

        if site == PokerSite.POKERSTARS:
            hand_texts = re.split(r'\n\n(?=PokerStars )', text)
        elif site == PokerSite.GGPOKER:
            hand_texts = re.split(r'\n\n(?=Poker Hand #)', text)
        else:
            hand_texts = re.split(r'\n\n+', text)

        for hand_text in hand_texts:
            hand_text = hand_text.strip()
            if len(hand_text) < 50:
                continue
            try:
                parsed = self.parse(hand_text)
                if parsed.hand_id:
                    hands.append(parsed)
                    self.hands_parsed += 1
            except Exception as e:
                self.errors.append(str(e))

        return hands

    def _parse_pokerstars(self, text: str) -> ParsedHand:
        """Parse PokerStars format"""
        hand = ParsedHand(hand_id="", site=PokerSite.POKERSTARS)

        lines = text.split('\n')
        current_street = Street.PREFLOP

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Hand ID and stakes
            match = re.match(r"PokerStars (?:Zoom )?Hand #(\d+)", line)
            if match:
                hand.hand_id = match.group(1)
                # Extract stakes
                stakes_match = re.search(r'\$?([\d.]+)/\$?([\d.]+)', line)
                if stakes_match:
                    hand.stakes = f"{stakes_match.group(1)}/{stakes_match.group(2)}"
                continue

            # Table name
            match = re.match(r"Table '(.+?)'", line)
            if match:
                hand.table_name = match.group(1)
                continue

            # Seat info
            match = re.match(r"Seat (\d+): (.+?) \(\$?([\d.]+)", line)
            if match:
                seat, player, stack = match.groups()
                hand.players[player] = float(stack)
                continue

            # Button
            match = re.search(r"Seat #(\d+) is the button", line)
            if match:
                hand.button_seat = int(match.group(1))
                continue

            # Hero's cards
            match = re.match(r"Dealt to (.+?) \[(.+?)\]", line)
            if match:
                hand.hero = match.group(1)
                hand.hero_cards = match.group(2)
                continue

            # Street changes
            if line.startswith("*** FLOP ***"):
                current_street = Street.FLOP
                match = re.search(r'\[(.+?)\]', line)
                if match:
                    hand.flop = match.group(1)
                continue
            elif line.startswith("*** TURN ***"):
                current_street = Street.TURN
                match = re.search(r'\] \[(.+?)\]', line)
                if match:
                    hand.turn = match.group(1)
                continue
            elif line.startswith("*** RIVER ***"):
                current_street = Street.RIVER
                match = re.search(r'\] \[(.+?)\]', line)
                if match:
                    hand.river = match.group(1)
                continue
            elif line.startswith("*** SHOW DOWN ***"):
                current_street = Street.SHOWDOWN
                continue

            # Actions
            action = self._parse_action_line(line)
            if action:
                if current_street == Street.PREFLOP:
                    hand.preflop_actions.append(action)
                elif current_street == Street.FLOP:
                    hand.flop_actions.append(action)
                elif current_street == Street.TURN:
                    hand.turn_actions.append(action)
                elif current_street == Street.RIVER:
                    hand.river_actions.append(action)

            # Pot and winner
            match = re.match(r"Total pot \$?([\d.]+)", line)
            if match:
                hand.pot_size = float(match.group(1))
                continue

            match = re.match(r"(.+?) collected \$?([\d.]+)", line)
            if match:
                winner, amount = match.groups()
                hand.winners[winner] = float(amount)
                continue

            # Shown hands
            match = re.match(r"(.+?): shows \[(.+?)\]", line)
            if match:
                player, cards = match.groups()
                hand.shown_hands[player] = cards

        return hand

    def _parse_ggpoker(self, text: str) -> ParsedHand:
        """Parse GGPoker format"""
        hand = ParsedHand(hand_id="", site=PokerSite.GGPOKER)

        lines = text.split('\n')
        current_street = Street.PREFLOP

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Hand ID
            match = re.match(r"Poker Hand #(\w+)", line)
            if match:
                hand.hand_id = match.group(1)
                stakes_match = re.search(r'\$?([\d.]+)/\$?([\d.]+)', line)
                if stakes_match:
                    hand.stakes = f"{stakes_match.group(1)}/{stakes_match.group(2)}"
                continue

            # Seat info
            match = re.match(r"Seat (\d+): (.+?) \(\$?([\d.,]+)", line)
            if match:
                seat, player, stack = match.groups()
                hand.players[player] = float(stack.replace(',', ''))
                continue

            # Hero cards
            match = re.match(r"Dealt to (.+?) \[(.+?)\]", line)
            if match:
                hand.hero = match.group(1)
                hand.hero_cards = match.group(2)
                continue

            # Streets
            if "FLOP" in line and "[" in line:
                current_street = Street.FLOP
                match = re.search(r'\[(.+?)\]', line)
                if match:
                    hand.flop = match.group(1)
            elif "TURN" in line and "[" in line:
                current_street = Street.TURN
                match = re.findall(r'\[(.+?)\]', line)
                if len(match) >= 2:
                    hand.turn = match[-1]
            elif "RIVER" in line and "[" in line:
                current_street = Street.RIVER
                match = re.findall(r'\[(.+?)\]', line)
                if len(match) >= 2:
                    hand.river = match[-1]

            # Actions
            action = self._parse_action_line(line)
            if action:
                if current_street == Street.PREFLOP:
                    hand.preflop_actions.append(action)
                elif current_street == Street.FLOP:
                    hand.flop_actions.append(action)
                elif current_street == Street.TURN:
                    hand.turn_actions.append(action)
                elif current_street == Street.RIVER:
                    hand.river_actions.append(action)

            # Winner
            match = re.search(r"(.+?) collected \$?([\d.,]+)", line)
            if match and "collected" in line:
                winner, amount = match.groups()
                hand.winners[winner.strip()] = float(amount.replace(',', ''))

        return hand

    def _parse_generic(self, text: str) -> ParsedHand:
        """Parse generic/unknown format"""
        hand = ParsedHand(hand_id="", site=PokerSite.GENERIC)

        # Try to extract basic info
        match = re.search(r"#?(\d+)", text[:100])
        if match:
            hand.hand_id = match.group(1)

        # Look for dealt cards
        match = re.search(r"Dealt.+?\[(.+?)\]", text)
        if match:
            hand.hero_cards = match.group(1)

        # Look for board
        match = re.search(r"Board:?\s*\[(.+?)\]", text)
        if match:
            board = match.group(1).split()
            if len(board) >= 3:
                hand.flop = " ".join(board[:3])
            if len(board) >= 4:
                hand.turn = board[3]
            if len(board) >= 5:
                hand.river = board[4]

        return hand

    def _parse_action_line(self, line: str) -> Optional[ParsedAction]:
        """Parse a single action line"""
        # Fold
        match = re.match(r"(.+?): folds", line, re.IGNORECASE)
        if match:
            return ParsedAction(player=match.group(1), action_type=ActionType.FOLD)

        # Check
        match = re.match(r"(.+?): checks", line, re.IGNORECASE)
        if match:
            return ParsedAction(player=match.group(1), action_type=ActionType.CHECK)

        # Call
        match = re.match(r"(.+?): calls \$?([\d.]+)", line, re.IGNORECASE)
        if match:
            return ParsedAction(
                player=match.group(1),
                action_type=ActionType.CALL,
                amount=float(match.group(2)),
                is_all_in="all-in" in line.lower()
            )

        # Bet
        match = re.match(r"(.+?): bets \$?([\d.]+)", line, re.IGNORECASE)
        if match:
            return ParsedAction(
                player=match.group(1),
                action_type=ActionType.BET,
                amount=float(match.group(2)),
                is_all_in="all-in" in line.lower()
            )

        # Raise
        match = re.match(r"(.+?): raises .+? to \$?([\d.]+)", line, re.IGNORECASE)
        if match:
            return ParsedAction(
                player=match.group(1),
                action_type=ActionType.RAISE,
                amount=float(match.group(2)),
                is_all_in="all-in" in line.lower()
            )

        # Post blinds
        match = re.match(r"(.+?): posts (?:small |big )?blind \$?([\d.]+)", line, re.IGNORECASE)
        if match:
            return ParsedAction(
                player=match.group(1),
                action_type=ActionType.POST_BLIND,
                amount=float(match.group(2))
            )

        return None

    def extract_player_stats(self, hands: List[ParsedHand], player: str) -> Dict:
        """
        Extract stats for a player from hand histories

        Args:
            hands: List of parsed hands
            player: Player name to analyze
        """
        total_hands = 0
        vpip_count = 0
        pfr_count = 0
        three_bet_count = 0
        three_bet_opportunities = 0
        cbet_flop_count = 0
        cbet_flop_opportunities = 0
        showdowns = 0
        showdown_wins = 0

        for hand in hands:
            if player not in hand.players:
                continue

            total_hands += 1

            # Check if player voluntarily put money in pot
            for action in hand.preflop_actions:
                if action.player == player:
                    if action.action_type in [ActionType.CALL, ActionType.RAISE, ActionType.BET]:
                        vpip_count += 1
                        break

            # Check for PFR
            for action in hand.preflop_actions:
                if action.player == player and action.action_type == ActionType.RAISE:
                    pfr_count += 1
                    break

            # Check for showdown
            if player in hand.shown_hands or player in hand.winners:
                showdowns += 1
                if player in hand.winners:
                    showdown_wins += 1

        if total_hands == 0:
            return {"error": "No hands found for player"}

        return {
            "player": player,
            "hands": total_hands,
            "vpip": vpip_count / total_hands * 100,
            "pfr": pfr_count / total_hands * 100,
            "wtsd": showdowns / total_hands * 100 if total_hands > 0 else 0,
            "w$sd": showdown_wins / showdowns * 100 if showdowns > 0 else 0
        }

    def get_stats(self) -> Dict:
        """Get parser stats"""
        return {
            "hands_parsed": self.hands_parsed,
            "errors": len(self.errors)
        }


# === Quick Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n📜 Testing Hand History Parser...\n", "cyan", attrs=["bold"])

    # Sample PokerStars hand
    sample_hh = """
PokerStars Hand #123456789: Hold'em No Limit ($0.50/$1.00 USD) - 2024/01/01 12:00:00 ET
Table 'Test Table' 6-max Seat #5 is the button
Seat 1: Player1 ($100.00 in chips)
Seat 2: Player2 ($95.50 in chips)
Seat 3: Hero ($105.25 in chips)
Seat 4: Player4 ($98.00 in chips)
Seat 5: Player5 ($102.00 in chips)
Player1: posts small blind $0.50
Player2: posts big blind $1.00
*** HOLE CARDS ***
Dealt to Hero [Ah Kh]
Hero: raises $2.50 to $3.50
Player4: folds
Player5: calls $3.50
Player1: folds
Player2: calls $2.50
*** FLOP *** [Ks 7c 2d]
Player2: checks
Hero: bets $5.00
Player5: folds
Player2: calls $5.00
*** TURN *** [Ks 7c 2d] [Qh]
Player2: checks
Hero: bets $12.00
Player2: folds
Uncalled bet ($12.00) returned to Hero
Hero collected $17.50 from pot
*** SUMMARY ***
Total pot $18.00 | Rake $0.50
    """

    parser = HandHistoryParser()

    # Parse the hand
    hand = parser.parse(sample_hh)

    cprint(f"Parsed hand: {hand.summary()}", "green")
    print(f"  Site: {hand.site.value}")
    print(f"  Stakes: {hand.stakes}")
    print(f"  Hero: {hand.hero} with {hand.hero_cards}")
    print(f"  Board: {hand.board}")
    print(f"  Pot: ${hand.pot_size:.2f}")
    print(f"  Preflop actions: {len(hand.preflop_actions)}")
    print(f"  Flop actions: {len(hand.flop_actions)}")

    cprint(f"\n📊 Parser stats: {parser.get_stats()}", "cyan")
