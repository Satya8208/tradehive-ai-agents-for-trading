"""
Pro Trainer — Advanced blackjack training for real casino play

5 drills to make you table-ready:
1. Deviation Drill — Illustrious 18 mastery
2. Full-Table Speed Counting — Count entire rounds fast
3. Bet Sizing Drill — Instant bet calculation
4. Session Planner — Optimal strategy card for your casino
5. Post-Session Review — Analyze results, find leaks

Usage:
    python -m src.agents.blackjack.pro_trainer
    python -m src.agents.blackjack.pro_trainer --system omega_ii
"""

import argparse
import csv
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from termcolor import cprint, colored

from .card_counter import CardCounter, HI_LO_VALUES, OMEGA_II_VALUES, WONG_HALVES_VALUES
from .strategy_engine import (
    ILLUSTRIOUS_18, BasicStrategy, StrategyEngine, Hand as StratHand,
)
from .game_engine import Deck, GameRules
from .batch_simulator import HeadlessBetCalculator
from .casino_profiles import CASINO_PROFILES


# Deviation drill descriptions for display
DEVIATION_NAMES = {
    ('insurance', 'A', False, False): "Insurance vs Ace",
    (16, '10', False, False): "16 vs 10",
    (15, '10', False, False): "15 vs 10",
    (12, '2', False, False): "12 vs 2",
    (12, '3', False, False): "12 vs 3",
    (12, '4', False, False): "12 vs 4",
    (13, '2', False, False): "13 vs 2",
    (13, '3', False, False): "13 vs 3",
    (12, '5', False, False): "12 vs 5",
    (12, '6', False, False): "12 vs 6",
    (10, '10', False, False): "10 vs 10",
    (10, 'A', False, False): "10 vs A",
    (9, '2', False, False): "9 vs 2",
    (9, '7', False, False): "9 vs 7",
    (11, 'A', False, False): "11 vs A",
    ('10', '5', False, True): "Split 10s vs 5",
    ('10', '6', False, True): "Split 10s vs 6",
    (14, '10', False, False): "Surrender 14 vs 10",
    (14, 'A', False, False): "Surrender 14 vs A",
    (15, '9', False, False): "Surrender 15 vs 9",
}

ACTION_NAMES = {'H': 'HIT', 'S': 'STAND', 'D': 'DOUBLE', 'P': 'SPLIT', 'R': 'SURRENDER', 'Y': 'YES (Insurance)'}

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "blackjack_agent"


class ProTrainer:
    """Advanced blackjack training for real casino readiness"""

    def __init__(self, counting_system: str = 'hi_lo'):
        self.system = counting_system
        self.values = CardCounter.SYSTEMS[counting_system]
        self.basic = BasicStrategy()
        self.strategy = StrategyEngine(ai_model=None)

        # Progress tracking
        self.progress_file = DATA_DIR / "training_progress.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.progress = self._load_progress()

        # Session stats for current run
        self.session_stats: Dict[str, Dict] = {}

    def run(self) -> None:
        """Main menu"""
        system_name = {'hi_lo': 'Hi-Lo', 'omega_ii': 'Omega II', 'wong_halves': 'Wong Halves'}
        cprint(f"\n{'=' * 55}", "cyan")
        cprint("  PRO TRAINER — Real Casino Readiness", "cyan", attrs=["bold"])
        cprint(f"  Counting System: {system_name.get(self.system, self.system)}", "cyan")
        cprint(f"{'=' * 55}\n", "cyan")

        while True:
            cprint("  1. Deviation Drill (Illustrious 18)", "white")
            cprint("  2. Full-Table Speed Counting", "white")
            cprint("  3. Bet Sizing Drill", "white")
            cprint("  4. Session Planner", "white")
            cprint("  5. Post-Session Review", "white")
            cprint("  6. View Progress", "white")
            cprint("  7. Quit\n", "white")

            choice = input("  Select drill: ").strip()

            if choice == '1':
                self.deviation_drill()
            elif choice == '2':
                self.full_table_counting_drill()
            elif choice == '3':
                self.bet_sizing_drill()
            elif choice == '4':
                self.session_planner()
            elif choice == '5':
                self.post_session_review()
            elif choice == '6':
                self.view_progress()
            elif choice in ('7', 'q', 'quit'):
                self._save_progress()
                cprint("\nProgress saved. Keep grinding!", "green")
                break
            else:
                cprint("  Invalid choice\n", "red")

    # ─────────────────────────────────────────────
    # DRILL 1: Deviation Drill (Illustrious 18)
    # ─────────────────────────────────────────────

    def deviation_drill(self, num_questions: int = 20) -> None:
        """Practice Illustrious 18 count-based deviations"""
        cprint("\n=== DEVIATION DRILL (Illustrious 18) ===\n", "yellow", attrs=["bold"])
        cprint("Given hand + dealer + TC, name the correct action.", "white")
        cprint("Actions: H=Hit, S=Stand, D=Double, P=Split, R=Surrender, Y=Insurance\n", "white")

        correct = 0
        total = 0
        mistakes: List[str] = []
        dev_keys = [k for k in ILLUSTRIOUS_18.keys() if k[0] != 'insurance']
        insurance_key = ('insurance', 'A', False, False)

        for _ in range(num_questions):
            # 70% chance: test a deviation scenario, 30% chance: test basic strategy at same hand
            test_deviation = random.random() < 0.70

            if random.random() < 0.15 and test_deviation:
                # Insurance question
                action, threshold = ILLUSTRIOUS_18[insurance_key]
                if test_deviation:
                    tc = round(threshold + random.uniform(0, 3), 1)
                    correct_action = 'Y'
                else:
                    tc = round(threshold - random.uniform(1, 4), 1)
                    correct_action = 'N'

                cprint(f"  Dealer shows ACE. True Count: {tc:+.1f}", "cyan")
                cprint(f"  Take insurance? (Y/N): ", "yellow", end="")
                answer = input().strip().upper()

                if answer == correct_action:
                    correct += 1
                    cprint("  Correct!", "green")
                else:
                    cprint(f"  Wrong! Answer: {correct_action} (insurance at TC >= +{threshold:.0f})", "red")
                    mistakes.append(f"Insurance at TC {tc:+.1f}: said {answer}, correct {correct_action}")
                total += 1
                continue

            # Pick a random deviation
            key = random.choice(dev_keys)
            dev_action, threshold = ILLUSTRIOUS_18[key]
            hand_total, dealer, is_soft, is_pair = key

            if test_deviation:
                # Set TC to trigger the deviation
                if threshold < 0:
                    tc = round(threshold - random.uniform(0, 2), 1)  # More negative
                else:
                    tc = round(threshold + random.uniform(0, 3), 1)  # More positive
                expected = dev_action
            else:
                # Set TC to NOT trigger — basic strategy applies
                if threshold < 0:
                    tc = round(threshold + random.uniform(1, 4), 1)  # Above negative threshold
                else:
                    tc = round(threshold - random.uniform(1, 4), 1)  # Below positive threshold

                # Get basic strategy action for this hand
                if is_pair:
                    cards = [str(hand_total), str(hand_total)]
                else:
                    # Create a plausible hand with this total
                    cards = self._make_hand(hand_total, is_soft)
                strat_hand = StratHand(cards=cards)
                expected = self.basic.get_action(strat_hand, dealer, True, is_pair, True)

            name = DEVIATION_NAMES.get(key, f"{hand_total} vs {dealer}")
            pair_tag = " (PAIR)" if is_pair else ""
            cprint(f"  {name}{pair_tag} | TC: {tc:+.1f}", "cyan")
            cprint(f"  Action? (H/S/D/P/R): ", "yellow", end="")
            answer = input().strip().upper()

            if answer == expected:
                correct += 1
                cprint("  Correct!", "green")
            else:
                exp_name = ACTION_NAMES.get(expected, expected)
                cprint(f"  Wrong! Answer: {exp_name} (threshold: TC {threshold:+.0f})", "red")
                mistakes.append(f"{name} at TC {tc:+.1f}: said {answer}, correct {expected}")
            total += 1

        # Results
        pct = correct / total * 100 if total > 0 else 0
        print()
        color = "green" if pct >= 90 else "yellow" if pct >= 70 else "red"
        cprint(f"  Score: {correct}/{total} ({pct:.0f}%)", color, attrs=["bold"])

        if mistakes:
            cprint(f"\n  Mistakes to review:", "red")
            for m in mistakes[:5]:
                cprint(f"    - {m}", "red")

        if pct >= 95:
            cprint("  Casino ready for deviations!", "green")
        elif pct >= 80:
            cprint("  Good progress — drill daily until 95%+", "yellow")
        else:
            cprint("  Need more practice — focus on the top 6 deviations first", "red")

        self._record_drill("deviation", correct, total)

    # ─────────────────────────────────────────────
    # DRILL 2: Full-Table Speed Counting
    # ─────────────────────────────────────────────

    def full_table_counting_drill(self, num_rounds: int = 8) -> None:
        """Count cards across a full 5-6 player table"""
        cprint("\n=== FULL-TABLE SPEED COUNTING ===\n", "yellow", attrs=["bold"])

        system_name = {'hi_lo': 'Hi-Lo', 'omega_ii': 'Omega II', 'wong_halves': 'Wong Halves'}
        cprint(f"  System: {system_name.get(self.system, self.system)}", "white")
        cprint("  Count all cards per round. Give running count after each.\n", "white")

        # Speed selection
        cprint("  Speed: 1=Slow(3s) 2=Normal(2s) 3=Fast(1s) 4=Expert(0.5s)", "white")
        speed_choice = input("  Select: ").strip()
        delays = {'1': 3.0, '2': 2.0, '3': 1.0, '4': 0.5}
        delay = delays.get(speed_choice, 2.0)

        deck = Deck(num_decks=6, penetration=0.75)
        running_count = 0.0
        correct = 0
        total = 0
        times: List[float] = []

        for round_num in range(1, num_rounds + 1):
            # Deal 5-6 spots × 2 cards + dealer upcard
            num_players = random.choice([5, 6])
            num_cards = num_players * 2 + 1  # players' hands + dealer upcard
            cards = [deck.deal() for _ in range(num_cards)]

            # Calculate correct count change
            round_value = sum(self.values.get(c, 0) for c in cards)
            running_count += round_value

            cprint(f"\n  Round {round_num} ({num_players} players + dealer):", "cyan")

            # Show cards
            card_str = "  "
            for i, card in enumerate(cards):
                if i == num_players * 2:
                    card_str += " | D: "
                elif i > 0 and i % 2 == 0:
                    card_str += " | "
                card_str += f"{card} "

            cprint(card_str, "white", attrs=["bold"])
            time.sleep(delay)

            start = time.time()
            answer = input(f"  Running count? ").strip()
            elapsed = time.time() - start
            times.append(elapsed)

            try:
                user_rc = float(answer)
                tolerance = 0.5 if self.system == 'wong_halves' else 0
                if abs(user_rc - running_count) <= tolerance:
                    correct += 1
                    cprint(f"  Correct! RC={running_count:+.1f} ({elapsed:.1f}s)", "green")
                else:
                    cprint(f"  Wrong! RC={running_count:+.1f} (you said {user_rc:+.1f}) ({elapsed:.1f}s)", "red")
            except ValueError:
                cprint(f"  Invalid input. RC={running_count:+.1f}", "red")
            total += 1

            # Check shuffle
            if deck.needs_shuffle():
                deck.shuffle()
                running_count = 0
                cprint("  [SHUFFLE — count reset to 0]", "yellow")

        # Results
        pct = correct / total * 100 if total > 0 else 0
        avg_time = sum(times) / len(times) if times else 0
        print()
        color = "green" if pct >= 85 else "yellow" if pct >= 65 else "red"
        cprint(f"  Score: {correct}/{total} ({pct:.0f}%) | Avg time: {avg_time:.1f}s", color, attrs=["bold"])

        if pct >= 90 and avg_time < 3.0:
            cprint("  Table-ready counting speed!", "green")
        elif pct >= 75:
            cprint("  Accuracy good — work on speed", "yellow")
        else:
            cprint("  Keep drilling — accuracy first, then speed", "red")

        self._record_drill("full_table_counting", correct, total, {"avg_time_sec": round(avg_time, 1)})

    # ─────────────────────────────────────────────
    # DRILL 3: Bet Sizing Drill
    # ─────────────────────────────────────────────

    def bet_sizing_drill(self, num_questions: int = 10) -> None:
        """Practice instant bet calculation given TC and conditions"""
        cprint("\n=== BET SIZING DRILL ===\n", "yellow", attrs=["bold"])
        cprint("  Given TC + conditions, name the correct bet amount.\n", "white")

        correct = 0
        total = 0

        for _ in range(num_questions):
            tc = round(random.uniform(-3, 6), 1)
            bankroll = random.choice([1000, 2000, 5000, 10000, 20000])
            min_bet = random.choice([5, 10, 15, 25])
            max_bet = min_bet * random.choice([10, 15, 20])
            method = random.choice(['spread', 'spread_aggressive', 'kelly'])

            calc = HeadlessBetCalculator(
                min_bet=min_bet, max_bet=max_bet, bankroll=bankroll,
                kelly_fraction=0.5, spread_ratio=12.0, method=method,
            )
            correct_bet = calc.get_bet(tc)

            method_display = {'spread': 'Spread', 'spread_aggressive': 'Aggressive', 'kelly': 'Kelly'}
            cprint(f"  TC: {tc:+.1f} | Bankroll: ${bankroll:,} | "
                   f"Bet: ${min_bet}-${max_bet} | Method: {method_display[method]}", "cyan")
            answer = input(f"  Your bet? $").strip()

            try:
                user_bet = float(answer)
                tolerance = max(5, correct_bet * 0.10)  # ±$5 or ±10%
                if abs(user_bet - correct_bet) <= tolerance:
                    correct += 1
                    cprint(f"  Correct! (${correct_bet:.0f})", "green")
                else:
                    cprint(f"  Wrong! Correct: ${correct_bet:.0f} (you said ${user_bet:.0f})", "red")
            except ValueError:
                cprint(f"  Invalid. Correct: ${correct_bet:.0f}", "red")
            total += 1

        pct = correct / total * 100 if total > 0 else 0
        print()
        color = "green" if pct >= 80 else "yellow" if pct >= 60 else "red"
        cprint(f"  Score: {correct}/{total} ({pct:.0f}%)", color, attrs=["bold"])
        self._record_drill("bet_sizing", correct, total)

    # ─────────────────────────────────────────────
    # DRILL 4: Session Planner
    # ─────────────────────────────────────────────

    def session_planner(self) -> None:
        """Generate optimal strategy card for a casino"""
        cprint("\n=== SESSION PLANNER ===\n", "yellow", attrs=["bold"])

        # List available profiles
        cprint("  Available casino profiles:", "white")
        for i, (name, profile) in enumerate(CASINO_PROFILES.items(), 1):
            cprint(f"    {i}. {name} — {profile['description']}", "white")
        cprint(f"    {len(CASINO_PROFILES) + 1}. Custom\n", "white")

        choice = input("  Select: ").strip()
        profiles = list(CASINO_PROFILES.items())

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(profiles):
                profile_name, profile = profiles[idx]
            else:
                cprint("  Custom mode not yet implemented. Select a profile.", "yellow")
                return
        except ValueError:
            # Try by name
            if choice in CASINO_PROFILES:
                profile_name = choice
                profile = CASINO_PROFILES[choice]
            else:
                cprint("  Invalid choice", "red")
                return

        # Try to load optimization results
        tsv_path = DATA_DIR / "optimization_results.tsv"
        best_params = self._load_best_optimization(tsv_path)

        cprint(f"\n  {'=' * 50}", "cyan")
        cprint(f"  STRATEGY CARD: {profile_name.upper()}", "cyan", attrs=["bold"])
        cprint(f"  {profile['description']}", "cyan")
        cprint(f"  {'=' * 50}\n", "cyan")

        cprint(f"  Game Conditions:", "yellow")
        cprint(f"    Decks:       {profile['num_decks']}", "white")
        pen = profile.get('penetration', 0.50)
        cprint(f"    Penetration: {pen:.0%}", "white")
        h17 = profile.get('dealer_hits_soft_17', True)
        cprint(f"    Dealer:      {'H17 (hits soft 17)' if h17 else 'S17 (stands all 17s)'}", "white")
        cprint(f"    BJ pays:     {'3:2' if profile.get('blackjack_pays', 1.5) == 1.5 else '6:5'}", "white")
        cprint(f"    Surrender:   {'Yes' if profile.get('late_surrender', False) else 'No'}", "white")
        cprint(f"    DAS:         {'Yes' if profile.get('double_after_split', True) else 'No'}", "white")

        if best_params:
            cprint(f"\n  Optimal Strategy (from autoresearch):", "yellow")
            cprint(f"    Count system:  {best_params.get('counting_system', 'hi_lo')}", "green")
            cprint(f"    Bet method:    {best_params.get('betting_method', 'spread')}", "green")
            cprint(f"    Spread ratio:  {best_params.get('spread_ratio', 12.0):.0f}x", "green")
            cprint(f"    Bet ramp at:   TC +{best_params.get('bet_ramp_tc', 1.0):.1f}", "green")
            cprint(f"    Wong OUT at:   TC {best_params.get('wong_out_tc', -2.0):+.1f}", "green")
            cprint(f"    Wong IN at:    TC +{best_params.get('wong_in_tc', 1.0):.1f}", "green")
            cprint(f"    Kelly frac:    {best_params.get('kelly_fraction', 0.5):.0%}", "green")

            score = best_params.get('score', 0)
            hourly = best_params.get('hourly_rate', 0)
            cprint(f"\n  Expected Performance:", "yellow")
            cprint(f"    Score:    {score:.1f}", "white")
            cprint(f"    Hourly:   ${hourly:+.2f}/hr (at $10 min bet)", "white")
        else:
            cprint(f"\n  No optimization results found.", "yellow")
            cprint(f"  Run: python -m src.agents.blackjack.auto_optimize --profile {profile_name}", "yellow")

        cprint(f"\n  {'=' * 50}", "cyan")
        cprint(f"  Memorize this card before your session!", "cyan")
        cprint(f"  {'=' * 50}\n", "cyan")

    # ─────────────────────────────────────────────
    # DRILL 5: Post-Session Review
    # ─────────────────────────────────────────────

    def post_session_review(self) -> None:
        """Analyze a real session's results"""
        cprint("\n=== POST-SESSION REVIEW ===\n", "yellow", attrs=["bold"])
        cprint("  Enter your session results:\n", "white")

        try:
            hands = int(input("  Hands played: ").strip())
            hours = float(input("  Hours played: ").strip())
            wagered = float(input("  Total wagered ($): ").strip())
            pnl = float(input("  Net P&L ($): ").strip())
            min_bet = float(input("  Min bet ($): ").strip())
            max_bet = float(input("  Max bet ($): ").strip())
        except (ValueError, KeyboardInterrupt):
            cprint("\n  Invalid input.", "red")
            return

        # Calculate metrics
        hands_per_hour = hands / hours if hours > 0 else 0
        avg_bet = wagered / hands if hands > 0 else 0
        roi = pnl / wagered * 100 if wagered > 0 else 0
        hourly_rate = pnl / hours if hours > 0 else 0
        profit_per_hand = pnl / hands if hands > 0 else 0

        # Theoretical comparison (1% edge with counting at good pen)
        # At 50% pen: ~0.1% edge. At 75% pen: ~1% edge.
        # Conservative estimate: 0.5% average edge on action
        theoretical_edge = 0.005
        expected_pnl = wagered * theoretical_edge
        expected_hourly = expected_pnl / hours if hours > 0 else 0

        cprint(f"\n  {'=' * 45}", "cyan")
        cprint(f"  SESSION ANALYSIS", "cyan", attrs=["bold"])
        cprint(f"  {'=' * 45}\n", "cyan")

        cprint(f"  Your Results:", "yellow")
        cprint(f"    Hands:          {hands} ({hands_per_hour:.0f}/hr)", "white")
        cprint(f"    Total wagered:  ${wagered:,.0f}", "white")
        cprint(f"    Avg bet:        ${avg_bet:.0f}", "white")
        color = "green" if pnl > 0 else "red"
        cprint(f"    Net P&L:        ${pnl:+,.0f}", color)
        cprint(f"    ROI:            {roi:+.2f}%", color)
        cprint(f"    Hourly rate:    ${hourly_rate:+.1f}/hr", color)

        cprint(f"\n  Theoretical Benchmark (0.5% avg edge):", "yellow")
        cprint(f"    Expected P&L:   ${expected_pnl:+,.0f}", "white")
        cprint(f"    Expected hourly: ${expected_hourly:+.1f}/hr", "white")

        # Leak detection
        cprint(f"\n  Leak Analysis:", "yellow")
        spread = max_bet / min_bet if min_bet > 0 else 1
        if spread < 6:
            cprint(f"    Spread too tight ({spread:.0f}:1). Aim for 8:1+", "red")
        else:
            cprint(f"    Spread OK ({spread:.0f}:1)", "green")

        if avg_bet < min_bet * 1.5:
            cprint(f"    Avg bet too low — not betting enough at positive counts", "red")
        elif avg_bet > min_bet * 3:
            cprint(f"    Avg bet looks healthy", "green")

        if hands_per_hour < 50:
            cprint(f"    Slow pace ({hands_per_hour:.0f}/hr). Target: 60-80/hr", "yellow")
        elif hands_per_hour > 100:
            cprint(f"    Very fast pace — make sure counting is accurate", "yellow")

        variance = abs(pnl - expected_pnl)
        if variance > wagered * 0.05:
            cprint(f"    High variance — could be luck (good or bad). Need more hands.", "yellow")

        # Save session
        session_record = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "hands": hands, "hours": hours, "wagered": wagered,
            "pnl": pnl, "min_bet": min_bet, "max_bet": max_bet,
            "hourly_rate": round(hourly_rate, 2),
        }
        self.progress.setdefault("sessions", []).append(session_record)
        self._save_progress()
        cprint(f"\n  Session saved to progress file.", "green")

    # ─────────────────────────────────────────────
    # Progress Management
    # ─────────────────────────────────────────────

    def view_progress(self) -> None:
        """Show long-term progress"""
        cprint("\n=== TRAINING PROGRESS ===\n", "yellow", attrs=["bold"])

        drills = self.progress.get("drills", {})
        if not drills:
            cprint("  No training data yet. Start drilling!", "white")
            return

        for drill_name, records in drills.items():
            if not records:
                continue
            total_correct = sum(r["correct"] for r in records)
            total_questions = sum(r["total"] for r in records)
            pct = total_correct / total_questions * 100 if total_questions > 0 else 0

            # Last 5 sessions trend
            recent = records[-5:]
            recent_pct = sum(r["correct"] for r in recent) / sum(r["total"] for r in recent) * 100 if recent else 0

            color = "green" if recent_pct >= 85 else "yellow" if recent_pct >= 65 else "red"
            cprint(f"  {drill_name:25s} | All-time: {pct:.0f}% ({total_questions} Qs) | "
                   f"Recent: {recent_pct:.0f}% ({len(recent)} sessions)", color)

        sessions = self.progress.get("sessions", [])
        if sessions:
            total_pnl = sum(s.get("pnl", 0) for s in sessions)
            total_hours = sum(s.get("hours", 0) for s in sessions)
            cprint(f"\n  Casino Sessions: {len(sessions)} | "
                   f"Total P&L: ${total_pnl:+,.0f} | "
                   f"Hours: {total_hours:.1f}", "cyan")
        print()

    def get_progress_summary(self) -> Dict:
        """Return structured progress for dashboards and APIs."""
        drills = self.progress.get("drills", {})
        drill_summaries = {}

        for drill_name, records in drills.items():
            if not records:
                continue

            total_correct = sum(r.get("correct", 0) for r in records)
            total_questions = sum(r.get("total", 0) for r in records)
            recent = records[-5:]
            recent_correct = sum(r.get("correct", 0) for r in recent)
            recent_total = sum(r.get("total", 0) for r in recent)
            avg_time = None
            timed = [r.get("avg_time_sec") for r in recent if r.get("avg_time_sec") is not None]
            if timed:
                avg_time = round(sum(timed) / len(timed), 2)

            drill_summaries[drill_name] = {
                "sessions": len(records),
                "all_time_pct": round((total_correct / total_questions * 100), 1) if total_questions else 0.0,
                "recent_pct": round((recent_correct / recent_total * 100), 1) if recent_total else 0.0,
                "recent_avg_time_sec": avg_time,
            }

        sessions = self.progress.get("sessions", [])
        total_pnl = sum(s.get("pnl", 0) for s in sessions)
        total_hours = sum(s.get("hours", 0) for s in sessions)

        return {
            "counting_system": self.system,
            "last_updated": self.progress.get("last_updated"),
            "drills": drill_summaries,
            "sessions": {
                "count": len(sessions),
                "total_pnl": round(total_pnl, 2),
                "total_hours": round(total_hours, 2),
            },
        }

    def get_readiness_report(self) -> Dict:
        """Compute a concrete readiness score and blockers."""
        summary = self.get_progress_summary()
        drills = summary["drills"]
        readiness_weights = {
            "deviation": 0.4,
            "full_table_counting": 0.4,
            "bet_sizing": 0.2,
        }
        thresholds = {
            "deviation": 90.0,
            "full_table_counting": 85.0,
            "bet_sizing": 80.0,
        }
        certification_targets = {
            "deviation": {
                "label": "Illustrious 18 deviations",
                "target_pct": 95.0,
                "min_sessions": 3,
                "target_time_sec": None,
            },
            "full_table_counting": {
                "label": "Full-table counting",
                "target_pct": 90.0,
                "min_sessions": 3,
                "target_time_sec": 3.0,
            },
            "bet_sizing": {
                "label": "Bet sizing",
                "target_pct": 90.0,
                "min_sessions": 3,
                "target_time_sec": None,
            },
        }

        weighted_score = 0.0
        blockers = []
        recommendations = []
        completed_weight = 0.0
        drill_gaps = []

        for drill_name, weight in readiness_weights.items():
            drill = drills.get(drill_name)
            recent_pct = drill.get("recent_pct", 0.0) if drill else 0.0
            weighted_score += recent_pct * weight
            completed_weight += weight if drill else 0.0

            threshold = thresholds[drill_name]
            if not drill:
                blockers.append(f"{drill_name} has no recorded sessions")
                recommendations.append(f"Start the {drill_name.replace('_', ' ')} drill")
                continue

            if recent_pct < threshold:
                blockers.append(
                    f"{drill_name} recent accuracy {recent_pct:.0f}% is below {threshold:.0f}% target"
                )
                recommendations.append(
                    f"Focus the next session on {drill_name.replace('_', ' ')} until recent accuracy clears {threshold:.0f}%"
                )

            if drill_name == "full_table_counting":
                avg_time = drill.get("recent_avg_time_sec")
                if avg_time is None or avg_time > 3.0:
                    blockers.append("full table counting speed is not yet table-ready")
                    recommendations.append("Drill full-table counting at normal speed until average response is under 3 seconds")

            target = certification_targets[drill_name]
            pct_gap = max(0.0, target["target_pct"] - recent_pct)
            time_gap = 0.0
            if target["target_time_sec"] is not None:
                avg_time = drill.get("recent_avg_time_sec")
                if avg_time is None:
                    time_gap = 3.0
                else:
                    time_gap = max(0.0, avg_time - target["target_time_sec"]) * 10
            session_gap = max(0, target["min_sessions"] - drill.get("sessions", 0)) * 4
            drill_gaps.append((pct_gap + time_gap + session_gap, drill_name, drill))

        readiness_score = round(weighted_score if completed_weight else 0.0, 1)
        if readiness_score >= 92 and not blockers:
            level = "table_ready"
        elif readiness_score >= 80:
            level = "advanced"
        elif readiness_score >= 65:
            level = "developing"
        else:
            level = "foundation"

        certification_checks = []
        failed_checks = []
        for drill_name, target in certification_targets.items():
            drill = drills.get(drill_name, {})
            sessions = drill.get("sessions", 0)
            recent_pct = drill.get("recent_pct", 0.0)
            avg_time = drill.get("recent_avg_time_sec")
            accuracy_pass = recent_pct >= target["target_pct"]
            sessions_pass = sessions >= target["min_sessions"]
            time_pass = (
                True
                if target["target_time_sec"] is None
                else avg_time is not None and avg_time <= target["target_time_sec"]
            )
            passed = accuracy_pass and sessions_pass and time_pass

            check = {
                "drill": drill_name,
                "label": target["label"],
                "passed": passed,
                "recent_pct": recent_pct,
                "sessions": sessions,
                "target_pct": target["target_pct"],
                "min_sessions": target["min_sessions"],
                "recent_avg_time_sec": avg_time,
                "target_time_sec": target["target_time_sec"],
            }
            certification_checks.append(check)
            if not passed:
                reasons = []
                if not accuracy_pass:
                    reasons.append(f"accuracy {recent_pct:.0f}% vs target {target['target_pct']:.0f}%")
                if not sessions_pass:
                    reasons.append(f"{sessions} session(s) logged vs {target['min_sessions']} required")
                if not time_pass and target["target_time_sec"] is not None:
                    if avg_time is None:
                        reasons.append("timed reps missing")
                    else:
                        reasons.append(
                            f"speed {avg_time:.1f}s vs target {target['target_time_sec']:.1f}s"
                        )
                failed_checks.append(f"{target['label']}: " + ", ".join(reasons))

        ready_for_live_play = all(check["passed"] for check in certification_checks)
        if ready_for_live_play:
            certification_status = "certified"
        elif readiness_score >= 85:
            certification_status = "near_ready"
        else:
            certification_status = "in_training"

        practice_blocks = []
        for _, drill_name, drill in sorted(drill_gaps, reverse=True)[:3]:
            target = certification_targets[drill_name]
            current_pct = drill.get("recent_pct", 0.0) if drill else 0.0
            current_time = drill.get("recent_avg_time_sec") if drill else None
            focus = f"Push {drill_name.replace('_', ' ')} to {target['target_pct']:.0f}%+"
            if target["target_time_sec"] is not None:
                if current_time is None:
                    focus += f" and add timed reps under {target['target_time_sec']:.1f}s"
                elif current_time > target["target_time_sec"]:
                    focus += f" with timed reps under {target['target_time_sec']:.1f}s"
            practice_blocks.append(
                {
                    "drill": drill_name,
                    "label": target["label"],
                    "current_pct": current_pct,
                    "target_pct": target["target_pct"],
                    "current_time_sec": current_time,
                    "target_time_sec": target["target_time_sec"],
                    "prescription": focus,
                }
            )

        return {
            "score": readiness_score,
            "level": level,
            "blockers": blockers,
            "recommendations": recommendations[:4],
            "practice_blocks": practice_blocks,
            "certification": {
                "status": certification_status,
                "ready_for_live_play": ready_for_live_play,
                "checks": certification_checks,
                "failed_checks": failed_checks,
            },
            "summary": summary,
        }

    def build_session_plan(
        self,
        profile_name: Optional[str] = None,
        custom_profile: Optional[Dict] = None,
    ) -> Dict:
        """Build a deterministic session plan for UI/API use."""
        if custom_profile:
            profile = dict(custom_profile)
            plan_name = custom_profile.get("name", "custom")
        else:
            plan_name = profile_name or next(iter(CASINO_PROFILES))
            if plan_name not in CASINO_PROFILES:
                raise ValueError(f"Unknown profile: {plan_name}")
            profile = dict(CASINO_PROFILES[plan_name])

        best_params = self._load_best_optimization(DATA_DIR / "optimization_results.tsv")
        readiness = self.get_readiness_report()

        validation_status = "unvalidated"
        validation_notes = ["No validated optimization snapshot found for this profile yet."]

        if best_params:
            hourly_low = float(best_params.get("hourly_ci_low", 0))
            hands = int(float(best_params.get("hands", 0)))
            play_rate = float(best_params.get("play_rate", 0))

            validation_notes = []
            if hourly_low > 0 and hands >= 5000 and play_rate >= 0.35:
                validation_status = "validated"
            elif hands > 0:
                validation_status = "provisional"

            if hourly_low <= 0:
                validation_notes.append("Expected hourly confidence interval still crosses zero.")
            if hands < 5000:
                validation_notes.append("Optimization sample size is still small for real-money confidence.")
            if play_rate and play_rate < 0.35:
                validation_notes.append("Play rate is low, so the strategy may sit out too often to be practical.")
            if not validation_notes:
                validation_notes.append("Optimization snapshot cleared the current validation gate.")

        plan = {
            "profile_name": plan_name,
            "profile": profile,
            "counting_system": best_params.get("counting_system", self.system) if best_params else self.system,
            "betting_method": best_params.get("betting_method", "spread") if best_params else "spread",
            "spread_ratio": float(best_params.get("spread_ratio", 12.0)) if best_params else 12.0,
            "bet_ramp_tc": float(best_params.get("bet_ramp_tc", 1.0)) if best_params else 1.0,
            "wong_out_tc": float(best_params.get("wong_out_tc", -2.0)) if best_params else -2.0,
            "wong_in_tc": float(best_params.get("wong_in_tc", 1.0)) if best_params else 1.0,
            "kelly_fraction": float(best_params.get("kelly_fraction", 0.5)) if best_params else 0.5,
            "expected_hourly_rate": float(best_params.get("hourly_rate", 0.0)) if best_params else 0.0,
            "validation_status": validation_status,
            "validation_notes": validation_notes,
            "readiness": readiness,
            "readiness_gate": "approved" if readiness["certification"]["ready_for_live_play"] else "hold",
            "operator_note": (
                "Training standards cleared for live use."
                if readiness["certification"]["ready_for_live_play"]
                else "Do not trust this plan live until certification blockers are cleared."
            ),
        }
        return plan

    def analyze_session(
        self,
        hands: int,
        hours: float,
        wagered: float,
        pnl: float,
        min_bet: float,
        max_bet: float,
        save: bool = True,
    ) -> Dict:
        """Analyze a session without using interactive input."""
        hands_per_hour = hands / hours if hours > 0 else 0.0
        avg_bet = wagered / hands if hands > 0 else 0.0
        roi = pnl / wagered * 100 if wagered > 0 else 0.0
        hourly_rate = pnl / hours if hours > 0 else 0.0
        theoretical_edge = 0.005
        expected_pnl = wagered * theoretical_edge
        expected_hourly = expected_pnl / hours if hours > 0 else 0.0
        spread = max_bet / min_bet if min_bet > 0 else 1.0

        leaks = []
        strengths = []

        if spread < 6:
            leaks.append(f"Spread is tight at {spread:.1f}:1; target 8:1 or better where conditions allow.")
        else:
            strengths.append(f"Spread is workable at {spread:.1f}:1.")

        if avg_bet < min_bet * 1.5:
            leaks.append("Average bet suggests you are not pressing enough at positive counts.")
        else:
            strengths.append("Average bet level suggests you are actually scaling up when advantage appears.")

        if hands_per_hour < 50:
            leaks.append("Pace is slow; target 60-80 hands/hour.")
        elif hands_per_hour > 100:
            leaks.append("Pace is very fast; make sure counting accuracy is not dropping.")
        else:
            strengths.append("Session pace was in a practical live range.")

        if abs(pnl - expected_pnl) > wagered * 0.05:
            leaks.append("Observed result is far from theoretical expectation; variance may dominate this sample.")

        analysis = {
            "metrics": {
                "hands": hands,
                "hours": hours,
                "hands_per_hour": round(hands_per_hour, 1),
                "wagered": wagered,
                "avg_bet": round(avg_bet, 2),
                "pnl": pnl,
                "roi_pct": round(roi, 2),
                "hourly_rate": round(hourly_rate, 2),
            },
            "benchmark": {
                "expected_pnl": round(expected_pnl, 2),
                "expected_hourly_rate": round(expected_hourly, 2),
                "theoretical_edge_pct": theoretical_edge * 100,
            },
            "discipline_score": round(
                max(
                    0.0,
                    min(
                        100.0,
                        100.0
                        - (10.0 if spread < 6 else 0.0)
                        - (8.0 if avg_bet < min_bet * 1.5 else 0.0)
                        - (8.0 if hands_per_hour < 50 or hands_per_hour > 100 else 0.0),
                    ),
                ),
                1,
            ),
            "leaks": leaks,
            "strengths": strengths,
            "next_drills": self._session_next_drills(leaks),
            "validation_status": "provisional" if hands < 500 else "validated",
        }

        if save:
            session_record = {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "hands": hands,
                "hours": hours,
                "wagered": wagered,
                "pnl": pnl,
                "min_bet": min_bet,
                "max_bet": max_bet,
                "hourly_rate": round(hourly_rate, 2),
            }
            self.progress.setdefault("sessions", []).append(session_record)
            self._save_progress()

        return analysis

    def _session_next_drills(self, leaks: List[str]) -> List[str]:
        """Map observed session leaks back into specific drill recommendations."""
        drill_map = []
        leak_text = " ".join(leaks).lower()
        if "spread" in leak_text or "average bet" in leak_text:
            drill_map.append("bet_sizing")
        if "pace" in leak_text:
            drill_map.append("full_table_counting")
        if "variance" in leak_text or "expectation" in leak_text:
            drill_map.append("session_planning_review")
        return drill_map or ["full_table_counting", "deviation"]

    def _record_drill(self, drill_name: str, correct: int, total: int, extra: Dict = None) -> None:
        """Record drill results to progress"""
        record = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "correct": correct,
            "total": total,
        }
        if extra:
            record.update(extra)

        self.progress.setdefault("drills", {}).setdefault(drill_name, []).append(record)
        self._save_progress()

    def _load_progress(self) -> Dict:
        """Load training progress from JSON"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"drills": {}, "sessions": []}

    def _save_progress(self) -> None:
        """Save training progress to JSON"""
        self.progress["last_updated"] = datetime.now().isoformat()
        self.progress["counting_system"] = self.system
        with open(self.progress_file, "w") as f:
            json.dump(self.progress, f, indent=2)

    def _load_best_optimization(self, tsv_path: Path) -> Optional[Dict]:
        """Load best parameters from auto_optimize results TSV"""
        if not tsv_path.exists():
            return None

        best_score = float('-inf')
        best_row = None

        try:
            with open(tsv_path) as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    if row.get('status') in ('keep', 'baseline'):
                        score = float(row.get('score', 0))
                        if score > best_score:
                            best_score = score
                            best_row = row
        except (IOError, csv.Error):
            return None

        if not best_row:
            return None

        # Parse params from the row
        result = {
            'score': float(best_row.get('score', 0)),
            'hourly_rate': float(best_row.get('hourly_rate', 0)),
            'win_rate': float(best_row.get('win_rate', 0)),
        }

        # Newer optimizer runs persist the full winning parameter snapshot.
        params_json = best_row.get('params_snapshot') or best_row.get('params_changed', '{}')
        try:
            params = json.loads(params_json)
            for k, v in params.items():
                if isinstance(v, dict) and 'new' in v:
                    result[k] = v['new']
                else:
                    result[k] = v
        except (json.JSONDecodeError, TypeError):
            pass

        return result

    def _make_hand(self, total: int, is_soft: bool) -> List[str]:
        """Create a plausible hand with the given total"""
        if is_soft:
            other = total - 11
            return ['A', str(max(2, min(9, other)))]
        elif total <= 11:
            return [str(max(2, total - 2)), '2']
        else:
            high = min(10, total - 2)
            low = total - high
            if low > 10:
                return ['10', str(total - 10)]
            return [str(high) if high <= 9 else '10', str(max(2, low))]


# Standalone entry point
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BJ Pro Trainer — Real Casino Readiness")
    parser.add_argument("--system", type=str, default="hi_lo",
                        choices=["hi_lo", "omega_ii", "wong_halves"],
                        help="Counting system to train")
    args = parser.parse_args()

    trainer = ProTrainer(counting_system=args.system)
    trainer.run()
