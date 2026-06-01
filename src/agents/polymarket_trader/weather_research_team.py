"""
Weather-market research team for Polymarket.

This is a read-only research runner. It scans active weather markets, enriches
each market with live forecast context, ranks the clearest forecast-vs-market
edges, and writes JSON plus Markdown artifacts for operator review.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .data_signals import ExchangeDataSignals
from .market_scanner import CLIMarketScanner
from .models import CLIMarket
from .weather_contracts import FEATURE_SCHEMA_VERSION
from .weather_edge_discovery import WeatherEdgeDiscoveryBoard
from .weather_agent_teams import WeatherAgentTeamPlanner
from .weather_high_res_cycle import WeatherHighResolutionIngestCycleRunner


@dataclass(frozen=True)
class WeatherResearchRole:
    role_id: str
    title: str
    mandate: str
    key_questions: List[str]
    daily_output: str
    success_metrics: List[str]


@dataclass(frozen=True)
class WeatherDataSourcePlan:
    source_id: str
    name: str
    url: str
    coverage: str
    edge_use: str
    integration_status: str
    caveats: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class WeatherEdgeTrack:
    code: str
    title: str
    hypothesis: str
    data_sources: List[str]
    analysis_method: str
    daily_deliverable: str
    acceptance_gate: str
    owner_role: str


@dataclass(frozen=True)
class WeatherResearchExperiment:
    code: str
    title: str
    why_it_creates_edge: str
    implementation_notes: List[str]
    promotion_evidence: List[str]
    owner_role: str


class WeatherResearchTeam:
    """Read-only weather market research workflow."""

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        scanner: Optional[CLIMarketScanner] = None,
        signals: Optional[ExchangeDataSignals] = None,
        high_res_cycle_runner: Optional[WeatherHighResolutionIngestCycleRunner] = None,
        output_dir: Optional[Path] = None,
    ):
        self.config = config or PolymarketCLIConfig(
            execution_mode=ExecutionMode.DRY_RUN,
            market_vertical="weather",
            search_symbols=["WEATHER"],
            min_liquidity_usd=500.0,
            min_volume_24h_usd=0.0,
            max_expiry_hours=16 * 24,
            min_expiry_minutes=0.0,
            max_markets_to_analyze=25,
        )
        self.scanner = scanner or CLIMarketScanner(config=self.config)
        self.signals = signals or ExchangeDataSignals(self.config)
        self.high_res_cycle_runner = high_res_cycle_runner
        self.output_dir = output_dir or (self.config.data_dir / "weather_research_team")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_report(self, force_refresh: bool = True, limit: Optional[int] = None) -> Dict[str, Any]:
        markets = self.scanner.scan_markets(force_refresh=force_refresh)
        ranked = self.scanner.rank_markets(markets)
        if limit is None:
            limit = int(self.config.max_markets_to_analyze)
        selected = [market for market, _score in ranked[:limit]]
        high_resolution_ingest = self._refresh_high_resolution_sources(selected)
        run_lag_evidence = self._run_lag_evidence_summary()
        edge_discovery = WeatherEdgeDiscoveryBoard(config=self.config).build_report(write=True)
        contexts = self.signals.get_market_context(selected)

        market_rows = [
            self._market_row(market, contexts.get(market.condition_id, {}))
            for market in selected
        ]
        candidates = [
            row
            for row in market_rows
            if row.get("context_status") == "ok"
            and abs(float(row.get("weather_edge_percent", 0.0) or 0.0))
            >= float(self.config.weather_min_probability_gap * 100.0)
        ]
        candidates.sort(
            key=lambda row: (
                abs(float(row.get("weather_edge_percent", 0.0) or 0.0)),
                float(row.get("liquidity", 0.0) or 0.0),
            ),
            reverse=True,
        )

        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "market_vertical": "weather",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "markets_scanned": len(markets),
            "markets_selected": len(selected),
            "candidate_count": len(candidates),
            "config": {
                "min_liquidity_usd": self.config.min_liquidity_usd,
                "min_volume_24h_usd": self.config.min_volume_24h_usd,
                "max_expiry_hours": self.config.max_expiry_hours,
                "weather_min_probability_gap": self.config.weather_min_probability_gap,
            },
            "candidates": candidates,
            "markets": market_rows,
            "scanner_telemetry": getattr(self.scanner, "last_scan_telemetry", {}),
            "high_resolution_ingest": high_resolution_ingest,
            "run_lag_evidence": run_lag_evidence,
            "edge_discovery": edge_discovery,
            "team_manifest": self.build_team_manifest(),
            "research_team_operating_model": self.build_research_team_operating_model(),
            "data_source_backlog": self.build_data_source_backlog(),
            "edge_generation_plan": self.build_edge_generation_plan(candidates, market_rows),
            "ranked_edge_roadmap": self.build_ranked_edge_roadmap(),
            "experiment_backlog": self.build_experiment_backlog(),
            "deployment_verdict": self.build_deployment_verdict(candidates),
            "artifacts": {
                "json": str(self.output_dir / "latest_weather_edge_report.json"),
                "markdown": str(self.output_dir / "latest_weather_edge_report.md"),
            },
        }
        report["agent_team_plan"] = WeatherAgentTeamPlanner(self.config).build_from_files(
            research_report=report
        )
        self._write_report(report)
        return report

    def _refresh_high_resolution_sources(self, selected: List[CLIMarket]) -> Dict[str, Any]:
        if not bool(getattr(self.config, "weather_auto_ingest_high_resolution", False)):
            return {"status": "disabled", "reason": "weather_auto_ingest_high_resolution_false"}
        if not selected:
            return {"status": "empty", "reason": "no_selected_markets"}
        runner = self.high_res_cycle_runner or WeatherHighResolutionIngestCycleRunner(
            self.config,
            cache_dir=getattr(self.config, "weather_high_resolution_cache_dir", "") or None,
        )
        self.high_res_cycle_runner = runner
        report = runner.run(selected, dry_run=False, force=False)
        return report.summary()

    def _run_lag_evidence_summary(self) -> Dict[str, Any]:
        state_path = self.config.data_dir / "weather_run_lag" / "latest_weather_run_lag_state.json"
        if not state_path.exists():
            return {"status": "missing", "state_path": str(state_path)}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "unreadable",
                "state_path": str(state_path),
                "error": f"{type(exc).__name__}: {exc}",
            }
        latest = payload.get("latest_by_key", {}) if isinstance(payload, dict) else {}
        if not isinstance(latest, dict):
            latest = {}
        last_event = payload.get("last_event", {}) if isinstance(payload, dict) else {}
        return {
            "status": "ready" if latest else "empty",
            "state_path": str(state_path),
            "event_log_path": str(payload.get("event_log_path") or "") if isinstance(payload, dict) else "",
            "updated_at": str(payload.get("updated_at") or "") if isinstance(payload, dict) else "",
            "tracked_source_station_metrics": len(latest),
            "last_event_type": str(last_event.get("event_type") or "") if isinstance(last_event, dict) else "",
            "last_event_run_id": str(last_event.get("run_id") or "") if isinstance(last_event, dict) else "",
        }

    def build_team_manifest(self) -> Dict[str, Any]:
        roles = [
            WeatherResearchRole(
                role_id="market_structure_cartographer",
                title="Market Structure Cartographer",
                mandate=(
                    "Map every active weather event into condition IDs, CLOB token IDs, "
                    "range buckets, resolution source, expiry, fees, and book depth."
                ),
                key_questions=[
                    "Are there mutually exclusive buckets whose NO basket is mispriced?",
                    "Does the market resolve from a station, city forecast, advisory, or manual source?",
                    "Which markets have enough depth to capture the measured edge?",
                ],
                daily_output=(
                    "Weather universe inventory with exact token IDs, resolution text, "
                    "bucket groups, fee flags, and executable structural-arb candidates."
                ),
                success_metrics=[
                    "weather markets parsed without manual cleanup",
                    "bucket groups with non-overlapping intervals",
                    "book depth available at target stake after fees",
                ],
            ),
            WeatherResearchRole(
                role_id="meteorological_data_engineer",
                title="Meteorological Data Engineer",
                mandate=(
                    "Ingest as-of-safe forecasts, official observations, and source metadata "
                    "for each market's exact location, date window, metric, and resolution rule."
                ),
                key_questions=[
                    "Which official or model source best matches the resolution rule?",
                    "What data arrives fastest near settlement without lookahead?",
                    "Where do forecast APIs disagree enough to make a tradable distribution?",
                ],
                daily_output=(
                    "As-of data packet per market with forecast run time, model member, "
                    "observation source, station mapping, latency, and missing-data flags."
                ),
                success_metrics=[
                    "forecast run timestamp captured",
                    "station or gridpoint tied to resolution text",
                    "no historical forecast source used as live evidence",
                ],
            ),
            WeatherResearchRole(
                role_id="forecast_modeling_lead",
                title="Forecast Modeling Lead",
                mandate=(
                    "Turn weather inputs into calibrated YES probabilities using ensembles, "
                    "bias correction, forecast-error distributions, and market-aware blending."
                ),
                key_questions=[
                    "Does a model beat market-implied probabilities out of sample?",
                    "Which horizons, cities, and metrics have persistent market bias?",
                    "Does model disagreement predict future market repricing?",
                ],
                daily_output=(
                    "Probability table with raw forecast probability, calibrated probability, "
                    "market probability, edge, confidence interval, and reason codes."
                ),
                success_metrics=[
                    "holdout Brier and log loss beat market baseline",
                    "positive ROI after fees and spread",
                    "edge survives by date, city, and metric slices",
                ],
            ),
            WeatherResearchRole(
                role_id="resolution_source_analyst",
                title="Resolution Source Analyst",
                mandate=(
                    "Read the market text like a contract and identify where generic weather "
                    "forecasts differ from the actual settlement source."
                ),
                key_questions=[
                    "Is the official source a named station, NWS product, NHC advisory, or SWPC scale?",
                    "Does the market define a local day, UTC day, range bucket, or exact integer?",
                    "Can official observations make the outcome knowable before market reprices?",
                ],
                daily_output=(
                    "Resolution-risk memo per candidate covering source, timezone, unit conversion, "
                    "rounding, station mismatch, and evidence needed before entry."
                ),
                success_metrics=[
                    "zero trades on ambiguous resolution text",
                    "all unit conversions explicit",
                    "timezone and local-day windows documented",
                ],
            ),
            WeatherResearchRole(
                role_id="microstructure_execution_lead",
                title="Microstructure Execution Lead",
                mandate=(
                    "Decide whether the theoretical edge can be captured on the CLOB after "
                    "spread, taker fee, partial fills, basket sequencing, and unwind risk."
                ),
                key_questions=[
                    "Can we fill the whole basket or directional stake at the edge price?",
                    "Is maker posting safer than taker crossing for this market?",
                    "What is the worst-case loss if only part of a weather basket fills?",
                ],
                daily_output=(
                    "Executable order plan with limit prices, max shares, fee estimate, "
                    "fill-or-kill requirement, and abort/unwind rule."
                ),
                success_metrics=[
                    "paper/live fill price tracked against signal price",
                    "no orphan basket legs",
                    "net edge remains positive after fees and slippage",
                ],
            ),
            WeatherResearchRole(
                role_id="validation_risk_lead",
                title="Validation and Risk Lead",
                mandate=(
                    "Keep the team honest by rejecting edge claims that do not survive "
                    "chronological holdout, sufficient sample size, and execution-cost gates."
                ),
                key_questions=[
                    "Is this a real edge or a one-day/weather-regime artifact?",
                    "Do results hold when the biggest winner is removed?",
                    "What capital cap is justified by observed drawdown and liquidity?",
                ],
                daily_output=(
                    "Promotion verdict with blockers, minimum evidence still missing, "
                    "risk limits, and next experiment priority."
                ),
                success_metrics=[
                    "chronological holdout used for promotion",
                    "minimum record and candidate counts met",
                    "directional weather trading stays research-only until accepted",
                ],
            ),
        ]
        roles.extend(
            [
                WeatherResearchRole(
                    role_id="weather_data_engineer",
                    title="Weather Data Engineer",
                    mandate=(
                        "Own HRRR/NBM/NWS/METAR ingestion, parser blockers, source timestamps, "
                        "and fail-closed data-quality contracts."
                    ),
                    key_questions=[
                        "Did the latest model run arrive and parse cleanly?",
                        "Which source fields are missing or stale?",
                        "Can every live feature be reconstructed as-of without lookahead?",
                    ],
                    daily_output="Source packet health ledger with run IDs, parser status, and missing-data blockers.",
                    success_metrics=[
                        "HRRR/NBM snapshots parsed with source_age_minutes",
                        "source outages create blockers instead of stale fills",
                    ],
                ),
                WeatherResearchRole(
                    role_id="quantitative_meteorologist",
                    title="Quantitative Meteorologist",
                    mandate=(
                        "Convert model grids and station observations into calibrated, station-corrected "
                        "threshold probabilities."
                    ),
                    key_questions=[
                        "Does station bias vary by season, metric, or weather regime?",
                        "Which model family is best by lead time and city?",
                        "Does ensemble disagreement help or only add noise?",
                    ],
                    daily_output="Forecast-error and station-bias memo with calibration deltas versus market baseline.",
                    success_metrics=[
                        "bias adjustment improves holdout Brier/log loss",
                        "station catalog has sufficient real observations",
                    ],
                ),
                WeatherResearchRole(
                    role_id="market_microstructure_specialist",
                    title="Market Microstructure Specialist",
                    mandate=(
                        "Measure whether forecast or structural edge survives Polymarket fees, spread, "
                        "depth, partial fills, and repricing speed."
                    ),
                    key_questions=[
                        "Did the market reprice after the model run before we could fill?",
                        "What size clears without eating the edge?",
                        "Are structural baskets all-leg executable?",
                    ],
                    daily_output="Depth, latency, and fill-quality report for each candidate lane.",
                    success_metrics=[
                        "predicted slippage matches paper fills",
                        "no accepted candidate depends on unavailable depth",
                    ],
                ),
                WeatherResearchRole(
                    role_id="quant_research_trader",
                    title="Quant Research Trader",
                    mandate=(
                        "Run experiments, compare edge lanes, tune thresholds, and keep paper/live promotion "
                        "behind strict evidence gates."
                    ),
                    key_questions=[
                        "Which lane beats the market out of sample?",
                        "Which threshold maximizes after-cost ROI without concentration?",
                        "Which candidates should be paper traded and which should be killed?",
                    ],
                    daily_output="Ranked experiment board with go/kill/needs-data verdicts.",
                    success_metrics=[
                        ">=75 holdout candidates before paper promotion",
                        "positive after-cost ROI with concentration checks",
                    ],
                ),
                WeatherResearchRole(
                    role_id="orchestration_devops_engineer",
                    title="Orchestration and DevOps Engineer",
                    mandate=(
                        "Keep research jobs reproducible, ledgers complete, and live weather execution blocked "
                        "until explicit promotion and preflight pass."
                    ),
                    key_questions=[
                        "Can each report be replayed from saved inputs?",
                        "Did every blocked candidate write a reason code?",
                        "Are schema/version mismatches caught before order creation?",
                    ],
                    daily_output="Pipeline status, regression-test status, and failed-source ledger.",
                    success_metrics=[
                        "cycle reports include skipped, blocked, and accepted candidates",
                        "schema and live gates fail closed",
                    ],
                ),
            ]
        )
        return {
            "objective": (
                "Create edge in Polymarket weather markets by combining structural "
                "arbitrage, as-of-safe weather data, calibrated probability models, "
                "contract-resolution analysis, and execution-cost controls."
            ),
            "operating_rules": [
                "Separate structural arbitrage from directional forecast edge.",
                "Do not use hindsight forecasts or observations as live-entry evidence.",
                "Every trade thesis must state the exact resolution source and timezone.",
                "Directional weather trading requires accepted alpha verification before live use.",
                "Basket arbitrage requires all-leg execution or a predefined abort/unwind path.",
            ],
            "roles": [asdict(role) for role in roles],
        }

    def build_research_team_operating_model(self) -> Dict[str, Any]:
        return {
            "north_star": "Find weather edges that beat Polymarket prices after costs, then prove them in paper mode.",
            "workstreams": [
                {
                    "lane": "model_update_lag",
                    "owner": "weather_data_engineer",
                    "consumer_modules": [
                        "weather_model_update_detector.py",
                        "weather_edge_features.py",
                        "weather_signals.py",
                        "weather_edge_lab.py",
                    ],
                    "daily_artifact": "run-lag ledger with run_id changes and CLOB repricing status",
                },
                {
                    "lane": "station_bias",
                    "owner": "quantitative_meteorologist",
                    "consumer_modules": [
                        "weather_station_bias_catalog.py",
                        "weather_edge_features.py",
                        "weather_alpha.py",
                    ],
                    "daily_artifact": "station bias catalog and forecast-error report",
                },
                {
                    "lane": "behavioral_mispricing",
                    "owner": "quant_research_trader",
                    "consumer_modules": [
                        "weather_behavior_monitor.py",
                        "weather_candidate_ranker.py",
                        "weather_edge_lab.py",
                    ],
                    "daily_artifact": "objective behavior flags and holdout ROI table",
                },
                {
                    "lane": "structural_bucket_arbitrage",
                    "owner": "market_microstructure_specialist",
                    "consumer_modules": [
                        "weather_structural_arb.py",
                        "arbitrage_detector.py",
                        "orchestrator.py",
                    ],
                    "daily_artifact": "basket candidates with all-leg fill requirements",
                },
                {
                    "lane": "execution_capacity",
                    "owner": "market_microstructure_specialist",
                    "consumer_modules": [
                        "weather_candidate_ranker.py",
                        "risk_manager.py",
                        "trader.py",
                    ],
                    "daily_artifact": "net-edge capacity table after spread, fees, and slippage",
                },
            ],
            "meeting_cadence": [
                "Daily: source health, live-scanned candidates, blocked reasons.",
                "Twice weekly: holdout and paper metrics by lane.",
                "Weekly: promote, continue, or kill each edge lane with evidence.",
            ],
        }

    def build_ranked_edge_roadmap(self) -> List[Dict[str, Any]]:
        return [
            {
                "rank": 1,
                "lane": "model_update_lag",
                "why_it_could_win": "New HRRR/NBM runs can change threshold probabilities before thin CLOB books fully reprice.",
                "modules": [
                    "weather_hrrr_parser.py",
                    "weather_nbm_parser.py",
                    "weather_model_update_detector.py",
                    "weather_price_latency_tracker",
                ],
                "data_needed": ["HRRR/NBM run files or parsed grids", "run_id/cycle_time", "CLOB price snapshots"],
                "validation": "Compare entries within X minutes of run changes against entries after market repricing.",
                "paper_gate": "parsed high-res snapshot, run_age under threshold, market not repriced, positive after-cost holdout ROI",
                "kill_condition": "run-lag signal does not beat market baseline or fills arrive after repricing",
            },
            {
                "rank": 2,
                "lane": "station_bias",
                "why_it_could_win": "Retail traders often anchor on city forecasts while settlement can depend on airport stations.",
                "modules": [
                    "weather_station_bias_catalog.py",
                    "weather_edge_features.py",
                    "weather_alpha_model.py",
                ],
                "data_needed": ["METAR/ASOS observations", "RTMA/URMA or comparable station/city joins", "market resolution station"],
                "validation": "Bias-adjusted probabilities improve Brier/log-loss and after-cost candidate ROI.",
                "paper_gate": "catalog sample size passes minimum and station mapping is unambiguous",
                "kill_condition": "bias adjustment worsens holdout calibration or is concentrated in one station",
            },
            {
                "rank": 3,
                "lane": "official_observation_latency",
                "why_it_could_win": "Near settlement, official observations/advisories can resolve facts before markets update.",
                "modules": [
                    "weather_source_registry.py",
                    "weather_model_update_detector.py",
                    "weather_gate.py",
                ],
                "data_needed": ["METAR/MADIS/NWS/NHC/SWPC timestamps", "CLOB snapshots", "resolution text"],
                "validation": "Measure minutes of stale tradable price after timestamped official updates.",
                "paper_gate": "source is official, timestamped, and market remains stale at executable depth",
                "kill_condition": "updates arrive after resolution or CLOB reprices before usable fill",
            },
            {
                "rank": 4,
                "lane": "behavioral_mispricing",
                "why_it_could_win": "Longshot/favorite and recency biases can persist in small weather markets.",
                "modules": ["weather_behavior_monitor.py", "weather_edge_lab.py", "weather_candidate_ranker.py"],
                "data_needed": ["price history", "prior observations", "model probabilities", "resolved outcomes"],
                "validation": "Behavior flags improve Sharpe/ROI over the base forecast edge without raising drawdown.",
                "paper_gate": "objective behavior flag plus model edge, with holdout improvement over no-flag baseline",
                "kill_condition": "flags increase variance or only work in one city/date cluster",
            },
            {
                "rank": 5,
                "lane": "structural_bucket_arbitrage",
                "why_it_could_win": "Thin bucket markets can have mathematically inconsistent YES/NO baskets.",
                "modules": ["weather_structural_arb.py", "arbitrage_detector.py", "trader.py"],
                "data_needed": ["full related bucket set", "token IDs", "bid/ask depth", "fees", "settlement bucket definitions"],
                "validation": "Candidate remains positive after all-leg execution, fees, slippage, and partial-fill controls.",
                "paper_gate": "all legs fillable or fill-or-kill simulated, no overlapping/ambiguous bucket ranges",
                "kill_condition": "partial-fill or liquidity risk erases theoretical edge",
            },
        ]

    def build_data_source_backlog(self) -> List[Dict[str, Any]]:
        sources = [
            WeatherDataSourcePlan(
                source_id="polymarket_gamma",
                name="Polymarket Gamma API",
                url="https://docs.polymarket.com/api-reference",
                coverage="Public market and event discovery, metadata, tags, resolution text, and token IDs.",
                edge_use="Build the active weather universe and group related bucket markets.",
                integration_status="already_used_by_scanner",
                caveats=["metadata can be incomplete", "resolution text must still be parsed defensively"],
            ),
            WeatherDataSourcePlan(
                source_id="polymarket_clob_orderbook",
                name="Polymarket CLOB orderbook and batch book endpoints",
                url="https://docs.polymarket.com/trading/orderbook",
                coverage="Public bid/ask books, prices, spreads, midpoints, and batch orderbook reads.",
                edge_use="Verify whether forecast or structural edge is executable at real depth.",
                integration_status="backlog_high_priority",
                caveats=["displayed market probability is not necessarily executable", "batch reads still need rate limiting"],
            ),
            WeatherDataSourcePlan(
                source_id="polymarket_price_history",
                name="Polymarket CLOB price history",
                url="https://docs.polymarket.com/api-reference/markets/get-prices-history",
                coverage="Historical token price series with configurable intervals and fidelity.",
                edge_use="Backtest as-of entry prices against resolved weather outcomes.",
                integration_status="partially_integrated_weather_alpha",
                caveats=["price series is not the same as full historical orderbook depth"],
            ),
            WeatherDataSourcePlan(
                source_id="polymarket_market_websocket",
                name="Polymarket market WebSocket",
                url="https://docs.polymarket.com/developers/CLOB/websocket/market-channel-migration-guide",
                coverage="Real-time orderbook snapshots, price changes, trades, new markets, and resolutions.",
                edge_use="Capture repricing and stale-book windows faster than polling.",
                integration_status="backlog",
                caveats=["stream handling needs reconnect and replay logic"],
            ),
            WeatherDataSourcePlan(
                source_id="polymarket_fees",
                name="Polymarket fee schedule",
                url="https://docs.polymarket.com/trading/fees",
                coverage="Per-category taker fee formula and fee-enabled market metadata.",
                edge_use="Convert gross model or basket edge into net executable edge.",
                integration_status="backlog_high_priority",
                caveats=["fee parameters should be fetched dynamically", "builder fees must be kept out unless intentional"],
            ),
            WeatherDataSourcePlan(
                source_id="open_meteo_forecast",
                name="Open-Meteo Forecast API",
                url="https://open-meteo.com/en/docs",
                coverage="Global hourly forecasts and model selection for temperature, precipitation, snow, and wind.",
                edge_use="Fast baseline probability estimates for active weather markets.",
                integration_status="already_integrated_live_signals",
                caveats=["not always the official resolution source", "model timestamps should be stored"],
            ),
            WeatherDataSourcePlan(
                source_id="nws_api",
                name="National Weather Service API",
                url="https://www.weather.gov/documentation/services-web-api",
                coverage="US forecasts, alerts, observations, hourly forecasts, and forecast grid data.",
                edge_use="Use official public forecast changes and observations for US settlement-source matching.",
                integration_status="backlog_high_priority",
                caveats=["requires User-Agent", "observation endpoints can lag and need station mapping"],
            ),
            WeatherDataSourcePlan(
                source_id="open_meteo_previous_runs",
                name="Open-Meteo Previous Model Runs API",
                url="https://open-meteo.com/en/docs/previous-runs-api",
                coverage="Archived previous forecasts by lead time for comparing run-to-run changes.",
                edge_use="Train and evaluate as-of-safe forecast-error distributions.",
                integration_status="integrated_weather_alpha",
                caveats=["model availability differs by provider and variable"],
            ),
            WeatherDataSourcePlan(
                source_id="open_meteo_historical_forecast",
                name="Open-Meteo Historical Forecast API",
                url="https://open-meteo.com/en/docs/historical-forecast-api",
                coverage="Archived high-resolution forecast model data for training and model comparison.",
                edge_use="Research feature engineering and historical calibration only.",
                integration_status="research_only_guarded",
                caveats=["not as-of safe for live entry unless run timestamps are reconstructed"],
            ),
            WeatherDataSourcePlan(
                source_id="nws_gridpoints",
                name="National Weather Service gridpoint API",
                url="https://weather-gov.github.io/api/gridpoints",
                coverage="US 2.5 km official forecast grid time series exposed through api.weather.gov.",
                edge_use="Match US city markets to official NWS forecast grids and identify deviations from generic APIs.",
                integration_status="backlog_high_priority",
                caveats=["US coverage only", "gridpoint lookup and WFO mapping required"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_nbm",
                name="NOAA National Blend of Models",
                url="https://nomads.ncep.noaa.gov/txt_descriptions/BLEND_txt.html",
                coverage="Calibrated blended model guidance with deterministic and probabilistic forecast fields.",
                edge_use="Build calibrated exceedance probabilities instead of heuristic sigmoid probabilities.",
                integration_status="backlog_high_priority",
                caveats=["GRIB2 ingestion and variable mapping required"],
            ),
            WeatherDataSourcePlan(
                source_id="ncep_nomads",
                name="NCEP NOMADS operational model gateway",
                url="https://nomads.ncep.noaa.gov/",
                coverage="NOAA operational GRIB2 model output including HRRR, GFS, GEFS, NBM, RTMA, and URMA.",
                edge_use="Pull source model fields around target locations without waiting for convenience APIs.",
                integration_status="backlog_high_priority",
                caveats=["operational files arrive by cycle and forecast hour", "GRIB filtering and completeness checks required"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_hrrr",
                name="NOAA High-Resolution Rapid Refresh",
                url="https://rapidrefresh.noaa.gov/hrrr/",
                coverage="Hourly updated 3 km short-range model for North America.",
                edge_use="Nowcast intraday temperature, wind, precipitation, and severe weather settlement windows.",
                integration_status="backlog",
                caveats=["short horizon", "GRIB2 processing required"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_awc_metar",
                name="NOAA Aviation Weather Center Data API",
                url="https://aviationweather.gov/data/api/",
                coverage="METAR observations and TAF terminal forecasts with current and recent-history access.",
                edge_use="Map city weather markets to airport observations for temperature, wind, gust, and present weather.",
                integration_status="backlog_high_priority",
                caveats=["METAR temperatures are often whole Celsius", "API limits require caching for broad scans"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_rtma_urma",
                name="NOAA RTMA and URMA analyses",
                url="https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/rtma.php",
                coverage="Near-surface analysis grids for current and recently verified temperature, wind, and humidity.",
                edge_use="Nowcast whether a threshold has already been crossed when station data is delayed.",
                integration_status="backlog",
                caveats=["analysis grids are not always the resolution source", "latency varies by product"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_nexrad",
                name="NOAA NEXRAD radar archive and open data",
                url="https://www.ncei.noaa.gov/products/radar/next-generation-weather-radar",
                coverage="US radar Level II and Level III products for precipitation and storm nowcasting.",
                edge_use="Detect rain/no-rain and snow-band reality before slower official daily summaries publish.",
                integration_status="backlog",
                caveats=["large binary products", "radar/gauge mismatch must be modeled"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_stage_iv_qpe",
                name="NOAA Stage IV quantitative precipitation estimates",
                url="https://api.water.noaa.gov/about/precipitation-data-access",
                coverage="Hourly and daily precipitation estimate products for US accumulation analysis.",
                edge_use="Support precipitation-total markets and post-resolution verification.",
                integration_status="backlog",
                caveats=["product day boundaries can differ from market rules", "not always the settlement source"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_nhc",
                name="NOAA National Hurricane Center data archive",
                url="https://www.nhc.noaa.gov/data/",
                coverage="Tropical cyclone advisories, forecasts, tracks, and public products.",
                edge_use="Analyze hurricane and tropical-storm markets with official advisory timing.",
                integration_status="backlog",
                caveats=["seasonal opportunity set", "advisory semantics differ by market"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_swpc",
                name="NOAA Space Weather Prediction Center products",
                url="https://www.swpc.noaa.gov/products/",
                coverage="Geomagnetic, solar radiation, and radio blackout forecasts, alerts, and reports.",
                edge_use="Support space-weather markets that the surface-weather adapter explicitly rejects.",
                integration_status="backlog",
                caveats=["different outcome taxonomy than surface weather", "event counts and scales need custom parser"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_ncei_cdo",
                name="NOAA NCEI Climate Data Online and data services",
                url="https://www.ncei.noaa.gov/cdo-web/webservices/v2",
                coverage="Historical daily and subdaily observation datasets and station metadata.",
                edge_use="Verify settled outcomes and build station-level calibration baselines.",
                integration_status="backlog",
                caveats=["API token may be required", "station coverage and latency vary"],
            ),
            WeatherDataSourcePlan(
                source_id="noaa_madis_metar",
                name="NOAA MADIS METAR and ASOS observations",
                url="https://madis.ncep.noaa.gov/madis_metar.shtml",
                coverage="METAR and ASOS observations, including high-frequency observation feeds.",
                edge_use="Near-resolution nowcasting and official station reconciliation.",
                integration_status="backlog",
                caveats=["access path is more operationally complex than JSON forecast APIs"],
            ),
            WeatherDataSourcePlan(
                source_id="ecmwf_open_data",
                name="ECMWF Open Data",
                url="https://www.ecmwf.int/en/forecasts/datasets/open-data",
                coverage="Global IFS/AIFS forecast subset from recent model cycles.",
                edge_use="Add independent global-model signal and disagreement features versus NOAA guidance.",
                integration_status="backlog",
                caveats=["attribution required", "full-resolution or historical depth may require paid access"],
            ),
            WeatherDataSourcePlan(
                source_id="dwd_icon_open_data",
                name="DWD ICON Open Data",
                url="https://www.dwd.de/EN/ourservices/nwp_forecast_data/nwp_forecast_data.html",
                coverage="German Weather Service ICON global and regional GRIB2 model suite.",
                edge_use="Add independent model input for Europe and global cross-model ensemble features.",
                integration_status="backlog",
                caveats=["GRIB2 integration required", "less directly tied to US settlement sources"],
            ),
        ]
        return [asdict(source) for source in sources]

    def build_edge_generation_plan(
        self,
        candidates: List[Dict[str, Any]],
        market_rows: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        status_counts: Dict[str, int] = {}
        for row in market_rows:
            status = str(row.get("context_status", "missing"))
            status_counts[status] = status_counts.get(status, 0) + 1

        tracks = [
            WeatherEdgeTrack(
                code="structural_bucket_arbitrage",
                title="Weather Range NO-Basket Arbitrage",
                hypothesis=(
                    "Mutually exclusive weather range buckets can overprice YES collectively. "
                    "Buying all NO legs can have positive worst-case payout without forecasting the weather."
                ),
                data_sources=[
                    "polymarket_gamma",
                    "polymarket_clob_orderbook",
                    "polymarket_fees",
                    "polymarket_market_websocket",
                ],
                analysis_method=(
                    "Group markets by location, metric, target date, and non-overlapping numeric interval. "
                    "Compute best NO basket using executable ask prices, fees, min/max stake, and all-leg fill constraints."
                ),
                daily_deliverable="Arbitrage basket sheet with leg token IDs, target shares, net edge, and FOK order plan.",
                acceptance_gate=(
                    "Net edge remains positive after fee and slippage buffers, all legs fit size limits, "
                    "and partial-fill unwind risk is explicitly bounded."
                ),
                owner_role="market_structure_cartographer",
            ),
            WeatherEdgeTrack(
                code="forecast_mispricing",
                title="Live Forecast Versus Market Mispricing",
                hypothesis=(
                    "Some weather markets price stale narratives while deterministic forecast data has already moved."
                ),
                data_sources=[
                    "open_meteo_forecast",
                    "nws_gridpoints",
                    "noaa_nbm",
                    "noaa_hrrr",
                    "polymarket_clob_orderbook",
                ],
                analysis_method=(
                    "Parse the contract rule, pull the closest matching forecast grids/models, estimate YES probability, "
                    "compare to executable CLOB probability, and flag only large gaps."
                ),
                daily_deliverable="Ranked forecast edge report with probability, market price, rule parse, and model evidence.",
                acceptance_gate=(
                    "Candidate is research-only until the same feature set beats market baseline on chronological holdout."
                ),
                owner_role="forecast_modeling_lead",
            ),
            WeatherEdgeTrack(
                code="asof_calibrated_model",
                title="As-Of Historical Forecast Calibration",
                hypothesis=(
                    "Forecast-model error by city, metric, and lead time can be learned and converted into better "
                    "probabilities than raw forecast heuristics or market prices."
                ),
                data_sources=[
                    "open_meteo_previous_runs",
                    "open_meteo_historical_forecast",
                    "polymarket_price_history",
                    "noaa_ncei_cdo",
                ],
                analysis_method=(
                    "Join resolved markets to entry-time CLOB prices, previous forecast runs, and official outcomes. "
                    "Fit simple blends first, then add city/metric/horizon calibration and ensemble disagreement features."
                ),
                daily_deliverable="Calibration report with best policy, holdout Brier/log loss, ROI, blockers, and next slice.",
                acceptance_gate=(
                    "At least 300 resolved records, 8 target dates, and 75 holdout candidates; "
                    "holdout Brier/log loss improve by at least 2% versus market; bootstrap ROI lower bound is positive."
                ),
                owner_role="validation_risk_lead",
            ),
            WeatherEdgeTrack(
                code="resolution_source_latency",
                title="Resolution Source and Observation Latency",
                hypothesis=(
                    "Markets sometimes lag official station observations, NHC advisories, or SWPC products near resolution."
                ),
                data_sources=[
                    "nws_gridpoints",
                    "noaa_madis_metar",
                    "noaa_nhc",
                    "noaa_swpc",
                    "polymarket_market_websocket",
                ],
                analysis_method=(
                    "Map each market to the exact official source, monitor source updates and CLOB repricing, "
                    "and measure minutes of tradable lag after source publication."
                ),
                daily_deliverable="Latency watchlist with official source URL, expected update time, and stale-market trigger.",
                acceptance_gate=(
                    "Only trade when the source is unambiguous, update is timestamped, and the market remains stale "
                    "at executable size after fees."
                ),
                owner_role="resolution_source_analyst",
            ),
            WeatherEdgeTrack(
                code="model_disagreement_repricing",
                title="Model Disagreement and Repricing Signals",
                hypothesis=(
                    "Large disagreement between NBM, HRRR, NWS grids, and Open-Meteo providers predicts later "
                    "market repricing when the consensus resolves."
                ),
                data_sources=[
                    "open_meteo_forecast",
                    "nws_gridpoints",
                    "noaa_nbm",
                    "noaa_hrrr",
                    "polymarket_price_history",
                ],
                analysis_method=(
                    "Track forecast dispersion, run-to-run drift, and threshold crossing probability. "
                    "Backtest whether dispersion plus market skew predicts profitable entries or abstentions."
                ),
                daily_deliverable="Disagreement dashboard and avoid/trade tags by market.",
                acceptance_gate=(
                    "Feature improves holdout calibration or reduces drawdown versus the simpler forecast-gap strategy."
                ),
                owner_role="forecast_modeling_lead",
            ),
            WeatherEdgeTrack(
                code="execution_alpha",
                title="CLOB Execution and Maker Edge",
                hypothesis=(
                    "Some theoretical edges only become real by placing patient maker orders or avoiding thin books."
                ),
                data_sources=[
                    "polymarket_clob_orderbook",
                    "polymarket_market_websocket",
                    "polymarket_fees",
                    "polymarket_price_history",
                ],
                analysis_method=(
                    "Replay candidate signals against bid/ask depth, fee schedule, fill probability, and post-entry drift. "
                    "Compare taker crossing to maker posting."
                ),
                daily_deliverable="Net-edge execution table with max stake, limit price, fee, spread, and expected fill mode.",
                acceptance_gate=(
                    "Net expected value is positive after realistic fill assumptions and the risk manager can enforce caps."
                ),
                owner_role="microstructure_execution_lead",
            ),
        ]

        top_candidate = candidates[0] if candidates else {}
        return {
            "current_surface": {
                "markets_with_context": status_counts.get("ok", 0),
                "candidate_count": len(candidates),
                "top_candidate": {
                    "question": top_candidate.get("question", ""),
                    "recommended_side": top_candidate.get("recommended_side", ""),
                    "weather_edge_percent": top_candidate.get("weather_edge_percent"),
                    "weather_signal": top_candidate.get("weather_signal", ""),
                    "url": top_candidate.get("url", ""),
                },
                "context_status_counts": dict(sorted(status_counts.items())),
            },
            "tracks": [asdict(track) for track in tracks],
            "promotion_gates": [
                "contract rule parsed into location, metric, date window, operator, units, and source",
                "input data is as-of safe for the proposed entry timestamp",
                "edge is measured against executable bid/ask, not displayed midpoint only",
                "fees, spread, slippage, and partial-fill risk are included",
                "directional model passes chronological holdout before live deployment",
                "holdout Brier and log loss beat market baseline by at least 2% relative",
                "bootstrap 95% lower bound for holdout candidate ROI is positive after fill haircut",
                "no single location, target date, or metric contributes more than 35% of accepted holdout PnL",
                "paper mode runs for 30 days or 100 live-scanned candidates before real capital",
                "structural arbitrage has all-leg execution or explicit abort/unwind logic",
            ],
        }

    def build_experiment_backlog(self) -> List[Dict[str, Any]]:
        experiments = [
            WeatherResearchExperiment(
                code="leakage_audit",
                title="As-Of Leakage and Source Safety Audit",
                why_it_creates_edge=(
                    "It prevents the team from mistaking hindsight forecasts or stale prices for tradable signal."
                ),
                implementation_notes=[
                    "Store forecast source, forecast cycle proxy, previous-run lead key, target date, and price timestamp distance.",
                    "Fail records that use historical-forecast data as live evidence or whose price is more than 3 hours from asof_time.",
                ],
                promotion_evidence=[
                    "unsafe-source count is zero for promoted candidates",
                    "price freshness distribution is included in every alpha report",
                ],
                owner_role="meteorological_data_engineer",
            ),
            WeatherResearchExperiment(
                code="calibration_curves",
                title="Reliability Curves and Calibration Bins",
                why_it_creates_edge=(
                    "Weather markets can look profitable by ROI while probabilities are miscalibrated; calibration bins expose that."
                ),
                implementation_notes=[
                    "Add decile reliability output for market, raw forecast, and calibrated blend.",
                    "Report expected calibration error and per-bin sample count by metric and lead time.",
                ],
                promotion_evidence=[
                    "calibrated blend improves ECE versus market and raw heuristic",
                    "no accepted bin depends on tiny samples only",
                ],
                owner_role="forecast_modeling_lead",
            ),
            WeatherResearchExperiment(
                code="walk_forward_evaluator",
                title="Walk-Forward Weather Alpha Evaluator",
                why_it_creates_edge=(
                    "A rolling split checks whether edge survives changing weather regimes and market behavior."
                ),
                implementation_notes=[
                    "Train on earlier target dates and test on the next chronological fold.",
                    "Aggregate Brier, log loss, ROI, drawdown, and candidate count across folds.",
                ],
                promotion_evidence=[
                    "majority of folds beat market baseline",
                    "train-to-holdout degradation stays within configured tolerance",
                ],
                owner_role="validation_risk_lead",
            ),
            WeatherResearchExperiment(
                code="blend_search_v2",
                title="Calibration Model Search V2",
                why_it_creates_edge=(
                    "The current linear blend may miss nonlinear threshold behavior and city-specific forecast bias."
                ),
                implementation_notes=[
                    "Compare linear blend, logistic calibration, isotonic calibration, beta calibration, and market shrinkage.",
                    "Log every tried policy and penalize multiple testing before promotion.",
                ],
                promotion_evidence=[
                    "winning model survives out-of-sample and multiple-test penalty",
                    "model coefficients or bins are interpretable by metric and lead",
                ],
                owner_role="forecast_modeling_lead",
            ),
            WeatherResearchExperiment(
                code="source_ensemble",
                title="NOAA/Open-Meteo/ECMWF Source Ensemble",
                why_it_creates_edge=(
                    "Independent model disagreement can identify stale market pricing and reduce false confidence."
                ),
                implementation_notes=[
                    "Join Open-Meteo previous runs, NWS grids, NBM, HRRR, GFS/GEFS, and ECMWF where available.",
                    "Create features for run-to-run drift, ensemble spread, threshold exceedance count, and source disagreement.",
                ],
                promotion_evidence=[
                    "source features improve holdout Brier/log loss or reduce drawdown",
                    "source outages fail closed rather than filling with stale values",
                ],
                owner_role="meteorological_data_engineer",
            ),
            WeatherResearchExperiment(
                code="execution_cost_model",
                title="Execution Cost and Capacity Model",
                why_it_creates_edge=(
                    "A model edge is worthless if it cannot be filled at size after spread, fees, and slippage."
                ),
                implementation_notes=[
                    "Score candidates at midpoint, worse-side fill, and conservative book-walk fill.",
                    "Apply weather taker fee formula, tick rounding, min size, and max capacity by depth.",
                ],
                promotion_evidence=[
                    "net edge remains positive after conservative fill haircut",
                    "recommended stake is below liquidity and exposure caps",
                ],
                owner_role="microstructure_execution_lead",
            ),
            WeatherResearchExperiment(
                code="cluster_risk",
                title="Weather Cluster Exposure Limits",
                why_it_creates_edge=(
                    "Weather candidates are correlated by city, storm, date, and model error; sizing must account for that."
                ),
                implementation_notes=[
                    "Group candidates by target_date, location, metric, storm, and shared resolution source.",
                    "Cap one-sided exposure and reject portfolios where one cluster dominates expected PnL.",
                ],
                promotion_evidence=[
                    "no accepted location/date/metric cluster contributes more than 35% of holdout PnL",
                    "paper drawdown remains inside configured weather loss limit",
                ],
                owner_role="portfolio_risk_lead",
            ),
            WeatherResearchExperiment(
                code="shadow_live_harness",
                title="Shadow Live Weather Harness",
                why_it_creates_edge=(
                    "It measures whether live-scanned signals behave like backtests before risking capital."
                ),
                implementation_notes=[
                    "Save every live scan recommendation, including rejects, with as-of inputs and executable book snapshot.",
                    "After resolution, reconcile against outcomes and compare realized calibration to backtest expectations.",
                ],
                promotion_evidence=[
                    "30 days or 100 live-scanned candidates completed",
                    "rolling 30-candidate Brier still beats market baseline",
                ],
                owner_role="validation_risk_lead",
            ),
        ]
        return [asdict(experiment) for experiment in experiments]

    def build_deployment_verdict(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "current_scope": "research_only",
            "directional_weather_trading": "blocked_until_alpha_report_accepted",
            "structural_arbitrage": "allowed_only_after_all_leg_execution_checks",
            "candidate_signal_status": "live_candidates_found" if candidates else "no_live_candidates_found",
            "strict_promotion_bar": {
                "min_resolved_records": 300,
                "min_target_dates": 8,
                "min_holdout_candidate_edges": 75,
                "min_relative_brier_improvement": 0.02,
                "min_relative_log_loss_improvement": 0.02,
                "max_pnl_concentration_share": 0.35,
                "max_entry_price_age_hours": 3,
                "shadow_mode": "30_days_or_100_live_scanned_candidates",
            },
            "requirements": [
                "Run weather_alpha backtests with as-of forecast data and resolved Polymarket labels.",
                "Promote only if calibrated alpha accepts chronological holdout gates.",
                "Add CLOB depth and fee checks before treating any forecast gap as executable.",
                "Add official station/source mapping before trading markets that resolve from named observations.",
                "Use fractional Kelly only after promotion, capped by bankroll, liquidity, and cluster exposure.",
                "Keep unsupported space-weather markets out of surface-weather heuristics until SWPC ingestion exists.",
            ],
        }

    def _market_row(self, market: CLIMarket, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "market_id": market.condition_id,
            "question": market.question,
            "url": market.market_url,
            "yes_price": round(float(market.yes_price or 0.0), 4),
            "no_price": round(float(market.no_price or 0.0), 4),
            "liquidity": round(float(market.liquidity or 0.0), 2),
            "volume_24h": round(float(market.volume_24h or 0.0), 2),
            "time_remaining_hours": round(float(market.time_remaining_hours or 0.0), 2),
            "context_status": context.get("status", "missing"),
            "location": context.get("location", ""),
            "metric": context.get("metric", ""),
            "threshold": context.get("threshold"),
            "upper_threshold": context.get("upper_threshold"),
            "threshold_unit": context.get("threshold_unit", ""),
            "weather_probability": context.get("weather_probability"),
            "weather_edge_percent": context.get("weather_edge_percent"),
            "recommended_side": context.get("recommended_side", ""),
            "weather_signal": context.get("weather_signal", ""),
            "forecast_metrics": context.get("forecast_metrics", {}),
            "feature_schema_version": context.get("feature_schema_version", ""),
            "source_statuses": context.get("source_statuses", {}),
            "station_mapping": context.get("station_mapping", {}),
            "station_bias": context.get("station_bias", {}),
            "high_resolution_sources": context.get("high_resolution_sources", []),
            "latency_signals": context.get("latency_signals", {}),
            "model_update_events": context.get("model_update_events", []),
            "edge_reason_flags": context.get("edge_reason_flags", []),
            "quality_flags": context.get("quality_flags", []),
        }

    def _write_report(self, report: Dict[str, Any]) -> None:
        json_path = self.output_dir / "latest_weather_edge_report.json"
        md_path = self.output_dir / "latest_weather_edge_report.md"
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        md_path.write_text(self._format_markdown(report), encoding="utf-8")

    def _format_markdown(self, report: Dict[str, Any]) -> str:
        lines = [
            "# Polymarket Weather Research Team",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Feature schema: `{report.get('feature_schema_version')}`",
            f"- Markets scanned: `{report.get('markets_scanned')}`",
            f"- Markets selected: `{report.get('markets_selected')}`",
            f"- Candidate edges: `{report.get('candidate_count')}`",
            f"- High-resolution ingest: `{report.get('high_resolution_ingest', {}).get('status', 'missing')}`",
            f"- Run-lag evidence: `{report.get('run_lag_evidence', {}).get('status', 'missing')}`",
            f"- Edge-building phase: `{report.get('edge_discovery', {}).get('current_phase', 'missing')}`",
            f"- Edge built: `{report.get('edge_discovery', {}).get('edge_built', False)}`",
            "",
            "## Top Forecast Edges",
        ]

        candidates = report.get("candidates", [])
        if not candidates:
            lines.append("- No weather candidate cleared the configured forecast edge gap.")
        for row in candidates[:10]:
            lines.append(
                f"- `{row.get('recommended_side')}` edge `{row.get('weather_edge_percent'):+.2f}%` "
                f"on {row.get('question')} | YES `{row.get('yes_price')}` | "
                f"{row.get('weather_signal')}"
            )

        lines.extend(["", "## How Edge Gets Created"])
        for track in report.get("edge_generation_plan", {}).get("tracks", []):
            lines.append(f"- `{track.get('code')}`: {track.get('hypothesis')}")

        lines.extend(["", "## Edge Building State"])
        edge_discovery = report.get("edge_discovery", {})
        edge_summary = edge_discovery.get("summary", {}) if isinstance(edge_discovery, dict) else {}
        lines.append(f"- Current phase: `{edge_discovery.get('current_phase', 'missing')}`")
        lines.append(f"- Edge built: `{edge_discovery.get('edge_built', False)}`")
        lines.append(f"- Resolved records: `{edge_summary.get('resolved_record_count', 0)}`")
        lines.append(f"- Executable replay decisions: `{edge_summary.get('tradeable_replay_count', 0)}`")
        for action in edge_discovery.get("next_actions", [])[:6]:
            lines.append(f"- Next: {action}")

        lines.extend(["", "## Ranked Edge Roadmap"])
        for item in report.get("ranked_edge_roadmap", []):
            modules = ", ".join(item.get("modules", [])[:3])
            lines.append(
                f"- `{item.get('rank')}` `{item.get('lane')}`: {item.get('why_it_could_win')} "
                f"Modules: {modules}. Paper gate: {item.get('paper_gate')}"
            )

        agent_plan = report.get("agent_team_plan", {}) if isinstance(report.get("agent_team_plan"), dict) else {}
        if agent_plan:
            verdict = agent_plan.get("architecture_verdict", {}) or {}
            lines.extend(
                [
                    "",
                    "## Agent Team Operating Plan",
                    f"- Plan schema: `{agent_plan.get('schema_version')}`",
                    f"- Stage: `{verdict.get('current_stage', 'unknown')}`",
                    f"- Bottleneck: `{verdict.get('primary_bottleneck', 'unknown')}`",
                    f"- Verdict: {verdict.get('summary', '')}",
                    "",
                    "## Strategy Edge Team",
                ]
            )
            for role in (agent_plan.get("teams", {}) or {}).get("strategy_edge_team", []):
                rights = ", ".join(role.get("decision_rights", [])[:3])
                lines.append(
                    f"- `{role.get('role_id')}` - {role.get('title')}: "
                    f"{role.get('mandate')} Rights: {rights}."
                )
            lines.extend(["", "## Reviewer Builder Team"])
            for role in (agent_plan.get("teams", {}) or {}).get("reviewer_builder_team", []):
                veto = ", ".join(role.get("veto_power", [])[:3]) or "no explicit veto"
                lines.append(
                    f"- `{role.get('role_id')}` - {role.get('title')}: "
                    f"{role.get('mandate')} Veto: {veto}."
                )
            lines.extend(["", "## Alpha Lane Cards"])
            for card in agent_plan.get("alpha_lane_cards", []):
                lines.append(
                    f"- `{card.get('rank')}` `{card.get('lane')}` ({card.get('status')}): "
                    f"{card.get('hypothesis')} Next: {card.get('next_build_action')}"
                )
            lines.extend(["", "## Current Review Findings"])
            for finding in agent_plan.get("current_review_findings", []):
                lines.append(
                    f"- `{finding.get('severity')}` `{finding.get('status')}` "
                    f"`{finding.get('finding_id')}`: {finding.get('required_change')}"
                )
            lines.extend(["", "## Team Output Contracts"])
            lines.append(
                f"- Strategy contract: `{(agent_plan.get('strategy_output_contract') or {}).get('schema_version')}`"
            )
            lines.append(
                f"- Review contract: `{(agent_plan.get('review_output_contract') or {}).get('schema_version')}`"
            )
            for patch in agent_plan.get("pro_patch_sequence", [])[:8]:
                lines.append(
                    f"- Pro patch `{patch.get('id')}`: `{patch.get('status')}` "
                    f"owner `{patch.get('owner_role')}`"
                )
            for item in agent_plan.get("immediate_build_queue", [])[:6]:
                lines.append(
                    f"- Build queue `{item.get('priority')}` `{item.get('work_item')}`: "
                    f"{item.get('required_change')}"
                )

        lines.extend(["", "## Research Agent Team"])
        for role in report.get("team_manifest", {}).get("roles", []):
            metrics = "; ".join(role.get("success_metrics", [])[:2])
            lines.append(
                f"- `{role.get('role_id')}` - {role.get('title')}: "
                f"{role.get('daily_output')} Success: {metrics}."
            )

        lines.extend(["", "## Operating Model"])
        for workstream in report.get("research_team_operating_model", {}).get("workstreams", []):
            modules = ", ".join(workstream.get("consumer_modules", [])[:4])
            lines.append(
                f"- `{workstream.get('lane')}` owned by `{workstream.get('owner')}` -> "
                f"{workstream.get('daily_artifact')}. Modules: {modules}."
            )

        lines.extend(["", "## Data Backlog"])
        for source in report.get("data_source_backlog", [])[:16]:
            lines.append(
                f"- `{source.get('source_id')}` ({source.get('integration_status')}): "
                f"{source.get('edge_use')} {source.get('url')}"
            )

        lines.extend(["", "## Experiment Backlog"])
        for experiment in report.get("experiment_backlog", [])[:10]:
            lines.append(
                f"- `{experiment.get('code')}`: {experiment.get('why_it_creates_edge')}"
            )

        verdict = report.get("deployment_verdict", {})
        lines.extend(
            [
                "",
                "## Deployment Verdict",
                f"- Current scope: `{verdict.get('current_scope', 'unknown')}`",
                f"- Directional weather trading: `{verdict.get('directional_weather_trading', 'unknown')}`",
                f"- Structural arbitrage: `{verdict.get('structural_arbitrage', 'unknown')}`",
            ]
        )
        strict_bar = verdict.get("strict_promotion_bar", {})
        if strict_bar:
            lines.append(
                "- Strict promotion bar: "
                f"`{strict_bar.get('min_resolved_records')}` records, "
                f"`{strict_bar.get('min_target_dates')}` target dates, "
                f"`{strict_bar.get('min_holdout_candidate_edges')}` holdout candidates, "
                f"`{strict_bar.get('min_relative_brier_improvement'):.0%}` Brier improvement."
            )
        for requirement in verdict.get("requirements", []):
            lines.append(f"- Requirement: {requirement}")

        lines.extend(["", "## Coverage"])
        status_counts: Dict[str, int] = {}
        for row in report.get("markets", []):
            status = str(row.get("context_status", "missing"))
            status_counts[status] = status_counts.get(status, 0) + 1
        for status, count in sorted(status_counts.items()):
            lines.append(f"- `{status}`: `{count}`")
        lines.append("")
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Polymarket weather edge report")
    parser.add_argument("--markets", type=int, default=25, help="Markets to include in the report")
    parser.add_argument("--min-liquidity", type=float, default=500.0, help="Minimum market liquidity")
    parser.add_argument("--min-volume", type=float, default=0.0, help="Minimum 24h volume")
    parser.add_argument("--max-expiry-hours", type=float, default=16 * 24, help="Max weather forecast horizon")
    parser.add_argument("--max-search-queries", type=int, default=12, help="Max Polymarket weather search queries")
    parser.add_argument("--data-dir", type=str, default=None, help="Override data directory")
    parser.add_argument("--output-dir", type=str, default=None, help="Override report output directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = PolymarketCLIConfig(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        min_liquidity_usd=args.min_liquidity,
        min_volume_24h_usd=args.min_volume,
        max_expiry_hours=args.max_expiry_hours,
        min_expiry_minutes=0.0,
        max_markets_to_analyze=args.markets,
        max_weather_search_queries=args.max_search_queries,
    )
    if args.data_dir:
        config._data_dir_override = Path(args.data_dir)

    team = WeatherResearchTeam(
        config=config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    report = team.build_report(force_refresh=True, limit=args.markets)
    cprint("Weather research report written", "green")
    cprint(f"  Candidates: {report.get('candidate_count')}", "white")
    cprint(f"  Output: {team.output_dir}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
