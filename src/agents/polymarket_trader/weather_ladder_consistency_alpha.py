"""Ladder and threshold consistency alpha for weather markets.

This module emits research candidates only. It looks for executable CLOB
mispricings implied by threshold relationships, then records the proof or the
reason the apparent edge failed.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .market_scanner import CLIMarketScanner
from .models import CLIMarket
from .weather_market_tape import WeatherMarketTapeCollector, WeatherMarketTapeSnapshot
from .weather_market_type_classifier import LANE_LADDER_CONSISTENCY, WeatherMarketTypeClassifier
from .weather_orderbook_simulator import WeatherOrderbookFillSimulator


LADDER_ALPHA_SCHEMA_VERSION = "weather_ladder_consistency_alpha_v1"


@dataclass(frozen=True)
class WeatherLadderLeg:
    market_id: str
    side: str
    threshold: Optional[float]
    upper_threshold: Optional[float]
    price: Optional[float]
    token_id: str
    role: str
    fill: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherLadderConsistencyCandidate:
    candidate_id: str
    status: str
    alpha_type: str
    group_key: str
    edge_after_cost: Optional[float]
    worst_case_payout: float
    total_cost: Optional[float]
    leg_count: int
    max_atomic_qty: float = 0.0
    max_atomic_notional_usd: float = 0.0
    limiting_leg: str = ""
    schema_version: str = LADDER_ALPHA_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    proof: List[str] = field(default_factory=list)
    disproof: List[str] = field(default_factory=list)
    legs: List[WeatherLadderLeg] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    @property
    def accepted_for_research(self) -> bool:
        return self.status == "candidate"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["accepted_for_research"] = self.accepted_for_research
        payload["legs"] = [leg.to_dict() for leg in self.legs]
        return payload


class WeatherLadderConsistencyAlpha:
    def __init__(
        self,
        *,
        classifier: Optional[WeatherMarketTypeClassifier] = None,
        fee_rate: float = 0.01,
        min_edge_after_cost: float = 0.0,
        target_fill_usd: float = 5.0,
        min_atomic_notional_usd: float = 1.0,
        fill_simulator: Optional[WeatherOrderbookFillSimulator] = None,
    ):
        self.classifier = classifier or WeatherMarketTypeClassifier()
        self.fee_rate = float(fee_rate)
        self.min_edge_after_cost = float(min_edge_after_cost)
        self.target_fill_usd = float(target_fill_usd)
        self.min_atomic_notional_usd = float(min_atomic_notional_usd)
        self.fill_simulator = fill_simulator or WeatherOrderbookFillSimulator(
            default_request_size_usd=max(0.01, self.target_fill_usd),
            allow_best_ask_without_depth=False,
        )

    def evaluate(
        self,
        markets: Iterable[CLIMarket],
        *,
        tape_by_market: Optional[Dict[str, WeatherMarketTapeSnapshot | Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> List[WeatherLadderConsistencyCandidate]:
        rows = []
        tape_by_market = tape_by_market or {}
        for market in markets:
            classification = self.classifier.classify(market, now=now)
            if LANE_LADDER_CONSISTENCY not in set(classification.alpha_lanes):
                continue
            rows.append(
                {
                    "market": market,
                    "classification": classification.to_dict(),
                    "tape": tape_by_market.get(str(getattr(market, "condition_id", "") or ""), {}),
                }
            )

        candidates: List[WeatherLadderConsistencyCandidate] = []
        for group_key, group_rows in self._groups(rows).items():
            candidates.extend(self._directional_candidates(group_key, group_rows, "above"))
            candidates.extend(self._directional_candidates(group_key, group_rows, "below"))
            range_candidate = self._range_no_basket_candidate(group_key, group_rows)
            if range_candidate is not None:
                candidates.append(range_candidate)
        candidates.sort(
            key=lambda item: (
                item.status == "candidate",
                float(item.edge_after_cost or -999.0),
                -len(item.blockers),
            ),
            reverse=True,
        )
        return candidates

    def _directional_candidates(
        self,
        group_key: str,
        rows: List[Dict[str, Any]],
        operator: str,
    ) -> List[WeatherLadderConsistencyCandidate]:
        clean = [
            row
            for row in rows
            if row["classification"].get("operator") == operator
            and _finite(row["classification"].get("threshold"))
        ]
        if len(clean) < 2:
            return []
        clean.sort(key=lambda row: float(row["classification"]["threshold"]))
        candidates: List[WeatherLadderConsistencyCandidate] = []
        for lower, higher in zip(clean, clean[1:]):
            if operator == "above":
                legs = [
                    self._leg(lower, "YES", "lower_threshold_yes"),
                    self._leg(higher, "NO", "higher_threshold_no"),
                ]
                proof = [
                    "If the higher threshold resolves YES, the lower threshold must also resolve YES.",
                    "Buying lower-threshold YES plus higher-threshold NO pays at least 1 share in every outcome.",
                ]
                alpha_type = "above_threshold_pair"
            else:
                legs = [
                    self._leg(lower, "NO", "lower_threshold_no"),
                    self._leg(higher, "YES", "higher_threshold_yes"),
                ]
                proof = [
                    "If the lower threshold resolves YES, the higher threshold must also resolve YES.",
                    "Buying lower-threshold NO plus higher-threshold YES pays at least 1 share in every outcome.",
                ]
                alpha_type = "below_threshold_pair"
            candidates.append(self._candidate_from_legs(group_key, alpha_type, 1.0, legs, proof))
        return candidates

    def _range_no_basket_candidate(
        self,
        group_key: str,
        rows: List[Dict[str, Any]],
    ) -> Optional[WeatherLadderConsistencyCandidate]:
        ranges = [
            row
            for row in rows
            if row["classification"].get("operator") == "between"
            and _finite(row["classification"].get("threshold"))
            and _finite(row["classification"].get("upper_threshold"))
        ]
        if len(ranges) < 2:
            return None
        ranges.sort(key=lambda row: (float(row["classification"]["threshold"]), float(row["classification"]["upper_threshold"])))
        proof = [
            "Non-overlapping temperature buckets are mutually exclusive.",
            "Buying NO on every bucket pays at least N-1 shares if at most one bucket resolves YES.",
        ]
        legs = [self._leg(row, "NO", "range_bucket_no") for row in ranges]
        candidate = self._candidate_from_legs(
            group_key,
            "mutually_exclusive_range_no_basket",
            float(len(ranges) - 1),
            legs,
            proof,
        )
        overlap_blocker = "ladder_bucket_ranges_overlap"
        if self._ranges_overlap(ranges) and overlap_blocker not in candidate.blockers:
            blockers = sorted(set(candidate.blockers + [overlap_blocker]))
            disproof = list(candidate.disproof) + ["At least two included bucket ranges overlap, so the NO basket proof is invalid."]
            return WeatherLadderConsistencyCandidate(
                candidate_id=candidate.candidate_id,
                status="blocked",
                alpha_type=candidate.alpha_type,
                group_key=candidate.group_key,
                edge_after_cost=candidate.edge_after_cost,
                worst_case_payout=candidate.worst_case_payout,
                total_cost=candidate.total_cost,
                leg_count=candidate.leg_count,
                max_atomic_qty=candidate.max_atomic_qty,
                max_atomic_notional_usd=candidate.max_atomic_notional_usd,
                limiting_leg=candidate.limiting_leg,
                proof=candidate.proof,
                disproof=disproof,
                legs=candidate.legs,
                blockers=blockers,
                quality_flags=candidate.quality_flags,
            )
        return candidate

    def _candidate_from_legs(
        self,
        group_key: str,
        alpha_type: str,
        worst_case_payout: float,
        legs: List[WeatherLadderLeg],
        proof: List[str],
    ) -> WeatherLadderConsistencyCandidate:
        blockers: List[str] = []
        disproof: List[str] = []
        prices = []
        for leg in legs:
            if leg.price is None or leg.price <= 0:
                blockers.append("ladder_leg_executable_price_missing")
            else:
                prices.append(float(leg.price))
            fill_status = str((leg.fill or {}).get("status") or "")
            filled_shares = _optional_float((leg.fill or {}).get("filled_shares")) or 0.0
            if fill_status != "full" and filled_shares <= 0:
                blockers.extend(str(item) for item in (leg.fill or {}).get("blockers", []) or [])
                blockers.append(f"ladder_leg_fill_not_atomic:{fill_status or 'missing'}")

        total_cost = None
        edge = None
        capacity = self._atomic_capacity(legs)
        if capacity["max_atomic_qty"] <= 0:
            blockers.append("ladder_atomic_capacity_missing")
            disproof.append("At least one leg had no executable shares, so no atomic basket can be formed.")
        if len(prices) == len(legs):
            gross_cost = sum(prices)
            fee_buffer = gross_cost * self.fee_rate
            total_cost = gross_cost + fee_buffer
            edge = worst_case_payout - total_cost
            if edge < self.min_edge_after_cost:
                blockers.append("ladder_edge_below_cost_buffer")
                disproof.append(
                    f"Worst-case payout {worst_case_payout:.4f} is not above cost plus fee buffer {total_cost:.4f}."
                )
            if capacity["max_atomic_notional_usd"] < self.min_atomic_notional_usd:
                blockers.append("ladder_atomic_capacity_below_minimum")
                disproof.append(
                    f"Atomic basket capacity {capacity['max_atomic_notional_usd']:.4f} USD is below the research minimum."
                )
        else:
            disproof.append("At least one leg did not have an executable orderbook ask.")

        status = "candidate" if not blockers else "rejected" if edge is not None else "blocked"
        candidate_id = f"{alpha_type}:{group_key}:{'|'.join(leg.market_id + ':' + leg.side for leg in legs)}"
        flags = ["ladder_consistency_research_only", "requires_all_leg_execution"]
        if status == "candidate":
            flags.append("threshold_ladder_executable_edge")
        return WeatherLadderConsistencyCandidate(
            candidate_id=candidate_id,
            status=status,
            alpha_type=alpha_type,
            group_key=group_key,
            edge_after_cost=round(edge, 6) if edge is not None else None,
            worst_case_payout=round(worst_case_payout, 6),
            total_cost=round(total_cost, 6) if total_cost is not None else None,
            leg_count=len(legs),
            max_atomic_qty=round(capacity["max_atomic_qty"], 6),
            max_atomic_notional_usd=round(capacity["max_atomic_notional_usd"], 6),
            limiting_leg=capacity["limiting_leg"],
            proof=proof,
            disproof=disproof,
            legs=legs,
            blockers=sorted(set(blockers)),
            quality_flags=sorted(set(flags + capacity["quality_flags"])),
        )

    @staticmethod
    def _atomic_capacity(legs: List[WeatherLadderLeg]) -> Dict[str, Any]:
        shares_by_leg = []
        for leg in legs:
            filled_shares = _optional_float((leg.fill or {}).get("filled_shares")) or 0.0
            shares_by_leg.append((leg, max(0.0, filled_shares)))
        if not shares_by_leg:
            return {"max_atomic_qty": 0.0, "max_atomic_notional_usd": 0.0, "limiting_leg": "", "quality_flags": []}
        limiting_leg, max_qty = min(shares_by_leg, key=lambda item: item[1])
        gross_price = sum(float(leg.price or 0.0) for leg in legs)
        flags = ["atomic_basket_capacity_simulated"]
        if any(str((leg.fill or {}).get("status") or "") == "partial" for leg in legs):
            flags.append("atomic_basket_scaled_to_partial_fill")
        return {
            "max_atomic_qty": max_qty,
            "max_atomic_notional_usd": max_qty * gross_price,
            "limiting_leg": f"{limiting_leg.market_id}:{limiting_leg.side}:{limiting_leg.role}",
            "quality_flags": flags,
        }

    def _leg(self, row: Dict[str, Any], side: str, role: str) -> WeatherLadderLeg:
        market = row["market"]
        classification = row["classification"]
        tape = row.get("tape", {})
        tape_dict = tape.to_dict() if hasattr(tape, "to_dict") else dict(tape or {})
        price = self._side_ask(tape_dict, side)
        fill = self.fill_simulator.simulate(
            tape_dict,
            side,
            requested_size_usd=self.target_fill_usd,
            limit_price=price,
        ).to_dict()
        return WeatherLadderLeg(
            market_id=str(getattr(market, "condition_id", "") or ""),
            side=side,
            threshold=_optional_float(classification.get("threshold")),
            upper_threshold=_optional_float(classification.get("upper_threshold")),
            price=round(price, 6) if price is not None else None,
            token_id=str(
                getattr(market, "yes_token_id" if side == "YES" else "no_token_id", "")
                or ""
            ),
            role=role,
            fill=fill,
        )

    @staticmethod
    def _groups(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            classification = row["classification"]
            station = str(classification.get("station_id") or "").strip().upper()
            location = str(classification.get("location_name") or "").strip().lower()
            metric = str(classification.get("metric") or "").strip()
            target_date = str(classification.get("target_date") or "").strip()
            if station or location:
                group_key = "|".join([station, location, metric, target_date])
            else:
                group_key = (
                    str(classification.get("event_slug") or "").strip()
                    or str(classification.get("slug") or "").strip()
                    or str(classification.get("market_id") or "").strip()
                )
            groups[group_key].append(row)
        return groups

    @staticmethod
    def _side_ask(tape: Dict[str, Any], side: str) -> Optional[float]:
        key = "executable_yes_price" if side == "YES" else "executable_no_price"
        source_key = "executable_yes_price_source" if side == "YES" else "executable_no_price_source"
        source = str(tape.get(source_key) or tape.get("executable_price_source") or "")
        if source != "orderbook_best_ask":
            return None
        return _optional_float(tape.get(key))

    @staticmethod
    def _ranges_overlap(rows: List[Dict[str, Any]]) -> bool:
        ordered = sorted(
            rows,
            key=lambda row: (float(row["classification"]["threshold"]), float(row["classification"]["upper_threshold"])),
        )
        for left, right in zip(ordered, ordered[1:]):
            if float(left["classification"]["upper_threshold"]) > float(right["classification"]["threshold"]):
                return True
        return False


class WeatherLadderConsistencyAlphaScanner:
    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        scanner: Optional[CLIMarketScanner] = None,
        tape_collector: Optional[WeatherMarketTapeCollector] = None,
        alpha: Optional[WeatherLadderConsistencyAlpha] = None,
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
        )
        self.scanner = scanner or CLIMarketScanner(self.config)
        self.tape_collector = tape_collector or WeatherMarketTapeCollector(self.config, getattr(self.scanner, "cli", None))
        self.alpha = alpha or WeatherLadderConsistencyAlpha(
            fee_rate=float(getattr(self.config, "arb_fee_estimate_percent", 1.0) or 1.0) / 100.0,
            target_fill_usd=float(getattr(self.config, "min_position_usd", 5.0) or 5.0),
        )
        self.output_dir = output_dir or (self.config.data_dir / "weather_ladder_consistency_alpha")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def latest_report_path(self) -> Path:
        return self.output_dir / "latest_weather_ladder_consistency_report.json"

    @property
    def latest_report_markdown_path(self) -> Path:
        return self.output_dir / "latest_weather_ladder_consistency_report.md"

    def build_report(
        self,
        *,
        force_refresh: bool = True,
        orderbook_limit: int = 250,
        write: bool = True,
    ) -> Dict[str, Any]:
        markets = self.scanner.scan_markets(force_refresh=force_refresh)
        ladder_rows = self._ladder_rows(markets)
        ladder_markets = [row["market"] for row in ladder_rows]
        selected_groups = self._select_orderbook_groups(ladder_rows, orderbook_limit=max(1, int(orderbook_limit)))
        targets = self._unique_markets(row for group in selected_groups for row in group["rows"])
        tape_rows = self.tape_collector.snapshot_markets(targets, fetch_orderbook=True)
        tape_by_market = {row.market_id: row for row in tape_rows}
        candidates = self.alpha.evaluate(targets, tape_by_market=tape_by_market)
        rows = [candidate.to_dict() for candidate in candidates]
        status_counts = Counter(row.get("status", "missing") for row in rows)
        blocker_counts = Counter(blocker for row in rows for blocker in row.get("blockers", []))
        group_selection = self._group_selection_summary(
            ladder_rows=ladder_rows,
            selected_groups=selected_groups,
            tape_by_market=tape_by_market,
            orderbook_limit=orderbook_limit,
        )
        report = {
            "schema_version": LADDER_ALPHA_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "market_vertical": "weather",
            "markets_scanned": len(markets),
            "ladder_markets": len(ladder_markets),
            "selected_ladder_groups": len(selected_groups),
            "selected_ladder_markets": len(targets),
            "orderbook_snapshots": len(tape_rows),
            "group_selection": group_selection,
            "candidate_count": int(status_counts.get("candidate", 0)),
            "rejected_count": int(status_counts.get("rejected", 0)),
            "blocked_count": int(status_counts.get("blocked", 0)),
            "status_counts": dict(sorted(status_counts.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "candidates": rows,
            "top_candidates": rows[:50],
            "artifacts": {
                "json": str(self.latest_report_path),
                "markdown": str(self.latest_report_markdown_path),
            },
        }
        if write:
            self.latest_report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            self.latest_report_markdown_path.write_text(self._format_markdown(report), encoding="utf-8")
        return report

    def _ladder_rows(self, markets: Iterable[CLIMarket]) -> List[Dict[str, Any]]:
        selected = []
        for market in markets:
            classification = self.alpha.classifier.classify(market)
            if LANE_LADDER_CONSISTENCY in set(classification.alpha_lanes):
                selected.append({"market": market, "classification": classification.to_dict()})
        return selected

    def _select_orderbook_groups(
        self,
        ladder_rows: List[Dict[str, Any]],
        *,
        orderbook_limit: int,
    ) -> List[Dict[str, Any]]:
        groups = self.alpha._groups(ladder_rows)
        scored = []
        for group_key, rows in groups.items():
            opportunity_count = self._opportunity_count(rows)
            if opportunity_count <= 0:
                continue
            group_size = len(rows)
            if group_size > orderbook_limit:
                continue
            liquidity = sum(float(getattr(row["market"], "liquidity", 0.0) or 0.0) for row in rows)
            avg_liquidity = liquidity / max(1, group_size)
            score = (opportunity_count * 1000.0) + min(100.0, math.log10(max(10.0, liquidity)) * 20.0) - group_size
            scored.append(
                {
                    "group_key": group_key,
                    "rows": rows,
                    "group_size": group_size,
                    "opportunity_count": opportunity_count,
                    "liquidity": liquidity,
                    "avg_liquidity": avg_liquidity,
                    "score": score,
                }
            )
        scored.sort(
            key=lambda group: (
                group["score"],
                group["opportunity_count"],
                group["avg_liquidity"],
                -group["group_size"],
            ),
            reverse=True,
        )

        selected: List[Dict[str, Any]] = []
        used_market_ids: set[str] = set()
        used_slots = 0
        for group in scored:
            market_ids = [str(getattr(row["market"], "condition_id", "") or "") for row in group["rows"]]
            new_ids = [market_id for market_id in market_ids if market_id not in used_market_ids]
            if not new_ids:
                continue
            if used_slots + len(new_ids) > orderbook_limit:
                continue
            selected.append(group)
            used_market_ids.update(new_ids)
            used_slots += len(new_ids)
            if used_slots >= orderbook_limit:
                break
        return selected

    @staticmethod
    def _opportunity_count(rows: List[Dict[str, Any]]) -> int:
        operators = Counter(str(row["classification"].get("operator") or "") for row in rows)
        range_count = sum(
            1
            for row in rows
            if row["classification"].get("operator") == "between"
            and _finite(row["classification"].get("threshold"))
            and _finite(row["classification"].get("upper_threshold"))
        )
        return (
            max(0, int(operators.get("above", 0)) - 1)
            + max(0, int(operators.get("below", 0)) - 1)
            + (1 if range_count >= 2 else 0)
        )

    @staticmethod
    def _unique_markets(rows: Iterable[Dict[str, Any]]) -> List[CLIMarket]:
        markets: List[CLIMarket] = []
        seen: set[str] = set()
        for row in rows:
            market = row["market"]
            market_id = str(getattr(market, "condition_id", "") or "")
            if not market_id or market_id in seen:
                continue
            seen.add(market_id)
            markets.append(market)
        return markets

    def _group_selection_summary(
        self,
        *,
        ladder_rows: List[Dict[str, Any]],
        selected_groups: List[Dict[str, Any]],
        tape_by_market: Dict[str, WeatherMarketTapeSnapshot],
        orderbook_limit: int,
    ) -> Dict[str, Any]:
        all_groups = self.alpha._groups(ladder_rows)
        eligible = [
            {"group_key": key, "rows": rows, "opportunity_count": self._opportunity_count(rows)}
            for key, rows in all_groups.items()
            if self._opportunity_count(rows) > 0
        ]
        selected_market_ids = {
            str(getattr(row["market"], "condition_id", "") or "")
            for group in selected_groups
            for row in group["rows"]
        }
        groups_with_complete_tape = 0
        for group in selected_groups:
            group_ids = [str(getattr(row["market"], "condition_id", "") or "") for row in group["rows"]]
            if group_ids and all(market_id in tape_by_market for market_id in group_ids):
                groups_with_complete_tape += 1
        too_large = sum(1 for item in eligible if len(item["rows"]) > max(1, int(orderbook_limit)))
        return {
            "orderbook_limit": int(orderbook_limit),
            "total_groups": len(all_groups),
            "eligible_groups": len(eligible),
            "selected_groups": len(selected_groups),
            "selected_market_count": len(selected_market_ids),
            "groups_with_complete_tape": groups_with_complete_tape,
            "too_large_groups_skipped": too_large,
            "unselected_eligible_groups": max(0, len(eligible) - len(selected_groups) - too_large),
            "top_selected_groups": [
                {
                    "group_key": group["group_key"],
                    "group_size": group["group_size"],
                    "opportunity_count": group["opportunity_count"],
                    "liquidity": round(float(group["liquidity"]), 4),
                    "score": round(float(group["score"]), 4),
                }
                for group in selected_groups[:10]
            ],
        }

    @staticmethod
    def _format_markdown(report: Dict[str, Any]) -> str:
        lines = [
            "# Polymarket Weather Ladder Consistency Alpha",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Markets scanned: `{report.get('markets_scanned')}`",
            f"- Ladder markets: `{report.get('ladder_markets')}`",
            f"- Selected ladder groups: `{report.get('selected_ladder_groups')}`",
            f"- Selected ladder markets: `{report.get('selected_ladder_markets')}`",
            f"- Orderbook snapshots: `{report.get('orderbook_snapshots')}`",
            f"- Candidate count: `{report.get('candidate_count')}`",
            f"- Rejected count: `{report.get('rejected_count')}`",
            f"- Blocked count: `{report.get('blocked_count')}`",
            "",
            "## Group Selection",
            f"- `{report.get('group_selection', {})}`",
            "",
            "## Blockers",
        ]
        for blocker, count in report.get("blocker_counts", {}).items():
            lines.append(f"- `{blocker}`: `{count}`")
        lines.extend(["", "## Top Proof Records"])
        for row in report.get("top_candidates", [])[:20]:
            proof = " ".join(row.get("proof", [])[:2])
            disproof = " ".join(row.get("disproof", [])[:1])
            lines.append(
                f"- `{row.get('status')}` `{row.get('alpha_type')}` edge `{row.get('edge_after_cost')}` "
                f"capacity `${row.get('max_atomic_notional_usd')}` legs `{row.get('leg_count')}` "
                f"blockers `{row.get('blockers')}` | {proof or disproof}"
            )
        lines.append("")
        return "\n".join(lines)


def _optional_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _finite(value: Any) -> bool:
    return _optional_float(value) is not None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan weather ladder consistency alpha")
    parser.add_argument("--orderbook-limit", type=int, default=250)
    parser.add_argument("--min-liquidity", type=float, default=500.0)
    parser.add_argument("--min-volume", type=float, default=0.0)
    parser.add_argument("--max-expiry-hours", type=float, default=16 * 24)
    parser.add_argument("--max-search-queries", type=int, default=12)
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
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
        max_weather_search_queries=args.max_search_queries,
        weather_market_tape_fetch_orderbook=True,
    )
    if args.data_dir:
        config._data_dir_override = Path(args.data_dir)
    scanner = WeatherLadderConsistencyAlphaScanner(
        config=config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    report = scanner.build_report(orderbook_limit=args.orderbook_limit)
    cprint("Weather ladder consistency report written", "green")
    cprint(f"  Ladder markets: {report.get('ladder_markets')}", "white")
    cprint(f"  Candidates: {report.get('candidate_count')}", "white")
    cprint(f"  Output: {scanner.output_dir}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
