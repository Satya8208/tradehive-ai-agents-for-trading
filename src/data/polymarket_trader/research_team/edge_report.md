# Polymarket Quant Research Team

Generated: 2026-05-03T06:04:26.999081+00:00

## Current Edge

- Shipping verdict variant: `no_replay_accepted_variant`
- Best exploratory active-cohort variant: `current_config`
- Best active configuration: `current_config -79.75 (15 trades, replay=False, holdout=0)`
- Positive active configurations: `0`
- Best positive active configuration: `none`
- Replay-accepted active configurations: `0`
- Supported symbols today: `none`
- ETH vs BTC PnL delta: `-79.75`
- ETH+BTC expansion penalty: `+0.00`
- Any replay gate accepted: `False`
- Current runtime blocker: `NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN; reasons=['low_volume_24h', 'low_liquidity', 'symbol_filtered']`
- Runtime blocker regime: `LATEST_INVENTORY_BLOCKED__CHRONIC_PROVIDER_BLOCKED; latest=NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN; reasons=['low_volume_24h', 'low_liquidity', 'symbol_filtered']; chronic=CURRENTLY_BLOCKED; healthy_set=xai; reasons=['no_recent_consensus_ready_runs', 'persistently_blocked_providers']; recent_mix=inventory_blocked_no_tradeable_markets:2; single_provider_control:2; provider_blocked_no_healthy_provider:1; dirs=5; prediction_runs=3`
- Active edge read: `PATCH_ONLY_NON_PROMOTABLE; reasons=['best_active_configuration_negative_or_flat', 'best_active_configuration_not_replay_accepted', 'surviving_patch_is_slice_not_configuration', 'surviving_patch_not_promotable']`
- Surviving ETH patch: `<=0.10 / bullish / NO: 3 trades, WR 33.3%, PnL $+5.72, avg px 0.059, avg edge 28.43`
- Surviving ETH patch stress test: `3 trades / 2 markets, top win $+29.61, largest loss $-22.15, residual ex-best $-23.89, top-win share 517.6%, survives ex-best False`
- Surviving ETH patch verdict: `NON_INDEPENDENT_PATCH; reasons=['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`
- Surviving ETH patch promotability: `RESEARCH_ONLY_NON_INDEPENDENT; reasons=['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`

## Deployment Verdict

- Status: `NO_GO`
- Deployable now: `False`
- Current scope: `research_only`
- Deployment target: `attended_micro_cap`
- Approved symbols: `none`
- BTC allowed: `False`
- Arbitrage policy: `structural_only`
- Verdict reason codes: `['runtime_swarm_unavailable', 'latest_runtime_inventory_blocked', 'no_holdout_support', 'positive_lane_low_sample', 'positive_patch_non_independent', 'negative_realized_book', 'high_confidence_anti_signal', 'yes_direction_anti_signal', 'strict_inventory_empty']`

## Symbol Verdicts

- ETH: `RESEARCH_ONLY` / `non_independent_low_sample_patch`
- ETH current lane: `eth_only -79.75 (15 trades, replay=False, holdout=0)`
- ETH best measured positive lane: `none`
- ETH best low-sample positive lane: `ETH:swarm_only:min=none:max=1.0 +4.57 (2 trades, replay=False, holdout=0)`
- ETH reason codes: `['eth_not_approved', 'eth_not_supported', 'no_replay_acceptance', 'no_filtered_holdout_trades', 'negative_current_lane', 'positive_lane_low_sample', 'runtime_swarm_unavailable', 'positive_patch_non_independent', 'negative_realized_book']`
- BTC: `RESEARCH_ONLY` / `no_measured_edge`
- BTC current lane: `btc_only +0.00 (0 trades, replay=False, holdout=0)`
- BTC best measured positive lane: `none`
- BTC best low-sample positive lane: `none`
- BTC reason codes: `['btc_not_approved', 'btc_not_supported', 'no_replay_acceptance', 'no_filtered_holdout_trades', 'no_current_filtered_trades', 'no_positive_measured_lane']`

## Best Measured Candidate

## Deployment Requirements

- Restore runtime consensus so at least one recent run is genuinely swarm-ready.
- Increase short-horizon ETH inventory quality or discovery so the latest runtime scan returns tradeable markets.
- Earn filtered holdout support and a replay-accepted variant before deployment.
- Increase the only positive lane beyond the 5-trade research bar.
- Find a positive ETH patch that survives without one outsized winner and spans more distinct markets before treating it as edge.
- Improve the realized ETH book from negative to durable positive territory.
- Recalibrate confidence so the >=50% cohort stops losing before using conviction as an edge amplifier.
- Repair directional bias so YES-side calls stop behaving like anti-signal before trusting the swarm on binary direction.
- Fix strict ETH inventory sourcing so production-style scans return candidates.

- Candidate: `none with >= 5 filtered trades`
- Best low-sample lead: `ETH:swarm_only:min=none:max=1.0` (2 trades, PnL `$+4.57`)
- Best low-sample lead verdict: `NON_INDEPENDENT_PATCH; reasons=['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`

## Expiry Policy

- Scope: `ETH-only`
- Active ETH profile basis: `swarm_arb min=none`
- Current ETH cap on active profile: `<=24h -79.75 (15 trades, replay=False)`
- Best active-profile ETH cap: `<=1h +4.57 (2 trades, replay=False)`
- Best active-profile cap delta vs current: `+84.32 PnL / -13 trades / +19.20 score`
- Best active-profile ETH cap with >= 5 trades: `<=4h -33.08 (10 trades, replay=False)`
- Best sampled active-profile cap delta vs current: `+46.67 PnL / -5 trades / +13.59 score`
- Best exploratory ETH cap across any profile: `<=1h +4.57 (2 trades, replay=False)`
- Active-profile cap verdict: `NO_PROMOTABLE_CAP; sampled=<=4h; exploratory=<=1h; reasons=['no_positive_cap_with_min_sample', 'best_sampled_cap_still_negative', 'best_sampled_cap_improves_but_not_profitable', 'only_low_sample_positive_cap']`
- Positive active-profile caps with >= 5 trades: `none`
- Positive active-profile low-sample caps: `<=1h`
- Active-profile ETH cap sweep: `<=1h +4.57 (2 trades, replay=False); <=4h -33.08 (10 trades, replay=False); <=12h -79.75 (15 trades, replay=False); <=24h -79.75 (15 trades, replay=False); uncapped -79.75 (15 trades, replay=False)`

## Swarm Health

- Ready for live paper analysis: `True`
- Available configured models: `3`
- Unavailable configured models: `0`

## Runtime Swarm Health

- Latest runtime data dir: `/home/satya/moon-dev-ai-agents/src/data/polymarket_trader_candidate_soak_20260503_runtime_b`
- Runtime ready: `False`
- Runtime freshness verdict: `runtime_recent`
- Latest run age hours: `0.01h`
- Runtime freshness threshold hours: `6.00h`
- Runtime fresh enough for summary: `True`
- Recent runtime dirs / prediction-bearing runs: `5` / `3`
- Runtime provider verdict: `CURRENTLY_BLOCKED; healthy_set=xai; reasons=['no_recent_consensus_ready_runs', 'persistently_blocked_providers']`
- Latest cycle interpretation: `NO_MARKETS_FOUND; reasons=['no_tradeable_markets']`
- Latest runtime scan verdict: `NO_TRADEABLE_MARKETS_IN_LATEST_RUNTIME_SCAN; reasons=['low_volume_24h', 'low_liquidity', 'symbol_filtered']`
- Latest runtime scan query/raw/parsed/filtered/tradeable: `21 / 1050 / 1017 / 1050 / 0`
- Latest runtime scan top exclusions: `low_volume_24h: 584; low_liquidity: 211; symbol_filtered: 108`
- Runtime dirs scanned / consensus-ready observed: `32` / `0`
- Consensus-ready history verdict: `no_consensus_ready_run_observed`
- Latest consensus-ready run age hours: `none`
- Latest consensus-ready data dir: `none`
- Historical runtime cohort (runs / ready / degraded): `23` / `0` / `23`
- Historical provider ok-rates: `{'claude': 0.0, 'deepseek': 0.0, 'xai': 0.522}`
- Historical healthy-provider sets: `{'xai': 12, 'none': 11}`
- Historical failure composition (xai-only / no-healthy / other): `12` / `11` / `0`
- Historical failure rates (xai-only / no-healthy): `52.2%` / `47.8%`
- Historical run-level error codes: `{'insufficient_credits': 10, 'insufficient_balance': 10}`
- Most common historical healthy-provider set: `xai`
- Recent runtime cohort (runs / ready / degraded): `3` / `0` / `3`
- Recent blocked-run streak: `3`
- Latest run timestamp / status: `2026-05-03T06:03:59.002077` / `no_markets`
- Latest cycle duration seconds: `12.585`
- Latest market scan / swarm analysis seconds: `12.585` / `0.0`
- Latest markets found / trades executed: `0` / `0`
- Recent avg latest successful models: `0.67`
- Latest successful model count: `0`
- Latest abstain reason: `none`
- Latest measurement boundary: `none`
- Latest analysis cohort: `none`
- Latest current price present: `False`
- Latest current price: `None`
- Latest sigma ratio: `None`
- Degraded predictions / single-model control: `0` / `0`
- Runtime error codes: `{}`
- Recent run-level error codes: `{'insufficient_credits': 3, 'insufficient_balance': 3}`
- Recent provider ok-rates: `{'claude': 0.0, 'deepseek': 0.0, 'xai': 0.667}`
- Persistently healthy / blocked providers: `[]` / `['claude', 'deepseek']`
- Recent runtime primary-cause mix: `inventory_blocked_no_tradeable_markets:2; single_provider_control:2; provider_blocked_no_healthy_provider:1`
- Most common recent primary cause: `inventory_blocked_no_tradeable_markets`
- Recent healthy-provider sets: `{'xai': 2, 'none': 1}`
- Most common recent healthy-provider set: `xai`
- Single-provider-only runs: `2` (66.7%)
- Recent single-provider-control streak: `1`

## Calibration Credibility

- Verdict: `HIGH_CONFIDENCE_ANTI_SIGNAL`
- Consensus accuracy / Brier / MAE: `0.114` / `0.2869` / `0.4974`
- High-confidence cohort: `>=50%: 13 trades, WR 0.0%, PnL $-106.51, avg p=0.672, gap=+0.672`
- Severe-confidence cohort: `>=70%: 6 trades, WR 0.0%, PnL $-62.82, avg p=0.785, gap=+0.785`
- Sub-50% cohort: `below threshold: 22 trades, WR 9.1%, PnL $-86.45, avg p=0.345, gap=+0.254`
- Confidence gate verdict: `NO_PROMOTABLE_CONFIDENCE_GATE; reasons=['best_cap_still_negative_or_thin', 'high_confidence_floor_negative', 'confidence_monotonicity_broken']`
- Best simple confidence cap: `<=30%: 5 trades, WR 20.0%, PnL $-18.59`
- Best simple confidence floor: `>=70%: 6 trades, WR 0.0%, PnL $-62.82`
- Confidence cap sweep: `<=30%: 5 trades, WR 20.0%, PnL $-18.59; <=40%: 14 trades, WR 14.3%, PnL $-41.47; <=50%: 24 trades, WR 8.3%, PnL $-104.75`
- Confidence floor sweep: `>=50%: 13 trades, WR 0.0%, PnL $-106.51; >=60%: 9 trades, WR 0.0%, PnL $-78.98; >=70%: 6 trades, WR 0.0%, PnL $-62.82`
- Confidence monotonicity broken: `True`

## Edge Quality

- Verdict: `ONLY_LOW_SAMPLE_EDGE_PATCH`
- Gate verdict: `NO_PROMOTABLE_EDGE_GATE; reasons=['best_sampled_edge_floor_still_negative_or_flat', 'best_sampled_edge_cap_still_negative_or_flat', 'only_low_sample_positive_edge_floor']`
- Sample bar: `5`
- Best sampled edge floor: `>=30: 7 trades, WR 28.6%, PnL $-10.00, avg edge 40.41`
- Best sampled edge cap: `<=10: 12 trades, WR 0.0%, PnL $-36.55, avg edge 6.48`
- Best low-sample edge floor: `>=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25`
- Low-edge cohort: `<=10: 12 trades, WR 0.0%, PnL $-36.55, avg edge 6.48`
- High-edge cohort: `>=20: 11 trades, WR 18.2%, PnL $-61.59, avg edge 34.48`
- Higher edge beats low edge: `False`
- Edge cap sweep: `<=10: 12 trades, WR 0.0%, PnL $-36.55, avg edge 6.48; <=15: 17 trades, WR 0.0%, PnL $-60.87, avg edge 8.43; <=20: 24 trades, WR 0.0%, PnL $-131.37, avg edge 11.21; <=25: 27 trades, WR 0.0%, PnL $-170.75, avg edge 12.47; <=30: 28 trades, WR 0.0%, PnL $-182.96, avg edge 13.05; <=40: 33 trades, WR 3.0%, PnL $-198.28, avg edge 16.85`
- Edge floor sweep: `>=10: 23 trades, WR 8.7%, PnL $-156.41, avg edge 24.81; >=15: 18 trades, WR 11.1%, PnL $-132.09, avg edge 28.06; >=20: 11 trades, WR 18.2%, PnL $-61.59, avg edge 34.48; >=25: 8 trades, WR 25.0%, PnL $-22.20, avg edge 38.98; >=30: 7 trades, WR 28.6%, PnL $-10.00, avg edge 40.41; >=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25`

## Timeframe + Edge Pockets

- Verdict: `ONLY_LOW_SAMPLE_TIMEFRAME_EDGE_PATCH`
- Gate verdict: `NO_PROMOTABLE_TIMEFRAME_EDGE_POCKET; reasons=['best_sampled_timeframe_edge_pocket_still_negative_or_flat', 'only_low_sample_positive_timeframe_edge_pocket', 'only_positive_timeframe_edge_pocket_is_ultra_short']`
- Sample bar: `5`
- Best sampled timeframe-edge pocket: `weekly / cap<=10: 5 trades, WR 0.0%, PnL $-9.06, avg edge 5.72`
- Best low-sample timeframe-edge pocket: `ultra_short / floor>=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25`
- Positive sampled / low-sample timeframe-edge pockets: `0` / `1`
- Top timeframe-edge pockets: `ultra_short / floor>=40: 2 trades, WR 50.0%, PnL $+5.32, avg edge 46.25; intraday / floor>=30: 4 trades, WR 25.0%, PnL $-7.42, avg edge 38.02; daily / floor>=30: 1 trades, WR 0.0%, PnL $-7.90, avg edge 38.30; weekly / cap<=10: 5 trades, WR 0.0%, PnL $-9.06, avg edge 5.72; daily / cap<=10: 3 trades, WR 0.0%, PnL $-10.84, avg edge 7.63`

## Market Archetype Pockets

- Verdict: `ONLY_LOW_SAMPLE_MARKET_ARCHETYPE_PATCH`
- Gate verdict: `NO_PROMOTABLE_MARKET_ARCHETYPE_POCKET; reasons=['best_sampled_market_archetype_pocket_still_negative_or_flat', 'only_low_sample_positive_market_archetype_pocket', 'only_positive_market_archetype_pockets_are_no_side']`
- Sample bar: `5`
- Best sampled market-archetype pocket: `weekly / bullish / NO: 5 trades, WR 0.0%, PnL $-9.06`
- Best low-sample market-archetype pocket: `intraday / bullish / NO: 2 trades, WR 50.0%, PnL $+7.46`
- Positive sampled / low-sample market-archetype pockets: `0` / `2`
- Top market-archetype pockets: `intraday / bullish / NO: 2 trades, WR 50.0%, PnL $+7.46; ultra_short / binary_updown / NO: 2 trades, WR 50.0%, PnL $+5.32; intraday / bullish / YES: 1 trades, WR 0.0%, PnL $-1.93; daily / bullish / NO: 1 trades, WR 0.0%, PnL $-5.16; weekly / bullish / NO: 5 trades, WR 0.0%, PnL $-9.06`

## Entry Price Pockets

- Verdict: `ONLY_LOW_SAMPLE_ENTRY_PRICE_PATCH`
- Gate verdict: `NO_PROMOTABLE_ENTRY_PRICE_POCKET; reasons=['best_sampled_entry_price_pocket_still_negative_or_flat', 'only_low_sample_positive_entry_price_pocket', 'only_positive_entry_price_pockets_are_cheap_bullish_no']`
- Sample bar: `5`
- Best sampled entry-price pocket: `0.10-0.20 / bullish / YES: 5 trades, WR 0.0%, PnL $-29.14, avg px 0.177, avg edge 13.50`
- Best low-sample entry-price pocket: `<=0.10 / bullish / NO: 3 trades, WR 33.3%, PnL $+5.72, avg px 0.059, avg edge 28.43`
- Cheap-tail all cohort: `<=0.10 / ALL / ALL: 4 trades, WR 25.0%, PnL $+3.79, avg px 0.061, avg edge 23.20`
- Cheap-tail bullish-NO cohort: `<=0.10 / bullish / NO: 3 trades, WR 33.3%, PnL $+5.72, avg px 0.059, avg edge 28.43`
- Cheap-tail bullish-NO fast cohort: `<=0.10 / bullish / NO / intraday+ultra_short: 2 trades, WR 50.0%, PnL $+7.46, avg px 0.057, avg edge 39.05`
- Best low-sample patch concentration: `3 trades / 2 markets, top win $+29.61, largest loss $-22.15, residual ex-best $-23.89, top-win share 517.6%, survives ex-best False`
- Cheap-tail bullish-NO fast concentration: `2 trades / 1 markets, top win $+29.61, largest loss $-22.15, residual ex-best $-22.15, top-win share 396.9%, survives ex-best False`
- Low-sample patch independence verdict: `NON_INDEPENDENT_PATCH; reasons=['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`
- Cheap-tail fast-subset independence verdict: `NON_INDEPENDENT_PATCH; reasons=['low_trade_count', 'single_market_patch', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl']`
- Positive sampled / low-sample entry-price pockets: `0` / `1`
- Top entry-price pockets: `<=0.10 / bullish / NO: 3 trades, WR 33.3%, PnL $+5.72, avg px 0.059, avg edge 28.43; <=0.10 / bullish / YES: 1 trades, WR 0.0%, PnL $-1.93, avg px 0.068, avg edge 7.50; 0.20-0.30 / bullish / NO: 1 trades, WR 0.0%, PnL $-5.16, avg px 0.250, avg edge 12.50; 0.10-0.20 / bullish / NO: 4 trades, WR 0.0%, PnL $-7.32, avg px 0.166, avg edge 5.35; 0.20-0.30 / neutral / NO: 1 trades, WR 0.0%, PnL $-7.90, avg px 0.280, avg edge 38.30`

## Directional Credibility

- Verdict: `YES_DIRECTION_ANTI_SIGNAL`
- Direction gate verdict: `NO_PROMOTABLE_DIRECTION_GATE; reasons=['yes_direction_losing', 'best_direction_still_negative', 'yes_worse_than_no']`
- YES cohort: `YES: 13 trades, WR 0.0%, PnL $-106.51, avg p=0.672`
- NO cohort: `NO: 22 trades, WR 9.1%, PnL $-86.45, avg p=0.345`
- Best direction gate: `NO: 22 trades, WR 9.1%, PnL $-86.45`
- Direction-timeframe pocket verdict: `NO_PROMOTABLE_DIRECTION_TIMEFRAME_POCKET; reasons=['best_pocket_low_sample', 'only_positive_pocket_is_no_ultra_short']`
- Best direction-timeframe pocket: `NO / ultra_short: 2 trades, WR 50.0%, PnL $+5.32`
- Worst direction-timeframe drag pocket: `YES / daily: 8 trades, WR 0.0%, PnL $-64.77, drag share 32.7%`
- Top directional drag pockets: `YES / daily: 8 trades, WR 0.0%, PnL $-64.77, drag share 32.7%; NO / intraday: 12 trades, WR 8.3%, PnL $-53.25, drag share 26.9%; NO / daily: 3 trades, WR 0.0%, PnL $-29.47, drag share 14.9%`
- Top-two directional drag share: `59.6%`
- Exclusion rescue verdict: `NO_SIMPLE_EXCLUSION_RESCUE; reasons=['residual_negative_after_all_simple_cuts', 'worst_pocket_not_dominant_enough', 'best_residual_still_negative']`
- Exclusion rescue scenarios: `drop_worst_pocket: removed 8 trades / $-64.77, residual $-128.20; drop_top2_pockets: removed 20 trades / $-118.02, residual $-74.95; drop_top3_pockets: removed 23 trades / $-147.49, residual $-45.48; drop_all_yes: removed 13 trades / $-106.51, residual $-86.46`

## Composite Policy Rescue

- Verdict: `ONLY_LOW_SAMPLE_COMPOSITE_PATCH`
- Gate verdict: `NO_PROMOTABLE_COMPOSITE_POLICY; reasons=['best_sampled_policy_still_negative_or_flat', 'only_low_sample_positive_composite_policy']`
- Sample bar: `5`
- Best sampled composite policy: `ALL / weekly / cap<=40%: 5 trades, WR 0.0%, PnL $-9.06`
- Best low-sample composite policy: `ALL / intraday / cap<=30%: 2 trades, WR 50.0%, PnL $+7.46`
- Positive sampled / low-sample composite policies: `0` / `7`
- Top composite policies: `ALL / intraday / cap<=30%: 2 trades, WR 50.0%, PnL $+7.46; NO / intraday / cap<=30%: 2 trades, WR 50.0%, PnL $+7.46; ALL / ultra_short / cap<=40%: 2 trades, WR 50.0%, PnL $+5.32; ALL / ultra_short / cap<=50%: 2 trades, WR 50.0%, PnL $+5.32; NO / ultra_short / ALL: 2 trades, WR 50.0%, PnL $+5.32`

## Risk/Return

- Expectancy per closed trade: `$-5.51`
- Avg win / avg loss: `$+22.73` / `$-7.22`
- Payoff ratio: `3.15`
- PnL to max drawdown: `-1.0`
- Best / worst timeframe: `ultra_short +5.32 (2 trades)` / `daily -94.24 (11 trades)`

## Performance

- Closed trades: `35`
- Win rate: `5.7%`
- Total PnL: `$-192.96`
- Max drawdown: `$192.96`
- Profit factor: `0.19`
- Positive timeframe lanes: `ultra_short +5.32 (2 trades)`
- Negative timeframe lanes: `daily -94.24 (11 trades); intraday -66.51 (15 trades); weekly -37.52 (7 trades)`
- PnL concentrated in one positive timeframe: `True`

## Replay Cohort

- Holdout gate feasible today: `False`
- Holdout raw trades: `3`
- Diagnostic widened holdout support: `False`
- Diagnostic widened holdout sweep: `20% raw=3 filtered=0; 30% raw=6 filtered=0; 40% raw=7 filtered=0; 50% raw=8 filtered=0`
- Active cohort trades / markets: `35` / `13`
- Active cohort entry span: `2026-03-24T08:34:28.017395` -> `2026-03-24T23:07:35.746890`
- Active cohort symbols: `{'ETH': 35}`
- Holdout trades / markets: `3` / `3`
- Holdout exclusion reasons: `{'expiry_too_far': 1, 'edge_below_threshold': 1, 'arb_edge_below_threshold': 1}`

## Inventory

- Inventory refresh mode: `live_scan`
- Inventory source generated at: `live_scan`
- Inventory freshness verdict: `live_fresh`
- Inventory snapshot age hours: `0.00h`
- Inventory freshness threshold hours: `4.00h`
- Inventory fresh enough for research summary: `True`
- Strict tradeable markets: `0`
- Broad tradeable markets: `63`
- Strict share of broad surface: `0.0%`
- Broad minus strict markets: `63`
- Inventory funnel read: `Market surface exists, but production filters eliminate all current candidates.`
- Strict ETH short-horizon markets: `0`
- Broad ETH short-horizon markets: `0`
- Broad BTC long-dated markets: `39`
- Broad ETH long-dated markets: `21`
- Thesis surface share of broad: `0.0%`
- Strict thesis capture rate: `none`
- BTC long-dated to ETH short-horizon ratio: `none`
- Top strict exclusion reasons: `low_volume_24h 584 (55.6%); low_liquidity 211 (20.1%); symbol_filtered 108 (10.3%)`
- Top broad exclusion reasons: `duplicate_key 998 (50.2%); expired_market 514 (25.9%); inactive_market 180 (9.1%)`
- Dominant broad symbol / expiry bucket: `BTC (66.7%)` / `>3d (93.7%)`
- Strict exclusion reasons: `{'symbol_filtered': 108, 'expiry_too_far': 62, 'expired_market': 20, 'low_liquidity': 211, 'low_volume_24h': 584, 'inactive_market': 32, 'non_crypto_question': 33}`

## Archive Context

- Context data dirs: `8`
- Current-config archive score: `28.16`
- Current-config archive PnL: `$-6.51`
- Current-config archive holdout trades: `0`

## Team

- `Universe Scout`: Own ETH/BTC market discovery, symbol hygiene, and expiry/volume policy so the bot scans the markets that actually exist.
- `Swarm Calibration Lead`: Own model availability, prompt calibration, abstain behavior, and price-anchored probability estimates.
- `Structural Arb Researcher`: Focus only on clean complementary, ladder, and range coherence edges instead of broad low-quality arbitrage.
- `Replay Guardian`: Own the truthful measurement stack so parameter changes only ship when holdout and trade-count gates pass.
- `Execution Risk Lead`: Translate measured edge into attended deployment rules, bankroll sizing, and kill-switch thresholds.

## Blockers

- `Runtime swarm is not operational`: 0/3 recent runtime runs were consensus-ready. Historical cohort: 0/23.
  - Recent paper abstains are infrastructure-driven, so they cannot be treated as real no-edge evidence. The runtime lane looks chronically unavailable, not just temporarily degraded.
- `The latest ETH runtime cycle found no tradeable markets`: Latest runtime scan counts were 21 queries / 1050 raw / 1017 parsed / 1050 filtered / 0 tradeable. Top exclusions: low_volume_24h: 584; low_liquidity: 211; symbol_filtered: 108.
  - The freshest ETH runtime bottleneck is current inventory scarcity, so the latest no-trade cycle should be read as search-and-filter blockage before provider consensus or alpha quality.
- `There is no filtered holdout support for the current ETH configuration`: Replay accepted=False and widened holdout support=False.
  - There is no out-of-sample evidence to justify deployment or BTC expansion.
- `The only positive exploratory lane is still low sample`: ETH:swarm_only:min=none:max=1.0 has 2 trades.
  - The observed positive patch is too small to promote into a deployable ETH edge thesis.
- `The only positive ETH patch is non-independent`: Best low-sample patch is 3 trades across 2 markets, with residual ex-best $-23.89.
  - The surviving positive patch still looks like a one-off tail winner rather than a repeatable ETH edge.
- `The realized ETH book is still negative`: Closed-trade PnL is $-192.96 with profit factor 0.19.
  - The current realized book does not support live deployment, even before accounting for runtime degradation.
- `Higher-confidence predictions are behaving like anti-signal`: >= 50% confidence cohort: 13 trades, 0.0% win rate, $-106.51 PnL.
  - The current confidence scale is not trustworthy enough for deployment, because stronger conviction is not translating into better outcomes.
- `YES-side directional calls are behaving like anti-signal`: YES cohort: 13 trades, 0.0% win rate, $-106.51 PnL.
  - The current swarm is not only miscalibrated on confidence; it is also leaning into a losing direction, so directional calls are not trustworthy enough for deployment.
- `Production-style inventory is empty while broader inventory still exists`: Strict tradeable markets=0, broad tradeable markets=63.
  - The search universe and filters still need work before the bot can reliably source candidates.

## Priorities

- `Increase sample size before promoting any exploratory ETH variant`: The best positive exploratory lane is based on too few trades to treat as meaningful evidence.
  - Treat `ETH:swarm_only:min=none:max=1.0` as a low-sample lead only; it has 2 trades, below the 5 trade research bar.
  - Gather more resolved ETH paper trades before changing defaults or celebrating a candidate edge.
- `Fix runtime swarm provider failures before interpreting paper abstains`: Recent paper artifacts show the swarm cannot currently reach the required model count at runtime, so no-trade cycles are partly infrastructure-driven.
  - Address recent runtime provider failures in `/home/satya/moon-dev-ai-agents/src/data/polymarket_trader_candidate_soak_20260503_runtime_b` before treating abstains as alpha evidence.
  - Recent runtime error codes: {'unknown': 0}. Funding or auth fixes should come before new strategy tuning.
  - Recent run-level error pattern: {'insufficient_credits': 3, 'insufficient_balance': 3}.
  - Persistently healthy providers: ['none']; persistently blocked providers: ['claude', 'deepseek'].
  - Most common recent healthy-provider set: xai; single-provider-only runs: 2 (66.7%).
  - Recent runtime cohort: 0/3 runs were runtime-ready.
  - Historical runtime cohort: 0/23 runs were runtime-ready.
  - Historical provider ok-rates: {'claude': 0.0, 'deepseek': 0.0, 'xai': 0.522}.
  - Historical healthy-provider sets: {'xai': 12, 'none': 11}; most common historical healthy-provider set: xai.
  - Historical failure composition: xai-only=12 (52.2%), no-healthy-provider=11 (47.8%), other=0.
  - Historical run-level error pattern: {'insufficient_credits': 10, 'insufficient_balance': 10}.
- `Split inventory policy between short-horizon ETH and broader ladder markets`: Strict production filters are finding no tradeable markets even though the broader live surface still has inventory.
  - Rework the 24h volume gate, which is currently blocking 584 candidates in the latest strict scan.
  - Separate binary up/down duration logic from longer-dated ladder and range markets before changing ranking logic.
- `Fix the latest ETH runtime inventory blockage before reading more no-trade cycles as strategy evidence`: The freshest ETH runtime cycle found zero tradeable markets, so the immediate blocker is current inventory quality rather than model output quality.
  - Latest runtime scan counts were 21 queries / 1050 raw / 1017 parsed / 1050 filtered / 0 tradeable.
  - Top latest-runtime exclusions were: low_volume_24h: 584; low_liquidity: 211; symbol_filtered: 108.
  - Treat the newest no-trade cycle as inventory-blocked first; only secondarily as a swarm-health signal.
- `Keep arbitrage structural and strict`: Recent performance still shows arbitrage losing money, so broad discrepancy hunting is dilutive.
  - Limit arb research to ladder, range, and complementary coherence setups.
  - Require replay evidence before broadening any arbitrage filter.
- `Repair confidence calibration before trusting stronger signals`: The current higher-confidence cohort is performing worse than the lower-confidence cohort, so increasing conviction does not currently improve edge quality.
  - Treat >= 50% confidence as untrusted until calibration improves; the current cohort is 13 trades with 0.0% win rate and $-106.51 PnL.
  - Compare against the lower-confidence cohort (22 trades, 9.1% win rate) before promoting any new threshold.
  - Bias future swarm work toward calibration, abstain rules, and price anchoring rather than stronger conviction prompts.
- `Do not expect a simple confidence gate to rescue the current strategy`: The best simple confidence cap in the current journal is still negative, so thresholding conviction alone is not enough to create edge.
  - The best current confidence cap is <= 30% with 5 trades and $-18.59 PnL.
  - Prioritize better probability calibration and market selection instead of only clipping high-confidence trades.
- `Strip YES-side bias out of the current swarm before trusting directional calls`: The current healthy journal shows YES calls are materially worse than NO calls, so the model is not just miscalibrated, it is leaning into the wrong side.
  - Treat current YES-side calls as anti-signal until fixed: 13 trades, 0.0% win rate, $-106.51 PnL.
  - The least-bad current side is NO, but it is still not promotable.
  - The dominant current directional drag is YES / daily: 8 trades, WR 0.0%, PnL $-64.77.
  - Bias future swarm prompt work toward directional neutrality and stronger downside / contrarian checks rather than stronger YES conviction.
- `Do not promote the best direction-timeframe patch without more sample`: The least-bad direction-timeframe pocket is still too thin to treat as a real edge.
  - Current best pocket is NO / ultra_short with 2 trades and $+5.32 PnL.
  - Keep this as a research patch only until it clears the normal minimum trade bar with positive PnL.
- `Do not expect one exclusion filter to rescue the current book`: Even after dropping the worst measured pockets, the remaining healthy cohort is still negative, so the edge problem is broader than one bad slice.
  - Best simple exclusion rescue still leaves residual PnL at $-45.48 after `drop_top3_pockets`.
  - Treat the current failure as a stacked weakness pattern, not a single filter bug.
- `Do not generalize the lone positive timeframe without more samples`: The only positive realized lane is concentrated in a tiny sample, so it is not enough to claim a durable edge.
  - Treat `ultra_short` as exploratory only: $+5.32 across 2 trades.
  - Require at least the normal research trade-count bar before promoting any timeframe-specific edge thesis.
- `Do not promote the surviving cheap-tail ETH patch as a real edge`: The only positive entry-price patch is not independent enough to trust, because it is still carried by too few trades and fails without its largest winner.
  - Current patch concentration is 3 trades across 2 markets, with residual ex-best $-23.89.
  - Treat reason codes ['low_trade_count', 'two_or_fewer_markets', 'fails_without_top_win', 'top_win_exceeds_total_patch_pnl'] as a hard stop on promoting this patch.
  - Require a positive ETH patch that survives without its top win and spans more distinct markets before treating it as real alpha.
- `Use holdout acceptance as the non-negotiable shipping gate`: The current strategy still lacks a clean accepted holdout result, so in-sample wins are not enough.
  - Do not treat current optimization wins as production-ready while holdout score remains 0.00.
  - Favor experiments that increase filtered holdout trade count before chasing marginal score gains.
  - The diagnostic widened trailing-holdout probe still finds no filtered holdout support across 20%-50% late-cohort splits.
