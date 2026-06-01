#!/usr/bin/env python3
"""
🎰 POKER GOD - LIVE ADVISOR MODE 🎰
Quick commands for real-time online play
Minimal keystrokes, maximum speed
Built with love by TradeHive
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime
import time

project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)


def _configure_console_output() -> None:
    """Force UTF-8 console output so live advisor symbols work on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_configure_console_output()

from src.agents.poker.core.hand_evaluator import Card, Rank, Suit, HandEvaluator, RANK_MAP, SUIT_MAP
from src.agents.poker.core.range_manager import Range
from src.agents.poker.core.odds_calculator import OddsCalculator
from src.agents.poker.core.equity_calculator import EquityCalculator
from src.agents.poker.core.board_analyzer import BoardAnalyzer
from src.agents.poker.strategy.preflop_engine import PreflopEngine, Position, FacingAction
from src.agents.poker.strategy.postflop_engine import PostflopEngine
from src.agents.poker.strategy.gto_engine import GTOEngine
from src.agents.poker.strategy.decision_engine import DecisionEngine
from src.agents.poker.core.poker_types import Street
from src.agents.poker.tournament.push_fold_engine import PushFoldEngine, Position as PFPos


class LiveAdvisor:
    """
    Live game advisor with quick commands
    
    QUICK COMMANDS:
    ───────────────
    n AhKs BTN     → New hand (cards + position)
    f Qh7c2d       → Set flop
    t 9s           → Add turn
    r 3c           → Add river
    
    a              → Get advice (preflop or postflop)
    a 3b           → Advice when facing 3-bet
    a vs CO        → Advice vs specific position
    
    e              → Quick equity vs default range
    e QQ+,AK       → Equity vs specific range
    
    o 50 100       → Pot odds (call 50 into 100)
    
    p 10           → Push/fold with 10bb
    
    v fish         → Set villain type (fish/tag/lag/nit/reg)
    
    s              → Session stats
    w 25           → Record win
    l 15           → Record loss
    
    q              → Quit
    """
    
    # Position shortcuts
    POS_MAP = {
        'u': Position.UTG, 'utg': Position.UTG,
        'm': Position.MP, 'mp': Position.MP,
        'h': Position.HJ, 'hj': Position.HJ,
        'c': Position.CO, 'co': Position.CO,
        'b': Position.BTN, 'btn': Position.BTN, 'bu': Position.BTN,
        's': Position.SB, 'sb': Position.SB,
        'd': Position.BB, 'bb': Position.BB,
    }
    
    # Villain range presets
    VILLAIN_RANGES = {
        'fish': "22+,A2s+,A5o+,K8s+,K9o+,Q9s+,QTo+,J9s+,JTo+,T9s,98s,87s,76s",
        'tag': "77+,A9s+,ATo+,KTs+,KQo,QTs+,JTs",
        'lag': "22+,A2s+,A7o+,K5s+,K9o+,Q8s+,QTo+,J8s+,JTo,T8s+,97s+,87s,76s,65s",
        'nit': "TT+,AQs+,AKo",
        'reg': "55+,A5s+,ATo+,KTs+,KQo,QTs+,JTs,T9s",
        'wide': "22+,A2s+,A2o+,K5s+,K9o+,Q8s+,QTo+,J9s+,T8s+,98s,87s,76s,65s,54s",
        'tight': "88+,AJs+,AQo+,KQs",
    }
    
    def __init__(self):
        # Engines
        self.evaluator = HandEvaluator()
        self.preflop = PreflopEngine()
        self.postflop = PostflopEngine()
        self.decision = DecisionEngine()
        self.odds = OddsCalculator()
        self.equity = EquityCalculator()
        self.board_analyzer = BoardAnalyzer()
        self.gto = GTOEngine()
        self.pushfold = PushFoldEngine()
        
        # State
        self.hole_cards = []
        self.board = []
        self.position = Position.BTN
        self.villain_range = Range.from_notation(self.VILLAIN_RANGES['reg'])
        self.villain_type = 'reg'
        self.pot = 1.5  # SB + BB
        self.effective_stack = 100.0  # Default 100bb
        self.facing = FacingAction.UNOPENED
        self.raiser_pos = None
        
        # Session tracking
        self.hands = 0
        self.wins = 0
        self.profit = 0.0
        self.hand_history = []
        self.session_start = time.time()

        # Persistence setup
        self.data_dir = Path(__file__).parent / "data" / "sessions"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def save_session(self) -> str:
        """Save session to JSON file"""
        if self.hands == 0:
            print("  ⚠️  No hands to save")
            return None

        filename = f"live_session_{self.session_id}.json"
        filepath = self.data_dir / filename

        data = {
            'session_id': self.session_id,
            'type': 'live_advisor',
            'start_time': datetime.fromtimestamp(self.session_start).isoformat(),
            'end_time': datetime.now().isoformat(),
            'duration_minutes': (time.time() - self.session_start) / 60,
            'stats': {
                'hands': self.hands,
                'wins': self.wins,
                'profit': self.profit,
                'win_rate': (self.wins / self.hands * 100) if self.hands > 0 else 0,
            },
            'hand_history': self.hand_history
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"  ✅ Session saved to {filename}")
        return str(filepath)

    def parse_cards(self, s: str) -> list:
        """Parse card string like 'AhKs' or 'Ah Ks' or 'ah ks' or 'A5s' (suit at end)"""
        s = s.replace(" ", "")
        cards = []
        i = 0

        # First try standard format: AhKs (rank+suit pairs)
        while i < len(s) - 1:
            rank_char = s[i].upper()
            suit_char = s[i+1].lower()

            if rank_char in RANK_MAP and suit_char in SUIT_MAP:
                cards.append(Card(RANK_MAP[rank_char], SUIT_MAP[suit_char]))
                i += 2
            else:
                i += 1

        # If we got 2 cards, we're good
        if len(cards) >= 2:
            return cards

        # Try shorthand format: A5s = both cards same suit, A5o = different suits
        cards = []
        s_clean = s.upper()
        if len(s_clean) >= 3 and s_clean[-1] in ['S', 'O']:
            suit_type = s_clean[-1]
            rank_chars = s_clean[:-1]

            if len(rank_chars) >= 2:
                r1 = rank_chars[0]
                r2 = rank_chars[1]

                if r1 in RANK_MAP and r2 in RANK_MAP:
                    if suit_type == 'S':
                        # Suited - both spades for simplicity
                        cards.append(Card(RANK_MAP[r1], Suit.SPADES))
                        cards.append(Card(RANK_MAP[r2], Suit.SPADES))
                    else:
                        # Offsuit
                        cards.append(Card(RANK_MAP[r1], Suit.SPADES))
                        cards.append(Card(RANK_MAP[r2], Suit.HEARTS))

        return cards
        
    def parse_position(self, s: str) -> Position:
        """Parse position string"""
        s = s.lower().strip()
        return self.POS_MAP.get(s, Position.BTN)
        
    def hand_notation(self, cards: list) -> str:
        """Get hand notation like 'AKs' or 'AKo'"""
        if len(cards) != 2:
            return "??"
        c1, c2 = cards
        if c2.rank > c1.rank:
            c1, c2 = c2, c1
        
        ranks = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}
        r1, r2 = ranks[c1.rank], ranks[c2.rank]
        
        if c1.rank == c2.rank:
            return f"{r1}{r2}"
        elif c1.suit == c2.suit:
            return f"{r1}{r2}s"
        else:
            return f"{r1}{r2}o"
            
    def print_state(self):
        """Print current game state"""
        if self.hole_cards:
            hand_str = " ".join(c.pretty() for c in self.hole_cards)
            print(f"  🃏 Hand: {hand_str} ({self.hand_notation(self.hole_cards)})")
        if self.board:
            board_str = " ".join(c.pretty() for c in self.board)
            street = ["", "", "", "FLOP", "TURN", "RIVER"][len(self.board)]
            print(f"  📋 {street}: {board_str}")
        print(f"  📍 Position: {self.position.name} | Villain: {self.villain_type}")
        
    def cmd_new(self, args: str):
        """n AhKs BTN - New hand"""
        parts = args.split()
        if len(parts) >= 1:
            self.hole_cards = self.parse_cards(parts[0])
        if len(parts) >= 2:
            self.position = self.parse_position(parts[1])
        
        self.board = []
        self.pot = 1.5  # SB + BB
        self.facing = FacingAction.UNOPENED
        self.raiser_pos = None
        self.hands += 1
        
        print(f"\n{'─'*50}")
        print(f"🆕 HAND #{self.hands}")
        self.print_state()
        
    def cmd_flop(self, args: str):
        """f Qh7c2d - Set flop"""
        cards = self.parse_cards(args)
        if len(cards) >= 3:
            self.board = cards[:3]
            board_str = " ".join(c.pretty() for c in self.board)
            
            # Analyze texture
            analysis = self.board_analyzer.analyze(self.board)
            print(f"\n  📋 FLOP: {board_str}")
            print(f"  Texture: {analysis.texture.value}")
            
            if self.hole_cards:
                result = self.evaluator.evaluate(self.hole_cards, self.board)
                print(f"  Your hand: {result.description}")
                
    def cmd_turn(self, args: str):
        """t 9s - Add turn"""
        cards = self.parse_cards(args)
        if cards and len(self.board) == 3:
            self.board.append(cards[0])
            board_str = " ".join(c.pretty() for c in self.board)
            print(f"\n  📋 TURN: {board_str}")
            
            if self.hole_cards:
                result = self.evaluator.evaluate(self.hole_cards, self.board)
                print(f"  Your hand: {result.description}")
                
    def cmd_river(self, args: str):
        """r 3c - Add river"""
        cards = self.parse_cards(args)
        if cards and len(self.board) == 4:
            self.board.append(cards[0])
            board_str = " ".join(c.pretty() for c in self.board)
            print(f"\n  📋 RIVER: {board_str}")
            
            if self.hole_cards:
                result = self.evaluator.evaluate(self.hole_cards, self.board)
                print(f"  Your hand: {result.description}")
                
    def cmd_advice(self, args: str = ""):
        """a - Get advice"""
        if not self.hole_cards:
            print("  ⚠️  Set hand first: n AhKs BTN")
            return
            
        # Parse facing action
        args_lower = args.lower()
        if '3b' in args_lower or '3bet' in args_lower:
            self.facing = FacingAction.THREE_BET
        elif '4b' in args_lower:
            self.facing = FacingAction.FOUR_BET
        elif 'vs' in args_lower:
            self.facing = FacingAction.RAISED
            for pos_key in self.POS_MAP:
                if pos_key in args_lower:
                    self.raiser_pos = self.POS_MAP[pos_key]
                    break
        elif 'limp' in args_lower:
            self.facing = FacingAction.LIMPED
            
        print()

        # Parse bet amount from args (for facing bet scenarios)
        bet_amount = 0.0
        if args:
            for token in args.split():
                try:
                    bet_amount = float(token)
                    break
                except ValueError:
                    continue

        # Determine street and position
        street_map = {0: Street.PREFLOP, 3: Street.FLOP, 4: Street.TURN, 5: Street.RIVER}
        current_street = street_map.get(len(self.board), Street.PREFLOP)

        # Better IP detection: IP if we act after villain
        villain_pos = self.raiser_pos
        if villain_pos:
            in_pos = self.position.value > villain_pos.value  # Higher seat = later position
        else:
            in_pos = self.position in [Position.BTN, Position.CO, Position.HJ]

        # Unified DecisionEngine call for ALL streets
        d = self.decision.get_decision(
            hole_cards=self.hole_cards,
            board=self.board,
            position=self.position or Position.BTN,
            pot=self.pot,
            bet_to_call=bet_amount,
            street=current_street,
            in_position=in_pos,
            villain_type=self.villain_type or 'reg',
            villain_position=villain_pos,
            effective_stack=self.effective_stack,
        )

        # === Unified Display ===
        self._display_decision(d, bet_amount)
            
    def _display_decision(self, d, bet_amount: float = 0):
        """Unified display for any Decision (preflop or postflop)."""
        from .strategy.decision_engine import Decision

        # Hand strength (postflop) or range strength (preflop)
        cat_icon = {'nuts': '🔥', 'very_strong': '💪', 'strong': '✅',
                    'medium': '⚠️', 'weak': '❌', 'draw': '🎯', 'trash': '🗑️',
                    'premium': '🔥', 'playable': '✅', 'marginal': '⚠️', 'n/a': ''}
        icon = cat_icon.get(d.hand_strength, '❓')

        if d.equity > 0:
            print(f"  {icon} {d.hand_strength.upper()} | Equity: {d.equity:.0%}")
        else:
            print(f"  {icon} {d.hand_strength.upper()}")

        # Action
        action_upper = d.action.upper()
        if action_upper in ('BET', 'RAISE', 'CHECK_RAISE', 'ALL_IN'):
            sizing_str = ""
            if d.sizing_fraction:
                sizing_str = f" ({d.sizing_fraction * 100:.0f}% pot)"
            elif d.sizing_bb:
                sizing_str = f" to {d.sizing_bb:.1f}bb"
            print(f"  🟢 {action_upper}{sizing_str}")
        elif action_upper in ('CHECK', 'CALL'):
            print(f"  🟡 {action_upper}")
        else:
            print(f"  🔴 {action_upper}")

        # Frequency
        if d.frequency < 0.95:
            print(f"  📊 Frequency: {d.frequency:.0%}")

        # Pot odds
        if d.pot_odds is not None:
            eq_emoji = "✅" if d.equity >= d.pot_odds else "❌"
            print(f"  🎲 Pot odds: need {d.pot_odds:.0%} | have {d.equity:.0%} {eq_emoji}")

        # Reasoning
        print(f"  💡 {d.reasoning}")

        # Alternative
        if d.alternative and d.alt_freq > 0.10:
            print(f"  ↩️  Alt: {d.alternative.upper()} ({d.alt_freq:.0%})")

        # Barrel plan
        if d.barrel_plan:
            print(f"  📋 {d.barrel_plan}")

        # Exploit note
        if d.exploit_note:
            print(f"  🎯 {d.exploit_note}")

        # Update pot if we decided to bet
        if bet_amount > 0 and action_upper in ('CALL',):
            self.pot += bet_amount * 2  # Our call + their bet
        elif d.sizing_bb and action_upper in ('BET', 'RAISE'):
            self.pot += d.sizing_bb

    def cmd_pot(self, args: str):
        """pot X - Set current pot size in BB"""
        try:
            self.pot = float(args.strip())
            print(f"  Pot set to {self.pot:.1f}bb")
        except ValueError:
            print(f"  Current pot: {self.pot:.1f}bb")

    def cmd_stack(self, args: str):
        """st X - Set effective stack in BB"""
        try:
            self.effective_stack = float(args.strip())
            print(f"  Effective stack set to {self.effective_stack:.0f}bb")
        except ValueError:
            print(f"  Current stack: {self.effective_stack:.0f}bb")

    def cmd_equity(self, args: str = ""):
        """e or e QQ+,AK - Calculate equity"""
        if not self.hole_cards:
            print("  ⚠️  Set hand first")
            return

        # Parse range or use default
        if args.strip():
            arg_lower = args.strip().lower()
            if arg_lower in self.VILLAIN_RANGES:
                villain_range = Range.from_notation(self.VILLAIN_RANGES[arg_lower])
            else:
                try:
                    villain_range = Range.from_notation(args.strip())
                except:
                    villain_range = self.villain_range
        else:
            villain_range = self.villain_range

        # Check if range is valid
        if villain_range.combo_count() == 0:
            print("  ⚠️  Empty range - using default")
            villain_range = self.villain_range

        try:
            result = self.equity.hand_vs_range(
                self.hole_cards,
                villain_range,
                self.board if self.board else [],
                iterations=5000
            )

            eq = result.equity * 100
            if eq >= 55:
                color = "🟢"
            elif eq >= 45:
                color = "🟡"
            else:
                color = "🔴"

            print(f"\n  {color} Equity: {eq:.1f}%")
            print(f"  Win: {result.win_rate*100:.1f}% | Tie: {result.tie_rate*100:.1f}%")
        except Exception as e:
            print(f"  ⚠️  Equity calculation error: {e}")
        
    def cmd_odds(self, args: str):
        """o 50 100 - Pot odds (call 50 into pot of 100)"""
        parts = args.split()
        if len(parts) >= 2:
            try:
                call = float(parts[0])
                pot = float(parts[1])
                
                result = self.odds.pot_odds(call, pot)
                
                print(f"\n  📊 Pot: ${pot:.0f} | Call: ${call:.0f}")
                print(f"  Pot Odds: {result.pot_odds*100:.1f}%")
                print(f"  Need {result.break_even_equity*100:.1f}% equity to call")
                
                # If we have cards, calculate if we should call
                if self.hole_cards:
                    eq = self.equity.hand_vs_range(
                        self.hole_cards, self.villain_range,
                        self.board if self.board else [],
                        iterations=3000
                    )
                    
                    if eq.equity >= result.break_even_equity:
                        print(f"  🟢 CALL - You have {eq.equity*100:.1f}% equity")
                    else:
                        print(f"  🔴 FOLD - You have {eq.equity*100:.1f}% equity")
            except:
                print("  ⚠️  Usage: o [call] [pot]")
                
    def cmd_push(self, args: str):
        """p 10 - Push/fold with X bb"""
        try:
            bb = float(args) if args else 10
            
            if not self.hole_cards:
                print("  ⚠️  Set hand first")
                return
                
            hand_str = self.hand_notation(self.hole_cards)
            
            # Map position
            pos_map = {
                Position.UTG: PFPos.UTG,
                Position.MP: PFPos.MP,
                Position.HJ: PFPos.HJ,
                Position.CO: PFPos.CO,
                Position.BTN: PFPos.BTN,
                Position.SB: PFPos.SB,
                Position.BB: PFPos.BTN,
            }
            pf_pos = pos_map.get(self.position, PFPos.BTN)
            
            decision = self.pushfold.should_push(hand_str, bb, pf_pos)
            
            print(f"\n  📊 {hand_str} with {bb:.0f}bb from {self.position.name}")
            if decision.action == "push":
                print(f"  🟢 PUSH!")
            else:
                print(f"  🔴 FOLD")
            print(f"  💡 {decision.reasoning}")
            
        except:
            print("  ⚠️  Usage: p [bb_count]")
            
    def cmd_villain(self, args: str):
        """v fish - Set villain type"""
        v_type = args.strip().lower()
        if v_type in self.VILLAIN_RANGES:
            self.villain_type = v_type
            self.villain_range = Range.from_notation(self.VILLAIN_RANGES[v_type])
            print(f"  👤 Villain: {v_type.upper()}")
        else:
            print(f"  Types: fish, tag, lag, nit, reg, wide, tight")
            
    def cmd_win(self, args: str):
        """w 25 - Record win"""
        try:
            amount = float(args) if args else 0
            self.wins += 1
            self.profit += amount
            self.hand_history.append({
                'hole_cards': " ".join(c.pretty() for c in self.hole_cards) if self.hole_cards else "",
                'board': " ".join(c.pretty() for c in self.board) if self.board else "",
                'position': self.position.value if self.position else "",
                'won': True,
                'amount': amount,
                'timestamp': datetime.now().isoformat()
            })
            print(f"  ✅ Win recorded: +${amount:.2f}")
        except:
            self.wins += 1
            print(f"  ✅ Win recorded")

    def cmd_loss(self, args: str):
        """l 15 - Record loss"""
        try:
            amount = float(args) if args else 0
            self.profit -= amount
            self.hand_history.append({
                'hole_cards': " ".join(c.pretty() for c in self.hole_cards) if self.hole_cards else "",
                'board': " ".join(c.pretty() for c in self.board) if self.board else "",
                'position': self.position.value if self.position else "",
                'won': False,
                'amount': amount,
                'timestamp': datetime.now().isoformat()
            })
            print(f"  ❌ Loss recorded: -${amount:.2f}")
        except:
            print(f"  ❌ Loss recorded")
            
    def cmd_stats(self, args: str = ""):
        """s - Show session stats"""
        wr = (self.wins / self.hands * 100) if self.hands > 0 else 0
        print(f"\n  📊 SESSION STATS")
        print(f"  ─────────────────")
        print(f"  Hands:  {self.hands}")
        print(f"  Wins:   {self.wins} ({wr:.0f}%)")
        color = "🟢" if self.profit >= 0 else "🔴"
        print(f"  P&L:    {color} ${self.profit:+.2f}")
        
    def cmd_swarm(self, args: str = ""):
        """sw - Get 3-AI consensus advice"""
        if not self.hole_cards:
            print("  Deal a hand first (n AhKs BTN)")
            return

        try:
            from .swarm_advisor import PokerSwarmAdvisor
        except ImportError:
            print("  Swarm advisor not available")
            return

        if not hasattr(self, '_swarm') or self._swarm is None:
            self._swarm = PokerSwarmAdvisor()

        board_str = " ".join(str(c) for c in self.board) if self.board else ""
        pos_str = self.position.name if self.position else "BTN"

        self._swarm.analyze_hand(
            hole_cards=" ".join(str(c) for c in self.hole_cards),
            board=board_str,
            position=pos_str,
            pot=0,  # TODO: track pot in live advisor
            to_call=0,
            villain_action=args if args else "",
            stack=100,
        )

    def cmd_help(self, args: str = ""):
        """h - Show help"""
        print("""
  🎰 QUICK COMMANDS
  ─────────────────
  n AhKs BTN    New hand (cards + position)
  f Qh7c2d      Set flop
  t 9s          Add turn
  r 3c          Add river
  
  a             Get advice (first to act)
  a bet 8       Advice facing 8bb bet
  a raise 25    Advice facing raise to 25bb
  a 3b          Advice vs 3-bet (preflop)
  
  e             Equity vs default range
  e QQ+,AK      Equity vs range
  e fish        Equity vs player type
  
  o 50 100      Pot odds (call/pot)
  p 10          Push/fold with 10bb
  
  v fish        Set villain (fish/tag/lag/nit/reg)
  
  pot 35        Set pot size (in BB)
  st 80         Set effective stack (in BB)
  sw            Swarm advice (3 AI advisors)

  w 25          Record win +$25
  l 15          Record loss -$15
  s             Session stats
  save          Save session now

  h             This help
  q             Quit (auto-saves)
        """)
        
    def run(self):
        """Main loop"""
        print("\n" + "="*50)
        print("  🎰 POKER GOD - LIVE ADVISOR 🎰")
        print("  Type 'h' for commands")
        print("="*50)
        
        while True:
            try:
                cmd = input("\n🎯 ").strip()
                
                if not cmd:
                    continue
                    
                # Parse command
                parts = cmd.split(maxsplit=1)
                action = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                
                # Route commands
                if action in ['q', 'quit', 'exit']:
                    self.cmd_stats()
                    self.save_session()
                    print("\n  👋 Good luck at the tables!")
                    break
                elif action == 'save':
                    self.save_session()
                elif action in ['n', 'new']:
                    self.cmd_new(args)
                elif action in ['f', 'flop']:
                    self.cmd_flop(args)
                elif action in ['t', 'turn']:
                    self.cmd_turn(args)
                elif action in ['r', 'river']:
                    self.cmd_river(args)
                elif action in ['a', 'advice', '?']:
                    self.cmd_advice(args)
                elif action in ['e', 'eq', 'equity']:
                    self.cmd_equity(args)
                elif action in ['o', 'odds']:
                    self.cmd_odds(args)
                elif action in ['p', 'push', 'pf']:
                    self.cmd_push(args)
                elif action in ['v', 'villain']:
                    self.cmd_villain(args)
                elif action in ['w', 'win']:
                    self.cmd_win(args)
                elif action in ['l', 'loss', 'lose']:
                    self.cmd_loss(args)
                elif action in ['sw', 'swarm']:
                    self.cmd_swarm(args)
                elif action in ['pot']:
                    self.cmd_pot(args)
                elif action in ['st', 'stack']:
                    self.cmd_stack(args)
                elif action in ['s', 'stats']:
                    self.cmd_stats()
                elif action in ['h', 'help', 'commands']:
                    self.cmd_help()
                elif action in ['c', 'clear']:
                    os.system('cls' if os.name == 'nt' else 'clear')
                else:
                    # Try to parse as quick hand entry
                    if len(action) >= 4 and any(c in action.upper() for c in 'HSDC'):
                        # Looks like card notation
                        self.cmd_new(cmd)
                    else:
                        print(f"  ⚠️  Unknown command. Type 'h' for help.")
                        
            except KeyboardInterrupt:
                print("\n")
                self.cmd_stats()
                self.save_session()
                print("\n  👋 Good luck!")
                break
            except Exception as e:
                print(f"  ⚠️  Error: {e}")


def main():
    advisor = LiveAdvisor()
    advisor.run()


if __name__ == "__main__":
    main()
