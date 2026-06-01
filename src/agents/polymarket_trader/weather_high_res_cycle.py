"""
Market-cycle orchestration for NOAA high-resolution weather ingestion.

The point ingestor handles one HRRR/NBM manifest at a time. This module turns a
set of active Polymarket weather markets into auditable ingest work: parse the
resolution rule, map the station, build HRRR/NBM manifests, optionally ingest
them into the point cache, and write a cycle ledger.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import PolymarketCLIConfig, get_polymarket_cli_config
from .models import CLIMarket
from .weather_contracts import WeatherResolutionTarget, utc_now_iso
from .weather_edge_features import WeatherHighResolutionSourceBuilder
from .weather_high_res_ingestor import (
    WeatherHighResolutionArtifactIngestor,
    WeatherHighResolutionIngestResult,
)
from .weather_run_lag_ledger import WeatherRunLagLedger
from .weather_signals import WeatherDataSignals


@dataclass(frozen=True)
class WeatherHighResolutionCycleItem:
    market_id: str
    question: str
    source_id: str
    status: str
    run_id: str = ""
    location: str = ""
    metric: str = ""
    target_date: str = ""
    manifest_status: str = ""
    request_url: str = ""
    point_artifact_path: str = ""
    latest_artifact_path: str = ""
    forecast_metrics: Dict[str, Any] = field(default_factory=dict)
    run_lag_event: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherHighResolutionCycleReport:
    status: str
    generated_at: str
    cache_dir: str
    total_markets: int
    total_items: int
    planned_count: int
    ingested_count: int
    cache_hit_count: int
    skipped_count: int
    blocked_count: int
    dry_run: bool
    run_lag_event_count: int = 0
    new_run_arrival_count: int = 0
    actionable_run_lag_count: int = 0
    ledger_path: str = ""
    report_path: str = ""
    items: List[WeatherHighResolutionCycleItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload

    def summary(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "cache_dir": self.cache_dir,
            "total_markets": self.total_markets,
            "total_items": self.total_items,
            "planned_count": self.planned_count,
            "ingested_count": self.ingested_count,
            "cache_hit_count": self.cache_hit_count,
            "skipped_count": self.skipped_count,
            "blocked_count": self.blocked_count,
            "run_lag_event_count": self.run_lag_event_count,
            "new_run_arrival_count": self.new_run_arrival_count,
            "actionable_run_lag_count": self.actionable_run_lag_count,
            "dry_run": self.dry_run,
            "ledger_path": self.ledger_path,
            "report_path": self.report_path,
        }


class WeatherHighResolutionIngestCycleRunner:
    """Build and run high-resolution weather ingest work for active markets."""

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        *,
        signals: Optional[WeatherDataSignals] = None,
        ingestor: Optional[WeatherHighResolutionArtifactIngestor] = None,
        source_builder: Optional[WeatherHighResolutionSourceBuilder] = None,
        run_lag_ledger: Optional[WeatherRunLagLedger] = None,
        cache_dir: str | Path | None = None,
    ):
        self.config = config or get_polymarket_cli_config(market_vertical="weather")
        self.cache_dir = _resolve_cache_dir(self.config, cache_dir)
        self.config.weather_high_resolution_cache_dir = str(self.cache_dir)
        self.signals = signals or WeatherDataSignals(self.config)
        self.source_builder = source_builder or WeatherHighResolutionSourceBuilder(cache_dir=self.cache_dir)
        self.ingestor = ingestor or WeatherHighResolutionArtifactIngestor(
            self.cache_dir,
            min_request_interval_seconds=float(
                getattr(self.config, "weather_high_resolution_min_request_interval_seconds", 10.0) or 10.0
            ),
            timeout_seconds=int(getattr(self.config, "weather_high_resolution_timeout_seconds", 60) or 60),
        )
        self.run_lag_ledger = run_lag_ledger or WeatherRunLagLedger(
            self.config.data_dir / "weather_run_lag"
        )

    def run(
        self,
        markets: Iterable[CLIMarket],
        *,
        dry_run: bool = False,
        force: bool = False,
        source_ids: Optional[Iterable[str]] = None,
        limit: Optional[int] = None,
        write_report: bool = True,
    ) -> WeatherHighResolutionCycleReport:
        selected_markets = list(markets)
        if limit is not None:
            selected_markets = selected_markets[: max(0, int(limit))]

        items: List[WeatherHighResolutionCycleItem] = []
        for market in selected_markets:
            items.extend(
                self._items_for_market(
                    market,
                    dry_run=dry_run,
                    force=force,
                    source_ids=source_ids,
                )
            )

        report = self._build_report(selected_markets, items, dry_run=dry_run)
        if write_report:
            report = self._write_report(report)
        return report

    def _items_for_market(
        self,
        market: CLIMarket,
        *,
        dry_run: bool,
        force: bool,
        source_ids: Optional[Iterable[str]],
    ) -> List[WeatherHighResolutionCycleItem]:
        parsed = self.signals.parse_market(market)
        base = {
            "market_id": str(getattr(market, "condition_id", "") or ""),
            "question": str(getattr(market, "question", "") or ""),
            "location": parsed.location.name if parsed.location else "",
            "metric": parsed.metric,
            "target_date": parsed.target_date.isoformat() if parsed.target_date else "",
        }

        if parsed.metric == "space_weather":
            return [
                WeatherHighResolutionCycleItem(
                    **base,
                    source_id="noaa_high_resolution",
                    status="skipped",
                    blockers=["space_weather_requires_swpc_ingestion"],
                    quality_flags=["high_resolution_cycle_fail_closed"],
                )
            ]
        if not parsed.location:
            return [
                WeatherHighResolutionCycleItem(
                    **base,
                    source_id="noaa_high_resolution",
                    status="skipped",
                    blockers=["unparsed_location"],
                    quality_flags=["high_resolution_cycle_fail_closed"],
                )
            ]

        resolution = self._resolve_market_station(market, parsed.location)
        if resolution.blockers:
            return [
                WeatherHighResolutionCycleItem(
                    **base,
                    source_id="noaa_high_resolution",
                    status="blocked",
                    blockers=list(resolution.blockers),
                    quality_flags=[*resolution.quality_flags, "high_resolution_cycle_fail_closed"],
                )
            ]
        if not parsed.metric or not parsed.operator or parsed.threshold is None:
            return [
                WeatherHighResolutionCycleItem(
                    **base,
                    source_id="noaa_high_resolution",
                    status="skipped",
                    blockers=["unparsed_resolution_rule"],
                    quality_flags=[*resolution.quality_flags, "high_resolution_cycle_fail_closed"],
                )
            ]

        manifests = self.source_builder.build_manifests(
            resolution=resolution,
            target_date=parsed.target_date,
            metric=parsed.metric,
            end_date=getattr(market, "end_date", None),
            source_ids=source_ids or getattr(self.config, "weather_high_resolution_sources", None),
        )
        if not manifests:
            return [
                WeatherHighResolutionCycleItem(
                    **base,
                    source_id="noaa_high_resolution",
                    status="blocked",
                    blockers=["high_resolution_manifests_missing"],
                    quality_flags=[*resolution.quality_flags, "high_resolution_cycle_fail_closed"],
                )
            ]

        items: List[WeatherHighResolutionCycleItem] = []
        for manifest in manifests:
            items.append(
                self._item_from_manifest(
                    market=market,
                    resolution=resolution,
                    manifest=manifest,
                    base=base,
                    metric=parsed.metric,
                    dry_run=dry_run,
                    force=force,
                )
            )
        return items

    def _resolve_market_station(self, market: CLIMarket, location) -> WeatherResolutionTarget:
        market_text = ""
        if hasattr(self.signals, "_market_text"):
            market_text = self.signals._market_text(market)  # package-private parser helper
        else:
            market_text = " ".join(
                [
                    str(getattr(market, "question", "") or ""),
                    str(getattr(market, "description", "") or ""),
                ]
            )
        return self.signals.station_mapper.resolve(
            market_id=str(getattr(market, "condition_id", "") or ""),
            location=location,
            market_text=market_text,
        )

    def _item_from_manifest(
        self,
        *,
        market: CLIMarket,
        resolution: WeatherResolutionTarget,
        manifest: Dict[str, Any],
        base: Dict[str, Any],
        metric: str,
        dry_run: bool,
        force: bool,
    ) -> WeatherHighResolutionCycleItem:
        source_id = str(manifest.get("source_id") or "")
        manifest_status = str(manifest.get("status") or "")
        run_id = str(manifest.get("run_id") or "")
        request_url = str(manifest.get("request_url") or "")
        manifest_blockers = [str(item) for item in manifest.get("blockers", []) or []]
        manifest_flags = [str(item) for item in manifest.get("quality_flags", []) or []]

        if manifest_status == "not_applicable" or not request_url:
            blockers = manifest_blockers or [f"high_resolution_request_url_missing:{source_id or 'unknown'}"]
            return WeatherHighResolutionCycleItem(
                **base,
                source_id=source_id,
                status="blocked",
                run_id=run_id,
                manifest_status=manifest_status,
                request_url=request_url,
                blockers=blockers,
                quality_flags=[*manifest_flags, "high_resolution_cycle_fail_closed"],
            )

        if dry_run:
            return WeatherHighResolutionCycleItem(
                **base,
                source_id=source_id,
                status="planned",
                run_id=run_id,
                manifest_status=manifest_status,
                request_url=request_url,
                blockers=manifest_blockers,
                quality_flags=[*manifest_flags, "high_resolution_cycle_planned"],
            )

        result = self.ingestor.ingest_manifest(manifest, resolution, metric=metric, force=force)
        run_lag_event = self._record_run_lag_event(
            market=market,
            resolution=resolution,
            manifest=manifest,
            result=result,
            metric=metric,
        )
        status = _cycle_status_from_ingest(result)
        flags = [*manifest_flags, *result.quality_flags]
        return WeatherHighResolutionCycleItem(
            **base,
            source_id=source_id,
            status=status,
            run_id=result.run_id or run_id,
            manifest_status=manifest_status,
            request_url=result.request_url or request_url,
            point_artifact_path=result.point_artifact_path,
            latest_artifact_path=result.latest_artifact_path,
            forecast_metrics=dict(result.forecast_metrics or {}),
            run_lag_event=run_lag_event,
            blockers=list(result.blockers or manifest_blockers),
            quality_flags=list(dict.fromkeys(flags)),
        )

    def _record_run_lag_event(
        self,
        *,
        market: CLIMarket,
        resolution: WeatherResolutionTarget,
        manifest: Dict[str, Any],
        result: WeatherHighResolutionIngestResult,
        metric: str,
    ) -> Dict[str, Any]:
        payload = {
            **dict(manifest),
            "source_id": result.source_id or str(manifest.get("source_id") or ""),
            "run_id": result.run_id or str(manifest.get("run_id") or ""),
            "status": result.status,
            "forecast_metrics": dict(result.forecast_metrics or {}),
            "resolution_station": str(
                resolution.resolution_station
                or resolution.metar_station
                or resolution.station_name
                or ""
            ),
            "metric": metric,
        }
        return self.run_lag_ledger.observe(
            payload,
            station=payload["resolution_station"],
            metric=metric,
            clob_snapshot={
                "market_id": str(getattr(market, "condition_id", "") or ""),
                "yes_price": getattr(market, "yes_price", None),
                "no_price": getattr(market, "no_price", None),
            },
        )

    def _build_report(
        self,
        markets: List[CLIMarket],
        items: List[WeatherHighResolutionCycleItem],
        *,
        dry_run: bool,
    ) -> WeatherHighResolutionCycleReport:
        planned = len([item for item in items if item.status == "planned"])
        ingested = len(
            [
                item
                for item in items
                if item.status == "ingested" and "high_resolution_point_cache_hit" not in item.quality_flags
            ]
        )
        cache_hits = len([item for item in items if item.status == "ingested" and "high_resolution_point_cache_hit" in item.quality_flags])
        skipped = len([item for item in items if item.status == "skipped"])
        blocked = len([item for item in items if item.status in {"blocked", "parser_unavailable", "failed"}])
        run_lag_events = [item.run_lag_event for item in items if item.run_lag_event]
        new_run_arrivals = len(
            [event for event in run_lag_events if event.get("event_type") == "new_run_arrival"]
        )
        actionable_run_lag = len(
            [event for event in run_lag_events if event.get("actionable_for_research")]
        )
        status = "ready"
        if not items:
            status = "empty"
        elif (blocked + skipped) == len(items):
            status = "blocked"
        elif blocked == len(items):
            status = "blocked"
        elif dry_run:
            status = "planned"
        elif ingested or cache_hits:
            status = "live_safe_cache_ready" if blocked == 0 else "partial_cache_ready"

        return WeatherHighResolutionCycleReport(
            status=status,
            generated_at=utc_now_iso(),
            cache_dir=str(self.cache_dir),
            total_markets=len(markets),
            total_items=len(items),
            planned_count=planned,
            ingested_count=ingested,
            cache_hit_count=cache_hits,
            skipped_count=skipped,
            blocked_count=blocked,
            dry_run=dry_run,
            run_lag_event_count=len(run_lag_events),
            new_run_arrival_count=new_run_arrivals,
            actionable_run_lag_count=actionable_run_lag,
            items=items,
        )

    def _write_report(self, report: WeatherHighResolutionCycleReport) -> WeatherHighResolutionCycleReport:
        run_dir = self.config.data_dir / "weather_high_resolution_ingest"
        run_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = run_dir / f"cycle_{stamp}.json"
        ledger_path = run_dir / "cycle_ledger.jsonl"
        payload = report.to_dict()
        payload["ledger_path"] = str(ledger_path)
        payload["report_path"] = str(report_path)
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        final_report = WeatherHighResolutionCycleReport(
            **{
                **payload,
                "items": report.items,
            }
        )
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(final_report.summary(), sort_keys=True) + "\n")
        return final_report


def _resolve_cache_dir(config: PolymarketCLIConfig, override: str | Path | None = None) -> Path:
    raw = str(override or getattr(config, "weather_high_resolution_cache_dir", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (config.data_dir / "weather_high_resolution_cache").expanduser().resolve()


def _cycle_status_from_ingest(result: WeatherHighResolutionIngestResult) -> str:
    if result.status == "live_safe":
        return "ingested"
    if result.status == "parser_unavailable":
        return "parser_unavailable"
    if result.status in {"not_applicable", "unavailable"}:
        return "blocked"
    return "failed"


def _market_from_payload(payload: Dict[str, Any]) -> CLIMarket:
    end_date = payload.get("end_date")
    if isinstance(end_date, str) and end_date:
        end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00")).replace(tzinfo=None)
    elif not isinstance(end_date, datetime):
        end_date = None
    return CLIMarket(
        condition_id=str(payload.get("condition_id") or payload.get("id") or payload.get("market_id") or ""),
        question=str(payload.get("question") or ""),
        symbol=str(payload.get("symbol") or "WEATHER"),
        yes_token_id=str(payload.get("yes_token_id") or payload.get("yesTokenId") or ""),
        no_token_id=str(payload.get("no_token_id") or payload.get("noTokenId") or ""),
        yes_price=float(payload.get("yes_price", payload.get("yesPrice", 0.0)) or 0.0),
        no_price=float(payload.get("no_price", payload.get("noPrice", 0.0)) or 0.0),
        liquidity=float(payload.get("liquidity", 0.0) or 0.0),
        volume_24h=float(payload.get("volume_24h", payload.get("volume24h", 0.0)) or 0.0),
        end_date=end_date,
        is_active=bool(payload.get("is_active", payload.get("active", True))),
        market_type=str(payload.get("market_type") or "neutral"),
        price_target=payload.get("price_target"),
        duration_minutes=payload.get("duration_minutes"),
        event_slug=str(payload.get("event_slug") or ""),
        spread=float(payload.get("spread", 0.0) or 0.0),
        slug=str(payload.get("slug") or ""),
        description=str(payload.get("description") or ""),
    )


def _load_market_json(path: str | Path) -> List[CLIMarket]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_markets = payload.get("markets", payload.get("items", []))
    else:
        raw_markets = payload
    if not isinstance(raw_markets, list):
        raise ValueError("market_json_must_be_list_or_object_with_markets")
    return [_market_from_payload(item) for item in raw_markets if isinstance(item, dict)]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run high-resolution weather ingest for market JSON.")
    parser.add_argument("--market-json", required=True, help="JSON list of CLIMarket-like weather market objects.")
    parser.add_argument("--cache-dir", default="", help="Point artifact cache directory.")
    parser.add_argument("--data-dir", default="", help="Override Polymarket trader data directory.")
    parser.add_argument("--sources", nargs="*", default=None, help="High-resolution source IDs, e.g. noaa_hrrr noaa_nbm.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    config_kwargs: Dict[str, Any] = {"market_vertical": "weather"}
    if args.data_dir:
        config_kwargs["_data_dir_override"] = Path(args.data_dir)
    if args.cache_dir:
        config_kwargs["weather_high_resolution_cache_dir"] = args.cache_dir
    if args.sources is not None:
        config_kwargs["weather_high_resolution_sources"] = args.sources
    config = get_polymarket_cli_config(**config_kwargs)
    markets = _load_market_json(args.market_json)
    report = WeatherHighResolutionIngestCycleRunner(config).run(
        markets,
        dry_run=args.dry_run,
        force=args.force,
        source_ids=args.sources,
        limit=args.limit,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.status not in {"blocked", "empty"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
