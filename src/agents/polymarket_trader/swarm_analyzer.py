"""
Swarm Analyzer for Polymarket CLI Agents

3-model AI consensus for market predictions.
Models: Claude (reasoning), DeepSeek (quantitative), Grok (contrarian)
Consensus: Simple majority â€” 2/3 agree = trade, all disagree = ABSTAIN
"""

import json
import math
import re
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import List, Optional, Dict, Any, Tuple
from termcolor import cprint

from .config import PolymarketCLIConfig, get_config
from .models import CLIMarket, SwarmPrediction, SwarmConsensus


BASE_SYSTEM_PROMPT = """You are an expert prediction market analyst specializing in crypto markets.

You are given a Polymarket prediction market question along with market data, current crypto prices, and portfolio context.
Your job is to estimate the TRUE probability of the YES outcome and decide whether to bet YES or NO.

CALIBRATION CONTEXT (from 150+ historical trades):
- Crypto "will price reach $X" markets resolve NO about 60% of the time
- The further the target from current price, the less likely it hits
- Short-term markets (< 24h) are more predictable than weekly ones
- Calculate the % move needed and compare to realistic volatility

Think step by step:
1. What is the current price vs the target? Calculate the % move needed.
2. How much time remains? Is the needed move realistic in that window?
3. Use crypto daily volatility: BTC ~3-5%, ETH ~4-6% to judge feasibility
4. Make your best probability estimate â€” don't force YES or NO, be honest
5. Set confidence based on how certain you actually are

IMPORTANT: You must respond with ONLY a valid JSON object, no other text:
{
    "prediction": "YES" or "NO",
    "probability": 0.0 to 1.0 (your estimated true probability of YES),
    "confidence": 0.0 to 1.0 (how confident you are in your estimate),
    "reasoning": "Brief explanation (1-2 sentences)"
}"""

WEATHER_BASE_SYSTEM_PROMPT = """You are an expert prediction market analyst specializing in weather markets.

You are given a Polymarket weather market question, live forecast context, market pricing, and portfolio context.
Your job is to estimate the TRUE probability of the YES outcome and decide whether to bet YES or NO.

WEATHER MARKET PRINCIPLES:
- Resolution criteria matter more than generic weather narratives. Identify the exact location, metric, threshold, date window, and source.
- Treat forecast data as a model input, not certainty. Temperature, precipitation, wind, and storm forecasts have materially different uncertainty.
- Near-term temperature thresholds are usually more modelable than precipitation amount, snowfall, wind gust, or hurricane landfall markets.
- If the forecast context is missing, stale, unsupported, or the question cannot be parsed, keep confidence low and prefer market-price anchoring.
- Do not force a trade when your estimate is close to market price.

Think step by step:
1. What exact weather event resolves YES?
2. What does the provided forecast imply versus the threshold?
3. How uncertain is that metric for the remaining horizon?
4. Compare your probability to the market price and avoid overconfidence.

IMPORTANT: You must respond with ONLY a valid JSON object, no other text:
{
    "prediction": "YES" or "NO",
    "probability": 0.0 to 1.0 (your estimated true probability of YES),
    "confidence": 0.0 to 1.0 (how confident you are in your estimate),
    "reasoning": "Brief explanation (1-2 sentences)"
}"""

# Role-differentiated prompts to reduce correlation between models
ROLE_PROMPTS = {
    "conservative": BASE_SYSTEM_PROMPT + """

YOUR ROLE: CONSERVATIVE ANALYST
- Default to 50% probability when evidence is ambiguous
- Only deviate significantly from 50% when you have strong, clear evidence
- Penalize extreme probabilities (< 0.15 or > 0.85) â€” require very high confidence
- When in doubt, err toward 50%
- Set your confidence LOW (0.3-0.5) when the situation is genuinely uncertain""",

    "quantitative": BASE_SYSTEM_PROMPT + """

YOUR ROLE: QUANTITATIVE ANALYST
- Calculate probability from first principles and base rates
- Do this math: (1) What % price move is needed? (2) How many hours remain? (3) What is expected volatility?
- Crypto daily volatility (1-sigma): BTC ~3-5%, ETH ~4-6%
- If the needed move exceeds 1.5 sigma for the time window, probability should be low (<20%)
- If the needed move is less than 0.5 sigma, probability can be moderate-high (50-70%)
- Focus on the numbers, not narratives or sentiment""",

    "contrarian": BASE_SYSTEM_PROMPT + """

YOUR ROLE: CONTRARIAN ANALYST
- Consider what the consensus might be getting wrong
- Think about: retail bias, news overreaction, mean reversion
- Crypto markets tend to overshoot on optimism â€” price targets are missed more often than hit
- If the obvious call seems too easy, seriously consider the opposite
- Be willing to take unpopular positions if your reasoning is sound
- Set confidence HIGH (0.7-0.9) when you have clear contrarian evidence""",
}

WEATHER_ROLE_PROMPTS = {
    "conservative": WEATHER_BASE_SYSTEM_PROMPT + """

YOUR ROLE: CONSERVATIVE WEATHER ANALYST
- Anchor to the market price unless the forecast margin is large and the resolution rule is clear
- Penalize unresolved parsing, unsupported sources, and long forecast horizons
- Keep confidence modest for precipitation/snow/wind markets unless the signal is overwhelming""",

    "quantitative": WEATHER_BASE_SYSTEM_PROMPT + """

YOUR ROLE: QUANTITATIVE WEATHER ANALYST
- Convert forecast margin versus threshold into probability
- Weight uncertainty by metric: temperature < wind < precipitation/snow < tropical systems
- Focus on the forecast numbers, horizon, and threshold distance""",

    "contrarian": WEATHER_BASE_SYSTEM_PROMPT + """

YOUR ROLE: CONTRARIAN WEATHER ANALYST
- Look for cases where traders overprice headline weather risk
- Challenge obvious forecast reads when the resolution source, timing, or threshold wording is ambiguous
- Be willing to say NO when the forecast barely clears a threshold or the data source is weak""",
}

# Map model providers/names to roles for diverse consensus
MODEL_ROLE_MAP = {
    "openai": "conservative",
    "gpt": "conservative",
    "deepseek": "quantitative",
    "xai": "contrarian",
    "grok": "contrarian",
    "x-ai": "contrarian",
    "claude": "conservative",
    "anthropic": "conservative",
}

# Backward compat: single prompt for any code referencing SYSTEM_PROMPT
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


class CLISwarmAnalyzer:
    """
    3-model AI swarm for Polymarket prediction consensus.

    Uses ModelFactory for unified LLM access.
    ThreadPoolExecutor for parallel queries.
    Simple majority consensus with dissent penalty.
    """

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()
        self._init_model_factory()
        self.last_analysis_metadata: Dict[str, Any] = {}
        self.last_model_statuses: List[Dict[str, Any]] = []

    def _init_model_factory(self):
        """Initialize ModelFactory (lazy import to avoid circular deps)."""
        try:
            from src.models.model_factory import ModelFactory
            self.model_factory = ModelFactory()
            cprint("Swarm analyzer initialized with ModelFactory", "green")
        except ImportError:
            cprint("ModelFactory not available, swarm will be limited", "yellow")
            self.model_factory = None

    def analyze_market(self, market: CLIMarket,
                       price_history: Optional[List] = None,
                       price_context: Optional[Dict] = None,
                       portfolio_positions: Optional[List] = None) -> SwarmConsensus:
        """
        Query all 3 models in parallel, aggregate into consensus.

        price_context: dict of {symbol: {inferred_price, direction}} for real crypto prices
        portfolio_positions: list of position dicts for portfolio awareness
        """
        cprint(f"Swarm analyzing: {market.question[:60]}...", "cyan")

        prompt = self._build_prompt(market, price_history, price_context, portfolio_positions)
        plausibility_context = self._build_plausibility_context(market, price_context)
        predictions = []
        model_statuses: List[Dict[str, Any]] = []

        # Query all models in parallel, assign roles by index
        roles_by_index = ["conservative", "quantitative", "contrarian"]
        executor = ThreadPoolExecutor(max_workers=3)
        try:
            futures = {}
            for idx, (provider, model_name) in enumerate(self.config.swarm_models):
                role = roles_by_index[idx] if idx < len(roles_by_index) else "conservative"
                status_entry = {
                    "provider": provider,
                    "model_name": model_name,
                    "role": role,
                    "status": "pending",
                }
                model_statuses.append(status_entry)
                future = executor.submit(
                    self._query_model, provider, model_name, prompt, role
                )
                futures[future] = (provider, f"{model_name}_{role}", status_entry)

            try:
                for future in as_completed(futures, timeout=self.config.swarm_timeout_seconds):
                    provider, model_name, status_entry = futures[future]
                    try:
                        result = future.result()
                        prediction = None
                        failure_reason = None
                        failure_detail = ""
                        if isinstance(result, tuple):
                            if len(result) >= 1:
                                prediction = result[0]
                            if len(result) >= 2:
                                failure_reason = result[1]
                            if len(result) >= 3:
                                failure_detail = str(result[2] or "")
                        if prediction:
                            status_entry["status"] = "ok"
                            predictions.append(prediction)
                            cprint(f"  {provider}: {prediction.prediction} "
                                   f"(prob={prediction.probability_estimate:.2f}, "
                                   f"conf={prediction.confidence:.2f})", "white")
                        else:
                            status_entry["status"] = failure_reason or "unknown_failure"
                            if failure_detail:
                                status_entry["error"] = failure_detail[:240]
                                status_entry["error_code"] = self._classify_model_error(failure_detail)
                    except Exception as e:
                        status_entry["status"] = "exception"
                        status_entry["error"] = str(e)
                        status_entry["error_code"] = self._classify_model_error(str(e))
                        cprint(f"  {provider} failed: {e}", "red")
            except (FuturesTimeoutError, TimeoutError):
                # Some models timed out â€” continue with what we have
                timed_out = [
                    prov for f, (prov, _, _) in futures.items() if not f.done()
                ]
                for future, (_, _, status_entry) in futures.items():
                    if not future.done() and status_entry.get("status") == "pending":
                        status_entry["status"] = "timeout"
                cprint(f"  Timeout: {', '.join(timed_out)} didn't respond in "
                       f"{self.config.swarm_timeout_seconds}s", "yellow")
                for future in futures:
                    future.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        consensus = self._aggregate_predictions(predictions, market, plausibility_context)
        self.last_model_statuses = model_statuses

        if self.last_analysis_metadata.get("abstain_reason") == "insufficient_predictions":
            if not model_statuses:
                self.last_analysis_metadata["abstain_reason"] = "no_swarm_models_configured"
            else:
                successful = [item for item in model_statuses if item.get("status") == "ok"]
                unavailable = [
                    item for item in model_statuses
                    if item.get("status") in {"provider_unavailable", "model_name_unavailable", "model_factory_unavailable"}
                ]
                failures = [
                    item for item in model_statuses
                    if item.get("status") in {"empty_response", "parse_failure", "timeout", "exception", "unknown_failure"}
                ]
                if not successful and unavailable:
                    self.last_analysis_metadata["abstain_reason"] = "swarm_models_unavailable"
                elif not successful and failures:
                    self.last_analysis_metadata["abstain_reason"] = "swarm_model_failures"
                elif len(successful) < max(1, int(getattr(self.config, "min_consensus_count", 2))) and failures:
                    self.last_analysis_metadata["abstain_reason"] = "insufficient_predictions_after_model_failures"
                elif len(successful) < max(1, int(getattr(self.config, "min_consensus_count", 2))) and unavailable:
                    self.last_analysis_metadata["abstain_reason"] = "insufficient_predictions_after_unavailable_models"

        self.last_analysis_metadata["model_statuses"] = model_statuses
        successful_model_count = len(
            [item for item in model_statuses if item.get("status") == "ok"]
        )
        self.last_analysis_metadata["successful_model_count"] = successful_model_count
        required_consensus_models = max(1, int(getattr(self.config, "min_consensus_count", 2)))
        runtime_ready = successful_model_count >= required_consensus_models
        analysis_cohort = "swarm"
        measurement_boundary = "swarm"
        if not runtime_ready:
            measurement_boundary = "degraded_swarm"
            analysis_cohort = "single_model_control" if successful_model_count == 1 else "degraded_swarm"
        self.last_analysis_metadata["required_consensus_models"] = required_consensus_models
        self.last_analysis_metadata["runtime_ready"] = runtime_ready
        self.last_analysis_metadata["measurement_boundary"] = measurement_boundary
        self.last_analysis_metadata["analysis_cohort"] = analysis_cohort

        # Log result
        color = "green" if consensus.consensus_prediction != "ABSTAIN" else "yellow"
        cprint(f"  Consensus: {consensus.consensus_prediction} "
               f"(prob={consensus.consensus_probability:.2f}, "
               f"conf={consensus.consensus_confidence:.2f}, "
               f"agree={consensus.agreement_ratio:.0%})", color)

        # Save analysis
        self._save_analysis(consensus, market)

        return consensus

    def _build_prompt(self, market: CLIMarket,
                      price_history: Optional[List],
                      price_context: Optional[Dict] = None,
                      portfolio_positions: Optional[List] = None) -> str:
        """Build analysis prompt with market data, crypto prices, and portfolio."""
        if self._is_weather_vertical():
            return self._build_weather_prompt(market, price_context, portfolio_positions)

        lines = [
            "## Polymarket Prediction Market",
            f"Question: {market.question}",
            f"",
            f"## Market Info",
            f"- Market YES price: ${market.yes_price:.3f} ({market.yes_price*100:.1f}% implied probability)",
            f"- The market is pricing YES at {market.yes_price*100:.1f}%. Consider why the market might be right before disagreeing.",
            f"- {'WARNING: Market prices YES below 20% â€” the market consensus is this is UNLIKELY. You need VERY strong evidence to disagree.' if market.yes_price < 0.20 else ('NOTE: Market prices YES above 70% â€” the market consensus is this is LIKELY.' if market.yes_price > 0.70 else '')}",
            f"- Liquidity: ${market.liquidity:,.0f}",
            f"- 24h Volume: ${market.volume_24h:,.0f}",
            f"- Symbol: {market.symbol}",
        ]

        if market.end_date:
            hours = market.time_remaining_hours
            if hours < 24:
                lines.append(f"- Time Remaining: {hours:.1f} hours")
            else:
                lines.append(f"- Time Remaining: {hours / 24:.1f} days")

        if market.price_target:
            lines.append(f"- Price Target: ${market.price_target:,.0f}")
            lines.append(f"- Market Type: {market.market_type}")

        if market.duration_minutes:
            lines.append(f"- Duration: {market.duration_minutes} minutes")

        # Current crypto prices (from web search or inferred)
        if price_context:
            lines.append(f"\n## Current Crypto Prices")
            for symbol, info in price_context.items():
                price = info.get("inferred_price", 0)
                direction = info.get("direction", "unknown")
                news = info.get("news", "")
                if price > 0:
                    lines.append(f"- {symbol}: ~${price:,.0f} (24h: {direction})")
                    if news:
                        lines.append(f"  Recent: {news}")
                exchange_sig = info.get("exchange_signal", "")
                if exchange_sig:
                    lines.append(f"  Exchange: {exchange_sig}")

            # Highlight gap between current price and target with sigma analysis
            if market.price_target and market.symbol in price_context:
                symbol_context = price_context[market.symbol]
                current = symbol_context.get("inferred_price", 0)
                if current > 0:
                    gap_pct = ((market.price_target - current) / current) * 100
                    lines.append(f"- Gap to target: {gap_pct:+.1f}% "
                                 f"(${current:,.0f} â†’ ${market.price_target:,.0f})")
                    daily_move_pct = self._safe_float(symbol_context.get("daily_move_pct", 0.0), 0.0)
                    if daily_move_pct:
                        lines.append(f"- Recent spot move: {daily_move_pct:+.1f}% over the last 24h")
                    # Add volatility context
                    daily_vol = self._safe_float(
                        symbol_context.get(
                            "daily_volatility_pct",
                            {"BTC": 4.0, "ETH": 5.0, "SOL": 7.0}.get(market.symbol, 5.0),
                        ),
                        {"BTC": 4.0, "ETH": 5.0, "SOL": 7.0}.get(market.symbol, 5.0),
                    )
                    hours = market.time_remaining_hours if market.end_date else 24
                    period_vol = daily_vol * (hours / 24) ** 0.5
                    if period_vol > 0:
                        sigma = abs(gap_pct) / period_vol
                        lines.append(f"- Sigma analysis: {abs(gap_pct):.1f}% move needed / "
                                     f"{period_vol:.1f}% period vol = {sigma:.1f} sigma")
                        if sigma > 2:
                            lines.append(f"  WARNING: >2 sigma move needed â€” historically very unlikely (<5%)")
                        elif sigma > 1.5:
                            lines.append(f"  CAUTION: >1.5 sigma move â€” historically unlikely (<15%)")
                        lines.append(
                            "  If the move needs more than ~2 sigma, be conservative and prefer ABSTAIN "
                            "unless the models are strongly aligned."
                        )

        lines.append(
            "- Anchor your estimate to the current market price and avoid overreacting to narratives. "
            "If your estimate is close to the market price, ABSTAIN is often the correct answer."
        )

        # Portfolio context
        if portfolio_positions:
            lines.append(f"\n## Current Portfolio ({len(portfolio_positions)} positions)")
            for pos in portfolio_positions[:5]:
                q = pos.get("question", "?")[:50]
                side = pos.get("side", "?")
                pnl = pos.get("unrealized_pnl", 0)
                lines.append(f"- {side} on \"{q}\" (PnL: ${pnl:+.2f})")
            lines.append("Note: Consider correlation risk with existing positions.")

        if price_history:
            lines.append(f"\n## Recent Price History (YES token)")
            recent = price_history[-10:] if len(price_history) > 10 else price_history
            for point in recent:
                if isinstance(point, dict):
                    t = point.get("t", point.get("timestamp", ""))
                    p = point.get("p", point.get("price", 0))
                    lines.append(f"  {t}: ${float(p):.4f}")

            # Summarize momentum
            if len(recent) >= 2:
                first_p = float(recent[0].get("p", recent[0].get("price", 0))) if isinstance(recent[0], dict) else 0
                last_p = float(recent[-1].get("p", recent[-1].get("price", 0))) if isinstance(recent[-1], dict) else 0
                if first_p > 0:
                    change_pct = ((last_p - first_p) / first_p) * 100
                    direction = "bullish" if change_pct > 1 else ("bearish" if change_pct < -1 else "flat")
                    lines.append(f"  Momentum: {change_pct:+.1f}% ({direction})")

        # Specialized prompt for Up/Down markets
        if market.market_type == "binary_updown":
            duration = market.duration_minutes or "unknown"
            lines.append(f"\n## Short-Term Up/Down Market")
            lines.append(f"This is a {duration}-minute Up/Down market. It resolves \"Up\" if the price at the END")
            lines.append(f"of the window is >= the price at the START. Otherwise \"Down.\"")
            lines.append(f"")
            lines.append(f"Key factors for short-term prediction:")
            lines.append(f"- Recent crypto price momentum (use price context provided)")
            lines.append(f"- YES token price history shows market sentiment shifts")
            lines.append(f"- Markets near 50/50 may have exploitable bias from retail flow")
            lines.append(f"- Mean reversion: if YES has spiked recently, consider NO")
            if duration and isinstance(duration, int):
                if duration <= 5:
                    lines.append(f"- 5-min window: noise-dominated, favor mean reversion, lower confidence")
                elif duration <= 15:
                    lines.append(f"- 15-min window: short-term momentum can work, moderate confidence")
                elif duration <= 60:
                    lines.append(f"- 1-hour window: trend-following works better, higher confidence")
                else:
                    lines.append(f"- {duration}-min window: longer window allows trends, moderate-high confidence")

        lines.append(f"\n## Your Analysis")
        lines.append("Estimate the TRUE probability of YES and decide your prediction.")
        lines.append("Respond with ONLY a JSON object.")

        return "\n".join(lines)

    def _build_plausibility_context(
        self,
        market: CLIMarket,
        price_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._is_weather_vertical():
            weather_context = self._weather_context_for_market(market, price_context)
            weather_probability = None
            probability_raw = weather_context.get("weather_probability")
            try:
                parsed_probability = float(probability_raw)
                if math.isfinite(parsed_probability):
                    weather_probability = max(0.0, min(1.0, parsed_probability))
            except (TypeError, ValueError):
                weather_probability = None

            return {
                "market_yes_price": market.yes_price,
                "market_price_anchor": market.yes_price,
                "current_price": None,
                "target_price": None,
                "gap_pct": None,
                "period_vol_pct": None,
                "sigma_ratio": None,
                "plausibility": weather_context.get("status", "unknown"),
                "weather_probability": weather_probability,
                "weather_edge_percent": weather_context.get("weather_edge_percent"),
                "weather_signal": weather_context.get("weather_signal", ""),
            }

        context: Dict[str, Any] = {
            "market_yes_price": market.yes_price,
            "market_price_anchor": market.yes_price,
            "current_price": None,
            "target_price": market.price_target,
            "gap_pct": None,
            "period_vol_pct": None,
            "sigma_ratio": None,
            "plausibility": "unknown",
        }

        if not price_context or not market.price_target or market.symbol not in price_context:
            return context

        symbol_info = price_context.get(market.symbol, {}) or {}
        current = self._safe_float(symbol_info.get("inferred_price", 0.0), 0.0)
        if current <= 0:
            return context

        daily_vol = self._safe_float(
            symbol_info.get("daily_volatility_pct", {"BTC": 4.0, "ETH": 5.0, "SOL": 7.0}.get(market.symbol, 5.0)),
            5.0,
        )
        hours = market.time_remaining_hours if market.end_date else 24.0
        period_vol = daily_vol * math.sqrt(max(hours, 0.0) / 24.0) if hours > 0 else daily_vol
        if period_vol <= 0:
            return context

        gap_pct = abs((market.price_target - current) / current) * 100.0
        sigma_ratio = gap_pct / period_vol if period_vol > 0 else None

        plausibility = "plausible"
        if sigma_ratio is not None:
            if sigma_ratio >= 2.5:
                plausibility = "improbable"
            elif sigma_ratio >= 1.5:
                plausibility = "caution"

        context.update(
            {
                "current_price": current,
                "gap_pct": gap_pct,
                "period_vol_pct": period_vol,
                "sigma_ratio": sigma_ratio,
                "plausibility": plausibility,
            }
        )
        return context

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed

    @staticmethod
    def _extract_json_payload(content: str) -> Optional[Dict[str, Any]]:
        text = content.strip()
        if not text:
            return None

        candidates = []
        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.IGNORECASE | re.DOTALL)
        candidates.extend(fenced)
        if text.startswith("{") and text.endswith("}"):
            candidates.append(text)
        if "{" in text and "}" in text:
            candidates.append(text[text.find("{"): text.rfind("}") + 1])

        seen = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            try:
                parsed = json.loads(normalized)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        return None

    def _query_model(self, provider: str, model_name: str,
                     prompt: str, role: str = None) -> Tuple[Optional[SwarmPrediction], Optional[str], Optional[str]]:
        """Query a single model via ModelFactory with role-specific prompt and temperature."""
        if not self.model_factory:
            return None, "model_factory_unavailable", ""

        start = time.time()
        try:
            model = self.model_factory.get_model(provider, model_name)
            if not model:
                provider_available = False
                try:
                    provider_available = self.model_factory.is_model_available(provider)
                except Exception:
                    provider_available = False
                return None, "model_name_unavailable" if provider_available else "provider_unavailable", ""

            # Temperature by role for diversity
            role_temp = {"conservative": 0.3, "quantitative": 0.5, "contrarian": 0.7}

            # Determine role (explicit param > provider map > default)
            if role is None:
                provider_lower = provider.lower()
                model_lower = model_name.lower()
                role = "conservative"
                for key, r in MODEL_ROLE_MAP.items():
                    if key in provider_lower or key in model_lower:
                        role = r
                        break

            temp = role_temp.get(role, 0.5)
            system_prompt = ROLE_PROMPTS.get(role, BASE_SYSTEM_PROMPT)
            if self._is_weather_vertical():
                system_prompt = WEATHER_ROLE_PROMPTS.get(role, WEATHER_BASE_SYSTEM_PROMPT)

            response = model.generate_response(
                system_prompt,
                prompt,
                temperature=temp,
                max_tokens=512
            )

            elapsed = time.time() - start

            if not response:
                return None, "empty_response", ""

            # Extract text content
            content = response.content if hasattr(response, "content") else str(response)
            if isinstance(content, list):
                content = content[0].text if hasattr(content[0], "text") else str(content[0])

            parsed = self._parse_model_response(content, provider, model_name, elapsed)
            if not parsed:
                return None, "parse_failure", content[:240]
            return parsed, None, None

        except Exception as e:
            cprint(f"Model query error ({provider}): {e}", "red")
            return None, "exception", str(e)

    @staticmethod
    def _classify_model_error(message: str) -> str:
        lowered = str(message or "").lower()
        if "credit balance is too low" in lowered or "insufficient credits" in lowered:
            return "insufficient_credits"
        if "insufficient balance" in lowered or "402" in lowered:
            return "insufficient_balance"
        if "401" in lowered or "unauthorized" in lowered or "invalid api key" in lowered:
            return "auth_error"
        if "429" in lowered or "rate limit" in lowered:
            return "rate_limited"
        if "timeout" in lowered or "timed out" in lowered:
            return "timeout"
        return "exception"

    def _parse_model_response(self, content: str, provider: str,
                              model_name: str, elapsed: float) -> Optional[SwarmPrediction]:
        """Extract JSON from model response."""
        try:
            data = self._extract_json_payload(content)
            if not data:
                return None

            prediction = data.get("prediction", "").upper()
            if prediction not in ("YES", "NO"):
                # Try to infer from probability if prediction field is missing
                prob_val = None
                for key in ["probability", "true_probability_yes", "prob", "probability_yes", "yes_probability"]:
                    if key in data:
                        prob_val = self._safe_float(data[key], default=math.nan)
                        break
                if prob_val is not None and not math.isnan(prob_val):
                    prediction = "YES" if prob_val >= 0.5 else "NO"
                else:
                    return None

            # Flexible probability extraction
            probability = 0.5
            for key in ["probability", "true_probability_yes", "prob", "probability_yes", "yes_probability", "estimated_probability"]:
                if key in data:
                    probability = self._safe_float(data[key], default=0.5)
                    break
            probability = max(0.0, min(1.0, probability))

            # Flexible confidence extraction (default 0.5 if not provided)
            confidence = 0.5
            for key in ["confidence", "conf", "certainty", "confidence_level"]:
                if key in data:
                    confidence = self._safe_float(data[key], default=0.5)
                    break
            confidence = max(0.0, min(1.0, confidence))

            reasoning = data.get("reasoning", "")

            return SwarmPrediction(
                model_provider=provider,
                model_name=model_name,
                prediction=prediction,
                probability_estimate=probability,
                confidence=confidence,
                reasoning=reasoning[:200],
                response_time=elapsed,
            )

        except Exception as e:
            cprint(f"Parse error ({provider}): {e}", "red")
            return None

    def _aggregate_predictions(self, predictions: List[SwarmPrediction],
                               market: CLIMarket,
                               plausibility_context: Optional[Dict[str, Any]] = None) -> SwarmConsensus:
        """
        Simple majority consensus:
        - 2/3 agree -> consensus = majority prediction
        - <2 agree -> ABSTAIN
        - Dissent penalty: if minority is >80% confident, reduce by 15%
        """
        now = datetime.utcnow()
        market_anchor = max(0.0, min(1.0, market.yes_price))
        plausibility_context = plausibility_context or {}
        sigma_ratio = plausibility_context.get("sigma_ratio")
        current_price = plausibility_context.get("current_price")
        market_plausibility = plausibility_context.get("plausibility", "unknown")
        weather_probability = plausibility_context.get("weather_probability")
        if weather_probability is not None:
            weather_probability = max(0.0, min(1.0, self._safe_float(weather_probability, market_anchor)))
        abstain_reason = ""
        raw_consensus_prob = market_anchor

        if len(predictions) < 2:
            self.last_analysis_metadata = {
                "market_yes_price": market_anchor,
                "raw_consensus_probability": market_anchor,
                "calibrated_probability": market_anchor,
                "probability_gap": 0.0,
                "sigma_ratio": sigma_ratio,
                "current_price": current_price,
                "plausibility": market_plausibility,
                "weather_probability": weather_probability,
                "weather_edge_percent": plausibility_context.get("weather_edge_percent"),
                "weather_signal": plausibility_context.get("weather_signal", ""),
                "abstain_reason": "insufficient_predictions",
            }
            return SwarmConsensus(
                market_id=market.condition_id,
                timestamp=now,
                predictions=predictions,
                consensus_prediction="ABSTAIN",
                consensus_probability=market_anchor,
                consensus_confidence=0.0,
                yes_votes=sum(1 for p in predictions if p.prediction == "YES"),
                no_votes=sum(1 for p in predictions if p.prediction == "NO"),
                agreement_ratio=0.0,
            )

        yes_count = sum(1 for p in predictions if p.prediction == "YES")
        no_count = sum(1 for p in predictions if p.prediction == "NO")

        # Determine consensus
        if yes_count >= self.config.min_consensus_count:
            consensus_pred = "YES"
        elif no_count >= self.config.min_consensus_count:
            consensus_pred = "NO"
        else:
            consensus_pred = "ABSTAIN"

        # Calculate probability from majority models
        if consensus_pred != "ABSTAIN":
            majority = [p for p in predictions if p.prediction == consensus_pred]
            minority = [p for p in predictions if p.prediction != consensus_pred]

            # Weighted average probability from majority
            total_weight = sum(p.confidence for p in majority)
            if total_weight > 0:
                consensus_prob = sum(
                    p.probability_estimate * p.confidence for p in majority
                ) / total_weight
            else:
                consensus_prob = sum(p.probability_estimate for p in majority) / len(majority)
            raw_consensus_prob = consensus_prob

            # Consensus confidence
            agreement_ratio = max(yes_count, no_count) / len(predictions)
            avg_confidence = sum(p.confidence for p in majority) / len(majority)
            consensus_conf = agreement_ratio * avg_confidence

            # Dissent penalty: stronger penalty when minority is confident
            # This fights bullish bias by giving contrarian voices more weight
            if minority:
                max_dissent_conf = max(p.confidence for p in minority)
                if max_dissent_conf > 0.7:
                    consensus_conf *= 0.70  # 30% penalty for strong dissent (was 15%)
                elif max_dissent_conf > 0.5:
                    consensus_conf *= 0.85  # 15% penalty for moderate dissent

            anchor_weight = 0.30
            if sigma_ratio is not None:
                if sigma_ratio >= 2.5:
                    anchor_weight = 0.55
                elif sigma_ratio >= 1.5:
                    anchor_weight = 0.42
            if market_anchor <= 0.20 or market_anchor >= 0.80:
                anchor_weight = max(anchor_weight, 0.40)

            consensus_prob = (consensus_prob * (1.0 - anchor_weight)) + (market_anchor * anchor_weight)
            if weather_probability is not None:
                forecast_weight = 0.40
                consensus_prob = (consensus_prob * (1.0 - forecast_weight)) + (weather_probability * forecast_weight)
            consensus_prob = max(0.0, min(1.0, consensus_prob))

            probability_gap = abs(consensus_prob - market_anchor)
            confidence_floor = max(self.config.min_consensus_confidence, 0.58)
            min_probability_gap = 0.06
            if self._is_weather_vertical():
                min_probability_gap = max(
                    min_probability_gap,
                    float(getattr(self.config, "weather_min_probability_gap", 0.08) or 0.08),
                )

            if sigma_ratio is not None and sigma_ratio >= 2.5:
                if consensus_conf < 0.78 or probability_gap < 0.12:
                    abstain_reason = "sigma_implausible"
            elif sigma_ratio is not None and sigma_ratio >= 1.5:
                if consensus_conf < 0.70 and probability_gap < 0.10:
                    abstain_reason = "sigma_caution"

            if not abstain_reason and consensus_conf < confidence_floor:
                abstain_reason = "low_confidence"
            elif not abstain_reason and probability_gap < min_probability_gap:
                abstain_reason = "insufficient_price_edge"
            elif not abstain_reason and (market_anchor <= 0.20 or market_anchor >= 0.80):
                if probability_gap < 0.10 or consensus_conf < 0.75:
                    abstain_reason = "market_price_anchor"

            if abstain_reason:
                consensus_pred = "ABSTAIN"
                consensus_prob = market_anchor
                consensus_conf = 0.0
        else:
            consensus_prob = market_anchor
            consensus_conf = 0.0
            agreement_ratio = 0.0

        self.last_analysis_metadata = {
            "market_yes_price": market_anchor,
            "raw_consensus_probability": raw_consensus_prob,
            "calibrated_probability": consensus_prob,
            "probability_gap": abs(consensus_prob - market_anchor),
            "sigma_ratio": sigma_ratio,
            "current_price": current_price,
            "plausibility": market_plausibility,
            "weather_probability": weather_probability,
            "weather_edge_percent": plausibility_context.get("weather_edge_percent"),
            "weather_signal": plausibility_context.get("weather_signal", ""),
            "abstain_reason": abstain_reason,
        }

        return SwarmConsensus(
            market_id=market.condition_id,
            timestamp=now,
            predictions=predictions,
            consensus_prediction=consensus_pred,
            consensus_probability=consensus_prob,
            consensus_confidence=consensus_conf,
            yes_votes=yes_count,
            no_votes=no_count,
            agreement_ratio=max(yes_count, no_count) / max(len(predictions), 1),
        )

    def _save_analysis(self, consensus: SwarmConsensus, market: CLIMarket):
        """Save analysis to predictions directory."""
        self.config.ensure_dirs()
        filename = self.config.predictions_dir / f"prediction_{market.condition_id[:16]}_{consensus.timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        try:
            consensus.analysis_path = str(filename)
            data = consensus.to_dict()
            data["market_question"] = market.question
            data["market_symbol"] = market.symbol
            data["market_yes_price"] = market.yes_price
            data["market_price_anchor"] = self.last_analysis_metadata.get("market_yes_price", market.yes_price)
            data["plausibility"] = self.last_analysis_metadata.get("plausibility", "unknown")
            data["sigma_ratio"] = self.last_analysis_metadata.get("sigma_ratio")
            data["probability_gap"] = self.last_analysis_metadata.get("probability_gap")
            data["abstain_reason"] = self.last_analysis_metadata.get("abstain_reason", "")
            data["current_price"] = self.last_analysis_metadata.get("current_price")
            data["weather_probability"] = self.last_analysis_metadata.get("weather_probability")
            data["weather_edge_percent"] = self.last_analysis_metadata.get("weather_edge_percent")
            data["weather_signal"] = self.last_analysis_metadata.get("weather_signal", "")
            data["model_statuses"] = self.last_analysis_metadata.get("model_statuses", [])
            data["successful_model_count"] = self.last_analysis_metadata.get("successful_model_count", 0)
            data["required_consensus_models"] = self.last_analysis_metadata.get("required_consensus_models", 0)
            data["runtime_ready"] = self.last_analysis_metadata.get("runtime_ready", False)
            data["measurement_boundary"] = self.last_analysis_metadata.get("measurement_boundary", "swarm")
            data["analysis_cohort"] = self.last_analysis_metadata.get("analysis_cohort", "swarm")
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            cprint(f"Failed to save prediction: {e}", "red")

    def _build_weather_prompt(
        self,
        market: CLIMarket,
        price_context: Optional[Dict[str, Any]] = None,
        portfolio_positions: Optional[List] = None,
    ) -> str:
        context = self._weather_context_for_market(market, price_context)
        lines = [
            "## Polymarket Weather Market",
            f"Question: {market.question}",
            "",
            "## Market Info",
            f"- Market YES price: ${market.yes_price:.3f} ({market.yes_price*100:.1f}% implied probability)",
            f"- Market NO price: ${market.no_price:.3f}",
            f"- Liquidity: ${market.liquidity:,.0f}",
            f"- 24h Volume: ${market.volume_24h:,.0f}",
            f"- Time Remaining: {market.time_remaining_hours:.1f} hours",
            "",
            "## Weather Forecast Signals",
            f"- Context status: {context.get('status', 'missing')}",
        ]

        for key, label in (
            ("location", "Location"),
            ("metric", "Metric"),
            ("operator", "Operator"),
            ("threshold", "Threshold"),
            ("upper_threshold", "Upper threshold"),
            ("threshold_unit", "Threshold unit"),
        ):
            value = context.get(key)
            if value not in (None, ""):
                lines.append(f"- {label}: {value}")

        signal = str(context.get("weather_signal", "") or "").strip()
        if signal:
            lines.append(f"- Signal: {signal}")

        if context.get("weather_probability") is not None:
            lines.append(f"- Deterministic forecast YES probability: {float(context['weather_probability']):.1%}")
        if context.get("weather_edge_percent") is not None:
            lines.append(f"- Forecast edge vs market: {float(context['weather_edge_percent']):+.1f}%")

        metrics = context.get("forecast_metrics")
        if isinstance(metrics, dict) and metrics:
            lines.append("- Forecast metrics:")
            for key, value in metrics.items():
                if value is not None:
                    lines.append(f"  - {key}: {value}")

        lines.extend(
            [
                "",
                "## Weather Research Rules",
                "- Verify the exact resolution wording before trusting a model signal.",
                "- If context status is not ok, keep confidence low and anchor near market price.",
                "- Temperature thresholds can justify higher confidence than precipitation, snow, wind, or tropical systems.",
                "- If your estimate is within a few points of market price, choose the side but keep confidence low.",
            ]
        )

        if portfolio_positions:
            lines.append(f"\n## Current Portfolio ({len(portfolio_positions)} positions)")
            for pos in portfolio_positions[:5]:
                q = pos.get("question", "?")[:50]
                side = pos.get("side", "?")
                pnl = pos.get("unrealized_pnl", 0)
                lines.append(f"- {side} on \"{q}\" (PnL: ${pnl:+.2f})")
            lines.append("Note: Consider correlated exposure across weather markets.")

        lines.append("\n## Your Analysis")
        lines.append("Estimate the TRUE probability of YES and decide your prediction.")
        lines.append("Respond with ONLY a JSON object.")
        return "\n".join(lines)

    def _weather_context_for_market(
        self,
        market: CLIMarket,
        price_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(price_context, dict):
            return {}
        for key in (
            str(getattr(market, "condition_id", "") or ""),
            "WEATHER",
            str(getattr(market, "symbol", "") or ""),
        ):
            if key and isinstance(price_context.get(key), dict):
                return dict(price_context[key])
        return {}

    def _is_weather_vertical(self) -> bool:
        return str(getattr(self.config, "market_vertical", "crypto") or "crypto").lower() == "weather"


if __name__ == "__main__":
    from .market_scanner import CLIMarketScanner

    scanner = CLIMarketScanner()
    markets = scanner.scan_markets()

    if markets:
        ranked = scanner.rank_markets(markets)
        top_market = ranked[0][0]

        print(f"\nAnalyzing: {top_market.question}")
        print(f"YES: ${top_market.yes_price:.3f}, NO: ${top_market.no_price:.3f}")

        analyzer = CLISwarmAnalyzer()
        consensus = analyzer.analyze_market(top_market)

        print(f"\nResult: {consensus.consensus_prediction}")
        print(f"Probability: {consensus.consensus_probability:.2%}")
        print(f"Confidence: {consensus.consensus_confidence:.2%}")
        print(f"Agreement: {consensus.agreement_ratio:.0%}")
    else:
        print("No markets to analyze")
