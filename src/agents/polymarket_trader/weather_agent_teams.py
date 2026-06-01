"""
Deterministic operating model for the Polymarket weather agent teams.

The strategy team is allowed to create hypotheses. The reviewer/builder team
is allowed to promote or block implementation work. Neither team can override
the deterministic paper/live gates.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PolymarketCLIConfig


WEATHER_AGENT_TEAM_PLAN_SCHEMA_VERSION = "weather_agent_team_plan_v1"


@dataclass(frozen=True)
class WeatherAgentRole:
    team_id: str
    role_id: str
    title: str
    mandate: str
    decision_rights: List[str]
    required_inputs: List[str]
    output_artifacts: List[str]
    success_metrics: List[str]
    veto_power: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class WeatherAlphaLaneCard:
    rank: int
    lane: str
    title: str
    owner_role: str
    status: str
    hypothesis: str
    implementation_targets: List[str]
    proof_evidence: List[str]
    disproof_evidence: List[str]
    promotion_gate: str
    current_blockers: List[str]
    next_build_action: str


@dataclass(frozen=True)
class WeatherReviewFinding:
    finding_id: str
    severity: str
    status: str
    title: str
    evidence: List[str]
    required_change: str
    owner_role: str
    tests_required: List[str]
    live_gate_impact: str


class WeatherAgentTeamPlanner:
    """Build strategy and reviewer-team packets from current weather artifacts."""

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config

    def build_from_files(self, *, research_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data_dir = self._data_dir()
        reports = {
            "candidate_supply": self._read_json(
                data_dir / "weather_candidate_supply" / "latest_weather_candidate_supply_report.json"
            ),
            "known_outcome": self._read_json(
                data_dir / "weather_known_outcome_alpha" / "latest_weather_known_outcome_alpha_report.json"
            ),
            "ladder": self._read_json(
                data_dir / "weather_ladder_consistency_alpha" / "latest_weather_ladder_consistency_report.json"
            ),
            "evidence": self._read_json(
                data_dir / "weather_evidence" / "latest_weather_evidence_report.json"
            ),
            "research": research_report or self._read_json(
                data_dir / "weather_research_team" / "latest_weather_edge_report.json"
            ),
        }
        return self.build(reports)

    def build(self, reports: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        reports = reports or {}
        known = reports.get("known_outcome", {}) or {}
        findings = self._review_findings(reports)
        lane_cards = self._alpha_lane_cards(reports)
        pro_patch_sequence = self._pro_patch_sequence()
        return {
            "schema_version": WEATHER_AGENT_TEAM_PLAN_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "mission": (
                "Run weather-market strategy discovery and system-quality review as two separate "
                "agent teams, with deterministic gates deciding what can move from research to replay, "
                "paper, or live eligibility."
            ),
            "architecture_verdict": self._architecture_verdict(known, findings),
            "pro_architecture_advice": self._pro_architecture_advice(),
            "promotion_chain": self._promotion_chain(),
            "pro_patch_sequence": pro_patch_sequence,
            "source_reports_considered": self._source_reports_considered(reports),
            "teams": {
                "strategy_edge_team": [asdict(role) for role in self._strategy_team()],
                "reviewer_builder_team": [asdict(role) for role in self._reviewer_builder_team()],
            },
            "strategy_output_contract": self._strategy_output_contract(),
            "review_output_contract": self._review_output_contract(),
            "alpha_lane_cards": [asdict(card) for card in lane_cards],
            "current_review_findings": [asdict(finding) for finding in findings],
            "immediate_build_queue": self._build_queue(lane_cards, findings, pro_patch_sequence),
            "release_non_negotiables": self._release_non_negotiables(),
        }

    def _data_dir(self) -> Path:
        if self.config is not None:
            return Path(self.config.data_dir)
        return Path("src/data/polymarket_trader")

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _strategy_team() -> List[WeatherAgentRole]:
        return [
            WeatherAgentRole(
                team_id="strategy_edge_team",
                role_id="chief_weather_strategist",
                title="Chief Weather Strategy Lead",
                mandate="Own the ranked alpha backlog and force every lane into proof or disproof.",
                decision_rights=["prioritize lanes", "kill weak hypotheses", "request builder work"],
                required_inputs=["candidate supply", "known-outcome report", "replay evidence", "orderbook depth"],
                output_artifacts=["ranked lane cards", "experiment briefs", "kill criteria"],
                success_metrics=["lanes have falsifiable gates", "weak lanes are killed quickly"],
            ),
            WeatherAgentRole(
                team_id="strategy_edge_team",
                role_id="contract_resolution_counsel",
                title="Contract Resolution Counsel",
                mandate="Treat every market question as a contract before any alpha logic sees it.",
                decision_rights=["block ambiguous settlement source", "require spec compiler changes"],
                required_inputs=["raw market rules", "WeatherMarketSpec", "station mapping", "resolution labels"],
                output_artifacts=["settlement-risk memos", "spec blocker backlog"],
                success_metrics=["zero accepted candidates with ambiguous source/window/unit"],
                veto_power=["market_spec_ambiguous", "settlement_source_unverified"],
            ),
            WeatherAgentRole(
                team_id="strategy_edge_team",
                role_id="meteorological_alpha_lead",
                title="Meteorological Alpha Lead",
                mandate="Design official-observation, model-run, station-bias, and source-disagreement experiments.",
                decision_rights=["choose weather data source", "define source freshness SLA"],
                required_inputs=["METAR/ASOS", "NWS/NOAA runs", "forecast packets", "station bias catalog"],
                output_artifacts=["weather-source experiment cards", "source-disagreement tables"],
                success_metrics=["source freshness captured", "as-of leakage stays blocked"],
            ),
            WeatherAgentRole(
                team_id="strategy_edge_team",
                role_id="microstructure_alpha_lead",
                title="Microstructure Alpha Lead",
                mandate="Decide whether any model edge survives real CLOB depth, spread, fees, and fill probability.",
                decision_rights=["reject non-fillable alpha", "choose taker/maker paper policy"],
                required_inputs=["orderbook snapshots", "fillability reports", "fee assumptions", "market tape"],
                output_artifacts=["capacity tables", "positive-depth candidate lists"],
                success_metrics=["no edge claim depends on midpoint or dust depth"],
                veto_power=["executable_depth_missing", "fillability_below_minimum"],
            ),
            WeatherAgentRole(
                team_id="strategy_edge_team",
                role_id="calibration_scientist",
                title="Calibration Scientist",
                mandate="Measure whether probabilities beat market baseline on chronological replay and paper data.",
                decision_rights=["set replay metrics", "reject overfit calibration"],
                required_inputs=["resolved labels", "feature snapshots", "paper decisions", "market prices"],
                output_artifacts=["Brier/log-loss tables", "false-positive ledgers", "bootstrap lower-bound reports"],
                success_metrics=["holdout improves market baseline", "false positives become disproof examples"],
            ),
        ]

    @staticmethod
    def _reviewer_builder_team() -> List[WeatherAgentRole]:
        return [
            WeatherAgentRole(
                team_id="reviewer_builder_team",
                role_id="system_architecture_reviewer",
                title="System Architecture Reviewer",
                mandate="Find places where data, gates, or artifacts are verbose but not enforceable.",
                decision_rights=["open build tickets", "block promotion", "demand simpler contracts"],
                required_inputs=["module map", "artifact schemas", "gate reports", "dashboard snapshot"],
                output_artifacts=["architecture findings", "patch priority list"],
                success_metrics=["findings point to modules and tests, not generic advice"],
                veto_power=["live_gate_bypass", "artifact_not_replayable"],
            ),
            WeatherAgentRole(
                team_id="reviewer_builder_team",
                role_id="evidence_lineage_reviewer",
                title="Evidence Lineage Reviewer",
                mandate="Verify every candidate can be replayed from raw source payloads and hashes.",
                decision_rights=["block candidate without evidence refs", "require append-only evidence"],
                required_inputs=["market tape", "feature snapshots", "candidate decisions", "resolution labels"],
                output_artifacts=["evidence lineage report", "missing-payload backlog"],
                success_metrics=["proof and disproof are both stored for rejected candidates"],
                veto_power=["missing_raw_payload", "source_timestamp_missing"],
            ),
            WeatherAgentRole(
                team_id="reviewer_builder_team",
                role_id="test_safety_engineer",
                title="Test and Safety Engineer",
                mandate="Turn each safety claim into a deterministic regression test.",
                decision_rights=["require test before patch acceptance", "define live-block suite"],
                required_inputs=["changed files", "gate rules", "command bus", "live eligibility"],
                output_artifacts=["test matrix", "live-block regressions", "dashboard wiring tests"],
                success_metrics=["paper/live tests fail closed", "dashboard buttons are backend-enforced"],
                veto_power=["missing_live_block_test", "untested_gate_change"],
            ),
            WeatherAgentRole(
                team_id="reviewer_builder_team",
                role_id="operator_workflow_builder",
                title="Operator Workflow Builder",
                mandate="Make the control room show what matters: lane status, blockers, evidence, and safe actions.",
                decision_rights=["wire read-only actions", "mark unfinished UI not-wired"],
                required_inputs=["snapshot payload", "action catalog", "artifact freshness", "lane reports"],
                output_artifacts=["operator dashboard deltas", "action audit rows"],
                success_metrics=["each button has backend command or explicit not-wired state"],
            ),
            WeatherAgentRole(
                team_id="reviewer_builder_team",
                role_id="release_gatekeeper",
                title="Release Gatekeeper",
                mandate="Keep live weather unreachable until release evidence, geoblock, secrets, and risk checks pass.",
                decision_rights=["deny release certificate", "expire stale evidence", "enforce non-negotiables"],
                required_inputs=["release certificate", "evidence report", "geoblock result", "risk state"],
                output_artifacts=["release verdict", "non-negotiable checklist"],
                success_metrics=["credentials alone never enable live trading"],
                veto_power=["release_certificate_missing", "geoblock_unknown", "allow_live_weather_trading_false"],
            ),
        ]

    @staticmethod
    def _strategy_output_contract() -> Dict[str, Any]:
        return {
            "schema_version": "weather_strategy_proposal_v1",
            "required_fields": [
                "lane",
                "hypothesis",
                "market_scope",
                "data_sources",
                "entry_logic",
                "exit_or_resolution_logic",
                "proof_evidence",
                "disproof_evidence",
                "required_artifacts",
                "promotion_gate",
                "kill_condition",
                "tests_required",
                "live_trading_impact",
            ],
            "hard_rules": [
                "No strategy proposal can request live enablement.",
                "Every proposal must define how it can be disproved.",
                "Every entry must reference executable bid/ask or fillability, not midpoint only.",
                "Every weather source must carry as-of timestamp and freshness policy.",
            ],
        }

    @staticmethod
    def _review_output_contract() -> Dict[str, Any]:
        return {
            "schema_version": "weather_system_review_v1",
            "required_fields": [
                "finding_id",
                "severity",
                "affected_modules",
                "evidence",
                "risk",
                "required_change",
                "tests_required",
                "owner_role",
                "live_gate_impact",
                "acceptance_criteria",
            ],
            "severity_scale": {
                "P0": "Possible live-safety, secret, geoblock, or irreversible-action issue.",
                "P1": "Can create false edge, unreplayable evidence, bad paper decisions, or weak gates.",
                "P2": "Quality, operator workflow, or reporting issue that slows the loop.",
            },
            "hard_rules": [
                "A review finding without a module/artifact target is not actionable.",
                "A builder patch without tests is incomplete unless it is docs-only.",
                "Reviewer notes can block or request work; they cannot mark evidence gates passed.",
            ],
        }

    @staticmethod
    def _pro_architecture_advice() -> Dict[str, Any]:
        return {
            "status": "incorporated",
            "summary": (
                "The system is pointed the right way, but the next work should harden the evidence spine "
                "before adding more model complexity or dashboard polish."
            ),
            "highest_value_sequence": [
                "canonical_weather_feature_packet",
                "typed_blocker_taxonomy",
                "known_outcome_probability_fix",
                "coverage_auditor",
                "fillability_subtype_report",
                "event_time_replay",
            ],
            "core_warning": (
                "The learned strategy team can propose hypotheses, but deterministic evidence gates must be "
                "the only path from proposal to paper or live eligibility."
            ),
        }

    @staticmethod
    def _promotion_chain() -> List[str]:
        return ["AlphaLaneProposal", "AlphaExperimentPlan", "WeatherFeaturePacket", "AlphaEvidenceReport",
                "ReviewerFinding", "SystemReviewReport", "PaperGateDecision", "LiveEligibilityReport"]

    @staticmethod
    def _pro_patch_sequence() -> List[Dict[str, Any]]:
        def patch(
            patch_id: str,
            priority: str,
            owner: str,
            goal: str,
            modules: List[str],
            tests: List[str],
            status: str = "pending",
        ) -> Dict[str, Any]:
            return {
                "id": patch_id,
                "priority": priority,
                "owner_role": owner,
                "status": status,
                "goal": goal,
                "module_targets": modules,
                "tests_required": tests,
            }

        return [
            patch(
                "canonical_weather_feature_packet",
                "P1",
                "evidence_lineage_reviewer",
                "Define one replayable feature packet with market spec, weather source, threshold state, book snapshot, features, and evidence refs.",
                ["weather_contracts.py", "weather_edge_features.py", "weather_evidence_store.py"],
                ["tests/test_polymarket_trader_weather_research_modules.py"],
                "implemented_initial",
            ),
            patch(
                "typed_blocker_taxonomy",
                "P1",
                "system_architecture_reviewer",
                "Replace loose blocker strings with typed categories that can drive review, dashboard filters, and next-build routing.",
                ["weather_gate.py", "weather_market_spec_compiler.py", "weather_threshold_state.py"],
                ["tests/test_polymarket_trader_weather_architecture.py"],
                "implemented",
            ),
            patch(
                "known_outcome_probability_fix",
                "P1",
                "calibration_scientist",
                "Separate known threshold facts from forecast probabilities so observation-lag candidates cannot look confident for the wrong reason.",
                ["weather_known_outcome_alpha.py", "weather_threshold_state.py", "weather_signals.py"],
                ["tests/test_polymarket_trader_weather_known_outcome_alpha.py"],
                "implemented",
            ),
            patch(
                "coverage_auditor",
                "P1",
                "test_safety_engineer",
                "Turn the weather funnel into a stage-by-stage audit from scanned markets to accepted candidates.",
                [
                    "weather_candidate_supply_report.py",
                    "weather_known_outcome_scan.py",
                    "src/dashboard/backend/polymarket_weather_store.py",
                ],
                ["tests/test_polymarket_trader_weather_candidate_supply.py"],
                "implemented",
            ),
            patch(
                "fillability_subtype_report",
                "P1",
                "microstructure_alpha_lead",
                "Break executable-price and no-depth failures into actionable causes with walked price, book age, book hash, capacity, and partial-fill policy.",
                ["weather_fillability_report.py", "weather_orderbook_simulator.py", "weather_known_outcome_scan.py"],
                ["tests/test_polymarket_trader_weather_fillability_report.py"],
                "implemented_initial",
            ),
            patch(
                "event_time_replay",
                "P1",
                "calibration_scientist",
                "Make replay event-time safe so feature timestamps, market prices, and outcomes cannot leak future data.",
                ["weather_replay.py", "weather_market_tape.py", "weather_evidence_store.py"],
                ["tests/test_polymarket_trader_weather_evidence.py"],
                "implemented_initial",
            ),
            patch(
                "alpha_lane_registry",
                "P2",
                "chief_weather_strategist",
                "Turn lane ideas into typed proposals and experiment reports instead of narrative-only research notes.",
                ["weather_alpha.py", "weather_edge_lab.py", "weather_research_team.py"],
                ["tests/test_polymarket_trader_weather_alpha.py"],
            ),
            patch(
                "dashboard_command_manifest_and_live_block",
                "P0",
                "release_gatekeeper",
                "Keep every dashboard action backend-enforced and keep live weather impossible by default, even when credentials exist.",
                ["polymarket_weather_actions.py", "polymarket_weather_store.py", "weather_live_eligibility.py"],
                ["tests/test_polymarket_weather_control_room_api.py", "tests/test_polymarket_trader_weather_live_eligibility.py"],
            ),
        ]

    def _alpha_lane_cards(self, reports: Dict[str, Dict[str, Any]]) -> List[WeatherAlphaLaneCard]:
        known = reports.get("known_outcome", {}) or {}
        ladder = reports.get("ladder", {}) or {}
        research = reports.get("research", {}) or {}
        blockers = known.get("blocker_counts", {}) or {}
        fill = known.get("orderbook_fill_coverage", {}) or {}
        run_lag = research.get("run_lag_evidence", {}) if isinstance(research, dict) else {}
        no_depth = _safe_int((fill.get("status_counts") or {}).get("no_depth"))
        candidate_count = _safe_int(known.get("candidate_count"))
        ladder_candidates = _safe_int(ladder.get("candidate_count"))
        run_lag_status = str(run_lag.get("status") or "missing")

        return [
            WeatherAlphaLaneCard(
                rank=1,
                lane="official_observation_latency",
                title="Official Observation Latency",
                owner_role="contract_resolution_counsel",
                status="paper_candidate" if candidate_count else "research",
                hypothesis="Official station observations can make thresholds near-known before the CLOB reprices.",
                implementation_targets=[
                    "weather_known_outcome_alpha.py",
                    "weather_known_outcome_scan.py",
                    "weather_threshold_state.py",
                    "weather_evidence_store.py",
                ],
                proof_evidence=[
                    "timestamped official observation",
                    "threshold state known or near-known",
                    "walked orderbook supports full paper size",
                    "proof and disproof lines stored per candidate",
                ],
                disproof_evidence=[
                    "threshold_not_known_from_observations",
                    "threshold_boundary_rounding_risk",
                    "executable_price_missing",
                    "executable_fill_below_minimum",
                ],
                promotion_gate=(
                    "Replay and paper results stay positive after depth, fees, slippage, and boundary guards; "
                    "accepted candidates span multiple stations and target dates."
                ),
                current_blockers=_top_blockers(blockers),
                next_build_action="Persist blocker-to-backlog rows and disproof examples for every rejected candidate.",
            ),
            WeatherAlphaLaneCard(
                rank=2,
                lane="orderbook_depth_capacity",
                title="Executable Depth and Capacity",
                owner_role="microstructure_alpha_lead",
                status="blocked_by_depth" if no_depth else "research",
                hypothesis="Most raw weather edge dies at the book; capacity is the alpha filter.",
                implementation_targets=[
                    "weather_orderbook_fetch_planner.py",
                    "weather_orderbook_simulator.py",
                    "weather_market_tape.py",
                    "weather_candidate_ranker.py",
                ],
                proof_evidence=[
                    "book hash and age",
                    "side-specific ask ladder",
                    "walked fill price by size",
                    "max positive-edge notional after costs",
                ],
                disproof_evidence=[
                    "no_depth",
                    "partial_fill_below_minimum",
                    "spread_erases_edge",
                    "book_stale_or_missing",
                ],
                promotion_gate="Paper fills must be less favorable than top-of-book and still positive after costs.",
                current_blockers=[f"no_depth={no_depth}"] if no_depth else [],
                next_build_action="Expose fillability report as a first-class lane artifact and dashboard panel.",
            ),
            WeatherAlphaLaneCard(
                rank=3,
                lane="model_update_lag",
                title="HRRR/NBM Model-Run Lag",
                owner_role="meteorological_alpha_lead",
                status=run_lag_status,
                hypothesis="Fresh HRRR/NBM changes can update fair value before thin weather books reprice.",
                implementation_targets=[
                    "weather_model_update_detector.py",
                    "weather_run_lag_ledger.py",
                    "weather_high_res_cycle.py",
                    "weather_edge_lab.py",
                ],
                proof_evidence=[
                    "new model run ID",
                    "forecast delta crosses threshold probability",
                    "market tape shows stale price after run arrival",
                    "post-run replay beats no-run baseline",
                ],
                disproof_evidence=[
                    "market reprices before executable fill",
                    "run-lag feature fails holdout",
                    "source outage or stale run",
                ],
                promotion_gate="At least 100 paper candidates or 75 holdout candidates, positive after-cost ROI, and no station/date concentration.",
                current_blockers=[] if run_lag_status == "ready" else [f"run_lag_evidence:{run_lag_status}"],
                next_build_action="Turn run-lag ledger into replay rows with market-price-before/after windows.",
            ),
            WeatherAlphaLaneCard(
                rank=4,
                lane="station_bias_calibration",
                title="Station Bias Calibration",
                owner_role="meteorological_alpha_lead",
                status="needs_resolved_dataset",
                hypothesis="Market makers may price city forecasts while resolution follows airport/station observations.",
                implementation_targets=[
                    "weather_station_bias_catalog.py",
                    "weather_edge_features.py",
                    "weather_alpha.py",
                    "weather_edge_lab.py",
                ],
                proof_evidence=[
                    "station-specific residuals",
                    "bias correction improves Brier/log-loss",
                    "candidate ROI survives by station and season",
                ],
                disproof_evidence=[
                    "bias does not improve holdout",
                    "single-station concentration",
                    "official station differs from assumed station",
                ],
                promotion_gate="At least 300 resolved records, 8 target dates, and 75 holdout candidates.",
                current_blockers=["resolved_station_dataset_needed"],
                next_build_action="Backfill resolved labels and station observations into the station-bias catalog.",
            ),
            WeatherAlphaLaneCard(
                rank=5,
                lane="ladder_consistency_baskets",
                title="Ladder and Bucket Consistency",
                owner_role="microstructure_alpha_lead",
                status="paper_candidate" if ladder_candidates else "research",
                hypothesis="Mutually exclusive range buckets can be mispriced, but only all-leg execution matters.",
                implementation_targets=[
                    "weather_ladder_consistency_alpha.py",
                    "weather_structural_arb.py",
                    "weather_orderbook_simulator.py",
                ],
                proof_evidence=[
                    "complete bucket group",
                    "all legs executable",
                    "net basket payoff positive after fees",
                    "partial-fill unwind rule defined",
                ],
                disproof_evidence=[
                    "incomplete group",
                    "overlapping ranges",
                    "one leg not fillable",
                    "partial-fill risk erases edge",
                ],
                promotion_gate="All legs are fill-or-kill simulated at positive net edge across repeated groups.",
                current_blockers=_top_blockers(ladder.get("blocker_counts", {}) or {}),
                next_build_action="Record rejected basket groups with the exact leg that killed execution.",
            ),
        ]

    def _review_findings(self, reports: Dict[str, Dict[str, Any]]) -> List[WeatherReviewFinding]:
        known = reports.get("known_outcome", {}) or {}
        evidence = reports.get("evidence", {}) or {}
        blockers = known.get("blocker_counts", {}) or {}
        fill = known.get("orderbook_fill_coverage", {}) or {}
        status_counts = fill.get("status_counts", {}) if isinstance(fill, dict) else {}
        findings = [
            WeatherReviewFinding(
                finding_id="live_weather_still_hard_blocked",
                severity="P0",
                status="pass",
                title="Live weather remains hard-blocked by configuration and release evidence.",
                evidence=[
                    "allow_live_weather_trading defaults false",
                    "release certificate required",
                    "live eligibility gate reports blockers unless all non-negotiables pass",
                ],
                required_change="Keep this invariant while adding strategy/review automation.",
                owner_role="release_gatekeeper",
                tests_required=["tests/test_polymarket_trader_weather_live_eligibility.py"],
                live_gate_impact="protects_live_gate",
            )
        ]
        candidate_count = _safe_int(known.get("candidate_count"))
        evaluated = _safe_int(known.get("evaluated_candidates"))
        if evaluated and candidate_count < max(3, int(evaluated * 0.05)):
            findings.append(
                WeatherReviewFinding(
                    finding_id="known_outcome_candidate_sample_not_promotable",
                    severity="P1",
                    status="blocked",
                    title="Known-outcome lane has paper evidence, but the sample is not promotable.",
                    evidence=[
                        f"evaluated_candidates={evaluated}",
                        f"accepted_paper_candidates={candidate_count}",
                    ],
                    required_change=(
                        "Keep the lane research-only and store rejected candidates as disproof/backlog rows "
                        "instead of loosening gates."
                    ),
                    owner_role="calibration_scientist",
                    tests_required=["tests/test_polymarket_trader_weather_known_outcome_alpha.py"],
                    live_gate_impact="blocks_promotion",
                )
            )
        no_depth = _safe_int(status_counts.get("no_depth"))
        simulated_count = _safe_int(fill.get("simulated_count"))
        if no_depth or _safe_float(fill.get("coverage_ratio")) < 0.75:
            findings.append(
                WeatherReviewFinding(
                    finding_id="orderbook_depth_coverage_incomplete",
                    severity="P1",
                    status="needs_build",
                    title="Orderbook depth coverage is still the main execution bottleneck.",
                    evidence=[
                        f"simulated_count={simulated_count}",
                        f"no_depth={no_depth}",
                        f"coverage_ratio={fill.get('coverage_ratio', 0)}",
                    ],
                    required_change=(
                        "Promote FillabilityReport as a first-class artifact with book hash, age, "
                        "walked price, and max positive-edge notional."
                    ),
                    owner_role="microstructure_alpha_lead",
                    tests_required=["tests/test_polymarket_trader_weather_orderbook_fetch_planner.py"],
                    live_gate_impact="blocks_promotion",
                )
            )
        threshold_unknown = _safe_int(blockers.get("threshold_not_known_from_observations"))
        if threshold_unknown:
            findings.append(
                WeatherReviewFinding(
                    finding_id="threshold_unknowns_need_disproof_dataset",
                    severity="P2",
                    status="needs_build",
                    title="Unknown threshold states should become explicit disproof examples.",
                    evidence=[f"threshold_not_known_from_observations={threshold_unknown}"],
                    required_change=(
                        "Write lane-level disproof rows that preserve station, target date, threshold, "
                        "observed value, and missing proof reason."
                    ),
                    owner_role="contract_resolution_counsel",
                    tests_required=["tests/test_polymarket_trader_weather_known_outcome_alpha.py"],
                    live_gate_impact="improves_replay_gate",
                )
            )
        deployment = evidence.get("deployment_verdict", {}) if isinstance(evidence, dict) else {}
        if deployment and deployment.get("accepted_for_live_weather_trading") is not True:
            findings.append(
                WeatherReviewFinding(
                    finding_id="replay_not_live_accepted",
                    severity="P0",
                    status="blocked",
                    title="Replay evidence does not accept live weather trading.",
                    evidence=["accepted_for_live_weather_trading=false"],
                    required_change="No live release certificate can be issued from the current evidence state.",
                    owner_role="release_gatekeeper",
                    tests_required=["tests/test_polymarket_trader_weather_live_eligibility.py"],
                    live_gate_impact="blocks_live",
                )
            )
        return findings

    @staticmethod
    def _architecture_verdict(known: Dict[str, Any], findings: List[WeatherReviewFinding]) -> Dict[str, Any]:
        p0_blocks = [finding.finding_id for finding in findings if finding.severity == "P0" and finding.status != "pass"]
        p1_blocks = [finding.finding_id for finding in findings if finding.severity == "P1" and finding.status != "pass"]
        return {
            "direction": "right",
            "current_stage": "research_to_replay_hardening",
            "not_live_ready": True,
            "primary_bottleneck": "orderbook_depth_and_disproof_backlog"
            if known
            else "artifact_refresh_needed",
            "p0_blocks": p0_blocks,
            "p1_blocks": p1_blocks,
            "summary": (
                "The architecture is pointed the right way because it separates market-spec truth, source-stamped "
                "weather evidence, threshold state, fillability, paper decisions, and live eligibility. The weak "
                "spot is turning rejects into reusable disproof/backlog artifacts and making fillability visible "
                "as a first-class output."
            ),
        }

    @staticmethod
    def _source_reports_considered(reports: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        return {
            key: {
                "present": bool(payload),
                "generated_at": payload.get("generated_at") or payload.get("updated_at") if isinstance(payload, dict) else "",
                "schema_version": payload.get("schema_version") or payload.get("feature_schema_version")
                if isinstance(payload, dict)
                else "",
            }
            for key, payload in sorted((reports or {}).items())
        }

    @staticmethod
    def _build_queue(
        lane_cards: List[WeatherAlphaLaneCard],
        findings: List[WeatherReviewFinding],
        pro_patch_sequence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        queue = []
        for patch in pro_patch_sequence:
            if str(patch.get("status") or "").startswith("implemented"):
                continue
            queue.append(
                {
                    "priority": patch.get("priority", "P2"),
                    "work_item": patch.get("id", ""),
                    "owner_role": patch.get("owner_role", ""),
                    "required_change": patch.get("goal", ""),
                    "module_targets": list(patch.get("module_targets", [])),
                    "tests_required": list(patch.get("tests_required", [])),
                }
            )
        for finding in findings:
            if finding.status == "pass":
                continue
            queue.append(
                {
                    "priority": finding.severity,
                    "work_item": finding.finding_id,
                    "owner_role": finding.owner_role,
                    "required_change": finding.required_change,
                    "module_targets": [],
                    "tests_required": list(finding.tests_required),
                }
            )
        for card in lane_cards[:3]:
            queue.append(
                {
                    "priority": "P2",
                    "work_item": f"advance_lane:{card.lane}",
                    "owner_role": card.owner_role,
                    "required_change": card.next_build_action,
                    "module_targets": list(card.implementation_targets),
                    "tests_required": ["focused lane test plus report-shape regression"],
                }
            )
        return queue[:12]

    @staticmethod
    def _release_non_negotiables() -> List[str]:
        return [
            "market_spec_gate_passes",
            "weather_source_freshness_gate_passes",
            "fillability_gate_passes",
            "alpha_replay_gate_passes",
            "risk_gate_passes",
            "geoblock_check_passes",
            "secrets_gate_passes",
            "live_block_tests_pass_for_git_sha",
            "dashboard_backend_enforces_actions",
            "operator_explicitly_arms_live_mode",
        ]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _top_blockers(blockers: Dict[str, Any], limit: int = 6) -> List[str]:
    if not isinstance(blockers, dict):
        return []
    rows = sorted(blockers.items(), key=lambda item: _safe_int(item[1]), reverse=True)
    return [f"{key}:{_safe_int(value)}" for key, value in rows[:limit]]
