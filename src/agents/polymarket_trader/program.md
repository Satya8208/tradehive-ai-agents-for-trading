# Polymarket AutoResearch

This is an autonomous strategy optimization experiment. You are an AI researcher whose job is to **improve a Polymarket prediction market trading system** by modifying its strategy code, scoring the changes against historical trades, and keeping improvements.

## Setup

To set up a new experiment session:

1. **Read the in-scope files** for full context:
   - `src/agents/polymarket_trader/swarm_analyzer.py` — AI swarm prompts, consensus logic, model temperatures
   - `src/agents/polymarket_trader/edge_calculator.py` — edge formula, time decay, Kelly sizing
   - `src/agents/polymarket_trader/config.py` — thresholds, symbol filters, search queries
   - `src/agents/polymarket_trader/arbitrage_detector.py` — arb detection algorithms
   - `src/agents/polymarket_trader/market_scanner.py` — market ranking and scoring
   - `src/agents/polymarket_trader/benchmark_markets.json` — 15 test markets with known outcomes
   - `src/agents/polymarket_trader/results.tsv` — past experiment results (learn from them!)

2. **Run the baseline score:**
   ```bash
   python -c "from src.agents.polymarket_trader.backtest_scorer import BacktestScorer, ParamSet; s=BacktestScorer(); r=s.score(ParamSet()); print(f'score={r.score:.2f} wr={r.win_rate:.1%} pnl=\${r.total_pnl:+.2f} trades={r.filtered_trades}')"
   ```

3. **Confirm baseline** matches approximately: score=57.2, WR=40.8%, P&L=+$273, 76 trades.

4. **Start the experiment loop.**

## What You CAN Modify

These files are your playground. Everything is fair game:

- **`swarm_analyzer.py`** — The 3 role-differentiated system prompts (CONSERVATIVE, QUANTITATIVE, CONTRARIAN), the user prompt construction, temperature per model, consensus aggregation logic, dissent penalty, model selection
- **`edge_calculator.py`** — Edge formula, time decay curve, Kelly fraction calculation, confidence penalty
- **`config.py`** — min_edge_threshold, kelly_fraction, search_symbols, min_arb_token_price, min_arb_edge_percent, swarm_models list, any parameter
- **`arbitrage_detector.py`** — Range-sum filter logic, combinatorial logic, cross-market matching threshold, fee buffer
- **`market_scanner.py`** — Market ranking weights (liquidity, volume, spread, time remaining, price attractiveness), filtering criteria

## What You CANNOT Modify

These are the evaluation harness. Do not touch:

- **`backtest_scorer.py`** — This is the ground truth metric. Modifying it is cheating.
- **`models.py`** — Data structures used by the scorer.
- **`cli_wrapper.py`** — Exchange API interface.
- **`performance_tracker.py`** — Analytics.
- **Any files in `src/data/`** — Historical trade data is sacred.
- **This file (`program.md`)** — Your instructions are fixed.

## The Metric

Run the scorer after every experiment:

```bash
python -c "
from src.agents.polymarket_trader.backtest_scorer import BacktestScorer, ParamSet
s = BacktestScorer()
r = s.score(ParamSet())
print(f'score={r.score:.2f} wr={r.win_rate:.1%} pnl=\${r.total_pnl:+.2f} trades={r.filtered_trades} roi={r.roi:.1%}')
for src, st in r.by_source.items():
    wr = st['wins']/st['count'] if st['count'] > 0 else 0
    print(f'  {src}: {st[\"count\"]}t \${st[\"pnl\"]:+.2f} {wr:.0%}WR')
for sym, st in r.by_symbol.items():
    wr = st['wins']/st['count'] if st['count'] > 0 else 0
    print(f'  {sym}: {st[\"count\"]}t \${st[\"pnl\"]:+.2f} {wr:.0%}WR')
" 2>&1 | tee /tmp/score.txt
```

**The score formula:** `(win_rate * 100 + ROI * 100) * min(trades/10, 1.0)`

Higher is better. The trade count penalty prevents the optimizer from gaming the score by filtering to 2 lucky trades.

## Known Issues to Fix (Read This!)

Based on 152 trades across 3 test rounds, these are the confirmed problems:

1. **BULLISH BIAS** — The swarm defaults to YES on almost everything. When BTC dropped from $84k to $67k, weekly bets went 1W/7L (-$105). The conservative and contrarian prompts aren't actually conservative or contrarian enough.

2. **BTC/SOL LOSE MONEY** — BTC: 0% WR on 3 closed trades (-$29.59). SOL: 0% WR (-$37.91). ETH: 42% WR (+$291.93). The system is only profitable on ETH.

3. **WEEKLY = TRAP** — Daily bucket: +$142 across 2 rounds. Weekly bucket: -$111. Too much time for market to move against us.

4. **BLIND ESTIMATION TRADEOFF** — We removed market price from swarm prompts to prevent anchoring. But this also prevents the swarm from seeing that a low YES price (10-12%) means the market is bearish. The swarm then predicts YES at 58% on a market priced at 33%, creating false edge.

5. **ARB EDGE DILUTED** — Range-sum arbs buy all ranges. You win one range and lose the rest. Net effect is roughly flat post-upgrade.

## The Experiment Loop

LOOP FOREVER:

1. **Read past results**: Check `results.tsv` to see what's been tried and what worked.
2. **Pick an experiment**: Based on past results and the known issues above, choose what to try. Favor high-impact changes (prompts, symbol filters) over small tweaks.
3. **Modify code**: Change one or two things at most per experiment. Small, testable changes.
4. **Git commit**: `git add -A && git commit -m "experiment: <short description>"`
5. **Run the score**: Use the scoring command above. Redirect output to avoid flooding context.
6. **Read the result**: `cat /tmp/score.txt`
7. **Log to results.tsv**: Append a row (tab-separated):
   ```
   <commit_hash>\t<score>\t<win_rate>\t<pnl>\t<trades>\t<keep|discard>\t<description>
   ```
8. **Keep or discard**:
   - If score IMPROVED: Keep the commit. You've advanced the strategy.
   - If score SAME or WORSE: `git reset --hard HEAD~1` — revert to where you were.
9. **Repeat from step 1.**

## Simplicity Criterion

All else being equal, simpler is better. A small improvement that adds 20 lines of hacky code? Probably not worth it. An improvement from DELETING code? Definitely keep. When evaluating, weigh complexity cost against improvement magnitude.

## NEVER STOP

Once the experiment loop has begun, do NOT pause to ask the human if you should continue. The human might be asleep and expects you to work indefinitely until manually stopped. If you run out of ideas, re-read the in-scope files, re-read results.tsv for patterns, try combining previous near-misses, or try more radical changes. The loop runs until the human interrupts you.

## Experiment Ideas to Get Started

1. Add market price back to swarm prompt but label it "The market currently prices YES at X%. Consider why the market might be right before disagreeing."
2. Filter to ETH-only in config (proven 75% WR)
3. Add to contrarian prompt: "If all other analysts say YES, your job is to argue NO with evidence"
4. Modify edge formula to use absolute probability gap instead of relative
5. Add a check: if swarm prob is within 5% of market price, ABSTAIN instead of trading
6. Remove SOL and XRP from search_symbols
7. Change min_consensus_count from 2 to 3 (require unanimous agreement)
8. Add to quantitative prompt: "Calculate the % price move needed to hit the target. BTC daily vol is 3-5%, ETH is 4-6%. If the needed move exceeds 1 standard deviation, probability should be low."
