"""
Decision Engine — Unified poker decision-making brain

Integrates ALL engines into one decision function:
- PreflopEngine for ranges (with mixed strategies)
- PostflopEngine for hand categorization
- EquityCalculator for REAL equity (replaces hardcoded values)
- GTOEngine for theory (MDF, bluff ratios)
- ExploitativeEngine for opponent adjustments
- SolverLite for pre-computed GTO solutions
- BoardAnalyzer for texture analysis

Every advisor call goes through get_decision() → one integrated answer.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

from ..core.hand_evaluator import Card, HandEvaluator, HandRank
from ..core.equity_calculator import EquityCalculator
from ..core.board_analyzer import BoardAnalyzer, BoardTexture as BATexture, DrawType
from ..core.range_manager import Range
from ..core.odds_calculator import OddsCalculator
from ..core.poker_types import Street, PostflopAction

from .preflop_engine import PreflopEngine, Position, FacingAction, PreflopAction
from .postflop_engine import PostflopEngine, HandCategory
from .gto_engine import GTOEngine
from .exploitative_engine import ExploitativeEngine, PlayerStats, PlayerTendency

try:
    from ..ai.solver_lite import SolverLite, BoardTexture as SLTexture, HandStrength
    SOLVER_AVAILABLE = True
except ImportError:
    SOLVER_AVAILABLE = False


@dataclass
class Decision:
    """Unified decision result from all engines."""
    action: str                          # fold, check, call, bet, raise, check_raise, all_in
    sizing_fraction: Optional[float]     # Fraction of pot (for bets/raises)
    sizing_bb: Optional[float]           # Absolute sizing in BB (preflop)
    frequency: float                     # How often to take this action (0-1)
    equity: float                        # Our equity vs estimated villain range
    pot_odds: Optional[float]            # Required equity to call (if facing bet)
    ev: Optional[float]                  # Expected value estimate
    reasoning: str                       # Primary reasoning
    hand_strength: str                   # Hand category name
    alternative: Optional[str] = None    # Alt action
    alt_freq: float = 0.0
    barrel_plan: Optional[str] = None    # Multi-street plan
    exploit_note: Optional[str] = None   # Exploitation adjustment applied


# Default villain ranges by type (standard notation)
VILLAIN_RANGES = {
    'nit':  "AA-99,AKs-ATs,KQs,AKo-AQo",
    'tag':  "AA-77,AKs-A8s,KQs-KTs,QJs-QTs,JTs,T9s,98s,AKo-ATo,KQo-KJo,QJo",
    'lag':  "AA-22,AKs-A2s,KQs-K5s,QJs-Q7s,JTs-J8s,T9s-T8s,98s-97s,87s-86s,76s-75s,65s,AKo-A5o,KQo-K8o,QJo-Q9o,JTo",
    'fish': "AA-22,AKs-A2s,KQs-K2s,QJs-Q5s,JTs-J7s,T9s-T7s,98s-96s,87s,76s,AKo-A2o,KQo-K5o,QJo-Q8o,JTo-J8o,T9o",
    'reg':  "AA-55,AKs-A5s,KQs-K9s,QJs-Q9s,JTs-J9s,T9s,98s,87s,AKo-A9o,KQo-KTo,QJo",
}

# Approximate range widths by position for unknown villain
POSITION_RANGE_WIDTH = {
    Position.UTG: 'AA-88,AKs-ATs,KQs,AKo-AQo',
    Position.MP: 'AA-77,AKs-A9s,KQs-KJs,QJs,AKo-ATo,KQo',
    Position.HJ: 'AA-66,AKs-A7s,KQs-K9s,QJs-QTs,JTs,AKo-A9o,KQo-KJo,QJo',
    Position.CO: 'AA-55,AKs-A5s,KQs-K8s,QJs-Q9s,JTs-J9s,T9s,98s,87s,AKo-A8o,KQo-KTo,QJo',
    Position.BTN: VILLAIN_RANGES['lag'],
    Position.SB: 'AA-77,AKs-A8s,KQs-KTs,QJs,AKo-ATo,KQo-KJo',
    Position.BB: VILLAIN_RANGES['tag'],  # BB defense range
}


class DecisionEngine:
    """
    The brain — integrates all poker engines into unified decisions.

    Usage:
        engine = DecisionEngine()
        decision = engine.get_decision(
            hole_cards, board, position, pot=15, bet_to_call=8,
            street=Street.FLOP, in_position=True
        )
    """

    def __init__(self):
        self.preflop = PreflopEngine()
        self.postflop = PostflopEngine()
        self.gto = GTOEngine()
        self.equity_calc = EquityCalculator()
        self.board_analyzer = BoardAnalyzer()
        self.odds_calc = OddsCalculator()
        self.evaluator = HandEvaluator()
        self.solver = SolverLite() if SOLVER_AVAILABLE else None

    def get_decision(
        self,
        hole_cards: List[Card],
        board: List[Card],
        position: Position,
        pot: float = 10.0,
        bet_to_call: float = 0.0,
        street: Street = Street.PREFLOP,
        in_position: bool = True,
        villain_type: str = 'reg',
        villain_position: Optional[Position] = None,
        effective_stack: float = 100.0,
        is_preflop_aggressor: bool = True,
    ) -> Decision:
        """Main entry point — routes to the right handler."""

        if street == Street.PREFLOP or not board:
            return self._preflop_decision(
                hole_cards, position, bet_to_call, villain_type,
                villain_position, effective_stack,
            )

        if bet_to_call > 0:
            return self._postflop_facing_bet(
                hole_cards, board, position, pot, bet_to_call,
                street, in_position, villain_type, villain_position,
                effective_stack, is_preflop_aggressor,
            )

        return self._postflop_first_to_act(
            hole_cards, board, position, pot, street, in_position,
            villain_type, villain_position, effective_stack,
            is_preflop_aggressor,
        )

    # ─────────────────────────────────────────
    # PREFLOP
    # ─────────────────────────────────────────

    def _preflop_decision(
        self, hole_cards, position, bet_to_call, villain_type,
        villain_position, effective_stack,
    ) -> Decision:
        """Preflop decision with mixed strategy support."""

        # Determine facing action
        if bet_to_call <= 1.0:
            facing = FacingAction.UNOPENED
        elif bet_to_call <= 4.0:
            facing = FacingAction.RAISED
        elif bet_to_call <= 12.0:
            facing = FacingAction.THREE_BET
        else:
            facing = FacingAction.FOUR_BET

        base = self.preflop.get_decision(
            hole_cards, position, facing,
            raiser_position=villain_position,
        )

        # Mixed strategy: reduce frequency for marginal hands
        freq = base.frequency
        if base.action == PreflopAction.RAISE and base.range_strength == 'playable':
            freq = 0.75  # Mix bottom of opening range
        elif base.action == PreflopAction.RAISE and base.range_strength == 'marginal':
            freq = 0.50
        elif base.action == PreflopAction.CALL and base.range_strength in ('playable', 'marginal'):
            freq = 0.70

        # Map action
        if base.action == PreflopAction.RAISE:
            action = "raise"
        elif base.action == PreflopAction.CALL:
            action = "call"
        elif base.action == PreflopAction.ALL_IN:
            action = "all_in"
        else:
            action = "fold"

        # Exploit adjustment
        exploit_note = None
        if villain_type == 'nit' and action == 'fold' and facing == FacingAction.UNOPENED:
            # Consider stealing from nits
            exploit_note = "Nit in blinds — consider wider steals"
        elif villain_type == 'fish' and action == 'call':
            exploit_note = "Fish — prefer raising for value over flat calling"

        return Decision(
            action=action,
            sizing_fraction=None,
            sizing_bb=base.sizing,
            frequency=freq,
            equity=0.0,  # Preflop equity not calculated per-hand
            pot_odds=None,
            ev=None,
            reasoning=base.reasoning,
            hand_strength=base.range_strength,
            alternative="fold" if action != "fold" else None,
            alt_freq=1 - freq if freq < 1.0 else 0,
            exploit_note=exploit_note,
        )

    # ─────────────────────────────────────────
    # POSTFLOP — First to Act (bet/check/check-raise)
    # ─────────────────────────────────────────

    def _postflop_first_to_act(
        self, hole_cards, board, position, pot, street,
        in_position, villain_type, villain_position, effective_stack,
        is_preflop_aggressor,
    ) -> Decision:
        """Postflop decision when first to act or checked to."""

        # 1. Hand categorization
        hand_cat, hand_result = self.postflop.analyze_hand_strength(hole_cards, board)
        board_analysis = self.board_analyzer.analyze(board)

        # 2. Real equity calculation
        villain_range = self._get_villain_range(villain_type, villain_position, street)
        equity_result = self.equity_calc.hand_vs_range(
            hole_cards, villain_range, board, iterations=1000
        )
        equity = equity_result.equity

        # 3. SPR for sizing decisions
        spr = effective_stack / pot if pot > 0 else 10.0
        streets_left = {Street.FLOP: 3, Street.TURN: 2, Street.RIVER: 1}.get(street, 1)

        # 4. Determine sizing based on board texture and SPR
        texture = board_analysis.texture
        if texture in (BATexture.WET, BATexture.MONOTONE):
            sizing = 0.66 if in_position else 0.75
        elif texture == BATexture.SEMI_WET:
            sizing = 0.50 if in_position else 0.66
        else:  # dry
            sizing = 0.33

        # Adjust sizing by hand strength
        if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG) and spr > 3:
            sizing = max(sizing, 0.66)  # Bet bigger with monsters to build pot

        # 5. Decision logic
        if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG):
            # Check-raise candidate OOP
            if not in_position and random.random() < 0.35:
                return Decision(
                    action="check_raise",
                    sizing_fraction=sizing * 2.5,
                    sizing_bb=None,
                    frequency=0.35,
                    equity=equity,
                    pot_odds=None,
                    ev=pot * equity * 0.8,
                    reasoning=f"Check-raise for value with {hand_result.description} ({equity:.0%} equity)",
                    hand_strength=hand_cat.value,
                    alternative="bet",
                    alt_freq=0.65,
                    barrel_plan=self._barrel_plan(hand_cat, equity, streets_left),
                )

            return Decision(
                action="bet",
                sizing_fraction=sizing,
                sizing_bb=None,
                frequency=0.95,
                equity=equity,
                pot_odds=None,
                ev=pot * sizing * equity,
                reasoning=f"Value bet {hand_result.description} ({equity:.0%} equity vs {villain_type})",
                hand_strength=hand_cat.value,
                barrel_plan=self._barrel_plan(hand_cat, equity, streets_left),
            )

        elif hand_cat == HandCategory.STRONG:
            bet_freq = 0.85 if is_preflop_aggressor else 0.65
            return Decision(
                action="bet",
                sizing_fraction=sizing,
                sizing_bb=None,
                frequency=bet_freq,
                equity=equity,
                pot_odds=None,
                ev=pot * sizing * equity * 0.6,
                reasoning=f"Value bet {hand_result.description} ({equity:.0%} equity)",
                hand_strength=hand_cat.value,
                alternative="check",
                alt_freq=1 - bet_freq,
                barrel_plan=self._barrel_plan(hand_cat, equity, streets_left),
            )

        elif hand_cat == HandCategory.MEDIUM:
            # Medium hands: bet on dry boards for protection, check wet boards
            if texture in (BATexture.DRY, BATexture.PAIRED, BATexture.SEMI_DRY):
                bet_freq = 0.60 if in_position else 0.40
                return Decision(
                    action="bet",
                    sizing_fraction=0.33,
                    sizing_bb=None,
                    frequency=bet_freq,
                    equity=equity,
                    pot_odds=None,
                    ev=pot * 0.33 * (equity - 0.5),
                    reasoning=f"Protection bet {hand_result.description} on {texture.value} board ({equity:.0%} eq)",
                    hand_strength=hand_cat.value,
                    alternative="check",
                    alt_freq=1 - bet_freq,
                )
            else:
                return Decision(
                    action="check",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.70,
                    equity=equity,
                    pot_odds=None,
                    ev=0,
                    reasoning=f"Check {hand_result.description} on {texture.value} board ({equity:.0%} eq) — pot control",
                    hand_strength=hand_cat.value,
                    alternative="bet",
                    alt_freq=0.30,
                )

        elif hand_cat == HandCategory.DRAW:
            # Semi-bluff draws with enough equity
            has_strong_draw = equity >= 0.30
            if has_strong_draw:
                bet_freq = 0.65 if in_position else 0.50

                # Check-raise as semi-bluff OOP
                if not in_position and equity >= 0.35:
                    return Decision(
                        action="check_raise",
                        sizing_fraction=sizing * 2.5,
                        sizing_bb=None,
                        frequency=0.25,
                        equity=equity,
                        pot_odds=None,
                        ev=pot * equity * 0.5,
                        reasoning=f"Semi-bluff check-raise with {hand_result.description} ({equity:.0%} eq)",
                        hand_strength=hand_cat.value,
                        alternative="bet" if random.random() < 0.5 else "check",
                        alt_freq=0.75,
                    )

                return Decision(
                    action="bet",
                    sizing_fraction=sizing,
                    sizing_bb=None,
                    frequency=bet_freq,
                    equity=equity,
                    pot_odds=None,
                    ev=pot * sizing * (equity - 0.3),
                    reasoning=f"Semi-bluff {hand_result.description} ({equity:.0%} eq, strong draw)",
                    hand_strength=hand_cat.value,
                    alternative="check",
                    alt_freq=1 - bet_freq,
                )
            else:
                return Decision(
                    action="check",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.80,
                    equity=equity,
                    pot_odds=None,
                    ev=0,
                    reasoning=f"Check weak draw {hand_result.description} ({equity:.0%} eq)",
                    hand_strength=hand_cat.value,
                    alternative="bet",
                    alt_freq=0.20,
                )

        elif hand_cat == HandCategory.WEAK:
            return Decision(
                action="check",
                sizing_fraction=None,
                sizing_bb=None,
                frequency=0.85,
                equity=equity,
                pot_odds=None,
                ev=0,
                reasoning=f"Check weak hand {hand_result.description} ({equity:.0%} eq)",
                hand_strength=hand_cat.value,
                alternative="bet",
                alt_freq=0.15,
            )

        else:  # TRASH
            # Occasional bluff on good boards
            bluff_freq = 0.15 if texture in (BATexture.DRY, BATexture.PAIRED) and is_preflop_aggressor else 0.05
            if bluff_freq > 0.10:
                return Decision(
                    action="bet",
                    sizing_fraction=0.33,
                    sizing_bb=None,
                    frequency=bluff_freq,
                    equity=equity,
                    pot_odds=None,
                    ev=pot * 0.33 * (bluff_freq - 0.5),
                    reasoning=f"Bluff c-bet on {texture.value} board ({equity:.0%} eq, {bluff_freq:.0%} freq)",
                    hand_strength=hand_cat.value,
                    alternative="check",
                    alt_freq=1 - bluff_freq,
                )
            return Decision(
                action="check",
                sizing_fraction=None,
                sizing_bb=None,
                frequency=0.95,
                equity=equity,
                pot_odds=None,
                ev=0,
                reasoning=f"Give up — {hand_result.description} ({equity:.0%} eq)",
                hand_strength=hand_cat.value,
            )

    # ─────────────────────────────────────────
    # POSTFLOP — Facing a Bet
    # ─────────────────────────────────────────

    def _postflop_facing_bet(
        self, hole_cards, board, position, pot, bet_to_call,
        street, in_position, villain_type, villain_position,
        effective_stack, is_preflop_aggressor,
    ) -> Decision:
        """Decision when facing a bet — call, raise, or fold with real math."""

        # 1. Hand categorization
        hand_cat, hand_result = self.postflop.analyze_hand_strength(hole_cards, board)

        # 2. Pot odds
        pot_odds_result = self.odds_calc.pot_odds(bet_to_call, pot)
        required_equity = pot_odds_result.pot_odds

        # 3. Real equity vs betting range (narrower than opening range)
        villain_range = self._narrow_range_for_bet(villain_type, villain_position, street, bet_to_call, pot)
        equity_result = self.equity_calc.hand_vs_range(
            hole_cards, villain_range, board, iterations=1000
        )
        equity = equity_result.equity

        # 4. GTO MDF check
        mdf = self.gto.calculate_mdf(bet_to_call, pot)

        # 5. SPR
        spr = effective_stack / pot if pot > 0 else 10.0
        streets_left = {Street.FLOP: 3, Street.TURN: 2, Street.RIVER: 1}.get(street, 1)

        # 6. Implied odds for draws
        implied_equity = equity
        if hand_cat == HandCategory.DRAW and streets_left > 1:
            # Adjust for implied odds: draws gain ~5-10% effective equity
            implied_boost = 0.08 if villain_type in ('fish', 'lag') else 0.05
            implied_equity = equity + implied_boost

        # 7. Decision
        raise_sizing = bet_to_call * 2.5 + pot  # Standard raise size

        if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG):
            # Raise for value
            raise_freq = 0.45 if street != Street.RIVER else 0.60
            return Decision(
                action="raise",
                sizing_fraction=None,
                sizing_bb=raise_sizing,
                frequency=raise_freq,
                equity=equity,
                pot_odds=required_equity,
                ev=(pot + bet_to_call) * equity,
                reasoning=f"Raise for value with {hand_result.description} ({equity:.0%} eq vs {required_equity:.0%} needed)",
                hand_strength=hand_cat.value,
                alternative="call",
                alt_freq=1 - raise_freq,
            )

        elif hand_cat == HandCategory.STRONG:
            if equity >= required_equity + 0.10:
                # Comfortable call, consider raise
                return Decision(
                    action="call",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.85,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=(pot + bet_to_call) * equity - bet_to_call,
                    reasoning=f"Call {hand_result.description} ({equity:.0%} eq vs {required_equity:.0%} needed)",
                    hand_strength=hand_cat.value,
                    alternative="raise",
                    alt_freq=0.15,
                )
            elif equity >= required_equity:
                return Decision(
                    action="call",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.70,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=(pot + bet_to_call) * equity - bet_to_call,
                    reasoning=f"Marginal call {hand_result.description} ({equity:.0%} eq vs {required_equity:.0%} needed)",
                    hand_strength=hand_cat.value,
                    alternative="fold",
                    alt_freq=0.30,
                )
            else:
                return Decision(
                    action="fold",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.70,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=0,
                    reasoning=f"Fold {hand_result.description} — equity {equity:.0%} < pot odds {required_equity:.0%}",
                    hand_strength=hand_cat.value,
                    alternative="call",
                    alt_freq=0.30,
                )

        elif hand_cat == HandCategory.MEDIUM:
            if equity >= required_equity:
                return Decision(
                    action="call",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.60,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=(pot + bet_to_call) * equity - bet_to_call,
                    reasoning=f"Call {hand_result.description} ({equity:.0%} eq vs {required_equity:.0%} needed)",
                    hand_strength=hand_cat.value,
                    alternative="fold",
                    alt_freq=0.40,
                )
            else:
                return Decision(
                    action="fold",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.80,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=0,
                    reasoning=f"Fold {hand_result.description} — equity {equity:.0%} < needed {required_equity:.0%}",
                    hand_strength=hand_cat.value,
                    alternative="call",
                    alt_freq=0.20,
                )

        elif hand_cat == HandCategory.DRAW:
            if implied_equity >= required_equity:
                # Check-raise semi-bluff option
                if not in_position and implied_equity >= required_equity + 0.05:
                    return Decision(
                        action="raise",
                        sizing_fraction=None,
                        sizing_bb=raise_sizing,
                        frequency=0.25,
                        equity=equity,
                        pot_odds=required_equity,
                        ev=(pot + bet_to_call) * equity * 1.3,
                        reasoning=f"Semi-bluff raise {hand_result.description} ({equity:.0%} + implied = {implied_equity:.0%} vs {required_equity:.0%})",
                        hand_strength=hand_cat.value,
                        alternative="call",
                        alt_freq=0.75,
                    )
                return Decision(
                    action="call",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.80,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=(pot + bet_to_call) * implied_equity - bet_to_call,
                    reasoning=f"Call draw {hand_result.description} ({equity:.0%} + implied {implied_equity:.0%} vs {required_equity:.0%})",
                    hand_strength=hand_cat.value,
                    alternative="fold",
                    alt_freq=0.20,
                )
            else:
                return Decision(
                    action="fold",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.75,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=0,
                    reasoning=f"Fold draw — {equity:.0%} + implied {implied_equity:.0%} < needed {required_equity:.0%}",
                    hand_strength=hand_cat.value,
                    alternative="call",
                    alt_freq=0.25,
                )

        else:  # WEAK or TRASH
            if equity >= required_equity:
                return Decision(
                    action="call",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.55 if hand_cat == HandCategory.TRASH else 0.65,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=(pot + bet_to_call) * equity - bet_to_call,
                    reasoning=f"Call {hand_result.description} ({equity:.0%} eq vs {required_equity:.0%} needed)",
                    hand_strength=hand_cat.value,
                    alternative="fold",
                    alt_freq=0.45 if hand_cat == HandCategory.TRASH else 0.35,
                )
            # Occasional bluff-raise
            if hand_cat == HandCategory.WEAK and equity >= required_equity * 0.85:
                return Decision(
                    action="call",
                    sizing_fraction=None,
                    sizing_bb=None,
                    frequency=0.40,
                    equity=equity,
                    pot_odds=required_equity,
                    ev=(pot + bet_to_call) * equity - bet_to_call,
                    reasoning=f"Thin call {hand_result.description} ({equity:.0%} close to {required_equity:.0%})",
                    hand_strength=hand_cat.value,
                    alternative="fold",
                    alt_freq=0.60,
                )
            return Decision(
                action="fold",
                sizing_fraction=None,
                sizing_bb=None,
                frequency=0.95,
                equity=equity,
                pot_odds=required_equity,
                ev=0,
                reasoning=f"Fold — {hand_result.description} ({equity:.0%} eq, need {required_equity:.0%})",
                hand_strength=hand_cat.value,
            )

    # ─────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────

    def _get_villain_range(self, villain_type: str, villain_position: Optional[Position], street: Street) -> Range:
        """Estimate villain's range with empty-range guard."""
        notation = None
        if villain_position and villain_position in POSITION_RANGE_WIDTH:
            notation = POSITION_RANGE_WIDTH[villain_position]
        elif villain_type in VILLAIN_RANGES:
            notation = VILLAIN_RANGES[villain_type]
        else:
            notation = VILLAIN_RANGES['reg']

        r = Range.from_notation(notation)
        # Guard: if range is empty or too narrow, fall back to reg
        if not r.hands or len(r.hands) < 5:
            r = Range.from_notation(VILLAIN_RANGES['reg'])
        return r

    def _narrow_range_for_bet(self, villain_type: str, villain_position: Optional[Position],
                              street: Street, bet_size: float, pot: float) -> Range:
        """Narrow villain's range when they bet — scaled by bet-to-pot ratio."""
        # Bigger bets = narrower (stronger) range
        bet_pot_ratio = bet_size / pot if pot > 0 else 0.5

        # Select range based on villain type + sizing
        if villain_type == 'nit':
            if bet_pot_ratio >= 0.67:
                return Range.from_notation("AA-QQ,AKs,AKo")
            else:
                return Range.from_notation("AA-TT,AKs-ATs,KQs,AKo-AQo")
        elif villain_type == 'fish':
            return self._get_villain_range(villain_type, villain_position, street)
        elif villain_type == 'lag':
            if bet_pot_ratio >= 1.0:  # overbet = polarized
                return Range.from_notation("AA-TT,AKs-ATs,KQs,AKo,98s-65s,A5s-A2s")
            return self._get_villain_range(villain_type, villain_position, street)
        else:
            # Reg: scale by bet size
            if bet_pot_ratio >= 1.0:
                return Range.from_notation("AA-JJ,AKs,AKo,A5s-A2s")  # Polarized (value + bluffs)
            elif bet_pot_ratio >= 0.67:
                return Range.from_notation("AA-99,AKs-AJs,KQs,AKo-AQo")
            elif bet_pot_ratio >= 0.33:
                return Range.from_notation("AA-77,AKs-A8s,KQs-KTs,QJs-QTs,JTs,AKo-ATo,KQo-KJo")
            else:
                # Small bet = wide range
                return Range.from_notation("AA-55,AKs-A5s,KQs-K8s,QJs-Q9s,JTs-J9s,T9s,98s,AKo-A9o,KQo-KTo,QJo")

    def _barrel_plan(self, hand_cat: HandCategory, equity: float, streets_left: int) -> Optional[str]:
        """Generate multi-street plan text (only for future streets)."""
        if streets_left <= 1:
            return None

        if streets_left == 3:  # On flop
            if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG):
                return f"Plan: barrel turn + river for max value ({equity:.0%} eq)"
            elif hand_cat == HandCategory.STRONG and equity >= 0.60:
                return f"Plan: bet turn ~75%, evaluate river"
            elif hand_cat == HandCategory.STRONG:
                return f"Plan: consider turn bet, shut down river if called"
            elif hand_cat == HandCategory.DRAW:
                return f"Plan: barrel turn if draw hits, give up if missed"
        elif streets_left == 2:  # On turn
            if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG):
                return f"Plan: value bet river ({equity:.0%} eq)"
            elif hand_cat == HandCategory.STRONG:
                return f"Plan: thin value river if board is safe"
            elif hand_cat == HandCategory.DRAW:
                return f"Plan: if river completes draw, bet; else check/fold"
        return None
