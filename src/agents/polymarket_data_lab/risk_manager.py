"""
Basic Risk Manager for Crypto Polymarket Agent

Implements essential risk management for trading safety:
- Position size validation
- Circuit breakers for consecutive losses
- Daily loss limits
- Maximum exposure controls

Built with love by TradeHive
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig
from src.agents.crypto_polymarket.models import TradeExecution, Position


@dataclass
class RiskMetrics:
    """Current risk metrics"""

    total_exposure: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    max_daily_loss: float = 0.0
    position_count: int = 0
    risk_score: float = 0.0  # 0-1 scale


@dataclass
class RiskLimits:
    """Risk limit configuration"""

    max_position_size: float
    max_total_exposure: float
    max_daily_loss: float
    max_consecutive_losses: int
    max_position_percentage: float


class BasicRiskManager:
    """
    Basic risk management for crypto polymarket trading.

    Features:
    - Position size validation against available capital
    - Circuit breaker for consecutive losses
    - Daily loss limits with automatic trading halt
    - Portfolio exposure monitoring
    - Risk score calculation based on multiple factors
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config

        # Risk limits from config
        self.limits = RiskLimits(
            max_position_size=config.max_trade_size_usd,
            max_total_exposure=config.max_total_exposure_usd,
            max_daily_loss=config.daily_loss_limit,
            max_consecutive_losses=5,  # Hard-coded for basic version
            max_position_percentage=config.max_position_percentage,
        )

        # Risk tracking
        self.metrics = RiskMetrics()
        self.daily_trades: List[TradeExecution] = []
        self.positions: Dict[str, Position] = {}

        # Circuit breaker state
        self.circuit_breaker_tripped = False
        self.last_circuit_breaker_reset = datetime.utcnow()

        # Daily reset tracking
        self.current_trading_day = datetime.utcnow().date()

        cprint("[RISK] Basic Risk Manager initialized", "cyan")
        cprint(
            f"[RISK] Max position size: ${self.limits.max_position_size:,.2f}", "white"
        )
        cprint(
            f"[RISK] Max total exposure: ${self.limits.max_total_exposure:,.2f}",
            "white",
        )
        cprint(f"[RISK] Max daily loss: ${self.limits.max_daily_loss:,.2f}", "white")

    def validate_trade(
        self, proposed_size: float, available_balance: float, market_id: str
    ) -> Tuple[bool, str]:
        """
        Validate a proposed trade against risk limits.

        Args:
            proposed_size: Size of the proposed trade in USD
            available_balance: Available trading balance
            market_id: Market identifier

        Returns:
            Tuple of (is_valid, reason_message)
        """
        # Check if circuit breaker is tripped
        if self.circuit_breaker_tripped:
            return False, "Circuit breaker active - trading halted"

        # Check daily reset
        self._check_daily_reset()

        # Validate position size
        if proposed_size > self.limits.max_position_size:
            return (
                False,
                f"Position size ${proposed_size:,.2f} exceeds max ${self.limits.max_position_size:,.2f}",
            )

        # Validate against available balance
        if proposed_size > available_balance * 0.95:  # 5% buffer
            return (
                False,
                f"Position size ${proposed_size:,.2f} exceeds available balance ${available_balance:,.2f}",
            )

        # Check total exposure
        new_total_exposure = self.metrics.total_exposure + proposed_size
        if new_total_exposure > self.limits.max_total_exposure:
            return (
                False,
                f"Total exposure ${new_total_exposure:,.2f} exceeds limit ${self.limits.max_total_exposure:,.2f}",
            )

        # Check daily loss limit
        if self.metrics.daily_pnl < -self.limits.max_daily_loss:
            return (
                False,
                f"Daily loss limit exceeded: ${abs(self.metrics.daily_pnl):,.2f}",
            )

        # Check consecutive losses
        if self.metrics.consecutive_losses >= self.limits.max_consecutive_losses:
            return (
                False,
                f"Max consecutive losses reached: {self.metrics.consecutive_losses}",
            )

        return True, "Trade approved by risk manager"

    def add_trade(self, trade: TradeExecution) -> None:
        """Add executed trade to risk tracking"""
        self.daily_trades.append(trade)

        # Update exposure
        trade_value = trade.size * trade.price
        if trade.side in ["YES", "NO"]:
            self.metrics.total_exposure += trade_value
        else:  # SELL - reducing exposure
            self.metrics.total_exposure = max(
                0, self.metrics.total_exposure - trade_value
            )

        # Update position count
        self.metrics.position_count += 1

        # Calculate P&L impact (simplified for basic version)
        # In a full implementation, this would track actual P&L from position changes
        if trade.fees > 0:
            self.metrics.daily_pnl -= trade.fees

        self._update_risk_score()

        cprint(f"[RISK] Trade added: {trade.side} ${trade_value:,.2f}", "white")
        cprint(f"[RISK] Total exposure: ${self.metrics.total_exposure:,.2f}", "white")

    def update_position_value(self, position: Position, current_price: float) -> float:
        """Update position value and calculate P&L"""
        try:
            # Calculate unrealized P&L
            position_value = position.size * current_price
            cost_basis = position.size * position.entry_price
            unrealized_pnl = position_value - cost_basis

            # Update metrics
            self.metrics.daily_pnl += unrealized_pnl

            # Check for loss streak
            if unrealized_pnl < 0:
                self.metrics.consecutive_losses += 1
            else:
                self.metrics.consecutive_losses = 0  # Reset on profit

            # Check circuit breaker
            self._check_circuit_breaker()

            self._update_risk_score()

            return unrealized_pnl

        except Exception as e:
            cprint(f"[RISK] Error updating position: {e}", "red")
            return 0.0

    def _check_circuit_breaker(self) -> None:
        """Check if circuit breaker should be triggered"""
        # Daily loss limit
        if self.metrics.daily_pnl < -self.limits.max_daily_loss:
            if not self.circuit_breaker_tripped:
                self.circuit_breaker_tripped = True
                cprint(
                    f"[RISK] ⚠️ CIRCUIT BREAKER TRIPPED - Daily loss limit exceeded: ${abs(self.metrics.daily_pnl):,.2f}",
                    "red",
                    attrs=["bold"],
                )

        # Consecutive losses
        if self.metrics.consecutive_losses >= self.limits.max_consecutive_losses:
            if not self.circuit_breaker_tripped:
                self.circuit_breaker_tripped = True
                cprint(
                    f"[RISK] ⚠️ CIRCUIT BREAKER TRIPPED - Max consecutive losses: {self.metrics.consecutive_losses}",
                    "red",
                    attrs=["bold"],
                )

    def _check_daily_reset(self) -> None:
        """Reset daily metrics if it's a new trading day"""
        current_day = datetime.utcnow().date()

        if current_day > self.current_trading_day:
            # New trading day - reset daily metrics
            self.current_trading_day = current_day
            self.metrics.daily_pnl = 0.0
            self.metrics.consecutive_losses = 0
            self.daily_trades.clear()

            # Reset circuit breaker if it's been more than 24 hours
            if self.circuit_breaker_tripped:
                time_since_breaker = datetime.utcnow() - self.last_circuit_breaker_reset
                if time_since_breaker > timedelta(hours=24):
                    self.circuit_breaker_tripped = False
                    self.last_circuit_breaker_reset = datetime.utcnow()
                    cprint("[RISK] Circuit breaker reset for new trading day", "green")

            cprint(f"[RISK] Daily metrics reset for {current_day}", "green")

    def _update_risk_score(self) -> None:
        """Calculate overall risk score (0-1)"""
        # Factors contributing to risk score
        exposure_ratio = min(
            1.0, self.metrics.total_exposure / self.limits.max_total_exposure
        )
        daily_loss_ratio = min(
            1.0, abs(self.metrics.daily_pnl) / self.limits.max_daily_loss
        )
        consecutive_loss_ratio = min(
            1.0, self.metrics.consecutive_losses / self.limits.max_consecutive_losses
        )

        # Weighted risk score
        self.metrics.risk_score = (
            exposure_ratio * 0.4 + daily_loss_ratio * 0.3 + consecutive_loss_ratio * 0.3
        )

    def get_risk_status(self) -> Dict[str, Any]:
        """Get current risk status summary"""
        return {
            "total_exposure": self.metrics.total_exposure,
            "daily_pnl": self.metrics.daily_pnl,
            "consecutive_losses": self.metrics.consecutive_losses,
            "risk_score": self.metrics.risk_score,
            "circuit_breaker_active": self.circuit_breaker_tripped,
            "daily_trades": len(self.daily_trades),
            "risk_limits": {
                "max_exposure": self.limits.max_total_exposure,
                "max_daily_loss": self.limits.max_daily_loss,
                "max_consecutive_losses": self.limits.max_consecutive_losses,
            },
        }

    def get_risk_summary(self) -> str:
        """Get human-readable risk summary"""
        status = self.get_risk_status()

        # Risk level color coding
        if status["risk_score"] > 0.8:
            risk_level = "HIGH RISK"
        elif status["risk_score"] > 0.5:
            risk_level = "MEDIUM RISK"
        else:
            risk_level = "LOW RISK"

        summary = f"""
[RISK] Risk Management Summary
{"=" * 40}
Overall Risk: {risk_level} ({status["risk_score"]:.1%})
Circuit Breaker: {"ACTIVE" if status["circuit_breaker_active"] else "INACTIVE"}

Exposure:
  Total: ${status["total_exposure"]:,.2f}
  Limit: ${status["risk_limits"]["max_exposure"]:,.2f}
  Utilization: {status["total_exposure"] / status["risk_limits"]["max_exposure"]:.1%}

Daily Performance:
  P&L: ${status["daily_pnl"]:+,.2f}
  Limit: ${status["risk_limits"]["max_daily_loss"]:,.2f}
  Trades: {status["daily_trades"]}

Consecutive Losses: {status["consecutive_losses"]}/{status["risk_limits"]["max_consecutive_losses"]}
{"=" * 40}
"""
        return summary

    def can_open_position(
        self, market_id: str, proposed_size: float
    ) -> Tuple[bool, str]:
        """
        Check if a new position can be opened.

        This is a simplified version - full implementation would track
        individual positions and their risk contributions.
        """
        # Use the main validation logic
        available_balance = self.limits.max_total_exposure - self.metrics.total_exposure

        return self.validate_trade(
            proposed_size=proposed_size,
            available_balance=available_balance,
            market_id=market_id,
        )

    def reset_circuit_breaker(self) -> bool:
        """Manually reset the circuit breaker (use with caution)"""
        if self.circuit_breaker_tripped:
            self.circuit_breaker_tripped = False
            self.last_circuit_breaker_reset = datetime.utcnow()
            cprint("[RISK] Circuit breaker manually reset", "yellow")
            return True
        return False
