# Chapter 2: Basic Strategy — The Foundation

## The Bet You're Making Right Now

Every hand you play without basic strategy is a donation.

Not a gamble. Not a risk. A *donation*.

You're handing the casino 6-8% of every bet because you didn't memorize a chart. That's like paying full price for a car when there's a guaranteed 90% discount sitting on the counter.

**Basic strategy isn't a suggestion. It isn't a guideline. It's the mathematically correct play for every single hand.**

How do we know? Computers ran millions of simulations. They tested every possible decision — hit, stand, double, split, surrender — for every combination of your cards and the dealer's upcard. They calculated which choice loses the least (or wins the most) money over time.

The result is basic strategy: the objectively optimal decision for every situation.

Without it: house edge 6-8%.
With it: house edge 0.5%.

That's a 90%+ reduction in expected losses from memorizing a single chart.

Even if you never count cards, mastering basic strategy makes you better than 95% of players in any casino. It's the foundation everything else is built on.

Let's build it.

---

## Why Basic Strategy Works: The Logic

This isn't arbitrary. Every recommendation follows from three insights:

### 1. You Know One of the Dealer's Cards

The dealer shows one card before you act. This is critical information.

A dealer showing a 6 is in trouble. A dealer showing an Ace is dangerous.

**Dealer bust probability by upcard:**

| Upcard | Bust Probability | What It Means |
|--------|-----------------|---------------|
| 2 | 35% | Weak, but not helpless |
| 3 | 37% | Getting weaker |
| 4 | 40% | Vulnerable |
| 5 | 42% | Very weak |
| 6 | 42% | Very weak |
| 7 | 26% | Strong transition |
| 8 | 24% | Strong |
| 9 | 23% | Strong |
| 10 | 23% | Strong |
| A | 17% | Strongest |

See the pattern? Dealer shows 4-6, they bust 40%+ of the time. Dealer shows 7-A, they bust less than 26%.

Basic strategy is aggressive against weak upcards, conservative against strong ones.

### 2. You Have Options the Dealer Doesn't

You can:
- Stand on any total
- Double down to maximize profit
- Split pairs to turn one hand into two
- Surrender to cut losses in half

The dealer follows fixed rules — hit 16 or below, stand 17 or above. No choices. No doubling. No strategic splits.

Your options are your edge. Basic strategy tells you when to use each one.

### 3. The Deck Has Known Composition

There are more 10-value cards (10, J, Q, K) than any other value — 16 out of 52, about 31%.

This matters because:
- Doubling on 11? You want that 10 for 21.
- Dealer has a stiff hand (12-16)? That 10 busts them.
- Splitting? Certain pairs benefit more from catching 10s.

Basic strategy accounts for all these probabilities.

---

## Hard Totals: Your Most Common Decisions

A "hard" hand has no Ace counted as 11, or an Ace forced to count as 1 to avoid busting.

This is where most decisions happen. Master this chart:

### Hard Total Strategy Chart

| Your Hand | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | A |
|-----------|---|---|---|---|---|---|---|---|----|----|
| 8 or less | H | H | H | H | H | H | H | H | H | H |
| 9 | H | D | D | D | D | H | H | H | H | H |
| 10 | D | D | D | D | D | D | D | D | H | H |
| 11 | D | D | D | D | D | D | D | D | D | D |
| 12 | H | H | S | S | S | H | H | H | H | H |
| 13 | S | S | S | S | S | H | H | H | H | H |
| 14 | S | S | S | S | S | H | H | H | H | H |
| 15 | S | S | S | S | S | H | H | H | H | H |
| 16 | S | S | S | S | S | H | H | H | H | H |
| 17+ | S | S | S | S | S | S | S | S | S | S |

**H** = Hit | **S** = Stand | **D** = Double (hit if doubling not allowed)

### The Logic Behind Each Play

**8 or less:** Always hit. You can't bust. Standing on 8 is insane.

**9:** Double against weak cards (3-6). You're hoping to catch a 10 for 19. Against 2, the dealer isn't weak enough — just hit.

**10:** Double against everything except 10 and Ace. You're a favorite to get 18-21.

**11:** Always double. Best doubling hand in the game. A 10 gives you 21.

**12:** Stand against 4-6 only. Against 2-3, the dealer isn't weak enough to risk busting.

**13-16:** Stand against 2-6, hit against 7-A. These are "stiff" hands — you'll likely bust if you hit. But against strong dealer upcards, you have to try. Standing on 14 against a dealer 10 is losing slowly.

**17+:** Always stand. You have a made hand.

### The Toughest Decision: 16 vs 10

Hitting 16 against a dealer 10 feels terrible. You're probably going to bust.

But here's the math:
- If you stand: Win only when dealer busts (~23% chance)
- If you hit: You improve or push ~40% of the time

Both options are bad. But **hitting loses less money over time.**

This is the essence of basic strategy — choosing the least bad option when all options are bad.

---

## Soft Hands: Playing Your Aces

A "soft" hand contains an Ace counted as 11. These hands are flexible — you can't bust with one hit because the Ace becomes 1.

### Soft Total Strategy Chart

| Your Hand | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | A |
|-----------|---|---|---|---|---|---|---|---|----|----|
| A,2 (Soft 13) | H | H | H | D | D | H | H | H | H | H |
| A,3 (Soft 14) | H | H | H | D | D | H | H | H | H | H |
| A,4 (Soft 15) | H | H | D | D | D | H | H | H | H | H |
| A,5 (Soft 16) | H | H | D | D | D | H | H | H | H | H |
| A,6 (Soft 17) | H | D | D | D | D | H | H | H | H | H |
| A,7 (Soft 18) | Ds| Ds| Ds| Ds| Ds| S | S | H | H | H |
| A,8 (Soft 19) | S | S | S | S | Ds| S | S | S | S | S |
| A,9 (Soft 20) | S | S | S | S | S | S | S | S | S | S |

**H** = Hit | **S** = Stand | **D** = Double (hit if can't) | **Ds** = Double (stand if can't)

### The Key Insight: Free Shots

Soft hands give you **free shots at improvement.** You can't bust by hitting once.

**Soft 13-16 (A,2 through A,5):** Double against dealer 5-6, otherwise hit. These hands aren't strong enough to stand, but against very weak dealer cards, you want more money in play.

**Soft 17 (A,6):** Double against 3-6, otherwise hit. Never stand on soft 17 — it's too weak, and you can't bust.

**Soft 18 (A,7):** This is tricky. Double against 3-6, stand against 2, 7, or 8, hit against 9, 10, or Ace.

Why hit a made 18? Because against a dealer 10 or Ace, 18 often isn't good enough. And you can't bust — you might improve.

**Soft 19-20:** Stand. These are strong hands. (Exception: doubling soft 19 against dealer 6 in some rule sets.)

---

## Pair Splitting: Turning One Hand Into Two

When dealt two cards of the same value, you can split into two hands, doubling your bet.

### Pair Splitting Strategy Chart

| Your Pair | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | A |
|-----------|---|---|---|---|---|---|---|---|----|----|
| A,A | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| 10,10 | N | N | N | N | N | N | N | N | N | N |
| 9,9 | Y | Y | Y | Y | Y | N | Y | Y | N | N |
| 8,8 | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| 7,7 | Y | Y | Y | Y | Y | Y | N | N | N | N |
| 6,6 | Y | Y | Y | Y | Y | N | N | N | N | N |
| 5,5 | N | N | N | N | N | N | N | N | N | N |
| 4,4 | N | N | N | Y | Y | N | N | N | N | N |
| 3,3 | Y | Y | Y | Y | Y | Y | N | N | N | N |
| 2,2 | Y | Y | Y | Y | Y | Y | N | N | N | N |

**Y** = Split | **N** = Don't Split

### The Rules That Never Change

**Always split Aces and 8s:**
- Two Aces: You have 12 (or soft 2). Split gives you two shots at 21.
- Two 8s: You have 16, the worst total. Split gives you two chances at 18.

**Never split 10s or 5s:**
- Two 10s: You have 20. Don't mess with a winning hand.
- Two 5s: You have 10 — a great doubling hand. Don't waste it.

---

## Surrender: The Smart Move Most Players Fear

Surrender lets you forfeit half your bet before playing the hand.

Most players never use it. That's a mistake.

### When to Surrender (If Available)

| Your Hand | Surrender Against |
|-----------|-------------------|
| 16 | 9, 10, A |
| 15 | 10 |

You're paying half to avoid losing the whole bet in terrible situations.

Think of it this way: if you're going to lose 60% of the time anyway, giving up 50% instantly is a bargain.

---

## How to Memorize This Fast

Don't try to memorize the charts cell by cell. Learn the patterns:

### Pattern 1: Dealer Weak (2-6) vs Strong (7-A)

Against weak dealer upcards: Let them bust. Stand on stiff hands.
Against strong dealer upcards: Take risks. Hit your stiff hands.

### Pattern 2: The "Always" Rules

- Always hit 8 or less
- Always double 11
- Always split A-A and 8-8
- Always stand on 17+
- Never split 10-10 or 5-5
- Never take insurance (until you're counting)

### Pattern 3: Soft Hands = Aggressive

You can't bust with one hit. Be aggressive. Double more often. Hit more often.

### Memory Trick for Stiff Hands (12-16)

**"Surrender 16 to 9, 10, A. Stand on 12-16 vs 2-6. Everything else, hit."**

That covers most of your hard hand decisions.

### The Fastest Path to Mastery

1. **Learn the "always" rules first** — they cover 40% of decisions
2. **Learn hard totals next** — most common hands
3. **Add soft hands** — the logic is intuitive (can't bust = be aggressive)
4. **Add pairs last** — least common situation

Practice until decisions are automatic. No thinking. Just reacting.

---

## Practice Exercises

Test yourself. Cover the answers.

1. You have 11, dealer shows 10. **Double**
2. You have A,7, dealer shows 9. **Hit**
3. You have 16, dealer shows 6. **Stand**
4. You have 8,8, dealer shows 10. **Split**
5. You have 12, dealer shows 3. **Hit**
6. You have A,6, dealer shows 4. **Double**
7. You have 10,10, dealer shows 5. **Stand**
8. You have 15, dealer shows 10. **Hit (or Surrender)**
9. You have 9, dealer shows 2. **Hit**
10. You have A,8, dealer shows 6. **Double (or Stand)**

Score: 10/10 = ready for the casino. Less than 8? Keep drilling.

---

## The Five Costly Mistakes

These errors drain money from players who "know" basic strategy but don't actually follow it:

### 1. Standing on Soft 17
You have A,6. You stand because "17 is good."

Wrong. Soft 17 is weak, and you can't bust. Always hit (or double vs 3-6).

### 2. Not Splitting 8s Against a 10
"But the dealer has a 10! I'll have two bad hands!"

You already have 16 — the worst hand. Two chances at 18 beats one guaranteed loss.

### 3. Hitting 12 Against Dealer 4
"I might bust!"

You might. But the dealer busts 40% of the time with a 4 showing. Let them take the risk.

### 4. Taking Insurance
"I want to protect my good hand!"

Insurance is a side bet with a 7% house edge. It's not protection — it's a trap. Never take it (until you're counting and the deck is 10-rich).

### 5. Playing Hunches
"I feel like the next card is a 10."

Your feelings don't change probability. The math doesn't care how confident you are.

---

## Why This Matters Emotionally

Here's what basic strategy actually gives you:

**Confidence.** When you know the correct play, you don't second-guess yourself. You don't feel stupid when you bust. You did the right thing — variance just didn't cooperate this time.

**Calm.** Every decision is predetermined. You're not agonizing over choices. You're executing a system.

**Control.** You can't control the cards. But you can control your decisions. Perfect strategy means perfect execution of what's within your control.

**Longer sessions.** With a 0.5% house edge instead of 6%, your bankroll lasts dramatically longer. More hands. More time at the table. More chances for variance to swing your way.

Basic strategy doesn't guarantee you'll win tonight. Nothing does.

But it guarantees you're not donating money through ignorance. And that's the first step toward actually having an edge.

---

## Key Takeaways

- **Basic strategy reduces house edge from 6-8% to ~0.5%** — a 90%+ reduction

- **Hard hands:** Stand on 12-16 vs weak dealer (2-6), hit vs strong (7-A)

- **Soft hands:** Be aggressive — you can't bust on one hit

- **Always split A-A and 8-8. Never split 10-10 or 5-5.**

- **Never take insurance** (until you're counting)

- **Practice until decisions are automatic** — no thinking, just executing

- **Memorize patterns, not cells** — the chart has logic behind it

---

You now have the foundation. Basic strategy alone makes you better than 95% of players.

But you're not here to be better than average. You're here for the edge.

**Next: Chapter 3 — Hi-Lo Card Counting**

Time to turn that 0.5% disadvantage into a 1%+ advantage.

