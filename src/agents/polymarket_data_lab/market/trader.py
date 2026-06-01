"""
Polymarket Trader

Executes trades on Polymarket via py-clob-client.
Handles order creation, execution, and position management.

Built with love by TradeHive
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any
from decimal import Decimal
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, ExecutionMode
from src.agents.crypto_polymarket.models import (
    TradeDecision,
    TradeExecution,
    CryptoMarket,
    Position,
)
from src.agents.crypto_polymarket.market.position_tracker import PositionTracker


class PolymarketTrader:
    """
    Executes trades on Polymarket.

    Modes:
    - DRY_RUN: Logs trades without execution
    - PAPER: Simulates trades with paper balance
    - LIVE: Executes real trades via py-clob-client

    Uses py-clob-client for order placement:
    - Market orders for immediate execution
    - Limit orders with configurable slippage
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.position_tracker = PositionTracker(config)
        self._clob_client = None
        self._paper_balance = 10000.0  # Paper trading balance
        self._trade_log: list[TradeExecution] = []

        # Initialize CLOB client if in live mode
        if config.execution_mode == ExecutionMode.LIVE:
            self._init_clob_client()

    def _init_clob_client(self) -> None:
        """Initialize the py-clob-client for live trading."""
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            private_key = self.config.polymarket_private_key
            if not private_key:
                cprint(
                    "[WARN]  No POLYMARKET_PRIVATE_KEY set - live trading disabled",
                    "yellow",
                )
                return

            # Initialize client
            self._clob_client = ClobClient(
                host=self.config.polymarket_clob_url,
                key=private_key,
                chain_id=137,  # Polygon mainnet
            )

            # Derive API credentials
            self._clob_client.set_api_creds(self._clob_client.derive_api_key())

            cprint("[OK] Polymarket CLOB client initialized", "green")

        except ImportError:
            cprint(
                "[WARN]  py-clob-client not installed. Run: pip install py-clob-client",
                "yellow",
            )
            self._clob_client = None
        except Exception as e:
            cprint(f"[FAIL] Error initializing CLOB client: {e}", "red")
            self._clob_client = None

    def execute_trade(
        self,
        decision: TradeDecision,
        market: CryptoMarket,
    ) -> Optional[TradeExecution]:
        """
        Execute a trade based on the decision.

        Args:
            decision: Trade decision from decision engine
            market: Market to trade

        Returns:
            TradeExecution if successful, None otherwise
        """
        # Validate decision
        if not decision.should_trade:
            cprint(f"[SKIP]  Trade skipped: {decision.reason}", "yellow")
            return None

        # Check position limits
        can_trade, reason = self.position_tracker.can_open_position(
            market.market_id, decision.size_usd
        )

        if not can_trade:
            cprint(f"[WARN]  Position limit: {reason}", "yellow")
            return None

        # Determine token and price
        if decision.side == "YES":
            token_id = market.yes_token_id
            price = market.yes_price
        else:
            token_id = market.no_token_id
            price = market.no_price

        if not token_id:
            cprint(f"[FAIL] No token ID for {decision.side} side", "red")
            return None

        # Execute based on mode
        if self.config.execution_mode == ExecutionMode.DRY_RUN:
            execution = self._dry_run_trade(decision, market, token_id, price)

        elif self.config.execution_mode == ExecutionMode.PAPER:
            execution = self._paper_trade(decision, market, token_id, price)

        elif self.config.execution_mode == ExecutionMode.LIVE:
            execution = self._live_trade(decision, market, token_id, price)

        else:
            cprint(
                f"[FAIL] Unknown execution mode: {self.config.execution_mode}", "red"
            )
            return None

        # Log and track
        if execution:
            self._trade_log.append(execution)
            self._save_trade_log(execution)

            # Update position tracker
            if execution.status == "filled":
                self.position_tracker.add_position(execution)

        return execution

    def _dry_run_trade(
        self,
        decision: TradeDecision,
        market: CryptoMarket,
        token_id: str,
        price: float,
    ) -> TradeExecution:
        """Simulate trade without execution (logging only)."""
        size = decision.size_usd / price if price > 0 else 0

        execution = TradeExecution(
            trade_id=f"DRY_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            market_id=market.market_id,
            token_id=token_id,
            side=decision.side,
            size=size,
            price=price,
            status="simulated",
            timestamp=datetime.utcnow(),
            order_type="market",
            fees=0.0,
            transaction_hash=None,
        )

        cprint(
            f"🧪 DRY RUN: {decision.side} {size:.2f} @ ${price:.3f} = ${decision.size_usd:.2f}",
            "cyan",
        )
        cprint(f"   Market: {market.question[:60]}...", "cyan")

        return execution

    def _paper_trade(
        self,
        decision: TradeDecision,
        market: CryptoMarket,
        token_id: str,
        price: float,
    ) -> Optional[TradeExecution]:
        """Execute paper trade with simulated balance."""
        # Check paper balance
        if decision.size_usd > self._paper_balance:
            cprint(
                f"[FAIL] Insufficient paper balance: ${self._paper_balance:.2f}", "red"
            )
            return None

        size = decision.size_usd / price if price > 0 else 0

        # Deduct from balance
        self._paper_balance -= decision.size_usd

        execution = TradeExecution(
            trade_id=f"PAPER_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            market_id=market.market_id,
            token_id=token_id,
            side=decision.side,
            size=size,
            price=price,
            status="filled",
            timestamp=datetime.utcnow(),
            order_type="market",
            fees=decision.size_usd * 0.001,  # 0.1% simulated fee
            transaction_hash=None,
        )

        cprint(
            f"📝 PAPER TRADE: {decision.side} {size:.2f} @ ${price:.3f} = ${decision.size_usd:.2f}",
            "yellow",
        )
        cprint(f"   Remaining balance: ${self._paper_balance:.2f}", "yellow")

        return execution

    def _live_trade(
        self,
        decision: TradeDecision,
        market: CryptoMarket,
        token_id: str,
        price: float,
    ) -> Optional[TradeExecution]:
        """Execute live trade via py-clob-client."""
        if not self._clob_client:
            cprint(
                "[FAIL] CLOB client not initialized - cannot execute live trade", "red"
            )
            return None

        try:
            from py_clob_client.order_builder.constants import BUY

            size = decision.size_usd / price if price > 0 else 0

            # Apply slippage tolerance
            limit_price = price * (1 + self.config.max_slippage)

            # Build and submit order
            order = self._clob_client.create_and_post_order(
                token_id=token_id,
                price=limit_price,
                size=size,
                side=BUY,
            )

            if order and order.get("orderID"):
                execution = TradeExecution(
                    trade_id=order["orderID"],
                    market_id=market.market_id,
                    token_id=token_id,
                    side=decision.side,
                    size=size,
                    price=price,
                    status="submitted",
                    timestamp=datetime.utcnow(),
                    order_type="limit",
                    fees=0.0,
                    transaction_hash=order.get("transactionsHashes", [None])[0],
                )

                cprint(
                    f"[START] LIVE TRADE: {decision.side} {size:.2f} @ ${price:.3f}",
                    "green",
                )
                cprint(f"   Order ID: {order['orderID']}", "green")

                return execution

            else:
                cprint(f"[FAIL] Order submission failed: {order}", "red")
                return None

        except Exception as e:
            cprint(f"[FAIL] Live trade error: {e}", "red")
            return None

    def close_position(
        self,
        position: Position,
        market: CryptoMarket,
    ) -> Optional[TradeExecution]:
        """
        Close an existing position.

        Sells the position tokens at market price.
        """
        # Determine opposite side
        if position.side == "YES":
            # Sell YES tokens
            token_id = market.yes_token_id
            current_price = market.yes_price
        else:
            # Sell NO tokens
            token_id = market.no_token_id
            current_price = market.no_price

        if self.config.execution_mode == ExecutionMode.DRY_RUN:
            execution = TradeExecution(
                trade_id=f"CLOSE_DRY_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                market_id=position.market_id,
                token_id=token_id,
                side=f"SELL_{position.side}",
                size=position.size,
                price=current_price,
                status="simulated",
                timestamp=datetime.utcnow(),
                order_type="market",
                fees=0.0,
                transaction_hash=None,
            )
            cprint(
                f"🧪 DRY RUN CLOSE: Sell {position.size:.2f} @ ${current_price:.3f}",
                "cyan",
            )

        elif self.config.execution_mode == ExecutionMode.PAPER:
            # Add back to paper balance
            proceeds = position.size * current_price
            self._paper_balance += proceeds

            execution = TradeExecution(
                trade_id=f"CLOSE_PAPER_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                market_id=position.market_id,
                token_id=token_id,
                side=f"SELL_{position.side}",
                size=position.size,
                price=current_price,
                status="filled",
                timestamp=datetime.utcnow(),
                order_type="market",
                fees=proceeds * 0.001,
                transaction_hash=None,
            )
            cprint(
                f"📝 PAPER CLOSE: Sell {position.size:.2f} @ ${current_price:.3f} = ${proceeds:.2f}",
                "yellow",
            )

        elif self.config.execution_mode == ExecutionMode.LIVE:
            if not self._clob_client:
                cprint("[FAIL] CLOB client not initialized", "red")
                return None

            try:
                from py_clob_client.order_builder.constants import SELL

                order = self._clob_client.create_and_post_order(
                    token_id=token_id,
                    price=current_price * (1 - self.config.max_slippage),
                    size=position.size,
                    side=SELL,
                )

                if order and order.get("orderID"):
                    execution = TradeExecution(
                        trade_id=order["orderID"],
                        market_id=position.market_id,
                        token_id=token_id,
                        side=f"SELL_{position.side}",
                        size=position.size,
                        price=current_price,
                        status="submitted",
                        timestamp=datetime.utcnow(),
                        order_type="limit",
                        fees=0.0,
                        transaction_hash=order.get("transactionsHashes", [None])[0],
                    )
                    cprint(f"[START] LIVE CLOSE: Order ID {order['orderID']}", "green")
                else:
                    cprint(f"[FAIL] Close order failed: {order}", "red")
                    return None

            except Exception as e:
                cprint(f"[FAIL] Close position error: {e}", "red")
                return None

        else:
            return None

        # Remove from position tracker
        self.position_tracker.remove_position(position.market_id)

        # Log trade
        self._trade_log.append(execution)
        self._save_trade_log(execution)

        return execution

    def get_open_orders(self) -> list[Dict]:
        """Get list of open orders from CLOB."""
        if not self._clob_client:
            return []

        try:
            orders = self._clob_client.get_orders()
            return orders if orders else []
        except Exception as e:
            cprint(f"Error fetching orders: {e}", "red")
            return []

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if not self._clob_client:
            cprint("[FAIL] CLOB client not initialized", "red")
            return False

        try:
            result = self._clob_client.cancel(order_id)
            if result:
                cprint(f"[OK] Order {order_id} cancelled", "green")
                return True
            return False
        except Exception as e:
            cprint(f"Error cancelling order: {e}", "red")
            return False

    def _save_trade_log(self, execution: TradeExecution) -> None:
        """Save trade execution to log file."""
        try:
            log_dir = self.config.data_dir / "trades"
            log_dir.mkdir(parents=True, exist_ok=True)

            log_file = log_dir / f"trades_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"

            trade_data = {
                "trade_id": execution.trade_id,
                "market_id": execution.market_id,
                "token_id": execution.token_id,
                "side": execution.side,
                "size": execution.size,
                "price": execution.price,
                "status": execution.status,
                "timestamp": execution.timestamp.isoformat(),
                "order_type": execution.order_type,
                "fees": execution.fees,
                "transaction_hash": execution.transaction_hash,
                "execution_mode": self.config.execution_mode.value,
            }

            with open(log_file, "a") as f:
                f.write(json.dumps(trade_data) + "\n")

        except Exception as e:
            cprint(f"Error saving trade log: {e}", "red")

    def get_trade_history(self, limit: int = 100) -> list[Dict]:
        """Get recent trade history from log files."""
        trades = []
        log_dir = self.config.data_dir / "trades"

        if not log_dir.exists():
            return []

        # Read from most recent log files
        log_files = sorted(log_dir.glob("trades_*.jsonl"), reverse=True)

        for log_file in log_files[:7]:  # Last 7 days
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        if line.strip():
                            trades.append(json.loads(line))
                            if len(trades) >= limit:
                                return trades
            except Exception:
                continue

        return trades

    def get_trading_stats(self) -> Dict[str, Any]:
        """Calculate trading statistics."""
        trades = self.get_trade_history(limit=1000)

        if not trades:
            return {
                "total_trades": 0,
                "total_volume": 0.0,
                "total_fees": 0.0,
            }

        total_volume = sum(t["size"] * t["price"] for t in trades)
        total_fees = sum(t.get("fees", 0) for t in trades)

        return {
            "total_trades": len(trades),
            "total_volume": total_volume,
            "total_fees": total_fees,
            "avg_trade_size": total_volume / len(trades) if trades else 0,
            "execution_mode": self.config.execution_mode.value,
        }

    def get_trader_summary(self) -> str:
        """Generate human-readable trading summary."""
        stats = self.get_trading_stats()
        positions = self.position_tracker.get_positions_summary()

        mode_emoji = {
            ExecutionMode.DRY_RUN: "🧪",
            ExecutionMode.PAPER: "📝",
            ExecutionMode.LIVE: "[START]",
        }

        emoji = mode_emoji.get(self.config.execution_mode, "❓")

        summary = f"{emoji} Trading Mode: {self.config.execution_mode.value.upper()}\n"
        summary += f"   Total Trades: {stats['total_trades']}\n"
        summary += f"   Total Volume: ${stats['total_volume']:,.2f}\n"
        summary += f"   Total Fees: ${stats['total_fees']:,.2f}\n\n"
        summary += positions

        return summary
