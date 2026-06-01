"""
API Clients for Crypto Polymarket Agent

Wrappers for TradeHive API and Polymarket APIs.
Built with love by TradeHive
"""

import os
import sys
import time
import requests
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from termcolor import cprint

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig


class TradeHiveAPIClient:
    """
    Client for TradeHive API endpoints.

    Provides access to:
    - Liquidation data
    - Funding rates
    - Open interest (OI) data
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.base_url = config.tradehive_api_url
        self.api_key = config.tradehive_api_key
        self.headers = {"X-API-Key": self.api_key} if self.api_key else {}
        self.session = requests.Session()
        self.max_retries = 3

    def get_liquidation_data(self, symbol: Optional[str] = None, limit: Optional[int] = None) -> pd.DataFrame:
        """
        Fetch liquidation data from TradeHive API.

        Args:
            symbol: Filter by symbol (BTC, ETH)
            limit: Maximum records to return

        Returns:
            DataFrame with liquidation data
        """
        try:
            url = f"{self.base_url}/files/liq_data.csv"
            if limit:
                url += f"?limit={limit}"

            response = self._make_request(url)
            if response is None:
                return pd.DataFrame()

            # Parse CSV from response
            df = pd.read_csv(pd.io.common.StringIO(response.text))

            # Filter by symbol if specified
            if symbol and 'symbol' in df.columns:
                df = df[df['symbol'].str.contains(symbol, case=False, na=False)]

            return df

        except Exception as e:
            cprint(f"Error fetching liquidation data: {e}", "red")
            return pd.DataFrame()

    def get_funding_data(self) -> pd.DataFrame:
        """
        Fetch current funding rate data.

        Returns:
            DataFrame with funding rates per symbol
        """
        try:
            url = f"{self.base_url}/files/funding.csv"
            response = self._make_request(url)
            if response is None:
                return pd.DataFrame()

            df = pd.read_csv(pd.io.common.StringIO(response.text))
            return df

        except Exception as e:
            cprint(f"Error fetching funding data: {e}", "red")
            return pd.DataFrame()

    def get_oi_data(self, symbol: str = "BTC") -> pd.DataFrame:
        """
        Fetch open interest data.

        Args:
            symbol: Symbol to fetch (BTC or ETH)

        Returns:
            DataFrame with OI data
        """
        try:
            url = f"{self.base_url}/files/oi_data.csv"
            response = self._make_request(url)
            if response is None:
                return pd.DataFrame()

            df = pd.read_csv(pd.io.common.StringIO(response.text))

            # Filter by symbol
            if 'symbol' in df.columns:
                df = df[df['symbol'].str.contains(symbol, case=False, na=False)]

            return df

        except Exception as e:
            cprint(f"Error fetching OI data: {e}", "red")
            return pd.DataFrame()

    def _make_request(self, url: str, method: str = "GET", **kwargs) -> Optional[requests.Response]:
        """
        Make HTTP request with retry logic.

        Args:
            url: Request URL
            method: HTTP method
            **kwargs: Additional request arguments

        Returns:
            Response object or None on failure
        """
        retry_delay = 1

        for attempt in range(self.max_retries):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=self.headers,
                    timeout=30,
                    **kwargs
                )
                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    cprint(f"Request failed after {self.max_retries} attempts: {e}", "red")
                    return None

        return None


class PolymarketAPIClient:
    """
    Client for Polymarket APIs.

    Provides access to:
    - Gamma API: Market metadata
    - CLOB API: Prices and order book
    - Data API: Historical trades
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.gamma_url = config.polymarket_gamma_url
        self.clob_url = config.polymarket_clob_url
        self.data_api_url = config.polymarket_data_api_url
        self.session = requests.Session()
        self.max_retries = 3

    def get_markets(self, limit: int = 100, active: bool = True) -> List[Dict]:
        """
        Fetch all markets from Gamma API.

        Args:
            limit: Maximum markets to return
            active: Only return active markets

        Returns:
            List of market dictionaries
        """
        try:
            url = f"{self.gamma_url}/markets"
            params = {
                "limit": limit,
                "active": str(active).lower(),
            }

            response = self._make_request(url, params=params)
            if response is None:
                return []

            data = response.json()
            return data if isinstance(data, list) else data.get("markets", [])

        except Exception as e:
            cprint(f"Error fetching markets: {e}", "red")
            return []

    def get_market(self, condition_id: str) -> Optional[Dict]:
        """
        Fetch a single market by condition ID.

        Args:
            condition_id: Market condition ID

        Returns:
            Market dictionary or None
        """
        try:
            url = f"{self.gamma_url}/markets/{condition_id}"
            response = self._make_request(url)
            if response is None:
                return None

            return response.json()

        except Exception as e:
            cprint(f"Error fetching market {condition_id}: {e}", "red")
            return None

    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """
        Get current price for a token.

        Args:
            token_id: Token ID (YES or NO token)
            side: BUY or SELL

        Returns:
            Current price or None
        """
        try:
            url = f"{self.clob_url}/price"
            params = {
                "token_id": token_id,
                "side": side,
            }

            response = self._make_request(url, params=params)
            if response is None:
                return None

            data = response.json()
            return float(data.get("price", 0))

        except Exception as e:
            cprint(f"Error fetching price for {token_id}: {e}", "red")
            return None

    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Get order book for a token.

        Args:
            token_id: Token ID

        Returns:
            Order book dictionary with bids and asks
        """
        try:
            url = f"{self.clob_url}/book"
            params = {"token_id": token_id}

            response = self._make_request(url, params=params)
            if response is None:
                return None

            return response.json()

        except Exception as e:
            cprint(f"Error fetching orderbook for {token_id}: {e}", "red")
            return None

    def get_trades(self, market_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """
        Fetch recent trades.

        Args:
            market_id: Filter by market ID
            limit: Maximum trades to return

        Returns:
            List of trade dictionaries
        """
        try:
            url = f"{self.data_api_url}/trades"
            params = {"limit": limit}
            if market_id:
                params["market"] = market_id

            response = self._make_request(url, params=params)
            if response is None:
                return []

            return response.json()

        except Exception as e:
            cprint(f"Error fetching trades: {e}", "red")
            return []

    def search_markets(self, query: str, limit: int = 50) -> List[Dict]:
        """
        Search markets by keyword.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching markets
        """
        try:
            url = f"{self.gamma_url}/markets"
            params = {
                "q": query,
                "limit": limit,
                "active": "true",
            }

            response = self._make_request(url, params=params)
            if response is None:
                return []

            data = response.json()
            return data if isinstance(data, list) else data.get("markets", [])

        except Exception as e:
            cprint(f"Error searching markets: {e}", "red")
            return []

    def _make_request(self, url: str, method: str = "GET", **kwargs) -> Optional[requests.Response]:
        """
        Make HTTP request with retry logic.
        """
        retry_delay = 1

        for attempt in range(self.max_retries):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=30,
                    **kwargs
                )
                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    cprint(f"Request failed after {self.max_retries} attempts: {e}", "red")
                    return None

        return None


class HyperliquidAPIClient:
    """
    Client for Hyperliquid API.

    Used for volume data collection.
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.api_url = config.hyperliquid_api_url
        self.session = requests.Session()

    def get_meta_and_asset_contexts(self) -> Optional[Dict]:
        """
        Fetch metadata and asset contexts.

        Returns:
            Dictionary with universe and context data
        """
        try:
            payload = {"type": "metaAndAssetCtxs"}
            response = self.session.post(self.api_url, json=payload, timeout=15)
            response.raise_for_status()
            return response.json()

        except Exception as e:
            cprint(f"Error fetching Hyperliquid data: {e}", "red")
            return None

    def get_all_tokens_volume(self) -> List[Dict]:
        """
        Fetch volume data for all tokens.

        Returns:
            List of token dictionaries with volume info
        """
        data = self.get_meta_and_asset_contexts()
        if data is None:
            return []

        tokens = []
        universe = data[0].get('universe', [])
        contexts = data[1]

        for i, token_info in enumerate(universe):
            symbol = token_info.get('name', 'UNKNOWN')

            if i < len(contexts):
                ctx = contexts[i]
                tokens.append({
                    'symbol': symbol,
                    'volume_24h': float(ctx.get('dayNtlVlm', 0)),
                    'price': float(ctx.get('markPx', 0)),
                    'funding_rate': float(ctx.get('funding', 0)),
                    'open_interest': float(ctx.get('openInterest', 0)),
                })

        return tokens
