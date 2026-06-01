"""
Exchange data signals for Polymarket CLI agents.

This adapter fetches public Hyperliquid market context and turns it into
price anchors for the swarm analyzer.
"""

import math
import time
from typing import Any, Dict, Iterable, List, Optional

from termcolor import cprint

from .config import PolymarketCLIConfig, get_config
from .models import CLIMarket
from .weather_signals import WeatherDataSignals


class ExchangeDataSignals:
    """
    Fetch exchange-level context to enrich swarm analysis.

    Returns signal context dict:
    {
        "BTC": {
            "funding_signal": "bearish" | "bullish" | "neutral",
            "funding_rate": 0.0005,
            "funding_summary": "High positive funding (0.05%) - overleveraged longs, contrarian bearish",
            "inferred_price": 65000.0,
            "direction": "up" | "down" | "flat" | "unknown",
            "daily_move_pct": 2.4,
            "daily_volatility_pct": 4.0,
            "exchange_signal": "spot ~$65,000, 24h up (+2.4%); funding bearish (0.0500%)",
        }
    }
    """

    DEFAULT_DAILY_VOL_PCT = {
        "BTC": 4.0,
        "ETH": 5.0,
        "SOL": 7.0,
    }

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_time: float = 0.0
        self._cache_ttl: float = 60.0  # 1 minute cache
        self.weather = WeatherDataSignals(self.config)

        # Funding thresholds (8-hour rate).
        self.extreme_high = 0.0005   # 0.05% - contrarian bearish
        self.extreme_low = -0.0002   # -0.02% - contrarian bullish
        self.strong_high = 0.001     # 0.1% - strong bearish
        self.strong_low = -0.0005    # -0.05% - strong bullish

    def get_market_context(self, markets: Iterable[CLIMarket]) -> Dict[str, Dict[str, Any]]:
        """
        Return analysis context keyed by market id.

        Crypto markets use symbol-level exchange context. Weather markets need
        market-specific parsing because the question contains the location,
        metric, threshold, and resolution window.
        """
        market_list = list(markets or [])
        if str(getattr(self.config, "market_vertical", "crypto") or "crypto").lower() == "weather":
            return self.weather.get_market_context(market_list)
        return self.get_signals(
            sorted(
                {
                    str(getattr(market, "symbol", "")).strip().upper()
                    for market in market_list
                    if str(getattr(market, "symbol", "")).strip()
                }
            )
        )

    def get_signals(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        Fetch exchange signals for the given symbols.

        Returns a cached subset if it is still fresh enough.
        """
        if symbols is None:
            symbols = ["BTC", "ETH"]

        normalized = [str(sym).strip().upper() for sym in symbols if str(sym).strip()]
        if not normalized:
            return {}

        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            if all(sym in self._cache for sym in normalized):
                return {sym: dict(self._cache[sym]) for sym in normalized}

        signals: Dict[str, Dict[str, Any]] = {}
        market_context = self._fetch_hyperliquid_market_context(normalized)
        for sym in normalized:
            snapshot = market_context.get(sym, {})
            rate = self._safe_float(snapshot.get("funding", 0.0), 0.0)
            funding_signal = self._analyze_funding(rate)

            inferred_price = self._infer_price(snapshot)
            prev_day_price = self._safe_float(snapshot.get("prevDayPx", 0.0), 0.0)
            daily_move_pct = self._compute_pct_change(inferred_price, prev_day_price)
            direction = self._classify_direction(daily_move_pct)
            daily_volatility_pct = self._estimate_daily_volatility_pct(sym, daily_move_pct)

            payload = {
                **funding_signal,
                "funding_rate": rate,
                "inferred_price": inferred_price,
                "direction": direction,
                "daily_move_pct": daily_move_pct,
                "daily_volatility_pct": daily_volatility_pct,
                "mark_price": self._safe_float(snapshot.get("markPx", 0.0), 0.0),
                "mid_price": self._safe_float(snapshot.get("midPx", 0.0), 0.0),
                "oracle_price": self._safe_float(snapshot.get("oraclePx", 0.0), 0.0),
                "prev_day_price": prev_day_price,
                "exchange_signal": self._build_exchange_signal_summary(
                    inferred_price=inferred_price,
                    direction=direction,
                    daily_move_pct=daily_move_pct,
                    funding_signal=funding_signal.get("funding_signal", "neutral"),
                    funding_rate=rate,
                ),
            }
            signals[sym] = payload

        self._cache = {sym: dict(payload) for sym, payload in signals.items()}
        self._cache_time = now

        for sym, sig in signals.items():
            funding = sig.get("funding_signal", "neutral")
            rate = self._safe_float(sig.get("funding_rate", 0.0), 0.0)
            price = self._safe_float(sig.get("inferred_price", 0.0), 0.0)
            direction = sig.get("direction", "unknown")
            if funding != "neutral" or price > 0:
                cprint(
                    f"  Exchange signal {sym}: spot=${price:,.0f} 24h={direction} "
                    f"funding={funding} ({rate*100:.4f}%)",
                    "magenta",
                )

        return signals

    def _fetch_hyperliquid_market_context(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch funding plus price context from Hyperliquid's public REST API."""
        import requests

        market_context: Dict[str, Dict[str, Any]] = {}
        try:
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "metaAndAssetCtxs"}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                return market_context

            data = resp.json()
            if not isinstance(data, list) or len(data) < 2:
                return market_context

            meta = data[0]
            ctxs = data[1]
            universe = meta.get("universe", []) if isinstance(meta, dict) else []

            for i, asset in enumerate(universe):
                name = str((asset or {}).get("name", "")).upper()
                if name in symbols and i < len(ctxs):
                    snapshot = dict(ctxs[i] or {})
                    snapshot["name"] = name
                    market_context[name] = snapshot

        except Exception as exc:
            cprint(f"Funding rate fetch error: {exc}", "red")

        return market_context

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed

    def _infer_price(self, snapshot: Dict[str, Any]) -> float:
        for field in ("midPx", "markPx", "oraclePx"):
            price = self._safe_float(snapshot.get(field, 0.0), 0.0)
            if price > 0:
                return price
        return 0.0

    @staticmethod
    def _compute_pct_change(current_price: float, previous_price: float) -> Optional[float]:
        if current_price <= 0 or previous_price <= 0:
            return None
        return ((current_price - previous_price) / previous_price) * 100.0

    @staticmethod
    def _classify_direction(daily_move_pct: Optional[float]) -> str:
        if daily_move_pct is None:
            return "unknown"
        if daily_move_pct >= 0.25:
            return "up"
        if daily_move_pct <= -0.25:
            return "down"
        return "flat"

    def _estimate_daily_volatility_pct(self, symbol: str, daily_move_pct: Optional[float]) -> float:
        baseline = float(self.DEFAULT_DAILY_VOL_PCT.get(str(symbol or "").upper(), 5.0))
        if daily_move_pct is None:
            return baseline

        realized_move = abs(float(daily_move_pct))
        if realized_move <= 0:
            return baseline

        # Keep a stable sigma baseline, but widen on genuinely large realized moves.
        return max(baseline, min(realized_move, baseline * 2.0))

    @staticmethod
    def _build_exchange_signal_summary(
        inferred_price: float,
        direction: str,
        daily_move_pct: Optional[float],
        funding_signal: str,
        funding_rate: float,
    ) -> str:
        parts: List[str] = []
        if inferred_price > 0:
            if daily_move_pct is None:
                parts.append(f"spot ~${inferred_price:,.0f}")
            else:
                parts.append(f"spot ~${inferred_price:,.0f}, 24h {direction} ({daily_move_pct:+.1f}%)")
        if funding_signal != "neutral":
            parts.append(f"funding {funding_signal} ({funding_rate*100:.4f}%)")
        return "; ".join(parts)

    def _analyze_funding(self, rate: float) -> Dict[str, str]:
        """Analyze a funding rate and return signal direction."""
        if rate >= self.strong_high:
            return {
                "funding_signal": "bearish",
                "funding_summary": (
                    f"Very high positive funding ({rate*100:.4f}%) - "
                    f"extreme long leverage, strong contrarian bearish"
                ),
            }
        if rate >= self.extreme_high:
            return {
                "funding_signal": "bearish",
                "funding_summary": (
                    f"High positive funding ({rate*100:.4f}%) - "
                    f"overleveraged longs, contrarian bearish"
                ),
            }
        if rate <= self.strong_low:
            return {
                "funding_signal": "bullish",
                "funding_summary": (
                    f"Very negative funding ({rate*100:.4f}%) - "
                    f"extreme short leverage, strong contrarian bullish"
                ),
            }
        if rate <= self.extreme_low:
            return {
                "funding_signal": "bullish",
                "funding_summary": (
                    f"Negative funding ({rate*100:.4f}%) - "
                    f"overleveraged shorts, contrarian bullish"
                ),
            }
        return {
            "funding_signal": "neutral",
            "funding_summary": f"Normal funding ({rate*100:.4f}%) - no directional signal",
        }

    def format_for_prompt(self, signals: Dict[str, Dict[str, Any]]) -> str:
        """Format signals as a text section for prompts."""
        if not signals:
            return ""

        lines = ["\n## Exchange Data Signals"]
        for sym, sig in signals.items():
            summary = sig.get("exchange_signal", "").strip()
            funding_summary = sig.get("funding_summary", "").strip()
            if summary:
                lines.append(f"- {sym}: {summary}")
            elif funding_summary:
                lines.append(f"- {sym}: {funding_summary}")

        if len(lines) == 1:
            return ""

        lines.append("Note: Funding signals are contrarian - extreme positioning suggests reversal risk.")
        return "\n".join(lines)


if __name__ == "__main__":
    ds = ExchangeDataSignals()
    signals = ds.get_signals(["BTC", "ETH", "SOL"])
    print(ds.format_for_prompt(signals))
    for sym, sig in signals.items():
        print(
            f"{sym}: price=${sig.get('inferred_price', 0):,.0f}, "
            f"rate={sig.get('funding_rate', 0)*100:.4f}%, "
            f"signal={sig.get('funding_signal')}"
        )
