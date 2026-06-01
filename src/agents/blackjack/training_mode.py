"""
Training Mode - Practice drills for basic strategy and card counting
Built with love by TradeHive
"""

import sys
import random
import time
from pathlib import Path
from typing import List, Tuple, Dict
from termcolor import cprint, colored

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from .card_counter import CardCounter, HI_LO_VALUES
from .strategy_engine import BasicStrategy, Hand
from .game_engine import Deck


class TrainingMode:
    """
    Practice drills for becoming a blackjack god

    Drills:
    1. Basic Strategy - Practice correct decisions
    2. Card Counting - Speed counting practice
    3. True Count - RC to TC conversion
    4. Deviations - Illustrious 18 practice
    """

    def __init__(self):
        self.strategy = BasicStrategy()
        self.counter = CardCounter('hi_lo', num_decks=6)

        # Training stats
        self.stats = {
            'strategy_correct': 0,
            'strategy_total': 0,
            'counting_correct': 0,
            'counting_total': 0,
            'true_count_correct': 0,
            'true_count_total': 0
        }

    def run(self) -> None:
        """Main training menu"""
        cprint("\n" + "=" * 50, "cyan")
        cprint("  BLACKJACK GOD - TRAINING MODE", "cyan", attrs=['bold'])
        cprint("=" * 50, "cyan")

        while True:
            print("\nSelect a drill:")
            print("  1. Basic Strategy Practice")
            print("  2. Card Counting Speed Drill")
            print("  3. True Count Calculation")
            print("  4. Mixed Training (All)")
            print("  5. Pro Training (Advanced)")
            print("  6. View Stats")
            print("  7. Exit")

            choice = input("\nChoice (1-7): ").strip()

            if choice == '1':
                self.basic_strategy_drill()
            elif choice == '2':
                self.counting_speed_drill()
            elif choice == '3':
                self.true_count_drill()
            elif choice == '4':
                self.mixed_training()
            elif choice == '5':
                from .pro_trainer import ProTrainer
                ProTrainer(counting_system=self.counter.system).run()
            elif choice == '6':
                self.show_stats()
            elif choice == '7':
                cprint("\nGoodbye! Keep practicing!", "cyan")
                break
            else:
                cprint("Invalid choice", "red")

    def basic_strategy_drill(self, num_hands: int = 20) -> None:
        """
        Practice making correct basic strategy decisions

        Args:
            num_hands: Number of hands to practice
        """
        cprint("\n=== BASIC STRATEGY DRILL ===", "yellow", attrs=['bold'])
        cprint(f"Practice {num_hands} hands. Enter: H(it), S(tand), D(ouble), P(split), R(surrender)\n", "white")

        correct = 0
        total = 0
        mistakes: List[Tuple] = []

        for i in range(num_hands):
            # Generate random hand
            hand, dealer_upcard = self._generate_random_hand()
            correct_action = self.strategy.get_action(hand, dealer_upcard)

            # Display hand
            cprint(f"Hand {i+1}/{num_hands}", "cyan")
            print(f"  Your hand: {hand.cards} = {hand.value}" +
                  (f" (Soft)" if hand.is_soft else "") +
                  (f" (Pair)" if hand.is_pair else ""))
            print(f"  Dealer shows: {dealer_upcard}")

            # Get user input
            user_action = input("  Your action: ").strip().upper()

            if not user_action:
                user_action = 'H'
            user_action = user_action[0]

            total += 1

            if user_action == correct_action:
                cprint("  CORRECT!", "green", attrs=['bold'])
                correct += 1
            else:
                cprint(f"  WRONG! Correct: {self._action_name(correct_action)}", "red")
                mistakes.append((hand.cards, hand.value, dealer_upcard, correct_action))

            print()

        # Show results
        accuracy = (correct / total * 100) if total > 0 else 0
        self.stats['strategy_correct'] += correct
        self.stats['strategy_total'] += total

        cprint("=" * 40, "yellow")
        cprint(f"Results: {correct}/{total} correct ({accuracy:.1f}%)", "cyan", attrs=['bold'])

        if mistakes:
            cprint("\nMistakes to review:", "red")
            for cards, value, dealer, action in mistakes[:5]:
                print(f"  {cards}={value} vs {dealer} -> {self._action_name(action)}")

        if accuracy >= 95:
            cprint("\nExcellent! You're ready for the tables!", "green", attrs=['bold'])
        elif accuracy >= 80:
            cprint("\nGood progress! Keep practicing.", "yellow")
        else:
            cprint("\nNeed more practice. Review basic strategy charts.", "red")

    def counting_speed_drill(self, speed: str = 'normal') -> None:
        """
        Practice card counting speed

        Args:
            speed: Drill speed (slow, normal, fast, expert)
        """
        speeds = {
            'slow': 2.5,
            'normal': 1.5,
            'fast': 0.8,
            'expert': 0.4
        }

        cprint("\n=== CARD COUNTING SPEED DRILL ===", "magenta", attrs=['bold'])
        print("\nSelect speed:")
        print("  1. Slow (2.5s per card)")
        print("  2. Normal (1.5s per card)")
        print("  3. Fast (0.8s per card)")
        print("  4. Expert (0.4s per card)")

        speed_choice = input("\nChoice (1-4): ").strip()
        speed_map = {'1': 'slow', '2': 'normal', '3': 'fast', '4': 'expert'}
        speed = speed_map.get(speed_choice, 'normal')
        delay = speeds[speed]

        cprint(f"\nSpeed: {speed.upper()} ({delay}s per card)", "cyan")
        cprint("Cards will flash. Track the running count.", "white")
        cprint("Press Enter to start...", "yellow")
        input()

        # Deal cards
        deck = Deck(num_decks=1)
        correct_count = 0
        cards_shown = []

        num_cards = random.randint(15, 25)

        for i in range(num_cards):
            card = deck.deal()
            cards_shown.append(card)

            # Update correct count
            value = HI_LO_VALUES.get(card, 0)
            correct_count += value

            # Display card
            print(f"\r  {colored(f'[{card:>2}]', 'yellow', attrs=['bold'])}  ", end='', flush=True)
            time.sleep(delay)
            print(f"\r       ", end='', flush=True)

        print()

        # Get user count
        try:
            user_count = int(input("\nRunning count? "))
        except ValueError:
            user_count = 0

        # Check result
        self.stats['counting_total'] += 1

        if user_count == correct_count:
            cprint(f"\nPERFECT! Count is {correct_count}", "green", attrs=['bold'])
            self.stats['counting_correct'] += 1
        else:
            diff = abs(user_count - correct_count)
            cprint(f"\nOff by {diff}. Correct count: {correct_count}", "red")
            cprint(f"Cards were: {' '.join(cards_shown)}", "yellow")

    def true_count_drill(self, num_questions: int = 10) -> None:
        """
        Practice converting running count to true count

        Args:
            num_questions: Number of questions
        """
        cprint("\n=== TRUE COUNT DRILL ===", "cyan", attrs=['bold'])
        cprint("Convert running count to true count (RC / decks remaining)\n", "white")

        correct = 0

        for i in range(num_questions):
            # Generate random scenario
            running_count = random.randint(-12, 15)
            decks_remaining = random.choice([1, 1.5, 2, 2.5, 3, 4, 5, 6])
            true_count = running_count / decks_remaining

            print(f"Question {i+1}/{num_questions}")
            print(f"  Running Count: {running_count:+d}")
            print(f"  Decks Remaining: {decks_remaining}")

            try:
                user_tc = float(input("  True Count? "))
            except ValueError:
                user_tc = 0

            self.stats['true_count_total'] += 1

            # Allow some tolerance
            if abs(user_tc - true_count) < 0.5:
                cprint(f"  CORRECT! TC = {true_count:+.1f}", "green")
                correct += 1
                self.stats['true_count_correct'] += 1
            else:
                cprint(f"  WRONG. TC = {true_count:+.1f} (you said {user_tc:+.1f})", "red")

            print()

        accuracy = (correct / num_questions * 100)
        cprint(f"Results: {correct}/{num_questions} ({accuracy:.0f}%)", "cyan", attrs=['bold'])

    def mixed_training(self) -> None:
        """Run a mixed training session"""
        cprint("\n=== MIXED TRAINING SESSION ===", "green", attrs=['bold'])
        cprint("Random mix of all drills for 5 minutes\n", "white")

        drills = [
            ('strategy', self._quick_strategy_question),
            ('counting', self._quick_counting_question),
            ('true_count', self._quick_true_count_question)
        ]

        start_time = time.time()
        duration = 300  # 5 minutes
        questions = 0
        correct = 0

        try:
            while time.time() - start_time < duration:
                # Random drill
                drill_name, drill_func = random.choice(drills)
                result = drill_func()

                questions += 1
                if result:
                    correct += 1

                # Show progress
                elapsed = int(time.time() - start_time)
                remaining = duration - elapsed
                print(f"\n  [{remaining//60}:{remaining%60:02d} remaining] "
                      f"Score: {correct}/{questions} ({correct/questions*100:.0f}%)\n")

                time.sleep(0.5)

        except KeyboardInterrupt:
            pass

        cprint("\n" + "=" * 40, "green")
        cprint(f"Session complete! {correct}/{questions} correct", "cyan", attrs=['bold'])

    def _quick_strategy_question(self) -> bool:
        """Single quick strategy question"""
        hand, dealer = self._generate_random_hand()
        correct_action = self.strategy.get_action(hand, dealer)

        cprint("[STRATEGY]", "yellow")
        print(f"  {hand.cards}={hand.value} vs {dealer}")
        user = input("  Action? ").strip().upper()
        user = user[0] if user else 'H'

        self.stats['strategy_total'] += 1
        if user == correct_action:
            cprint("  Correct!", "green")
            self.stats['strategy_correct'] += 1
            return True
        else:
            cprint(f"  Wrong! -> {self._action_name(correct_action)}", "red")
            return False

    def _quick_counting_question(self) -> bool:
        """Single quick counting question"""
        cards = [random.choice(list(HI_LO_VALUES.keys())) for _ in range(5)]
        correct = sum(HI_LO_VALUES[c] for c in cards)

        cprint("[COUNTING]", "magenta")
        print(f"  Cards: {' '.join(cards)}")

        try:
            user = int(input("  Count? "))
        except ValueError:
            user = 0

        self.stats['counting_total'] += 1
        if user == correct:
            cprint("  Correct!", "green")
            self.stats['counting_correct'] += 1
            return True
        else:
            cprint(f"  Wrong! -> {correct}", "red")
            return False

    def _quick_true_count_question(self) -> bool:
        """Single quick true count question"""
        rc = random.randint(-8, 10)
        decks = random.choice([2, 3, 4])
        tc = rc / decks

        cprint("[TRUE COUNT]", "cyan")
        print(f"  RC={rc:+d}, {decks} decks left")

        try:
            user = float(input("  TC? "))
        except ValueError:
            user = 0

        self.stats['true_count_total'] += 1
        if abs(user - tc) < 0.5:
            cprint("  Correct!", "green")
            self.stats['true_count_correct'] += 1
            return True
        else:
            cprint(f"  Wrong! -> {tc:+.1f}", "red")
            return False

    def _generate_random_hand(self) -> Tuple[Hand, str]:
        """Generate a random player hand and dealer upcard"""
        cards = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

        # Generate player hand
        card1 = random.choice(cards)
        card2 = random.choice(cards)
        hand = Hand(cards=[card1, card2])

        # Generate dealer upcard
        dealer_upcard = random.choice(cards)

        return hand, dealer_upcard

    def _action_name(self, action: str) -> str:
        """Get full action name"""
        names = {'H': 'HIT', 'S': 'STAND', 'D': 'DOUBLE', 'P': 'SPLIT', 'R': 'SURRENDER'}
        return names.get(action, action)

    def show_stats(self) -> None:
        """Display training statistics"""
        cprint("\n=== TRAINING STATISTICS ===", "cyan", attrs=['bold'])

        # Strategy
        s_total = self.stats['strategy_total']
        s_correct = self.stats['strategy_correct']
        s_pct = (s_correct / s_total * 100) if s_total > 0 else 0
        print(f"\nBasic Strategy: {s_correct}/{s_total} ({s_pct:.1f}%)")

        # Counting
        c_total = self.stats['counting_total']
        c_correct = self.stats['counting_correct']
        c_pct = (c_correct / c_total * 100) if c_total > 0 else 0
        print(f"Card Counting:  {c_correct}/{c_total} ({c_pct:.1f}%)")

        # True Count
        t_total = self.stats['true_count_total']
        t_correct = self.stats['true_count_correct']
        t_pct = (t_correct / t_total * 100) if t_total > 0 else 0
        print(f"True Count:     {t_correct}/{t_total} ({t_pct:.1f}%)")

        # Overall
        total = s_total + c_total + t_total
        correct = s_correct + c_correct + t_correct
        overall = (correct / total * 100) if total > 0 else 0

        cprint(f"\nOverall: {correct}/{total} ({overall:.1f}%)", "yellow", attrs=['bold'])

        if overall >= 90:
            cprint("Excellent! You're a blackjack god!", "green", attrs=['bold'])
        elif overall >= 75:
            cprint("Good progress! Keep training.", "yellow")
        else:
            cprint("More practice needed. Don't give up!", "red")


def main():
    """Run training mode"""
    trainer = TrainingMode()
    trainer.run()


if __name__ == "__main__":
    main()
