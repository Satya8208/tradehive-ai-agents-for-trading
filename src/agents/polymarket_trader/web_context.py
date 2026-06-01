"""
Web Context Enricher for Polymarket CLI Agents

Fetches real-time crypto prices and news context via web search
before swarm analysis. Replaces the _infer_crypto_prices() hack
with actual current data.

Uses OpenAI's gpt-4o-mini-search-preview for web-grounded search.
"""

import os
import json
import time
from typing import Dict, Optional
from termcolor import cprint

from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_KEY", "") or os.getenv("OPENAI_API_KEY", "")
WEB_SEARCH_MODEL = "gpt-4o-mini-search-preview"
WEB_SEARCH_TIMEOUT = 20  # seconds


class WebContextEnricher:
    """
    Fetches real-time crypto context via OpenAI's search-enabled model.

    Returns structured context dict that can be injected into swarm prompts:
    {
        "BTC": {"price": 84500, "trend": "up 2.3% today", "news": "..."},
        "ETH": {"price": 2150, "trend": "flat", "news": "..."},
    }
    """

    def __init__(self):
        self._cache: Dict[str, Dict] = {}
        self._cache_time: float = 0
        self._cache_ttl: float = 120  # 2 minute cache

    def get_context(self, symbols: list) -> Dict[str, Dict]:
        """
        Fetch current prices and news for given crypto symbols.
        Returns cached result if fresh enough.
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        if not OPENAI_API_KEY:
            cprint("Web context: No OpenAI API key, skipping", "yellow")
            return {}

        try:
            context = self._search_crypto_context(symbols)
            self._cache = context
            self._cache_time = now
            return context
        except Exception as e:
            cprint(f"Web context error: {e}", "red")
            return self._cache or {}

    def _search_crypto_context(self, symbols: list) -> Dict[str, Dict]:
        """Query OpenAI search model for current crypto prices and news."""
        import requests

        symbol_str = ", ".join(symbols)
        query = f"""What are the current prices of {symbol_str} cryptocurrencies right now?

For each cryptocurrency, provide:
1. Current price in USD
2. 24h price change percentage
3. Any major news from today affecting the price

Respond with ONLY a JSON object like this:
{{
    "BTC": {{"price": 84500, "change_24h": "+2.3%", "news": "brief news summary"}},
    "ETH": {{"price": 2150, "change_24h": "-0.5%", "news": "brief news summary"}}
}}"""

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": WEB_SEARCH_MODEL,
            "messages": [{"role": "user", "content": query}],
        }

        response = requests.post(url, headers=headers, json=payload,
                                 timeout=WEB_SEARCH_TIMEOUT)

        if response.status_code != 200:
            cprint(f"Web search API error: {response.status_code}", "red")
            return {}

        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return {}

        return self._parse_response(content, symbols)

    def _parse_response(self, content: str, symbols: list) -> Dict[str, Dict]:
        """Parse JSON response from search model."""
        import re

        # Try to extract JSON from response
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    return {}
            else:
                return {}

        context = {}
        for sym in symbols:
            if sym in data and isinstance(data[sym], dict):
                price = data[sym].get("price", 0)
                if isinstance(price, str):
                    price = float(re.sub(r'[,$]', '', price))
                change = data[sym].get("change_24h", "unknown")
                news = data[sym].get("news", "")

                context[sym] = {
                    "price": float(price),
                    "change_24h": str(change),
                    "news": str(news)[:200],
                }
                cprint(f"  {sym}: ${price:,.0f} ({change})", "cyan")

        return context

    def format_for_prompt(self, context: Dict[str, Dict]) -> str:
        """Format context dict as text section for swarm prompt."""
        if not context:
            return ""

        lines = ["\n## Current Crypto Prices (live web data)"]
        for sym, info in context.items():
            price = info.get("price", 0)
            change = info.get("change_24h", "?")
            news = info.get("news", "")
            if price > 0:
                lines.append(f"- {sym}: ${price:,.2f} ({change})")
                if news:
                    lines.append(f"  News: {news}")
        return "\n".join(lines)


if __name__ == "__main__":
    enricher = WebContextEnricher()
    ctx = enricher.get_context(["BTC", "ETH", "SOL"])
    if ctx:
        print(enricher.format_for_prompt(ctx))
    else:
        print("No context fetched (check OPENAI_KEY)")
