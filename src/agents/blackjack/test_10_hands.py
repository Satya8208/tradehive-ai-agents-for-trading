"""
Quick test script to run 10 random blackjack hands
Self-contained simulation
"""
import random

# Card values for Hi-Lo counting
CARD_VALUES = {
    '2': 1, '3': 1, '4': 1, '5': 1, '6': 1,  # Low cards = +1
    '7': 0, '8': 0, '9': 0,                    # Neutral = 0
    '10': -1, 'J': -1, 'Q': -1, 'K': -1, 'A': -1  # High cards = -1
}

CARDS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

class SimpleShoe:
    def __init__(self, num_decks=6):
        self.num_decks = num_decks
        self.cards = CARDS * 4 * num_decks
        random.shuffle(self.cards)
        self.dealt = 0

    def deal(self):
        if self.dealt >= len(self.cards) - 20:
            self.cards = CARDS * 4 * self.num_decks
            random.shuffle(self.cards)
            self.dealt = 0
        card = self.cards[self.dealt]
        self.dealt += 1
        return card

    def decks_remaining(self):
        return (len(self.cards) - self.dealt) / 52

def card_value(card):
    if card == 'A':
        return 11
    elif card in ['J', 'Q', 'K']:
        return 10
    return int(card)

def hand_total(cards):
    total = sum(card_value(c) for c in cards)
    aces = cards.count('A')
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def is_soft(cards):
    total = sum(card_value(c) for c in cards)
    aces = cards.count('A')
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return aces > 0 and total <= 21

# Basic strategy (simplified)
def get_action(player_cards, dealer_up):
    total = hand_total(player_cards)
    dealer_val = card_value(dealer_up)
    soft = is_soft(player_cards)

    # Simplified basic strategy
    if total >= 17:
        return 'S'
    elif total <= 11:
        return 'H'
    elif total == 12:
        return 'S' if 4 <= dealer_val <= 6 else 'H'
    elif total in [13, 14, 15, 16]:
        return 'S' if 2 <= dealer_val <= 6 else 'H'
    return 'H'

# Run simulation
shoe = SimpleShoe(6)
running_count = 0

results = {
    'wins': 0,
    'losses': 0,
    'pushes': 0,
    'blackjacks': 0,
    'total_bet': 0,
    'total_pnl': 0
}

base_bet = 10

print()
print("=" * 60)
print("  BLACKJACK 10-HAND TEST SIMULATION")
print("  Counting System: Hi-Lo | Decks: 6")
print("=" * 60)

for hand_num in range(1, 11):
    # Calculate true count
    decks_left = max(1, shoe.decks_remaining())
    true_count = running_count / decks_left

    # Calculate bet based on true count
    if true_count >= 2:
        bet = base_bet * min(int(true_count) * 2, 12)
    else:
        bet = base_bet

    results['total_bet'] += bet

    # Deal initial cards
    player = [shoe.deal(), shoe.deal()]
    dealer = [shoe.deal(), shoe.deal()]
    dealer_up = dealer[0]

    # Count visible cards
    for c in player:
        running_count += CARD_VALUES[c]
    running_count += CARD_VALUES[dealer_up]

    print(f"\n--- Hand #{hand_num} ---")
    print(f"Bet: ${bet} | RC: {running_count:+} TC: {true_count:+.1f}")
    print(f"Player: {player} = {hand_total(player)}")
    print(f"Dealer shows: {dealer_up}")

    # Check for player blackjack
    if len(player) == 2 and hand_total(player) == 21:
        running_count += CARD_VALUES[dealer[1]]  # Count hole card
        if hand_total(dealer) == 21:
            print("Both have Blackjack - PUSH")
            results['pushes'] += 1
        else:
            win = int(bet * 1.5)
            print(f"BLACKJACK! +${win}")
            results['blackjacks'] += 1
            results['wins'] += 1
            results['total_pnl'] += win
        continue

    # Play player hand
    while hand_total(player) < 21:
        action = get_action(player, dealer_up)
        if action == 'H':
            new_card = shoe.deal()
            player.append(new_card)
            running_count += CARD_VALUES[new_card]
            print(f"  HIT -> {new_card} = {hand_total(player)}")
        else:
            print(f"  STAND on {hand_total(player)}")
            break

    player_total = hand_total(player)

    # Count dealer hole card
    running_count += CARD_VALUES[dealer[1]]

    # Play dealer hand (only if player didn't bust)
    if player_total <= 21:
        while hand_total(dealer) < 17:
            new_card = shoe.deal()
            dealer.append(new_card)
            running_count += CARD_VALUES[new_card]

    dealer_total = hand_total(dealer)
    print(f"Dealer: {dealer} = {dealer_total}")

    # Determine result
    if player_total > 21:
        print(f"BUST - Lost ${bet}")
        results['losses'] += 1
        results['total_pnl'] -= bet
    elif dealer_total > 21:
        print(f"Dealer busts - Won ${bet}")
        results['wins'] += 1
        results['total_pnl'] += bet
    elif player_total > dealer_total:
        print(f"WIN +${bet}")
        results['wins'] += 1
        results['total_pnl'] += bet
    elif player_total < dealer_total:
        print(f"LOSS -${bet}")
        results['losses'] += 1
        results['total_pnl'] -= bet
    else:
        print("PUSH")
        results['pushes'] += 1

# Summary
print()
print("=" * 60)
print("  SESSION SUMMARY")
print("=" * 60)
print(f"  Hands:     10")
print(f"  Wins:      {results['wins']} (includes {results['blackjacks']} BJ)")
print(f"  Losses:    {results['losses']}")
print(f"  Pushes:    {results['pushes']}")
print(f"  Win Rate:  {results['wins']/10*100:.0f}%")
print("-" * 40)
print(f"  Total Bet: ${results['total_bet']}")
print(f"  Net P&L:   ${results['total_pnl']:+}")
roi = results['total_pnl']/results['total_bet']*100 if results['total_bet'] > 0 else 0
print(f"  ROI:       {roi:+.1f}%")
print("=" * 60)
