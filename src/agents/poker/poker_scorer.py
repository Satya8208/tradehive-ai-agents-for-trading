"""
Poker Scorer — ParamSet + scoring for poker autoresearch

Runs headless poker simulations with parameterized strategy
to evaluate different strategy configurations.

Usage:
    python -m src.agents.poker.poker_scorer
"""

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .game_engine import GameEngine, Action, Player
from .core.hand_evaluator import Card, Rank, Suit
from .strategy.preflop_engine import PreflopEngine, Position, FacingAction


@dataclass
class PokerParamSet:
    """Tunable poker strategy parameters"""

    # === Preflop RFI percentages by position (what % of hands to open) ===
    rfi_utg_pct: float = 12.0       # 8–18
    rfi_mp_pct: float = 16.0        # 12–22
    rfi_co_pct: float = 25.0        # 20–35
    rfi_btn_pct: float = 40.0       # 30–55
    rfi_sb_pct: float = 35.0        # 25–50

    # === 3-bet frequencies ===
    three_bet_vs_ep: float = 5.0    # 3–10
    three_bet_vs_lp: float = 10.0   # 6–18

    # === Postflop frequencies ===
    cbet_freq: float = 0.65          # 0.40–0.85
    cbet_size_pct: float = 0.50      # 0.25–0.75 (% of pot)
    turn_barrel_freq: float = 0.45   # 0.25–0.65
    river_bet_freq: float = 0.35     # 0.20–0.55

    # === Aggression ===
    raise_vs_bet_freq: float = 0.15  # 0.05–0.30
    bluff_ratio: float = 0.30        # 0.15–0.45


@dataclass
class PokerBacktestResult:
    """Metrics from a poker simulation"""
    hands_played: int = 0
    total_pnl: float = 0.0
    bb_per_100: float = 0.0
    win_rate: float = 0.0           # % of hands won at showdown
    vpip: float = 0.0              # % of hands voluntarily put $ in pot
    pfr: float = 0.0               # % of hands raised preflop
    max_drawdown: float = 0.0
    showdowns: int = 0
    showdowns_won: int = 0
    hand_errors: int = 0
    session_bb_per_100: List[float] = field(default_factory=list)
    bb_per_100_stddev: float = 0.0
    bb_per_100_ci_low: float = 0.0
    bb_per_100_ci_high: float = 0.0
    score: float = 0.0


# Hand strength buckets (simplified — rank 1-7462, lower is better)
PREMIUM_THRESHOLD = 1000    # Top ~13% hands (strong pairs, top flush, etc.)
STRONG_THRESHOLD = 2500     # Top ~33%
MEDIUM_THRESHOLD = 4000     # Top ~53%


class PokerScorer:
    """
    Scores a PokerParamSet by running headless poker simulations.

    Creates a 6-player table: 1 hero (parameterized) + 5 bots (default tight-passive).
    Runs N hands, measures bb/100.
    """

    def __init__(
        self,
        num_hands: int = 2000,
        num_sessions: int = 3,
        base_seed: int = 42,
        raise_on_hand_error: bool = False,
    ):
        self.num_hands = num_hands
        self.num_sessions = num_sessions
        self.base_seed = base_seed
        self.raise_on_hand_error = raise_on_hand_error

    def score(self, params: PokerParamSet) -> PokerBacktestResult:
        """Run simulation(s) and return scored result."""
        total_pnl = 0.0
        total_hands = 0
        total_vpip = 0
        total_pfr = 0
        total_showdowns = 0
        total_sd_won = 0
        max_dd = 0.0
        total_errors = 0
        session_bb_per_100: List[float] = []

        for session_idx in range(self.num_sessions):
            seed = self.base_seed + session_idx
            result = self._run_session(params, self.num_hands, seed)
            total_pnl += result['pnl']
            total_hands += result['hands']
            total_vpip += result['vpip_count']
            total_pfr += result['pfr_count']
            total_showdowns += result['showdowns']
            total_sd_won += result['sd_won']
            total_errors += result['hand_errors']
            if result['max_dd'] > max_dd:
                max_dd = result['max_dd']
            if result['hands'] > 0:
                session_bb_per_100.append(result['pnl'] / result['hands'] * 100)
            else:
                session_bb_per_100.append(0.0)

        # Build result
        out = PokerBacktestResult()
        out.hands_played = total_hands
        out.total_pnl = total_pnl
        out.hand_errors = total_errors
        out.session_bb_per_100 = session_bb_per_100

        if total_hands > 0:
            out.bb_per_100 = (total_pnl / 1.0) / total_hands * 100  # BB = 1.0
            out.vpip = total_vpip / total_hands * 100
            out.pfr = total_pfr / total_hands * 100
        if total_showdowns > 0:
            out.win_rate = total_sd_won / total_showdowns * 100
        out.showdowns = total_showdowns
        out.showdowns_won = total_sd_won
        out.max_drawdown = max_dd
        if len(session_bb_per_100) > 1:
            out.bb_per_100_stddev = statistics.stdev(session_bb_per_100)
            margin = 1.96 * out.bb_per_100_stddev / math.sqrt(len(session_bb_per_100))
            out.bb_per_100_ci_low = out.bb_per_100 - margin
            out.bb_per_100_ci_high = out.bb_per_100 + margin
        elif session_bb_per_100:
            out.bb_per_100_ci_low = out.bb_per_100
            out.bb_per_100_ci_high = out.bb_per_100
        out.score = self._compute_score(out)
        return out

    def _run_session(self, params: PokerParamSet, num_hands: int, seed: int) -> Dict:
        """Run a single session of N hands."""
        saved_state = random.getstate()
        random.seed(seed)

        engine = GameEngine(num_seats=6, small_blind=0.5, big_blind=1.0)

        # Add players: hero (seat 0) + 5 bots
        hero_start = 100.0
        engine.add_player("Hero", seat=0, stack=hero_start)
        for i in range(1, 6):
            engine.add_player(f"Bot{i}", seat=i, stack=100.0)

        preflop_engine = PreflopEngine()
        hero_pnl_history = []
        cumulative_pnl = 0.0
        peak_pnl = 0.0
        max_dd = 0.0
        vpip_count = 0
        pfr_count = 0
        showdowns = 0
        sd_won = 0
        hands_completed = 0
        hand_errors = 0

        try:
            for _ in range(num_hands):
                # Reset stacks if anyone is busted (keep game going)
                for seat, player in engine.players.items():
                    if player.stack < 2.0:
                        player.stack = 100.0

                hero_stack_before = engine.players[0].stack

                # Build action callback
                def get_action(seat: int, state: Dict) -> Tuple[Action, float]:
                    nonlocal vpip_count, pfr_count
                    player_state = state['players'].get(seat, {})
                    current_bet = state['current_bet']
                    player_bet = player_state.get('bet', 0)
                    stack = player_state.get('stack', 0)
                    position_name = player_state.get('position', 'MP')

                    if seat == 0:
                        # HERO — use parameterized strategy
                        return self._hero_action(
                            engine, seat, state, params, preflop_engine,
                        )
                    # BOTS — simple tight-passive strategy
                    return self._bot_action(seat, state, engine)

                try:
                    history = engine.run_hand(get_action)
                    hands_completed += 1

                    # Track hero P&L
                    hero_stack_after = engine.players[0].stack
                    hand_pnl = hero_stack_after - hero_stack_before
                    cumulative_pnl += hand_pnl

                    if cumulative_pnl > peak_pnl:
                        peak_pnl = cumulative_pnl
                    dd = (peak_pnl - cumulative_pnl) / max(hero_start, 1)
                    if dd > max_dd:
                        max_dd = dd

                    # Track showdown
                    if len(history.winners) > 0 and len([p for p in engine.players.values() if not p.has_folded]) > 1:
                        showdowns += 1
                        if "Hero" in history.winners:
                            sd_won += 1

                    # Track VPIP/PFR from actions
                    for act in history.actions:
                        if act['player'] == 'Hero' and act['street'] == 'preflop':
                            if act['action'] in ('call', 'raise', 'bet', 'all_in'):
                                vpip_count += 1
                            if act['action'] in ('raise', 'bet'):
                                pfr_count += 1
                            break  # Only count first preflop action

                except Exception as exc:
                    hand_errors += 1
                    if self.raise_on_hand_error:
                        raise RuntimeError(f"Poker simulation hand failed at seed={seed}") from exc
                    continue
        finally:
            random.setstate(saved_state)

        return {
            'pnl': cumulative_pnl,
            'hands': hands_completed,
            'vpip_count': vpip_count,
            'pfr_count': pfr_count,
            'showdowns': showdowns,
            'sd_won': sd_won,
            'max_dd': max_dd,
            'hand_errors': hand_errors,
        }

    def _hero_action(self, engine: GameEngine, seat: int, state: Dict,
                     params: PokerParamSet, preflop_engine: PreflopEngine) -> Tuple[Action, float]:
        """Hero's parameterized action."""
        current_bet = state['current_bet']
        player_state = state['players'].get(seat, {})
        player_bet = player_state.get('bet', 0)
        stack = player_state.get('stack', 0)
        position_name = player_state.get('position', 'MP')
        street = state['street']

        hero = engine.players[seat]

        if street == 'preflop':
            return self._hero_preflop(hero, engine, params, current_bet, player_bet, stack, position_name)
        else:
            return self._hero_postflop(hero, engine, params, current_bet, player_bet, stack, street)

    def _hero_preflop(self, hero: Player, engine: GameEngine, params: PokerParamSet,
                      current_bet: float, player_bet: float, stack: float,
                      position_name: str) -> Tuple[Action, float]:
        """Hero preflop decision based on params."""
        # Get RFI % for our position
        rfi_pct_map = {
            'UTG': params.rfi_utg_pct, 'UTG1': params.rfi_utg_pct,
            'MP': params.rfi_mp_pct, 'HJ': params.rfi_mp_pct,
            'CO': params.rfi_co_pct, 'BTN': params.rfi_btn_pct,
            'SB': params.rfi_sb_pct, 'BB': 100.0,  # BB defends
        }
        rfi_pct = rfi_pct_map.get(position_name, params.rfi_mp_pct)

        # Simple hand strength: estimate percentile from card ranks
        hand_strength = self._estimate_hand_strength(hero.hole_cards)

        if current_bet <= 1.0:
            # Unopened or just blinds — RFI decision
            if hand_strength <= rfi_pct:
                # Raise
                raise_size = current_bet * 2.5 + current_bet
                return Action.RAISE, min(raise_size, stack + player_bet)
            elif position_name == 'BB' and current_bet <= 1.0:
                return Action.CHECK, 0
            else:
                return Action.FOLD, 0
        else:
            # Facing a raise — tighter range
            defend_pct = rfi_pct * 0.6  # Defend ~60% of opening range
            three_bet_pct = params.three_bet_vs_lp if position_name in ('CO', 'BTN', 'SB', 'BB') else params.three_bet_vs_ep

            if hand_strength <= three_bet_pct:
                # 3-bet
                raise_size = current_bet * 3
                return Action.RAISE, min(raise_size, stack + player_bet)
            elif hand_strength <= defend_pct:
                return Action.CALL, 0
            else:
                return Action.FOLD, 0

    def _hero_postflop(self, hero: Player, engine: GameEngine, params: PokerParamSet,
                       current_bet: float, player_bet: float, stack: float,
                       street: str) -> Tuple[Action, float]:
        """Hero postflop decision based on params."""
        # Evaluate hand strength on board
        from .core.hand_evaluator import HandEvaluator
        he = HandEvaluator()
        if engine.board:
            result = he.evaluate(hero.hole_cards, engine.board)
            hand_rank = result.score  # 1 = best, 7462 = worst
        else:
            hand_rank = 4000  # default middle

        pot = sum(p.amount for p in engine.pots)

        if current_bet <= player_bet:
            # We can check or bet
            # Decide to bet based on hand strength + params
            bet_freq = params.cbet_freq if street == 'flop' else (
                params.turn_barrel_freq if street == 'turn' else params.river_bet_freq
            )

            should_bet = (hand_rank < STRONG_THRESHOLD) or (random.random() < params.bluff_ratio * bet_freq)

            if should_bet and random.random() < bet_freq:
                bet_size = pot * params.cbet_size_pct
                bet_size = max(1.0, min(bet_size, stack))
                return Action.BET, player_bet + bet_size
            else:
                return Action.CHECK, 0
        else:
            # Facing a bet — decide to call, raise, or fold
            to_call = current_bet - player_bet
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0

            if hand_rank < PREMIUM_THRESHOLD:
                # Strong hand — raise sometimes
                if random.random() < params.raise_vs_bet_freq:
                    raise_size = current_bet * 2.5
                    return Action.RAISE, min(raise_size, stack + player_bet)
                return Action.CALL, 0
            elif hand_rank < MEDIUM_THRESHOLD:
                # Decent hand — call if odds are right
                if pot_odds < 0.35:
                    return Action.CALL, 0
                return Action.FOLD, 0
            else:
                # Weak hand — mostly fold, occasional bluff raise
                if random.random() < params.bluff_ratio * 0.1:
                    raise_size = current_bet * 2.5
                    return Action.RAISE, min(raise_size, stack + player_bet)
                return Action.FOLD, 0

    def _bot_action(self, seat: int, state: Dict, engine: GameEngine) -> Tuple[Action, float]:
        """Simple tight-passive bot for opponents."""
        player_state = state['players'].get(seat, {})
        current_bet = state['current_bet']
        player_bet = player_state.get('bet', 0)
        stack = player_state.get('stack', 0)

        player = engine.players[seat]

        if state['street'] == 'preflop':
            hand_strength = self._estimate_hand_strength(player.hole_cards)
            if current_bet <= 1.0:
                # Unopened — open top 20%
                if hand_strength <= 20:
                    return Action.RAISE, min(3.0, stack + player_bet)
                elif player_bet >= 0.5:  # Already in for blind
                    return Action.CALL, 0 if current_bet <= 1.0 else Action.FOLD
                return Action.FOLD, 0
            else:
                # Facing raise — call top 15%, fold rest
                if hand_strength <= 15:
                    return Action.CALL, 0
                return Action.FOLD, 0
        else:
            # Postflop — passive play
            if current_bet <= player_bet:
                return Action.CHECK, 0
            else:
                # Call with decent hands, fold weak
                if player.hole_cards and engine.board:
                    from .core.hand_evaluator import HandEvaluator
                    he = HandEvaluator()
                    result = he.evaluate(player.hole_cards, engine.board)
                    if result.score < STRONG_THRESHOLD:
                        return Action.CALL, 0
                return Action.FOLD, 0

    def _estimate_hand_strength(self, cards: list) -> float:
        """
        Estimate preflop hand strength as a percentile (0 = best, 100 = worst).
        Simple rank-based heuristic.
        """
        if not cards or len(cards) < 2:
            return 50.0

        c1, c2 = cards[0], cards[1]
        r1, r2 = c1.rank.value, c2.rank.value

        # Higher rank value = higher card (Ace=14)
        high = max(r1, r2)
        low = min(r1, r2)
        suited = c1.suit == c2.suit
        paired = r1 == r2

        # Simple scoring: pairs are strong, high cards strong, suited bonus
        if paired:
            # AA=1, KK=2, ..., 22=13
            return max(1, 14 - high)
        else:
            # AKs ≈ 5, AKo ≈ 8, 72o ≈ 95
            gap = high - low
            base = (14 - high) * 5 + gap * 3
            if suited:
                base -= 5
            return max(3, min(95, base))

    def _compute_score(self, result: PokerBacktestResult) -> float:
        """Composite score balancing profit and reasonable play."""
        if result.hands_played == 0:
            return -999.0

        # Primary: bb/100
        base = result.bb_per_100 * 10

        # Drawdown penalty
        dd_penalty = max(1.0 - result.max_drawdown, 0.1)

        # VPIP sanity: penalize if outside 18-35% range
        vpip_penalty = 1.0
        if result.vpip < 15 or result.vpip > 40:
            vpip_penalty = 0.7

        confidence_penalty = 1.0 if result.bb_per_100_ci_low > 0 else 0.6
        error_penalty = 1.0 if result.hand_errors == 0 else 0.5
        score = base * dd_penalty * vpip_penalty * confidence_penalty * error_penalty
        return round(score, 2)


# Standalone test
if __name__ == "__main__":
    from termcolor import cprint
    import time

    cprint("\n=== Poker Scorer Test ===\n", "cyan", attrs=["bold"])

    scorer = PokerScorer(num_hands=500, num_sessions=3, base_seed=42)
    params = PokerParamSet()

    cprint("Scoring default params (500 hands x 3 sessions)...", "white")
    start = time.time()
    result = scorer.score(params)
    elapsed = time.time() - start

    cprint(f"\nResults ({result.hands_played} hands, {elapsed:.1f}s):", "yellow")
    cprint(f"  BB/100:      {result.bb_per_100:+.1f}", "green" if result.bb_per_100 > 0 else "red")
    cprint(f"  Total P&L:   ${result.total_pnl:+.1f} BB", "white")
    cprint(f"  VPIP:        {result.vpip:.1f}%", "white")
    cprint(f"  PFR:         {result.pfr:.1f}%", "white")
    cprint(f"  Showdowns:   {result.showdowns} ({result.showdowns_won} won)", "white")
    cprint(f"  95% CI:      {result.bb_per_100_ci_low:+.1f} to {result.bb_per_100_ci_high:+.1f}", "white")
    cprint(f"  Hand errors: {result.hand_errors}", "white")
    cprint(f"  Max DD:      {result.max_drawdown:.1%}", "white")
    cprint(f"  SCORE:       {result.score:.2f}", "cyan", attrs=["bold"])
