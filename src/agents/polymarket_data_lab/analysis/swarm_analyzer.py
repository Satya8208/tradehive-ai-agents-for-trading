"""
Swarm Analyzer

Multi-model AI consensus for trading decisions.
Queries multiple LLMs in parallel and aggregates their predictions.

Built with love by TradeHive
"""

import os
import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import (
    AggregatedSignal,
    CryptoMarket,
    SwarmAnalysisResult,
    ModelPrediction,
)


class SwarmAnalyzer:
    """
    Multi-model AI consensus analyzer.

    Queries multiple LLMs with market context and signals,
    aggregates their predictions into a consensus score.

    Models used:
    - Claude (Opus/Sonnet) via Anthropic
    - GPT-4 via OpenAI
    - DeepSeek via DeepSeek API
    - Grok via xAI API
    - Qwen via Alibaba Cloud

    Consensus is weighted by model accuracy and confidence.
    """

    # Model configurations with weights based on perceived accuracy
    MODELS = {
        "claude_sonnet": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "weight": 0.25,
        },
        "gpt4": {
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "weight": 0.25,
        },
        "deepseek": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "weight": 0.20,
        },
        "grok": {
            "provider": "xai",
            "model": "grok-3",
            "weight": 0.15,
        },
        "qwen": {
            "provider": "alibaba",
            "model": "qwen-max",
            "weight": 0.15,
        },
    }

    # Fast models for 15-min market trading (fastest response times)
    FAST_MODELS = {
        "deepseek": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "weight": 0.40,  # Higher weight - fastest and reliable
        },
        "gpt4_mini": {
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "weight": 0.35,  # Fast mini model
        },
        "grok": {
            "provider": "xai",
            "model": "grok-3",
            "weight": 0.25,  # Fast reasoning
        },
    }

    # System prompt for all models
    SYSTEM_PROMPT = """You are an expert crypto trading analyst specializing in BTC and ETH prediction markets on Polymarket.

Your task is to analyze market signals and predict the outcome of crypto prediction markets.

You will receive:
1. Aggregated signals from whale tracking, liquidation data, and funding rates
2. Information about a specific Polymarket prediction market
3. Current market prices and conditions

Provide your analysis in JSON format with:
- prediction: "YES" or "NO" (which outcome you predict will win)
- confidence: 0.0 to 1.0 (how confident you are)
- reasoning: brief explanation (2-3 sentences max)

Be concise and decisive. Base your prediction on the data provided."""

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self._executor = ThreadPoolExecutor(max_workers=6)
        self._clients: Dict[str, Any] = {}
        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize API clients for each provider."""
        # Anthropic (Claude)
        anthropic_key = os.getenv("ANTHROPIC_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            try:
                from anthropic import Anthropic

                self._clients["anthropic"] = Anthropic(api_key=anthropic_key)
                cprint("[OK] Anthropic client initialized", "green")
            except ImportError:
                cprint("[WARN]  anthropic package not installed", "yellow")

        # OpenAI (GPT-4)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                from openai import OpenAI

                self._clients["openai"] = OpenAI(api_key=openai_key)
                cprint("[OK] OpenAI client initialized", "green")
            except ImportError:
                cprint("[WARN]  openai package not installed", "yellow")

        # DeepSeek
        deepseek_key = os.getenv("DEEPSEEK_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            try:
                from openai import OpenAI

                self._clients["deepseek"] = OpenAI(
                    api_key=deepseek_key, base_url="https://api.deepseek.com"
                )
                cprint("[OK] DeepSeek client initialized", "green")
            except ImportError:
                pass

        # xAI (Grok)
        xai_key = os.getenv("XAI_API_KEY")
        if xai_key:
            try:
                from openai import OpenAI

                self._clients["xai"] = OpenAI(
                    api_key=xai_key, base_url="https://api.x.ai/v1"
                )
                cprint("[OK] xAI (Grok) client initialized", "green")
            except ImportError:
                pass

        # Alibaba (Qwen)
        alibaba_key = os.getenv("ALIBABA_API_KEY") or os.getenv("QWEN_API_KEY")
        if alibaba_key:
            try:
                from openai import OpenAI

                self._clients["alibaba"] = OpenAI(
                    api_key=alibaba_key,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
                cprint("[OK] Qwen (Alibaba) client initialized", "green")
            except ImportError:
                pass

    async def analyze(
        self,
        signal: AggregatedSignal,
        market: CryptoMarket,
        fast_mode: bool = False,
    ) -> SwarmAnalysisResult:
        """
        Run multi-model analysis on a market.

        Args:
            signal: Aggregated signal from data agents
            market: Polymarket market to analyze
            fast_mode: Use fast swarm mode for 15-min markets (fewer models, shorter timeout)

        Returns:
            SwarmAnalysisResult with consensus and individual predictions
        """
        # Build prompt with context
        prompt = self._build_prompt(signal, market)

        # Query all models in parallel (use fast mode for short-duration markets)
        predictions = await self._query_all_models(prompt, fast_mode=fast_mode)

        # Aggregate into consensus
        result = self._aggregate_predictions(predictions, signal, market)

        # Save analysis
        self._save_analysis(result)

        return result

    def _build_prompt(
        self,
        signal: AggregatedSignal,
        market: CryptoMarket,
    ) -> str:
        """Build analysis prompt with market context."""
        prompt = f"""## Market Analysis Request

### Aggregated Signals
- Symbol: {signal.symbol}
- Direction: {signal.direction.value.upper()}
- Composite Score: {signal.composite_score:+.3f} (range: -1.0 bearish to +1.0 bullish)
- Confidence: {signal.confidence:.1%}
- Dominant Signal: {signal.dominant_signal}

### Signal Breakdown"""

        if signal.signal_breakdown:
            for agent, contrib in sorted(
                signal.signal_breakdown.items(), key=lambda x: abs(x[1]), reverse=True
            ):
                prompt += f"\n- {agent}: {contrib:+.3f}"

        prompt += f"""

### Polymarket Market
- Question: {market.question}
- Symbol: {market.symbol}
- Market Type: {market.market_type} (does this bet on price going UP or DOWN?)
- YES Price: ${market.yes_price:.3f}
- NO Price: ${market.no_price:.3f}
- Liquidity: ${market.liquidity:,.0f}"""

        if market.price_target:
            prompt += f"\n- Price Target: ${market.price_target:,.0f}"

        if market.end_date:
            days_left = (market.end_date - datetime.utcnow()).days
            prompt += f"\n- Days Until Resolution: {days_left}"

        prompt += """

### Your Task
Based on the signals and market information above, predict whether YES or NO will win.

Respond ONLY with valid JSON:
{
  "prediction": "YES" or "NO",
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation"
}"""

        return prompt

    async def _query_all_models(
        self, prompt: str, fast_mode: bool = False
    ) -> List[ModelPrediction]:
        """
        Query all available models in parallel.

        Args:
            prompt: Analysis prompt
            fast_mode: Use fast models and shorter timeout for 15-min markets
        """
        tasks = []

        # Select model set based on mode
        models_to_use = self.FAST_MODELS if fast_mode else self.MODELS

        if fast_mode:
            cprint("[FAST] Using fast swarm mode (3 models, 30s timeout)", "cyan")

        for model_name, model_config in models_to_use.items():
            provider = model_config["provider"]
            if provider in self._clients:
                task = asyncio.create_task(
                    self._query_model(model_name, model_config, prompt, fast_mode)
                )
                tasks.append(task)

        if not tasks:
            cprint("[WARN]  No AI models available!", "yellow")
            return []

        # Wait for all models (with timeout)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        predictions = []
        for result in results:
            if isinstance(result, ModelPrediction):
                predictions.append(result)
            elif isinstance(result, Exception):
                cprint(f"Model query error: {result}", "red")

        return predictions

    async def _query_model(
        self,
        model_name: str,
        model_config: Dict,
        prompt: str,
        fast_mode: bool = False,
    ) -> Optional[ModelPrediction]:
        """Query a single model with timeout."""
        provider = model_config["provider"]
        model_id = model_config["model"]
        weight = model_config["weight"]

        # Use shorter timeout for fast mode (15-min markets)
        timeout = (
            self.config.swarm_timeout_fast_seconds
            if fast_mode
            else self.config.swarm_timeout_seconds
        )

        try:
            # Run in thread pool with timeout
            loop = asyncio.get_running_loop()

            if provider == "anthropic":
                task = loop.run_in_executor(
                    self._executor, lambda: self._query_anthropic(model_id, prompt)
                )
            else:
                # OpenAI-compatible providers
                task = loop.run_in_executor(
                    self._executor,
                    lambda: self._query_openai_compatible(provider, model_id, prompt),
                )

            # Apply timeout per model (shorter in fast mode)
            response = await asyncio.wait_for(task, timeout=timeout)

            if response:
                return ModelPrediction(
                    model_name=model_name,
                    prediction=response["prediction"],
                    confidence=response["confidence"],
                    reasoning=response["reasoning"],
                    weight=weight,
                    timestamp=datetime.utcnow(),
                )

        except asyncio.TimeoutError:
            cprint(
                f"[CLOCK] {model_name} timed out after {timeout}s",
                "yellow",
            )
        except Exception as e:
            cprint(f"Error querying {model_name}: {e}", "red")

        return None

    def _query_anthropic(self, model: str, prompt: str) -> Optional[Dict]:
        """Query Anthropic Claude model."""
        client = self._clients.get("anthropic")
        if not client:
            return None

        try:
            response = client.messages.create(
                model=model,
                max_tokens=500,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            return self._parse_response(content)

        except Exception as e:
            cprint(f"Anthropic error: {e}", "red")
            return None

    def _query_openai_compatible(
        self, provider: str, model: str, prompt: str
    ) -> Optional[Dict]:
        """Query OpenAI-compatible API."""
        client = self._clients.get(provider)
        if not client:
            return None

        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=500,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )

            content = response.choices[0].message.content
            return self._parse_response(content)

        except Exception as e:
            cprint(f"{provider} error: {e}", "red")
            return None

    def _parse_response(self, content: str) -> Optional[Dict]:
        """Parse JSON response from model."""
        try:
            # Find JSON in response
            start = content.find("{")
            end = content.rfind("}") + 1

            if start >= 0 and end > start:
                json_str = content[start:end]
                data = json.loads(json_str)

                prediction = data.get("prediction", "").upper()
                if prediction not in ["YES", "NO"]:
                    return None

                confidence = float(data.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                reasoning = data.get("reasoning", "No reasoning provided")

                return {
                    "prediction": prediction,
                    "confidence": confidence,
                    "reasoning": reasoning,
                }

        except (json.JSONDecodeError, ValueError) as e:
            cprint(f"Parse error: {e}", "red")

        return None

    def _aggregate_predictions(
        self,
        predictions: List[ModelPrediction],
        signal: AggregatedSignal,
        market: CryptoMarket,
    ) -> SwarmAnalysisResult:
        """Aggregate individual predictions into consensus."""
        if not predictions:
            return SwarmAnalysisResult(
                market_id=market.market_id,
                timestamp=datetime.utcnow(),
                predictions=[],
                consensus_prediction="ABSTAIN",
                consensus_confidence=0.0,
                yes_votes=0,
                no_votes=0,
                agreement_ratio=0.0,
            )

        # Count weighted votes
        yes_weight = 0.0
        no_weight = 0.0
        total_weight = 0.0

        for pred in predictions:
            weighted_vote = pred.weight * pred.confidence

            if pred.prediction == "YES":
                yes_weight += weighted_vote
            else:
                no_weight += weighted_vote

            total_weight += pred.weight

        # Normalize
        if total_weight > 0:
            yes_pct = yes_weight / total_weight
            no_pct = no_weight / total_weight
        else:
            yes_pct = 0.5
            no_pct = 0.5

        # Determine consensus
        if yes_pct > no_pct:
            consensus = "YES"
            consensus_confidence = yes_pct
        elif no_pct > yes_pct:
            consensus = "NO"
            consensus_confidence = no_pct
        else:
            consensus = "ABSTAIN"
            consensus_confidence = 0.5

        # Calculate agreement ratio
        yes_votes = sum(1 for p in predictions if p.prediction == "YES")
        no_votes = sum(1 for p in predictions if p.prediction == "NO")
        majority = max(yes_votes, no_votes)
        agreement_ratio = majority / len(predictions) if predictions else 0.0

        return SwarmAnalysisResult(
            market_id=market.market_id,
            timestamp=datetime.utcnow(),
            predictions=predictions,
            consensus_prediction=consensus,
            consensus_confidence=consensus_confidence,
            yes_votes=yes_votes,
            no_votes=no_votes,
            agreement_ratio=agreement_ratio,
        )

    def _save_analysis(self, result: SwarmAnalysisResult) -> None:
        """Save analysis result to disk."""
        try:
            save_dir = self.config.data_dir / "predictions"
            save_dir.mkdir(parents=True, exist_ok=True)

            filename = f"swarm_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

            data = {
                "market_id": result.market_id,
                "timestamp": result.timestamp.isoformat(),
                "consensus_prediction": result.consensus_prediction,
                "consensus_confidence": result.consensus_confidence,
                "yes_votes": result.yes_votes,
                "no_votes": result.no_votes,
                "agreement_ratio": result.agreement_ratio,
                "predictions": [
                    {
                        "model": p.model_name,
                        "prediction": p.prediction,
                        "confidence": p.confidence,
                        "reasoning": p.reasoning,
                    }
                    for p in result.predictions
                ],
            }

            with open(save_dir / filename, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            cprint(f"Error saving analysis: {e}", "red")

    def get_analysis_summary(self, result: SwarmAnalysisResult) -> str:
        """Generate human-readable summary of swarm analysis."""
        emoji = (
            "[BULL]"
            if result.consensus_prediction == "YES"
            else "[BEAR]"
            if result.consensus_prediction == "NO"
            else "[NEUTRAL]"
        )

        summary = f"{emoji} Swarm Consensus: {result.consensus_prediction}\n"
        summary += f"   Confidence: {result.consensus_confidence:.1%}\n"
        summary += f"   Agreement: {result.agreement_ratio:.1%} ({result.yes_votes} YES / {result.no_votes} NO)\n"
        summary += f"   Models Queried: {len(result.predictions)}\n\n"

        if result.predictions:
            summary += "   Individual Predictions:\n"
            for pred in sorted(
                result.predictions, key=lambda p: p.confidence, reverse=True
            ):
                pred_emoji = "[OK]" if pred.prediction == "YES" else "[FAIL]"
                summary += f"      {pred_emoji} {pred.model_name}: {pred.prediction} ({pred.confidence:.0%})\n"
                summary += f"         └ {pred.reasoning[:60]}...\n"

        return summary
