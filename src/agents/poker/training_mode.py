"""
Training Mode - Practice drills and skill development
The path to poker mastery
Built with love by TradeHive
"""

import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import time
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import HandEvaluator, Card, Deck, Rank, Suit
from src.agents.poker.core.range_manager import Range, RangeManager
from src.agents.poker.core.odds_calculator import OddsCalculator
from src.agents.poker.core.equity_calculator import EquityCalculator
from src.agents.poker.core.board_analyzer import BoardAnalyzer
from src.agents.poker.strategy.preflop_engine import PreflopEngine, Position, FacingAction


class DrillType(Enum):
    """Types of training drills"""
    PREFLOP_DECISIONS = "preflop"
    EQUITY_ESTIMATION = "equity"
    POT_ODDS = "pot_odds"
    HAND_READING = "hand_reading"
    PUSH_FOLD = "push_fold"
    BOARD_TEXTURE = "board_texture"


@dataclass
class DrillResult:
    """Result of a single drill"""
    drill_type: DrillType
    question: str
    correct_answer: str
    user_answer: str
    is_correct: bool
    time_taken: float
    explanation: str


@dataclass
class TrainingStats:
    """Training session statistics"""
    total_drills: int = 0
    correct_answers: int = 0
    drills_by_type: Dict[DrillType, Dict] = field(default_factory=dict)
    
    @property
    def accuracy(self) -> float:
        return self.correct_answers / self.total_drills if self.total_drills > 0 else 0
        
    def update(self, result: DrillResult):
        self.total_drills += 1
        if result.is_correct:
            self.correct_answers += 1
            
        if result.drill_type not in self.drills_by_type:
            self.drills_by_type[result.drill_type] = {'total': 0, 'correct': 0}
        self.drills_by_type[result.drill_type]['total'] += 1
        if result.is_correct:
            self.drills_by_type[result.drill_type]['correct'] += 1


class TrainingMode:
    """
    Poker training system with various drills
    
    Drill Types:
    - Preflop Decisions: Should you raise, call, or fold?
    - Equity Estimation: Guess your equity vs a range
    - Pot Odds: Calculate if a call is profitable
    - Hand Reading: What hands beat/lose to yours?
    - Push/Fold: Tournament short stack decisions
    - Board Texture: Analyze flop textures
    """
    
    def __init__(self):
        self.hand_evaluator = HandEvaluator()
        self.range_manager = RangeManager()
        self.odds_calc = OddsCalculator()
        self.equity_calc = EquityCalculator()
        self.board_analyzer = BoardAnalyzer()
        self.preflop_engine = PreflopEngine()
        
        self.stats = TrainingStats()
        self.drill_history: List[DrillResult] = []
        
    def _random_hand(self) -> List[Card]:
        """Generate random hole cards"""
        deck = Deck()
        deck.shuffle()
        return deck.deal(2)
        
    def _random_board(self, n: int = 3) -> List[Card]:
        """Generate random board"""
        deck = Deck()
        deck.shuffle()
        return deck.deal(n)
        
    def _hand_to_notation(self, cards: List[Card]) -> str:
        """Convert hand to notation"""
        if len(cards) != 2:
            return ""
        c1, c2 = cards
        if c2.rank > c1.rank:
            c1, c2 = c2, c1
        
        r1 = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}[c1.rank]
        r2 = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}[c2.rank]
        
        if c1.rank == c2.rank:
            return f"{r1}{r2}"
        elif c1.suit == c2.suit:
            return f"{r1}{r2}s"
        else:
            return f"{r1}{r2}o"

    # === PREFLOP DRILL ===
    def drill_preflop(self) -> Tuple[str, str, str]:
        """
        Generate preflop decision drill
        
        Returns:
            (question, correct_answer, explanation)
        """
        # Random hand and position
        hand = self._random_hand()
        hand_str = self._hand_to_notation(hand)
        position = random.choice([Position.UTG, Position.MP, Position.CO, Position.BTN, Position.SB])
        
        # Random scenario
        scenarios = [
            (FacingAction.UNOPENED, None, "first to act"),
            (FacingAction.RAISED, Position.UTG, "vs UTG open"),
            (FacingAction.RAISED, Position.CO, "vs CO open"),
            (FacingAction.RAISED, Position.BTN, "vs BTN open"),
        ]
        facing, raiser, scenario_desc = random.choice(scenarios)
        
        # Get correct decision
        decision = self.preflop_engine.get_decision(hand, position, facing, raiser)
        correct = decision.action.value.upper()
        
        question = f"You have {hand_str} in {position.name}, {scenario_desc}. What do you do?"
        explanation = decision.reasoning
        
        return question, correct, explanation
        
    # === EQUITY ESTIMATION DRILL ===
    def drill_equity(self) -> Tuple[str, int, str]:
        """
        Generate equity estimation drill
        
        Returns:
            (question, correct_equity_percent, explanation)
        """
        # Generate hands and board
        deck = Deck()
        deck.shuffle()
        hero = deck.deal(2)
        board = deck.deal(random.choice([0, 3, 4, 5]))
        
        # Calculate equity vs a range
        ranges = [
            ("top 20%", "22+,A2s+,A9o+,K9s+,KTo+,Q9s+,QTo+,J9s+,JTo,T9s"),
            ("top 10%", "66+,A4s+,ATo+,KTs+,KQo,QTs+,JTs"),
            ("premium", "TT+,AQs+,AKo"),
        ]
        range_name, range_notation = random.choice(ranges)
        villain_range = Range.from_notation(range_notation)
        
        result = self.equity_calc.hand_vs_range(hero, villain_range, board, iterations=3000)
        correct_equity = int(result.equity * 100)
        
        hero_str = " ".join(c.pretty() for c in hero)
        board_str = " ".join(c.pretty() for c in board) if board else "preflop"
        
        question = f"You have {hero_str} on {board_str} vs {range_name}. Estimate your equity (%)."
        explanation = f"Your equity is {correct_equity}% (Win: {result.win_rate*100:.0f}%, Tie: {result.tie_rate*100:.0f}%)"
        
        return question, correct_equity, explanation
        
    # === POT ODDS DRILL ===
    def drill_pot_odds(self) -> Tuple[str, str, str]:
        """
        Generate pot odds drill
        
        Returns:
            (question, correct_answer, explanation)
        """
        pot = random.choice([50, 75, 100, 150, 200])
        bet = random.choice([25, 33, 50, 75, 100])
        equity = random.randint(15, 55)
        
        odds_result = self.odds_calc.pot_odds(bet, pot)
        required_equity = odds_result.break_even_equity * 100
        
        is_profitable = equity >= required_equity
        correct = "CALL" if is_profitable else "FOLD"
        
        question = f"Pot is ${pot}, villain bets ${bet}. You have {equity}% equity. Call or Fold?"
        
        explanation = f"Pot odds: {odds_result.pot_odds*100:.1f}% (need {required_equity:.0f}% to call). "
        explanation += f"You have {equity}%, so {correct} is correct."
        
        return question, correct, explanation
        
    # === HAND READING DRILL ===
    def drill_hand_reading(self) -> Tuple[str, str, str]:
        """
        Generate hand reading drill
        
        Returns:
            (question, correct_answer, explanation)
        """
        deck = Deck()
        deck.shuffle()
        
        board = deck.deal(5)
        hero = deck.deal(2)
        
        hero_result = self.hand_evaluator.evaluate(hero, board)
        
        # Generate comparison hands
        villain = deck.deal(2)
        villain_result = self.hand_evaluator.evaluate(villain, board)
        
        comparison = self.hand_evaluator.compare(hero_result, villain_result)
        if comparison < 0:
            correct = "WIN"
        elif comparison > 0:
            correct = "LOSE"
        else:
            correct = "TIE"
            
        hero_str = " ".join(c.pretty() for c in hero)
        villain_str = " ".join(c.pretty() for c in villain)
        board_str = " ".join(c.pretty() for c in board)
        
        question = f"Board: {board_str}\nYou: {hero_str} ({hero_result.description})\nVillain: {villain_str}\n\nDo you WIN, LOSE, or TIE?"
        
        explanation = f"Villain has {villain_result.description}. You {correct}."
        
        return question, correct, explanation
        
    # === PUSH/FOLD DRILL ===
    def drill_push_fold(self) -> Tuple[str, str, str]:
        """
        Generate push/fold drill
        
        Returns:
            (question, correct_answer, explanation)
        """
        from src.agents.poker.tournament.push_fold_engine import PushFoldEngine, Position as PFPos
        
        pf_engine = PushFoldEngine()
        
        # Random scenario
        bb = random.choice([3, 5, 8, 10, 12, 15])
        position = random.choice(list(PFPos))
        hand = self._random_hand()
        hand_str = self._hand_to_notation(hand)
        
        decision = pf_engine.should_push(hand_str, bb, position)
        correct = decision.action.upper()
        
        question = f"You have {hand_str} with {bb}bb in {position.value.upper()}. Push or Fold?"
        explanation = decision.reasoning
        
        return question, correct, explanation
        
    # === BOARD TEXTURE DRILL ===
    def drill_board_texture(self) -> Tuple[str, str, str]:
        """
        Generate board texture drill
        
        Returns:
            (question, correct_answer, explanation)
        """
        board = self._random_board(3)
        analysis = self.board_analyzer.analyze(board)
        
        board_str = " ".join(c.pretty() for c in board)
        correct = analysis.texture.value.upper()
        
        question = f"What is the texture of this flop? {board_str}"
        
        explanation = f"Texture: {correct}. "
        if analysis.draws:
            explanation += f"Draws present: {', '.join(d.draw_type.value for d in analysis.draws[:3])}"
        if analysis.is_paired:
            explanation += " Board is paired."
            
        return question, correct, explanation
        
    def run_drill(self, drill_type: DrillType = None) -> DrillResult:
        """
        Run a single drill
        
        Args:
            drill_type: Type of drill (random if not specified)
            
        Returns:
            DrillResult
        """
        if drill_type is None:
            drill_type = random.choice(list(DrillType))
            
        # Generate drill
        if drill_type == DrillType.PREFLOP_DECISIONS:
            question, correct, explanation = self.drill_preflop()
        elif drill_type == DrillType.EQUITY_ESTIMATION:
            question, correct, explanation = self.drill_equity()
        elif drill_type == DrillType.POT_ODDS:
            question, correct, explanation = self.drill_pot_odds()
        elif drill_type == DrillType.HAND_READING:
            question, correct, explanation = self.drill_hand_reading()
        elif drill_type == DrillType.PUSH_FOLD:
            question, correct, explanation = self.drill_push_fold()
        else:
            question, correct, explanation = self.drill_board_texture()
            
        return question, str(correct), explanation, drill_type
        
    def check_answer(self, user_answer: str, correct_answer: str, 
                     question: str, explanation: str, drill_type: DrillType,
                     time_taken: float) -> DrillResult:
        """Check user's answer and record result"""
        
        # Flexible matching
        user_clean = user_answer.strip().upper()
        correct_clean = str(correct_answer).strip().upper()
        
        # For equity, allow ±10%
        is_correct = False
        if drill_type == DrillType.EQUITY_ESTIMATION:
            try:
                user_val = int(user_clean.replace('%', ''))
                correct_val = int(correct_clean)
                is_correct = abs(user_val - correct_val) <= 10
            except:
                is_correct = False
        else:
            is_correct = user_clean == correct_clean or user_clean.startswith(correct_clean[:4])
            
        result = DrillResult(
            drill_type=drill_type,
            question=question,
            correct_answer=correct_answer,
            user_answer=user_answer,
            is_correct=is_correct,
            time_taken=time_taken,
            explanation=explanation
        )
        
        self.stats.update(result)
        self.drill_history.append(result)
        
        return result
        
    def get_stats_summary(self) -> str:
        """Get training statistics summary"""
        lines = ["\n" + "="*50]
        lines.append("📚 TRAINING SUMMARY")
        lines.append("="*50)
        lines.append(f"Total Drills: {self.stats.total_drills}")
        lines.append(f"Correct: {self.stats.correct_answers}")
        lines.append(f"Accuracy: {self.stats.accuracy*100:.1f}%")
        
        lines.append("\nBy Drill Type:")
        for drill_type, data in self.stats.drills_by_type.items():
            acc = data['correct'] / data['total'] * 100 if data['total'] > 0 else 0
            lines.append(f"  {drill_type.value}: {data['correct']}/{data['total']} ({acc:.0f}%)")
            
        lines.append("="*50)
        return "\n".join(lines)
        
    def identify_weaknesses(self) -> List[DrillType]:
        """Identify areas needing improvement"""
        weak_areas = []
        
        for drill_type, data in self.stats.drills_by_type.items():
            if data['total'] >= 5:  # Need enough samples
                acc = data['correct'] / data['total']
                if acc < 0.7:  # Below 70%
                    weak_areas.append(drill_type)
                    
        return weak_areas


# === Interactive Training ===
if __name__ == "__main__":
    from termcolor import cprint
    
    cprint("\n" + "="*60, "cyan")
    cprint("  📚 POKER GOD TRAINING MODE 📚", "cyan", attrs=['bold'])
    cprint("="*60 + "\n", "cyan")
    
    trainer = TrainingMode()
    
    # Run 5 sample drills
    drill_types = [
        DrillType.PREFLOP_DECISIONS,
        DrillType.POT_ODDS,
        DrillType.PUSH_FOLD,
        DrillType.BOARD_TEXTURE,
        DrillType.EQUITY_ESTIMATION
    ]
    
    for drill_type in drill_types:
        cprint(f"\n[{drill_type.value.upper()} DRILL]", "yellow")
        question, correct, explanation, _ = trainer.run_drill(drill_type)
        
        cprint(question, "white")
        cprint(f"\nCorrect Answer: {correct}", "green")
        cprint(f"Explanation: {explanation}", "cyan")
        
        # Simulate correct answer for demo
        result = trainer.check_answer(str(correct), correct, question, explanation, drill_type, 5.0)
        
        print("-" * 40)
        
    cprint(trainer.get_stats_summary(), "cyan")
