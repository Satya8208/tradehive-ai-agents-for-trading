"""
🎰 POKER GOD AGENT 🎰
The Ultimate Poker Master - GTO + Exploitative Play
Texas Hold'em & Omaha | Cash Games & Tournaments
Built with love by TradeHive
"""

import sys
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum
from datetime import datetime
import time

project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)


def _configure_console_output() -> None:
    """Force UTF-8 console output so card suits and emojis don't crash on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_configure_console_output()

# Core imports
from src.agents.poker.core.hand_evaluator import HandEvaluator, Card, Rank, Suit, HandResult, RANK_NAMES
from src.agents.poker.core.range_manager import Range, RangeManager
from src.agents.poker.core.odds_calculator import OddsCalculator
from src.agents.poker.core.equity_calculator import EquityCalculator
from src.agents.poker.core.board_analyzer import BoardAnalyzer, BoardAnalyzer
from src.agents.poker.core.poker_types import Position, Street, GameMode, GameFormat, Variant, PostflopAction
from src.agents.poker.core.game_context import GameContext, HandState, SessionStats, TournamentState

# Strategy imports
from src.agents.poker.strategy.preflop_engine import PreflopEngine, FacingAction, PreflopDecision
from src.agents.poker.strategy.postflop_engine import PostflopEngine, PostflopDecision
from src.agents.poker.strategy.gto_engine import GTOEngine
from src.agents.poker.strategy.decision_engine import DecisionEngine
from src.agents.poker.strategy.exploitative_engine import ExploitativeEngine, PlayerStats, PlayerTendency

# Tournament imports
from src.agents.poker.tournament.icm_calculator import ICMCalculator
from src.agents.poker.tournament.stack_analyzer import StackAnalyzer, StackZone, TournamentPhase
from src.agents.poker.tournament.push_fold_engine import PushFoldEngine

# AI imports (God Mode)
try:
    from src.agents.poker.ai.ai_brain import AIBrain, AIModel, AIResponse
    from src.agents.poker.ai.solver_lite import SolverLite, BoardTexture as SolverBoardTexture, HandStrength
    from src.agents.poker.ai.session_reviewer import SessionReviewer
    from src.agents.poker.ai.population_db import PopulationDatabase, StakeLevel, PlayerPool
    from src.agents.poker.ai.dynamic_range import DynamicRangeEngine, TableDynamic, GameContext as RangeGameContext
    from src.agents.poker.ai.hand_history_parser import HandHistoryParser
    from src.agents.poker.ai.neural_evaluator import NeuralHandEvaluator
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


class PokerAgent:
    """
    🎰 THE POKER GOD 🎰

    Your ultimate poker advisor combining:
    - GTO (Game Theory Optimal) foundations
    - Exploitative adjustments
    - Real-time equity calculations
    - Range analysis
    - ICM awareness for tournaments

    Modes:
    - ADVISOR: Get real-time recommendations
    - TRAINING: Practice and improve
    - SIMULATION: Full poker simulation
    """

    WISDOM = [
        "Fold and live to fight another day.",
        "Position is power. Use it wisely.",
        "Every chip you save is a chip earned.",
        "The cards don't know who's winning.",
        "Patience is not passive—it's selective aggression.",
        "A bet tells a story. Make sure yours is believable.",
        "The best bluff is the one that doesn't feel like one.",
        "In poker, the money flows from the impatient to the patient.",
    ]

    def __init__(self, mode: GameMode = GameMode.ADVISOR,
                 game_format: GameFormat = GameFormat.CASH,
                 variant: Variant = Variant.HOLDEM,
                 starting_stack: float = 100.0):
        """
        Initialize the Poker God

        Args:
            mode: ADVISOR, TRAINING, or SIMULATION
            game_format: CASH or TOURNAMENT
            variant: HOLDEM or OMAHA
            starting_stack: Starting stack in BB (cash) or chips (tournament)
        """
        self.mode = mode
        self.game_format = game_format
        self.variant = variant
        self.starting_stack = starting_stack

        # Initialize engines
        self.hand_evaluator = HandEvaluator()
        self.range_manager = RangeManager()
        self.odds_calc = OddsCalculator()
        self.equity_calc = EquityCalculator()
        self.board_analyzer = BoardAnalyzer()
        self.preflop_engine = PreflopEngine()
        self.postflop_engine = PostflopEngine()
        self.gto_engine = GTOEngine()
        self.decision_engine = DecisionEngine()
        self.exploit_engine = ExploitativeEngine()
        self.icm_calc = ICMCalculator()
        self.stack_analyzer = StackAnalyzer()
        self.push_fold = PushFoldEngine()

        # State (Unified Context)
        self.context = GameContext(
            mode=mode,
            game_format=game_format,
            variant=variant,
            starting_stack=starting_stack
        )
        if game_format == GameFormat.TOURNAMENT:
            self.context.tournament_state = TournamentState()

        # Aliases for backward compatibility
        self.hand_state = self.context.hand_state
        self.session_stats = self.context.session_stats
        self.tournament_state = self.context.tournament_state
        self.opponent_profiles = self.context.opponents

        # Session tracking
        self.session_start = time.time()
        self.hand_history: List[Dict] = []

        # Persistence setup
        self.data_dir = Path(__file__).parent / "data" / "sessions"
        self.opponents_dir = Path(__file__).parent / "data" / "opponents"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.opponents_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Load persistent data
        self._load_opponents()

        # AI Brain (God Mode) - lazy initialization
        self.ai_brain: Optional[AIBrain] = None
        self.solver_lite: Optional[SolverLite] = None
        self.session_reviewer: Optional[SessionReviewer] = None
        self.population_db = None
        self.range_engine = None
        self.hh_parser = None
        self.neural_eval = None
        self._ai_initialized = False

    def _init_ai(self, verbose: bool = False):
        """Initialize AI components (lazy load)"""
        if self._ai_initialized or not AI_AVAILABLE:
            return

        try:
            # Tier 1: Core AI
            self.ai_brain = AIBrain(verbose=verbose)
            self.solver_lite = SolverLite()
            self.session_reviewer = SessionReviewer(ai_brain=self.ai_brain)

            # Tier 2: Advanced
            self.population_db = PopulationDatabase()
            self.range_engine = DynamicRangeEngine()
            self.hh_parser = HandHistoryParser()

            # Tier 3: God Mode
            self.neural_eval = NeuralHandEvaluator()

            self._ai_initialized = True
            if verbose:
                self.speak("🧠 AI Brain initialized - GOD MODE ACTIVE!", "success")
        except Exception as e:
            self.speak(f"⚠️ AI initialization failed: {e}", "warning")

    def _load_opponents(self):
        """Load opponent profiles from disk"""
        try:
            count = 0
            for f in self.opponents_dir.glob("*.json"):
                try:
                    with open(f, 'r') as fp:
                        data = json.load(fp)
                        # Reconstruct basic stats if needed, or store dict
                        # Ideally convert back to PlayerStats
                        self.context.opponents[f.stem] = data
                        count += 1
                except:
                    continue
            if count > 0:
                self.speak(f"Loaded {count} opponent profiles", "normal")
        except Exception as e:
            self.speak(f"Error loading opponents: {e}", "warning")

    def _save_opponent(self, name: str, stats: Any):
        """Save single opponent"""
        try:
            path = self.opponents_dir / f"{name}.json"
            # Handle dataclass or dict
            if hasattr(stats, '__dataclass_fields__'):
                from dataclasses import asdict
                data = asdict(stats)
            # Handle Enum in dict (if stats is dict containing enums)
            elif isinstance(stats, dict):
                data = stats
            else:
                data = str(stats) # Fallback
            
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            self.speak(f"Error saving opponent {name}: {e}", "warning")

    def speak(self, message: str, style: str = "normal"):
        """The Poker God speaks with authority"""
        styles = {
            "normal": "",
            "wisdom": "🎯 ",
            "warning": "⚠️  ",
            "success": "✅ ",
            "action": "🎰 ",
            "fold": "🃏 ",
            "value": "💰 ",
            "bluff": "🎭 ",
        }
        prefix = styles.get(style, "")
        text = f"{prefix}{message}"
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", errors="replace").decode("ascii"))

    def new_hand(self, hole_cards: List[Card] = None, position: Position = None):
        """Start a new hand"""
        self.context.hand_state = HandState()
        self.hand_state = self.context.hand_state
        
        if hole_cards:
            self.hand_state.hole_cards = hole_cards
        if position:
            self.hand_state.position = position
        self.hand_state.street = Street.PREFLOP
        self.session_stats.hands_played += 1

    def set_hole_cards(self, cards: List[Card]):
        """Set hero's hole cards"""
        self.hand_state.hole_cards = cards

    def set_board(self, cards: List[Card]):
        """Set board cards"""
        self.hand_state.board = cards
        if len(cards) == 3:
            self.hand_state.street = Street.FLOP
        elif len(cards) == 4:
            self.hand_state.street = Street.TURN
        elif len(cards) == 5:
            self.hand_state.street = Street.RIVER

    def set_position(self, position: Position):
        """Set hero's position"""
        self.hand_state.position = position

    def set_pot(self, pot_size: float, bet_to_call: float = 0):
        """Set pot size and bet facing"""
        self.hand_state.pot_size = pot_size
        self.hand_state.bet_to_call = bet_to_call

    def set_villain_range(self, notation: str):
        """Set villain's estimated range"""
        self.hand_state.villain_range = Range.from_notation(notation)

    def get_preflop_advice(self, facing: FacingAction = FacingAction.UNOPENED,
                           raiser_position: Position = None) -> PreflopDecision:
        """Get preflop recommendation"""
        if not self.hand_state.hole_cards:
            self.speak("No hole cards set!", "warning")
            return None

        decision = self.preflop_engine.get_decision(
            self.hand_state.hole_cards,
            self.hand_state.position,
            facing,
            raiser_position
        )

        # Add personality
        hand_str = self._cards_to_str(self.hand_state.hole_cards)

        if decision.action.value == "raise":
            self.speak(f"RAISE with {hand_str} from {self.hand_state.position.name}", "action")
            self.speak(f"  → Open to {decision.sizing}bb", "value")
        elif decision.action.value == "3bet":
            self.speak(f"3-BET with {hand_str}!", "action")
            self.speak(f"  → Size to {decision.sizing:.1f}bb", "value")
        elif decision.action.value == "call":
            self.speak(f"CALL with {hand_str}", "action")
        else:
            self.speak(f"FOLD {hand_str} - outside our range", "fold")

        self.speak(f"  {decision.reasoning}", "wisdom")

        return decision

    def get_postflop_advice(self, in_position: bool = True) -> Dict:
        """Get postflop recommendation"""
        if not self.hand_state.hole_cards or not self.hand_state.board:
            self.speak("Need hole cards and board!", "warning")
            return None

        # Analyze hand strength
        hand_cat, hand_result = self.postflop_engine.analyze_hand_strength(
            self.hand_state.hole_cards,
            self.hand_state.board
        )

        # Analyze board
        board_analysis = self.board_analyzer.analyze(self.hand_state.board)

        street_map = {
            3: Street.FLOP,
            4: Street.TURN,
            5: Street.RIVER,
        }
        decision = self.decision_engine.get_decision(
            hole_cards=self.hand_state.hole_cards,
            board=self.hand_state.board,
            position=self.hand_state.position,
            pot=self.hand_state.pot_size,
            bet_to_call=self.hand_state.bet_to_call,
            street=street_map.get(len(self.hand_state.board), Street.PREFLOP),
            in_position=in_position,
            villain_type="reg",
            effective_stack=self.hand_state.effective_stack,
        )

        # Calculate equity if we have villain range
        equity_info = None
        if self.hand_state.villain_range:
            eq_result = self.equity_calc.hand_vs_range(
                self.hand_state.hole_cards,
                self.hand_state.villain_range,
                self.hand_state.board,
                iterations=5000
            )
            equity_info = {
                'equity': eq_result.equity,
                'win_rate': eq_result.win_rate,
                'tie_rate': eq_result.tie_rate
            }

        # Speak the advice
        hand_str = self._cards_to_str(self.hand_state.hole_cards)
        board_str = " ".join(c.pretty() for c in self.hand_state.board)

        self.speak(f"\n{hand_str} on {board_str}", "normal")
        self.speak(f"Hand: {hand_result.description} ({hand_cat.value})", "normal")
        self.speak(f"Board: {board_analysis.texture.value} texture", "normal")

        if board_analysis.draws:
            draws = [d.draw_type.value for d in board_analysis.draws[:3]]
            self.speak(f"Draws: {', '.join(draws)}", "normal")

        if equity_info:
            self.speak(f"Equity vs range: {equity_info['equity']*100:.1f}%", "value")

        # Action recommendation
        action_style = "value" if decision.action in ["bet", "raise", "check_raise", "all_in"] else "normal"
        if decision.action == "fold":
            action_style = "fold"

        self.speak(f"\n→ {decision.action.upper()}", action_style)
        if decision.sizing_fraction:
            self.speak(f"  Size: {decision.sizing_fraction*100:.0f}% pot", "normal")
        self.speak(f"  {decision.reasoning}", "wisdom")

        return {
            'decision': decision,
            'hand_category': hand_cat,
            'hand_result': hand_result,
            'board_analysis': board_analysis,
            'equity': equity_info
        }

    def get_equity(self, villain_range_str: str = None, iterations: int = 5000) -> Dict:
        """Calculate equity vs a range"""
        if not self.hand_state.hole_cards:
            return {'error': 'No hole cards set'}

        if villain_range_str:
            villain_range = Range.from_notation(villain_range_str)
        elif self.hand_state.villain_range:
            villain_range = self.hand_state.villain_range
        else:
            # Default to top 20%
            villain_range = self.range_manager.get_preset('co_open')

        result = self.equity_calc.hand_vs_range(
            self.hand_state.hole_cards,
            villain_range,
            self.hand_state.board or [],
            iterations=iterations
        )

        hand_str = self._cards_to_str(self.hand_state.hole_cards)
        self.speak(f"\n{hand_str} vs range:", "normal")
        self.speak(f"  Equity: {result.equity*100:.1f}%", "value")
        self.speak(f"  Win: {result.win_rate*100:.1f}% | Tie: {result.tie_rate*100:.1f}%", "normal")
        self.speak(f"  ({result.simulations} simulations, {result.time_ms}ms)", "normal")

        return {
            'equity': result.equity,
            'win_rate': result.win_rate,
            'tie_rate': result.tie_rate,
            'loss_rate': result.loss_rate
        }

    def get_pot_odds(self) -> Dict:
        """Calculate pot odds for current situation"""
        if self.hand_state.bet_to_call <= 0:
            return {'error': 'No bet to call'}

        result = self.odds_calc.pot_odds(
            self.hand_state.bet_to_call,
            self.hand_state.pot_size
        )

        self.speak(f"\nPot Odds Analysis:", "normal")
        self.speak(f"  Pot: ${self.hand_state.pot_size:.0f} | Call: ${self.hand_state.bet_to_call:.0f}", "normal")
        self.speak(f"  Pot Odds: {result.pot_odds*100:.1f}% ({result.pot_odds_ratio})", "value")
        self.speak(f"  {result.description}", "wisdom")

        return {
            'pot_odds': result.pot_odds,
            'ratio': result.pot_odds_ratio,
            'break_even_equity': result.break_even_equity
        }

    def get_gto_metrics(self, bet_size: float = None) -> Dict:
        """Get GTO metrics for betting decision"""
        if bet_size is None:
            bet_size = self.hand_state.pot_size * 0.66

        metrics = self.gto_engine.get_gto_metrics(bet_size, self.hand_state.pot_size)

        self.speak(f"\nGTO Metrics (${bet_size:.0f} into ${self.hand_state.pot_size:.0f}):", "normal")
        self.speak(f"  MDF (villain must defend): {metrics.mdf*100:.0f}%", "normal")
        self.speak(f"  Bluff break-even: {metrics.alpha*100:.0f}%", "normal")
        self.speak(f"  Your bluff frequency: {metrics.required_bluff_freq*100:.0f}%", "value")

        return {
            'mdf': metrics.mdf,
            'alpha': metrics.alpha,
            'bluff_freq': metrics.required_bluff_freq
        }

    def add_opponent(self, name: str, stats: PlayerStats):
        """Add opponent profile for exploitation"""
        profile = self.exploit_engine.update_player_stats(name, stats)
        self.opponent_profiles[name] = stats
        self._save_opponent(name, stats)

        self.speak(f"\nOpponent Profile: {name}", "normal")
        self.speak(f"  Type: {profile.tendency.value.upper()}", "normal")
        if profile.leaks:
            self.speak(f"  Leaks: {', '.join(l.value for l in profile.leaks)}", "warning")

        exploits = self.exploit_engine.get_exploits(name)
        if exploits:
            self.speak(f"  Top exploit: {exploits[0].adjustment}", "value")

    def get_tournament_analysis(self) -> Dict:
        """Get tournament-specific analysis"""
        if self.game_format != GameFormat.TOURNAMENT:
            return {'error': 'Not in tournament mode'}

        ts = self.tournament_state

        # Stack analysis
        stack_analysis = self.stack_analyzer.analyze_stack(
            ts.our_stack,
            ts.blinds[0],
            ts.blinds[1],
            ts.ante,
            ts.players_remaining,
            ts.average_stack
        )

        # ICM if we have payouts
        icm_equity = None
        if ts.payouts:
            # Simplified: assume we're the average stack
            stacks = [ts.our_stack] + [ts.average_stack] * (ts.players_remaining - 1)
            icm_result = self.icm_calc.calculate_icm(stacks[:len(ts.payouts)+2], ts.payouts)
            icm_equity = icm_result.equities[0]

        self.speak(f"\n🏆 Tournament Analysis:", "normal")
        self.speak(f"  Stack: {ts.our_stack:,} chips ({stack_analysis.bb_count:.0f}bb)", "normal")
        self.speak(f"  M-Ratio: {stack_analysis.m_ratio:.1f} ({stack_analysis.zone.value.upper()} zone)",
                  "value" if stack_analysis.zone == StackZone.GREEN else "warning")
        self.speak(f"  Players: {ts.players_remaining}/{ts.total_players}", "normal")

        if icm_equity:
            self.speak(f"  ICM Equity: ${icm_equity:.2f}", "value")

        self.speak(f"\n  Strategy: {stack_analysis.strategy[:80]}...", "wisdom")

        return {
            'stack_analysis': stack_analysis,
            'icm_equity': icm_equity,
            'phase': self.stack_analyzer.phase_from_players(
                ts.players_remaining, ts.total_players, len(ts.payouts)
            )
        }

    def push_or_fold(self, hand: str) -> Dict:
        """Get push/fold decision for short stack play"""
        from src.agents.poker.tournament.push_fold_engine import Position as PFPos

        # Map position
        pos_map = {
            Position.UTG: PFPos.UTG,
            Position.MP: PFPos.MP,
            Position.HJ: PFPos.HJ,
            Position.CO: PFPos.CO,
            Position.BTN: PFPos.BTN,
            Position.SB: PFPos.SB,
        }
        pf_pos = pos_map.get(self.hand_state.position, PFPos.BTN)

        # Get BB count
        if self.tournament_state:
            bb = self.tournament_state.blinds[1]
            bb_count = self.tournament_state.our_stack / bb
        else:
            bb_count = self.hand_state.effective_stack

        decision = self.push_fold.should_push(hand, bb_count, pf_pos)

        self.speak(f"\n🎰 Push/Fold: {hand} with {bb_count:.0f}bb from {pf_pos.value.upper()}", "normal")
        if decision.action == "push":
            self.speak(f"  → PUSH IT!", "action")
        else:
            self.speak(f"  → Fold and wait", "fold")
        self.speak(f"  {decision.reasoning}", "wisdom")

        return {
            'action': decision.action,
            'is_profitable': decision.is_profitable,
            'reasoning': decision.reasoning
        }

    def record_result(self, won: bool, amount: float):
        """Record hand result"""
        if won:
            self.session_stats.hands_won += 1
            self.session_stats.total_profit += amount
            if amount > self.session_stats.biggest_pot_won:
                self.session_stats.biggest_pot_won = amount
        else:
            self.session_stats.total_profit -= amount
            if amount > self.session_stats.biggest_pot_lost:
                self.session_stats.biggest_pot_lost = amount

        self.hand_history.append({
            'hole_cards': self._cards_to_str(self.hand_state.hole_cards),
            'board': " ".join(c.pretty() for c in self.hand_state.board) if self.hand_state.board else "",
            'won': won,
            'amount': amount
        })

    def get_session_summary(self) -> Dict:
        """Get session statistics"""
        stats = self.session_stats
        duration = (time.time() - self.session_start) / 60

        self.speak("\n" + "="*50, "normal")
        self.speak("📊 SESSION SUMMARY", "normal")
        self.speak("="*50, "normal")
        self.speak(f"Duration: {duration:.0f} minutes", "normal")
        self.speak(f"Hands Played: {stats.hands_played}", "normal")
        self.speak(f"Hands Won: {stats.hands_won} ({stats.win_rate*100:.1f}%)", "normal")

        profit_style = "value" if stats.total_profit >= 0 else "warning"
        self.speak(f"Total Profit: ${stats.total_profit:+.2f}", profit_style)
        self.speak(f"BB/100: {stats.bb_per_100:+.1f}", profit_style)

        if stats.biggest_pot_won > 0:
            self.speak(f"Biggest Win: ${stats.biggest_pot_won:.2f}", "success")
        if stats.biggest_pot_lost > 0:
            self.speak(f"Biggest Loss: ${stats.biggest_pot_lost:.2f}", "warning")

        self.speak("="*50, "normal")

        return {
            'duration_minutes': duration,
            'hands_played': stats.hands_played,
            'win_rate': stats.win_rate,
            'total_profit': stats.total_profit,
            'bb_per_100': stats.bb_per_100
        }

    def save_session(self, filename: str = None) -> str:
        """Save session stats and hand history to JSON file

        Args:
            filename: Optional filename (defaults to session_{timestamp}.json)

        Returns:
            Path to saved file
        """
        if not filename:
            filename = f"session_{self.session_id}.json"

        filepath = self.data_dir / filename

        data = {
            'session_id': self.session_id,
            'start_time': datetime.fromtimestamp(self.session_start).isoformat(),
            'end_time': datetime.now().isoformat(),
            'duration_minutes': (time.time() - self.session_start) / 60,
            'game_format': self.game_format.value,
            'variant': self.variant.value,
            'starting_stack': self.starting_stack,
            'stats': {
                'hands_played': self.session_stats.hands_played,
                'hands_won': self.session_stats.hands_won,
                'total_profit': self.session_stats.total_profit,
                'vpip': self.session_stats.vpip,
                'pfr': self.session_stats.pfr,
                'three_bet': self.session_stats.three_bet,
                'showdowns': self.session_stats.showdowns,
                'showdown_wins': self.session_stats.showdown_wins,
                'biggest_pot_won': self.session_stats.biggest_pot_won,
                'biggest_pot_lost': self.session_stats.biggest_pot_lost,
                'win_rate': self.session_stats.win_rate,
                'bb_per_100': self.session_stats.bb_per_100,
            },
            'hand_history': self.hand_history
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        self.speak(f"Session saved to {filepath}", "success")
        return str(filepath)

    @classmethod
    def load_session(cls, filepath: str) -> 'PokerAgent':
        """Load a previous session from JSON file

        Args:
            filepath: Path to session JSON file

        Returns:
            PokerAgent instance with loaded session data
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        agent = cls(
            game_format=GameFormat(data['game_format']),
            variant=Variant(data['variant']),
            starting_stack=data.get('starting_stack', 100.0)
        )

        # Restore session data
        agent.session_id = data['session_id']
        agent.hand_history = data['hand_history']

        # Restore stats
        stats = data['stats']
        agent.session_stats.hands_played = stats['hands_played']
        agent.session_stats.hands_won = stats['hands_won']
        agent.session_stats.total_profit = stats['total_profit']
        agent.session_stats.vpip = stats.get('vpip', 0)
        agent.session_stats.pfr = stats.get('pfr', 0)
        agent.session_stats.three_bet = stats.get('three_bet', 0)
        agent.session_stats.showdowns = stats.get('showdowns', 0)
        agent.session_stats.showdown_wins = stats.get('showdown_wins', 0)
        agent.session_stats.biggest_pot_won = stats.get('biggest_pot_won', 0)
        agent.session_stats.biggest_pot_lost = stats.get('biggest_pot_lost', 0)

        agent.speak(f"Loaded session {data['session_id']} ({stats['hands_played']} hands)", "success")
        return agent

    def list_sessions(self) -> List[Dict]:
        """List all saved sessions

        Returns:
            List of session info dicts
        """
        sessions = []
        for f in sorted(self.data_dir.glob("session_*.json"), reverse=True):
            try:
                with open(f, 'r') as fp:
                    data = json.load(fp)
                    sessions.append({
                        'filename': f.name,
                        'session_id': data['session_id'],
                        'hands_played': data['stats']['hands_played'],
                        'total_profit': data['stats']['total_profit'],
                        'date': data.get('start_time', 'unknown')
                    })
            except:
                continue
        return sessions

    def visualize_range(self, notation: str):
        """Visualize a range as 13x13 grid"""
        r = Range.from_notation(notation)
        print(r.visualize())

    def _cards_to_str(self, cards: List[Card]) -> str:
        """Convert cards to pretty string"""
        return " ".join(c.pretty() for c in cards)

    def help(self):
        """Show available commands"""
        self.speak("\n🎰 POKER GOD COMMANDS 🎰\n", "action")
        commands = [
            ("new_hand(cards, position)", "Start new hand"),
            ("set_board(cards)", "Set flop/turn/river"),
            ("get_preflop_advice(facing)", "Get preflop action"),
            ("get_postflop_advice()", "Get postflop action"),
            ("get_equity(range)", "Calculate equity vs range"),
            ("get_pot_odds()", "Calculate pot odds"),
            ("get_gto_metrics()", "Get GTO betting metrics"),
            ("add_opponent(name, stats)", "Add opponent profile"),
            ("push_or_fold(hand)", "Push/fold decision"),
            ("get_session_summary()", "Show session stats"),
            ("visualize_range(notation)", "Show range grid"),
            ("save_session()", "Save session to file"),
            ("load_session(path)", "Load previous session"),
            ("list_sessions()", "List all saved sessions"),
        ]
        for cmd, desc in commands:
            self.speak(f"  {cmd:30} - {desc}", "normal")

        # AI God Mode commands
        if AI_AVAILABLE:
            self.speak("\n🧠 GOD MODE (AI-Powered) 🧠\n", "action")
            ai_commands = [
                ("ask(question)", "Ask AI any poker question"),
                ("get_ai_advice()", "Get AI analysis of current spot"),
                ("review_session()", "AI review of session"),
                ("get_solver_solution()", "Quick GTO lookup"),
                ("analyze_hand_ai(hand_id)", "Deep AI hand analysis"),
            ]
            for cmd, desc in ai_commands:
                self.speak(f"  {cmd:30} - {desc}", "normal")

    # =====================================
    # 🧠 GOD MODE - AI-POWERED METHODS
    # =====================================

    def ask(self, question: str) -> str:
        """
        Ask the AI Brain any poker question

        Args:
            question: Natural language question about poker

        Returns:
            AI response
        """
        self._init_ai()
        if not self.ai_brain:
            return "AI Brain not available. Check API keys in .env"

        response = self.ai_brain.ask_sync(question, task="analysis")

        if response.success:
            self.speak(f"\n🧠 AI RESPONSE:\n", "wisdom")
            print(response.content)
            self.speak(f"\n[{response.model} | {response.latency_ms}ms]", "normal")
            return response.content
        else:
            self.speak(f"AI Error: {response.error}", "warning")
            return ""

    def get_ai_advice(self) -> str:
        """
        Get AI analysis of the current hand state

        Uses current hole_cards, board, pot, position, etc.
        """
        self._init_ai()
        if not self.ai_brain:
            return "AI Brain not available"

        if not self.hand_state.hole_cards:
            return "Set hole cards first with set_hole_cards()"

        # Build context
        cards_str = self._cards_to_str(self.hand_state.hole_cards)
        board_str = self._cards_to_str(self.hand_state.board) if self.hand_state.board else "preflop"

        response = self.ai_brain.get_advice(
            hole_cards=cards_str,
            board=board_str,
            position=self.hand_state.position.name,
            pot_size=self.hand_state.pot_size,
            bet_to_call=self.hand_state.bet_to_call,
            stack_size=self.hand_state.effective_stack
        )

        if response.success:
            self.speak(f"\n🧠 AI ADVICE for {cards_str} on {board_str}:\n", "wisdom")
            print(response.content)
            return response.content
        else:
            self.speak(f"AI Error: {response.error}", "warning")
            return ""

    def review_session_ai(self) -> str:
        """
        Get AI-powered review of the current session
        """
        self._init_ai()
        if not self.ai_brain:
            return "AI Brain not available"

        if not self.hand_history:
            return "No hands played yet"

        response = self.ai_brain.review_session(
            hands=self.hand_history[-20:],  # Last 20 hands
            stats={
                'hands_played': self.session_stats.hands_played,
                'hands_won': self.session_stats.hands_won,
                'total_profit': self.session_stats.total_profit,
                'win_rate': self.session_stats.win_rate
            }
        )

        if response.success:
            self.speak(f"\n📊 AI SESSION REVIEW:\n", "wisdom")
            print(response.content)
            return response.content
        else:
            return f"Review failed: {response.error}"

    def get_solver_solution(self, texture: str = None, hand_strength: str = None) -> Dict:
        """
        Get quick GTO solution from solver lite

        Args:
            texture: Board texture (dry_paired, wet_broadway, etc.)
            hand_strength: Hand category (nuts, top_pair_good, etc.)
        """
        self._init_ai()
        if not self.solver_lite:
            return {"error": "Solver not available"}

        # Default to dry unpaired if not specified
        try:
            tex = SolverBoardTexture[texture.upper()] if texture else SolverBoardTexture.DRY_UNPAIRED
        except KeyError:
            tex = SolverBoardTexture.DRY_UNPAIRED

        try:
            strength = HandStrength[hand_strength.upper()] if hand_strength else HandStrength.TOP_PAIR_GOOD
        except KeyError:
            strength = HandStrength.TOP_PAIR_GOOD

        # Determine position
        in_position = self.hand_state.position in [Position.BTN, Position.CO, Position.HJ]

        # Get c-bet solution
        solution = self.solver_lite.get_cbet_solution(tex, in_position, strength)

        self.speak(f"\n🎯 SOLVER SOLUTION ({tex.value}, {strength.value}):", "value")
        self.speak(f"  Action: {solution.action} @ {solution.frequency*100:.0f}% frequency", "normal")
        self.speak(f"  Sizing: {solution.sizing*100:.0f}% pot", "normal")
        self.speak(f"  {solution.reasoning}", "wisdom")

        return {
            "action": solution.action,
            "frequency": solution.frequency,
            "sizing": solution.sizing,
            "reasoning": solution.reasoning
        }

    def analyze_hand_ai(self, hand_text: str) -> str:
        """
        Deep AI analysis of a hand

        Args:
            hand_text: Full hand history text
        """
        self._init_ai()
        if not self.ai_brain:
            return "AI Brain not available"

        response = self.ai_brain.analyze_hand(hand_text)

        if response.success:
            self.speak(f"\n📝 HAND ANALYSIS:\n", "wisdom")
            print(response.content)
            return response.content
        else:
            return f"Analysis failed: {response.error}"

    def profile_villain(self,
                        vpip: float = 25,
                        pfr: float = 18,
                        three_bet: float = 6,
                        cbet: float = 65,
                        aggression: float = 2.0,
                        wtsd: float = 25,
                        notes: str = "") -> str:
        """
        Get AI profile and exploits for an opponent

        Args:
            vpip: VPIP percentage
            pfr: PFR percentage
            three_bet: 3-bet percentage
            cbet: C-bet percentage
            aggression: Aggression factor
            wtsd: Went to showdown %
            notes: Additional observations
        """
        self._init_ai()
        if not self.ai_brain:
            return "AI Brain not available"

        stats = {
            "vpip": vpip,
            "pfr": pfr,
            "3bet": three_bet,
            "cbet": cbet,
            "af": aggression,
            "wtsd": wtsd
        }

        response = self.ai_brain.profile_opponent(stats, notes)

        if response.success:
            self.speak(f"\n🎭 VILLAIN PROFILE:\n", "wisdom")
            print(response.content)
            return response.content
        else:
            return f"Profile failed: {response.error}"

    # =====================================
    # 🔥 TIER 2/3: ADVANCED GOD MODE
    # =====================================

    def get_population_profile(self,
                               stake: str = "live_low",
                               player_type: str = "live_rec") -> Dict:
        """
        Get population tendencies for a stake level

        Args:
            stake: micro, low, mid, high, live_low, live_mid
            player_type: online_reg, online_rec, live_rec, live_reg
        """
        self._init_ai()
        if not self.population_db:
            return {"error": "Population database not available"}

        try:
            stake_level = StakeLevel[stake.upper()]
            pool = PlayerPool[player_type.upper()]
        except KeyError:
            self.speak("Available stakes: micro, low, mid, high, live_low, live_mid", "warning")
            self.speak("Available types: online_reg, online_rec, live_rec, live_reg", "warning")
            return {}

        profile = self.population_db.get_profile(stake_level, pool)
        if not profile:
            return {"error": "Profile not found"}

        self.population_db.print_profile(stake_level, pool)
        return {
            "vpip": profile.stats.vpip,
            "pfr": profile.stats.pfr,
            "3bet": profile.stats.three_bet,
            "exploits": profile.exploits
        }

    def get_adjusted_range(self,
                          stack_bb: float = 100,
                          table_type: str = "balanced",
                          is_live: bool = False) -> Dict:
        """
        Get dynamically adjusted opening range

        Args:
            stack_bb: Effective stack in big blinds
            table_type: passive, aggressive, loose, tight, balanced
            is_live: True for live game
        """
        self._init_ai()
        if not self.range_engine:
            return {"error": "Range engine not available"}

        try:
            dynamic = TableDynamic[table_type.upper()]
        except KeyError:
            dynamic = TableDynamic.BALANCED

        context = RangeGameContext(
            position=self.hand_state.position.name,
            stack_bb=stack_bb,
            table_dynamic=dynamic,
            is_live=is_live
        )

        result = self.range_engine.get_adjusted_opening_range(context)

        self.speak(f"\n🎯 ADJUSTED RANGE for {context.position}:", "value")
        self.speak(f"  Base: {result.base_range}", "normal")
        self.speak(f"  Adjusted: {result.adjusted_range}", "normal")
        self.speak(f"  Factor: {result.adjustment_factor:.2f}x", "normal")

        if result.reasoning:
            self.speak("  Reasoning:", "wisdom")
            for r in result.reasoning:
                self.speak(f"    - {r}", "normal")

        return {
            "base": result.base_range,
            "adjusted": result.adjusted_range,
            "factor": result.adjustment_factor,
            "reasoning": result.reasoning
        }

    def import_hand_history(self, filepath: str) -> Dict:
        """
        Import and analyze hand history file

        Args:
            filepath: Path to HH file (PokerStars/GG format)
        """
        self._init_ai()
        if not self.hh_parser:
            return {"error": "Hand history parser not available"}

        try:
            hands = self.hh_parser.parse_file(filepath)

            self.speak(f"\n📜 Imported {len(hands)} hands from {filepath}", "success")

            if hands:
                # Show summary
                total_profit = sum(h.hero_profit for h in hands)
                wins = sum(1 for h in hands if h.hero_won)

                self.speak(f"  Total profit: ${total_profit:+.2f}", "value")
                self.speak(f"  Win rate: {wins/len(hands)*100:.1f}%", "normal")

                # Show biggest pot
                biggest = max(hands, key=lambda h: abs(h.hero_profit))
                self.speak(f"  Biggest hand: {biggest.summary()}", "normal")

            return {
                "hands": len(hands),
                "profit": sum(h.hero_profit for h in hands),
                "parsed_hands": hands[:5]  # First 5 for inspection
            }
        except Exception as e:
            return {"error": str(e)}

    def quick_eval(self, hole_cards: str, board: str = "") -> Dict:
        """
        Ultra-fast neural hand evaluation

        Args:
            hole_cards: Cards like "AhKs"
            board: Board like "Qh Jc 2d"
        """
        self._init_ai()
        if not self.neural_eval:
            return {"error": "Neural evaluator not available"}

        result = self.neural_eval.evaluate(hole_cards, board)

        self.speak(f"\n⚡ NEURAL EVAL: {hole_cards} on {board or 'preflop'}", "value")
        self.speak(f"  Strength: {result.raw_strength:.2f} ({result.category.name})", "normal")
        self.speak(f"  Equity: {result.equity_estimate*100:.1f}%", "normal")
        self.speak(f"  Description: {result.hand_description}", "wisdom")

        if result.is_drawing:
            self.speak(f"  Drawing: {result.draw_outs} outs", "normal")
        if result.blockers:
            self.speak(f"  Blockers: {', '.join(result.blockers)}", "normal")

        return {
            "strength": result.raw_strength,
            "category": result.category.name,
            "equity": result.equity_estimate,
            "description": result.hand_description,
            "drawing": result.is_drawing,
            "outs": result.draw_outs
        }

    def god_mode_status(self) -> Dict:
        """Show God Mode status and all available components"""
        self._init_ai()

        self.speak("\n🧠 GOD MODE STATUS", "action")
        self.speak("=" * 40, "normal")

        components = {
            "AI Brain": self.ai_brain is not None,
            "Solver Lite": self.solver_lite is not None,
            "Session Reviewer": self.session_reviewer is not None,
            "Population DB": self.population_db is not None,
            "Range Engine": self.range_engine is not None,
            "HH Parser": self.hh_parser is not None,
            "Neural Evaluator": self.neural_eval is not None,
        }

        for name, available in components.items():
            status = "✅" if available else "❌"
            self.speak(f"  {status} {name}", "normal")

        if self.ai_brain:
            self.speak(f"\n  Available models: {[m.value for m in self.ai_brain.available_models]}", "normal")

        return components


def parse_cards(notation: str) -> List[Card]:
    """Parse card notation like 'AhKs' or 'Ah Ks'"""
    notation = notation.replace(" ", "")
    cards = []
    i = 0
    while i < len(notation):
        if i + 1 < len(notation):
            card_str = notation[i:i+2]
            cards.append(Card.from_string(card_str))
            i += 2
        else:
            break
    return cards


# === Interactive Mode ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n" + "="*60, "cyan")
    cprint("  🎰 POKER GOD - THE ULTIMATE POKER MASTER 🎰", "cyan", attrs=['bold'])
    cprint("  GTO + Exploitative | Hold'em & Omaha | Cash & Tournaments", "cyan")
    cprint("="*60 + "\n", "cyan")

    # Initialize agent
    god = PokerAgent(mode=GameMode.ADVISOR, game_format=GameFormat.CASH)

    # Demo hand
    cprint("Demo: Playing AKs from the Button\n", "yellow")

    # Set up hand
    hero = parse_cards("AhKh")
    god.new_hand(hero, Position.BTN)

    # Get preflop advice
    god.get_preflop_advice(FacingAction.UNOPENED)

    print()

    # Villain calls, see flop
    flop = parse_cards("Kd 7c 2h")
    god.set_board(flop)
    god.set_pot(6.5)
    god.set_villain_range("22+,A2s+,A9o+,K9s+,KTo+,Q9s+,QTo+,J9s+,JTo,T9s")

    # Get postflop advice
    god.get_postflop_advice(in_position=True)

    print()

    # Get equity
    god.get_equity()

    print()

    # Record win
    god.record_result(won=True, amount=12.5)

    # Session summary
    god.get_session_summary()

    print()
    cprint("💡 Type 'god.help()' for all commands", "cyan")
