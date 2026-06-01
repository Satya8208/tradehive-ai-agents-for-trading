# Polymarket Weather Trading End-to-End Plan

## Goal

Build the weather lane into a real alpha system, not just a forecast display. The target operating model is:

`market scan -> station mapping -> source ingestion -> feature packet -> candidate ranking -> paper gate -> alpha report -> live gate`

Live weather order placement remains blocked until a lane has real evidence, a compatible accepted alpha report, clean preflight, and clean geoblock/risk checks.

## Current State

- The weather path is isolated under `src/agents/polymarket_trader`; crypto behavior stays unchanged.
- Weather feature contracts exist and flow through research, paper, and live gates.
- Station mapping is conservative: known cities map to explicit stations/gridpoints, unknowns fail closed.
- Open-Meteo, NWS/METAR placeholders, HRRR, and NBM statuses normalize into structured source packets.
- HRRR/NBM point ingestion exists through `wgrib2`: manifest -> NOAA GRIB2 subset -> station point JSON -> latest cache.
- The orchestrator can optionally run high-resolution ingestion for selected weather markets before building weather signals.
- Live mode is still blocked unless alpha verification and live gates pass.

## Operating Architecture

### 1. Market Discovery

`market_scanner.py` scans active weather-tagged Polymarket events and produces `CLIMarket` objects. Weather-specific parsing must continue to reject:

- unsupported location
- unsupported metric
- ambiguous threshold/range
- unknown resolution station
- non-weather markets that slipped through tags

### 2. Station and Resolution Truth

`station_mapper.py` resolves each market to a `WeatherResolutionTarget`.

The mapper is the truth boundary. If the market cannot be tied to a station/gridpoint and resolution rule, the system can research it but cannot paper-trade or live-trade it.

### 3. Source Ingestion

`weather_high_res_cycle.py` is the cycle bridge:

- takes active weather markets
- builds HRRR/NBM manifests
- ingests point artifacts with `weather_high_res_ingestor.py`
- writes cycle reports and ledgers
- fills the same cache that `weather_signals.py` reads

CLI examples:

```bash
python -m src.agents.polymarket_trader.weather_high_res_cycle --market-json markets.json --dry-run
python -m src.agents.polymarket_trader.weather_high_res_cycle --market-json markets.json --sources noaa_hrrr noaa_nbm
```

Paper runner opt-in:

```bash
python -m src.agents.polymarket_trader.paper_run --weather --weather-high-res-ingest --weather-require-high-res --weather-fetch-orderbook
```

### 4. Feature Packet

`weather_signals.py` builds the `WeatherFeaturePacket` with:

- station mapping
- low-resolution forecast snapshot
- high-resolution source status
- station-bias correction
- source age and run ID
- CLOB price movement since prior scan
- raw forecast metrics and adjusted metrics
- edge flags and quality flags

No missing source is silently ignored. Missing or stale data becomes a blocker or quality flag.

### 5. Candidate Ranking

`weather_candidate_ranker.py` turns a weather packet into a candidate only when:

- schema is current
- source statuses are acceptable
- market probability and model probability are present
- edge clears the paper threshold after costs
- liquidity and size constraints are acceptable

### 6. Paper Gate

`weather_gate.py` blocks paper candidates when:

- feature schema mismatches
- station mapping failed
- selected source is unavailable/stale
- high-resolution confirmation is required but not live-safe
- station bias validation is required but missing
- accepted alpha report is required but absent/incompatible

The paper ledger must include accepted, skipped, and blocked weather candidates.

### 7. Research and Alpha

`weather_edge_lab.py`, `weather_alpha.py`, and `weather_research_team.py` should consume the same feature packet schema used by paper trading.

The research loop must build resolved datasets from real Polymarket outcomes and real weather observations. No synthetic weather or market data is allowed for edge claims.

### 8. Promotion

A lane can become live-eligible only after:

- accepted alpha report matches `feature_schema_version`, model config, source family, lead-time window, and minimum edge
- chronological holdout beats market baseline on Brier/log loss
- paper trades are positive after fees/slippage
- drawdown and concentration checks pass
- preflight, geoblock, and risk checks are clean

## Edge Lanes

### Station-Bias Edge

Hypothesis: city/airport/gridpoint resolution differences create systematic forecast errors.

Build:

- METAR/official observation catalog per station
- realized-vs-forecast residuals by station, season, lead time, and weather regime
- bias corrections in `WeatherStationBiasResolver`

Tradable only if:

- at least 300 resolved records in the lane
- at least 75 chronological holdout trades
- Brier/log loss improves at least 2% over uncorrected forecast baseline
- paper ROI remains positive after costs
- PnL is not one station or one date cluster

### Model-Update and Run-Lag Edge

Hypothesis: HRRR/NBM updates move fair value before Polymarket reprices.

Build:

- run-arrival ledger
- run-to-run forecast delta
- source age and target lead features
- CLOB price movement before/after new model runs

Tradable only if:

- paper entries occur inside a defined post-run window
- average net edge is at least 8 percentage points before sizing
- at least 100 paper candidates in the lane
- edge survives excluding the best week and best station

### Behavioral and Order-Book Edge

Hypothesis: traders overreact to recent weather, favorite/longshot framing, or stale headlines.

Build:

- recency and momentum features
- longshot/favorite bucket performance
- depth-aware slippage estimates
- size caps based on available book depth

Tradable only if:

- improves calibrated model ROI versus forecast-only baseline
- reduces drawdown or improves Sharpe in paper
- no dependency on thin-book fills that cannot execute

### Structural Cross-Market Edge

Hypothesis: mutually exclusive temperature buckets or related weather ranges are mispriced.

Build:

- exact bucket boundary parser
- mutually exclusive group validation
- fill-size-aware no-basket and yes-basket checks

Tradable only if:

- resolution rules match exactly
- order book supports full basket size
- net edge survives fees, spread, and partial-fill unwind risk

## Build Sequence From Here

1. Keep hardening `weather_high_res_cycle.py` against real market scans and real NOAA download behavior.
2. Add a station-bias catalog builder from official observations and resolved market dates.
3. Extend model update detection from in-memory signals to durable run-arrival and price-lag ledgers.
4. Feed high-resolution snapshots into `weather_alpha.py` historical datasets.
5. Run a first real resolved-market dataset and produce a rejected or accepted alpha report.
6. Only after a rejected report explains the weakness, improve the weakest lane instead of lowering gates.
7. Paper trade with high-resolution confirmation required.
8. Promote only the specific lane that passed evidence, not the whole weather system.

## Operator Runbook

The evidence loop has four separate steps. Do not skip the order-book or label steps when judging edge.

### 1. Paper Evidence Collection

```bash
~/miniconda3/envs/tflow/bin/python -m src.agents.polymarket_trader.paper_run --weather --cycles 1 --markets 5 --weather-high-res-ingest --weather-fetch-orderbook
```

Expected artifacts:

- `src/data/polymarket_trader/weather_evidence/market_tape.jsonl`
- `src/data/polymarket_trader/weather_evidence/feature_snapshots.jsonl`
- `src/data/polymarket_trader/weather_evidence/candidate_decisions.jsonl`

Replay tradeability requires side-specific `orderbook_best_ask` evidence. Scan prices are indicative only.

### 2. Resolution Label Collection

Run this after collected markets have settled:

```bash
~/miniconda3/envs/tflow/bin/python -m src.agents.polymarket_trader.weather_resolution_labels
```

Expected artifacts:

- `src/data/polymarket_trader/weather_evidence/resolution_labels.jsonl`
- `src/data/polymarket_trader/weather_evidence/label_collection_summary.json`

Labels must come from closed/resolved Polymarket market payloads. Active markets, even at 99c/1c, remain pending.

### 3. Replay and Evidence Report

```bash
~/miniconda3/envs/tflow/bin/python -m src.agents.polymarket_trader.weather_replay
```

Expected artifacts:

- `src/data/polymarket_trader/weather_evidence/replay_records.jsonl`
- `src/data/polymarket_trader/weather_evidence/latest_weather_evidence_report.json`
- `src/data/polymarket_trader/weather_evidence/latest_weather_evidence_report.md`

The fields that decide whether edge exists are:

- `edge_status`
- `tradeable_replay_count`
- `candidate_roi_per_1usd`
- `model_brier` versus `market_brier`
- `model_log_loss` versus `market_log_loss`
- `orderbook_coverage`
- `by_blocker`
- `deployment_verdict.blockers`

### 4. Live Status

Live weather trading is not enabled by this loop. The evidence report can only pass paper/research gates. Runtime still blocks live weather candidates with `WEATHER_LIVE_DISABLED` and the weather gate blocks live weather with `weather_live_requires_preflight_and_manual_enablement`.

## Do Not Build Yet

- no live weather order enablement
- no paid or proprietary weather feeds
- no full-grid weather platform
- no complex ensemble ML before simple calibrated baselines prove useful
- no global weather expansion before CONUS HRRR/NBM is stable
- no streaming architecture before hourly polling evidence exists
