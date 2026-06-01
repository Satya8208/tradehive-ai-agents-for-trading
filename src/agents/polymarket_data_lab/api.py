"""
Crypto Polymarket Trading Dashboard API

FastAPI backend serving the trading dashboard with real-time data
from the V2.1 agent system (5 core agents + whale).

Endpoints:
- GET /              - Serve dashboard HTML
- GET /api/status    - Agent status, mode, cycle count
- GET /api/signals   - Current signals from all data agents
- GET /api/regime    - Current market regime
- GET /api/markets   - Available Polymarket crypto markets
- GET /api/analysis/{market_id} - Edge + swarm analysis
- GET /api/positions - Current open positions
- POST /api/trade    - Execute a manual trade
- POST /api/cycle    - Trigger analysis cycle
- POST /api/mode     - Change execution mode

Built with love by TradeHive
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.crypto_polymarket.config import (
    CryptoPolymarketConfig,
    ExecutionMode,
    SignalDirection,
)
from src.agents.crypto_polymarket.models import MarketSignal, AggregatedSignal
from src.agents.crypto_polymarket.regime_detection import RegimeDetectionEngine, MarketRegime
from src.agents.crypto_polymarket.edge_calculator import EdgeCalculator
from src.agents.crypto_polymarket.analysis.signal_aggregator import SignalAggregator
from src.agents.crypto_polymarket.market.scanner import CryptoMarketScanner
from src.agents.crypto_polymarket.market.position_tracker import PositionTracker

# Data pipeline and agents
from src.data.connectors.unified_pipeline import UnifiedDataPipeline
from src.agents.crypto_polymarket.data_agents.liquidation_agent import LiquidationAgent
from src.agents.crypto_polymarket.data_agents.funding_agent import FundingAgent
from src.agents.crypto_polymarket.data_agents.open_interest_agent import OpenInterestAgent
from src.agents.crypto_polymarket.data_agents.volume_agent import VolumeAgent
from src.agents.crypto_polymarket.data_agents.orderbook_agent import OrderBookImbalanceAgent
from src.agents.crypto_polymarket.data_agents.whale_agent import WhaleAgent


# ============================================================================
# GLOBAL STATE
# ============================================================================

class DashboardState:
    """Global state for the dashboard API."""

    def __init__(self):
        self.config = CryptoPolymarketConfig()
        self.pipeline: Optional[UnifiedDataPipeline] = None
        self.pipeline_started = False

        # Data agents (v2.1: 5 core agents + whale)
        self.liquidation_agent: Optional[LiquidationAgent] = None
        self.funding_agent: Optional[FundingAgent] = None
        self.oi_agent: Optional[OpenInterestAgent] = None
        self.volume_agent: Optional[VolumeAgent] = None
        self.orderbook_agent: Optional[OrderBookImbalanceAgent] = None
        self.whale_agent: Optional[WhaleAgent] = None

        # Analysis components
        self.regime_engine: Optional[RegimeDetectionEngine] = None
        self.edge_calculator: Optional[EdgeCalculator] = None
        self.signal_aggregator: Optional[SignalAggregator] = None
        self.market_scanner: Optional[CryptoMarketScanner] = None
        self.position_tracker: Optional[PositionTracker] = None

        # Cycle state
        self.cycle_count = 0
        self.last_update = None
        self.last_signals: Dict[str, Any] = {}
        self.last_regime: Dict[str, Any] = {}
        self.last_aggregated: Optional[AggregatedSignal] = None
        self.is_running = False

    async def initialize(self):
        """Initialize all components."""
        print("[INIT] Initializing dashboard components...")

        # Initialize pipeline
        self.pipeline = UnifiedDataPipeline()

        # Initialize data agents (v2.1: 5 core agents + whale)
        self.liquidation_agent = LiquidationAgent(self.config, pipeline=self.pipeline)
        self.funding_agent = FundingAgent(self.config, pipeline=self.pipeline)
        self.oi_agent = OpenInterestAgent(self.config, pipeline=self.pipeline)
        self.volume_agent = VolumeAgent(self.config, pipeline=self.pipeline)
        self.orderbook_agent = OrderBookImbalanceAgent(self.config, pipeline=self.pipeline)
        self.whale_agent = WhaleAgent(self.config, pipeline=self.pipeline)

        # Initialize analysis components
        self.regime_engine = RegimeDetectionEngine(self.config, self.pipeline)
        self.edge_calculator = EdgeCalculator(self.config)
        self.signal_aggregator = SignalAggregator(self.config)
        self.market_scanner = CryptoMarketScanner(self.config)
        self.position_tracker = PositionTracker(self.config)

        print("[OK] Dashboard components initialized")

    async def start_pipeline(self):
        """Start the data pipeline."""
        if self.pipeline_started:
            return

        print("[PIPELINE] Starting real-time data pipeline...")
        await self.pipeline.start()
        self.pipeline_started = True
        print("[OK] Pipeline started - receiving data from exchanges")

    async def stop_pipeline(self):
        """Stop the data pipeline."""
        if not self.pipeline_started:
            return

        print("[PIPELINE] Stopping data pipeline...")
        await self.pipeline.stop()
        self.pipeline_started = False
        print("[OK] Pipeline stopped")

    def set_mode(self, mode: str):
        """Change execution mode."""
        self.config.execution_mode = ExecutionMode(mode)
        print(f"[MODE] Switched to {mode.upper()}")


# Global state instance
state = DashboardState()


# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifespan - startup and shutdown."""
    # Startup
    await state.initialize()
    await state.start_pipeline()

    # Let pipeline collect initial data
    await asyncio.sleep(3)

    yield

    # Shutdown
    await state.stop_pipeline()


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Crypto Polymarket Dashboard",
    description="Trading dashboard for Crypto Polymarket Agent V2.1 (5 core agents + whale)",
    version="2.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class TradeRequest(BaseModel):
    market_id: str
    side: str  # "YES" or "NO"
    size_usd: float


class ModeRequest(BaseModel):
    mode: str  # "dry_run", "paper", "live"


class SignalData(BaseModel):
    agent: str
    direction: str
    strength: float
    confidence: float
    reasoning: str


class StatusResponse(BaseModel):
    mode: str
    cycle_count: int
    is_running: bool
    pipeline_connected: bool
    last_update: Optional[str]


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the dashboard HTML."""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        return HTMLResponse(content=content, status_code=200)
    return HTMLResponse(
        content="<h1>Dashboard not found. Run frontend-design skill to create index.html</h1>",
        status_code=404
    )


@app.get("/api/status")
async def get_status() -> Dict[str, Any]:
    """Get current agent status."""
    return {
        "mode": state.config.execution_mode.value,
        "cycle_count": state.cycle_count,
        "is_running": state.is_running,
        "pipeline_connected": state.pipeline_started,
        "last_update": state.last_update.isoformat() if state.last_update else None,
        "config": {
            "min_edge_threshold": state.config.min_edge_threshold,
            "kelly_fraction": state.config.kelly_fraction,
            "max_trade_size_usd": state.config.max_trade_size_usd,
            "max_total_exposure_usd": state.config.max_total_exposure_usd,
        }
    }


@app.get("/api/signals")
async def get_signals() -> Dict[str, Any]:
    """Get current signals from all data agents."""
    signals = {}

    try:
        # Collect signals from all agents in parallel (v2.1: 6 agents)
        tasks = {
            "liquidation": state.liquidation_agent.get_signal() if state.liquidation_agent else None,
            "funding": state.funding_agent.get_signal() if state.funding_agent else None,
            "open_interest": state.oi_agent.get_signal() if state.oi_agent else None,
            "volume": state.volume_agent.get_signal() if state.volume_agent else None,
            "orderbook": state.orderbook_agent.get_signal() if state.orderbook_agent else None,
            "whale": state.whale_agent.get_signal() if state.whale_agent else None,
        }

        # Filter out None tasks
        active_tasks = {k: v for k, v in tasks.items() if v is not None}

        if active_tasks:
            results = await asyncio.gather(*active_tasks.values(), return_exceptions=True)

            for agent_name, result in zip(active_tasks.keys(), results):
                if isinstance(result, Exception):
                    signals[agent_name] = {
                        "agent": agent_name,
                        "direction": "error",
                        "strength": 0,
                        "confidence": 0,
                        "reasoning": str(result)
                    }
                elif isinstance(result, MarketSignal):
                    signals[agent_name] = {
                        "agent": agent_name,
                        "direction": result.direction.value,
                        "strength": result.strength,
                        "confidence": result.confidence,
                        "reasoning": result.reasoning,
                        "symbol": result.symbol,
                        "timestamp": result.timestamp.isoformat()
                    }

        # Aggregate signals
        if signals:
            signal_objects = {k: v for k, v in zip(active_tasks.keys(), results)
                             if isinstance(v, MarketSignal)}

            if signal_objects and state.signal_aggregator:
                aggregated = state.signal_aggregator.aggregate(signal_objects)
                state.last_aggregated = aggregated

                return {
                    "signals": signals,
                    "aggregated": {
                        "direction": aggregated.direction.value,
                        "composite_score": aggregated.composite_score,
                        "confidence": aggregated.confidence,
                        "dominant_signal": aggregated.dominant_signal,
                        "signal_breakdown": aggregated.signal_breakdown,
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }

        return {
            "signals": signals,
            "aggregated": None,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/regime")
async def get_regime() -> Dict[str, Any]:
    """Get current market regime."""
    try:
        if not state.regime_engine:
            return {"regime": "unknown", "confidence": 0, "reasoning": "Regime engine not initialized"}

        regime_data = await state.regime_engine.detect_regime("BTC")

        # Get weight adjustments for this regime
        weight_adjustments = state.regime_engine.get_signal_weight_adjustments(regime_data)
        position_multiplier = state.regime_engine.get_recommended_position_multiplier(regime_data)

        return {
            "regime": regime_data["regime"],
            "confidence": regime_data["confidence"],
            "reasoning": regime_data.get("reasoning", ""),
            "indicators": regime_data.get("indicators", {}),
            "weight_adjustments": weight_adjustments,
            "position_multiplier": position_multiplier,
            "since": regime_data.get("since").isoformat() if regime_data.get("since") else None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets")
async def get_markets() -> Dict[str, Any]:
    """Get available crypto markets from Polymarket."""
    try:
        if not state.market_scanner:
            return {"markets": [], "error": "Market scanner not initialized"}

        markets = state.market_scanner.scan_markets()

        # Rank by signal alignment if we have aggregated signal
        if state.last_aggregated and markets:
            ranked = state.market_scanner.rank_markets_by_signal(markets, state.last_aggregated)
            market_list = [
                {
                    "market_id": m.market_id,
                    "question": m.question,
                    "symbol": m.symbol,
                    "yes_price": m.yes_price,
                    "no_price": m.no_price,
                    "liquidity": m.liquidity,
                    "volume_24h": m.volume_24h,
                    "time_remaining_hours": m.time_remaining_hours,
                    "market_type": m.market_type,
                    "alignment_score": score
                }
                for m, score in ranked[:10]  # Top 10 markets
            ]
        else:
            market_list = [
                {
                    "market_id": m.market_id,
                    "question": m.question,
                    "symbol": m.symbol,
                    "yes_price": m.yes_price,
                    "no_price": m.no_price,
                    "liquidity": m.liquidity,
                    "volume_24h": m.volume_24h,
                    "time_remaining_hours": m.time_remaining_hours,
                    "market_type": m.market_type,
                    "alignment_score": 0
                }
                for m in markets[:10]
            ]

        return {
            "markets": market_list,
            "count": len(market_list),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/{market_id}")
async def get_analysis(market_id: str) -> Dict[str, Any]:
    """Get edge calculation and analysis for a specific market."""
    try:
        if not state.market_scanner:
            raise HTTPException(status_code=500, detail="Market scanner not initialized")

        # Find the market
        markets = state.market_scanner.scan_markets()
        market = next((m for m in markets if m.market_id == market_id), None)

        if not market:
            raise HTTPException(status_code=404, detail=f"Market {market_id} not found")

        # Get aggregated signal
        if not state.last_aggregated:
            # Run signals first
            await get_signals()

        if not state.last_aggregated:
            return {
                "market_id": market_id,
                "error": "No signal data available",
                "edge": None,
                "kelly": None
            }

        # Calculate edge
        composite_score = state.last_aggregated.composite_score

        # Convert composite score to probability estimate
        signal_probability = 0.5 + (composite_score * 0.25)
        signal_probability = max(0.3, min(0.7, signal_probability))

        edge_data = state.edge_calculator.calculate_edge(
            signal_probability=signal_probability,
            market_price=market.yes_price,
            confidence_interval=0.10,
            hours_until_resolution=market.time_remaining_hours
        )

        # Calculate Kelly sizing
        kelly_data = state.edge_calculator.calculate_kelly_fraction(
            edge_data=edge_data,
            risk_factor=state.config.kelly_fraction,
            confidence_penalty=True
        )

        return {
            "market_id": market_id,
            "market": {
                "question": market.question,
                "yes_price": market.yes_price,
                "no_price": market.no_price,
                "liquidity": market.liquidity,
                "time_remaining_hours": market.time_remaining_hours
            },
            "signal": {
                "composite_score": composite_score,
                "direction": state.last_aggregated.direction.value,
                "confidence": state.last_aggregated.confidence,
                "signal_probability": signal_probability
            },
            "edge": {
                "edge_percent": edge_data["edge_percent"],
                "edge_confidence": edge_data["edge_confidence"],
                "expected_value": edge_data["expected_value"],
                "time_decay": edge_data["time_decay"],
                "meets_threshold": edge_data["edge_percent"] >= state.config.min_edge_threshold
            },
            "kelly": {
                "kelly_fraction": kelly_data["kelly_fraction"],
                "fractional_kelly": kelly_data["fractional_kelly"],
                "recommended_size_usd": kelly_data["bet_size_usd"],
                "risk_level": kelly_data["risk_level"]
            },
            "recommendation": {
                "side": "YES" if composite_score > 0 else "NO",
                "size_usd": kelly_data["bet_size_usd"],
                "should_trade": edge_data["edge_percent"] >= state.config.min_edge_threshold
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/positions")
async def get_positions() -> Dict[str, Any]:
    """Get current open positions."""
    try:
        if not state.position_tracker:
            return {"positions": [], "summary": {}}

        positions = state.position_tracker.get_all_positions()
        risk_status = state.position_tracker.get_risk_status()

        return {
            "positions": [p.to_dict() for p in positions],
            "summary": {
                "total_positions": len(positions),
                "total_exposure": risk_status["total_exposure"],
                "max_exposure": state.config.max_total_exposure_usd,
                "exposure_utilization": risk_status["exposure_utilization"],
                "unrealized_pnl": risk_status["unrealized_pnl"],
            },
            "risk_status": risk_status
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trade")
async def execute_trade(request: TradeRequest) -> Dict[str, Any]:
    """Execute a manual trade."""
    try:
        # Validate mode
        if state.config.execution_mode == ExecutionMode.DRY_RUN:
            return {
                "success": False,
                "message": "Trading disabled in DRY_RUN mode. Switch to PAPER or LIVE mode.",
                "mode": state.config.execution_mode.value
            }

        # Find market
        markets = state.market_scanner.scan_markets()
        market = next((m for m in markets if m.market_id == request.market_id), None)

        if not market:
            raise HTTPException(status_code=404, detail=f"Market {request.market_id} not found")

        # Validate side
        if request.side not in ["YES", "NO"]:
            raise HTTPException(status_code=400, detail="Side must be 'YES' or 'NO'")

        # Validate size
        if request.size_usd < state.config.min_trade_size_usd:
            raise HTTPException(
                status_code=400,
                detail=f"Size must be at least ${state.config.min_trade_size_usd}"
            )

        if request.size_usd > state.config.max_trade_size_usd:
            raise HTTPException(
                status_code=400,
                detail=f"Size cannot exceed ${state.config.max_trade_size_usd}"
            )

        # Check exposure limits
        current_exposure = state.position_tracker.get_total_exposure()
        if current_exposure + request.size_usd > state.config.max_total_exposure_usd:
            raise HTTPException(
                status_code=400,
                detail=f"Trade would exceed max exposure of ${state.config.max_total_exposure_usd}"
            )

        # Execute trade based on mode
        if state.config.execution_mode == ExecutionMode.PAPER:
            # Paper trading - simulate the trade
            result = {
                "success": True,
                "mode": "paper",
                "order_id": f"PAPER_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                "market_id": request.market_id,
                "side": request.side,
                "size_usd": request.size_usd,
                "price": market.yes_price if request.side == "YES" else market.no_price,
                "message": "Paper trade executed successfully"
            }

        elif state.config.execution_mode == ExecutionMode.LIVE:
            # Live trading - would execute real trade via Polymarket API
            # For now, return placeholder
            result = {
                "success": False,
                "mode": "live",
                "message": "Live trading not yet implemented. Use PAPER mode for testing."
            }

        else:
            result = {
                "success": False,
                "message": f"Unknown mode: {state.config.execution_mode.value}"
            }

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cycle")
async def run_cycle() -> Dict[str, Any]:
    """Trigger a manual analysis cycle."""
    try:
        state.is_running = True
        state.cycle_count += 1
        cycle_start = datetime.utcnow()

        # Get signals
        signals_result = await get_signals()

        # Get regime
        regime_result = await get_regime()

        # Get markets
        markets_result = await get_markets()

        state.last_update = datetime.utcnow()
        state.is_running = False

        return {
            "cycle_number": state.cycle_count,
            "started_at": cycle_start.isoformat(),
            "completed_at": state.last_update.isoformat(),
            "duration_seconds": (state.last_update - cycle_start).total_seconds(),
            "signals": signals_result,
            "regime": regime_result,
            "markets_found": markets_result["count"],
            "status": "completed"
        }

    except Exception as e:
        state.is_running = False
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mode")
async def set_mode(request: ModeRequest) -> Dict[str, Any]:
    """Change execution mode."""
    try:
        valid_modes = ["dry_run", "paper", "live"]
        if request.mode not in valid_modes:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid mode. Must be one of: {valid_modes}"
            )

        old_mode = state.config.execution_mode.value
        state.set_mode(request.mode)

        return {
            "success": True,
            "old_mode": old_mode,
            "new_mode": request.mode,
            "message": f"Mode changed from {old_mode} to {request.mode}"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent": "crypto_polymarket",
        "version": "2.1.0",
        "agents": 6,  # 5 core + whale
        "pipeline": "connected" if state.pipeline_started else "disconnected"
    }


@app.get("/api/debug")
async def debug_info() -> Dict[str, Any]:
    """Debug endpoint - shows raw pipeline data for the Raw Data Panel."""
    from datetime import datetime, timedelta

    VOLUME_THRESHOLD = 25000  # Match liquidation_agent threshold

    debug_data = {
        "pipeline_started": state.pipeline_started,
        "timestamp": datetime.utcnow().isoformat(),
        "agents_initialized": {
            "liquidation": state.liquidation_agent is not None,
            "funding": state.funding_agent is not None,
            "open_interest": state.oi_agent is not None,
            "volume": state.volume_agent is not None,
            "orderbook": state.orderbook_agent is not None,
            "whale": state.whale_agent is not None,
        },
        "data_flow": {
            "liquidations_5m": {
                "count": 0,
                "long_volume": 0,
                "short_volume": 0,
                "total_volume": 0,
                "threshold": VOLUME_THRESHOLD,
                "threshold_percent": 0,
                "threshold_met": False,
                "last_received": None,
                "seconds_since_last": None,
            },
            "trades_5m": {
                "count": 0,
                "last_received": None,
            },
            "order_book": {
                "updates_1m": 0,
                "last_received": None,
                "btc_imbalance": 0,
                "eth_imbalance": 0,
            },
        },
        "exchange_status": {
            "binance": False,
            "bybit": False,
            "hyperliquid": False,
        },
    }

    if state.pipeline:
        try:
            now = datetime.utcnow()

            # Get liquidation data
            volume = state.pipeline.get_liquidation_volume(seconds=300)
            count = state.pipeline.get_liquidation_count(seconds=300)
            total_vol = volume.get("total", 0)

            # Get recent liquidations to find last received time
            recent_liqs = state.pipeline.get_recent_liquidations(seconds=300)
            last_liq_time = None
            if recent_liqs:
                last_liq_time = max(liq.timestamp for liq in recent_liqs)

            debug_data["data_flow"]["liquidations_5m"] = {
                "count": count.get("total", 0),
                "long_count": count.get("long", 0),
                "short_count": count.get("short", 0),
                "long_volume": volume.get("long", 0),
                "short_volume": volume.get("short", 0),
                "total_volume": total_vol,
                "threshold": VOLUME_THRESHOLD,
                "threshold_percent": min(100, (total_vol / VOLUME_THRESHOLD) * 100) if VOLUME_THRESHOLD > 0 else 0,
                "threshold_met": total_vol >= VOLUME_THRESHOLD,
                "last_received": last_liq_time.isoformat() if last_liq_time else None,
                "seconds_since_last": (now - last_liq_time).total_seconds() if last_liq_time else None,
            }

            # Get trade data
            if hasattr(state.pipeline, '_buffers'):
                from src.data.connectors.unified_pipeline import DataType
                trade_buffer = state.pipeline._buffers.get(DataType.TRADE)
                if trade_buffer and trade_buffer.items:
                    trade_count = len(trade_buffer.items)
                    last_trade = trade_buffer.items[-1] if trade_buffer.items else None
                    debug_data["data_flow"]["trades_5m"] = {
                        "count": trade_count,
                        "last_received": last_trade.timestamp.isoformat() if last_trade and hasattr(last_trade, 'timestamp') else None,
                    }

                # Order book data
                ob_buffer = state.pipeline._buffers.get(DataType.ORDER_BOOK)
                if ob_buffer and ob_buffer.items:
                    # Get order book imbalance for BTC and ETH
                    btc_imbalance = state.pipeline.get_order_book_imbalance("BTC", levels=10)
                    eth_imbalance = state.pipeline.get_order_book_imbalance("ETH", levels=10)

                    debug_data["data_flow"]["order_book"] = {
                        "updates_1m": len(ob_buffer.items),
                        "last_received": ob_buffer.items[-1].timestamp.isoformat() if ob_buffer.items and hasattr(ob_buffer.items[-1], 'timestamp') else None,
                        "btc_imbalance": btc_imbalance,
                        "eth_imbalance": eth_imbalance,
                    }

            # Exchange connection status
            if hasattr(state.pipeline, '_connectors'):
                for name, connector in state.pipeline._connectors.items():
                    if hasattr(connector, 'connected'):
                        debug_data["exchange_status"][name] = connector.connected

        except Exception as e:
            debug_data["error"] = str(e)

    return debug_data


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  CRYPTO POLYMARKET TRADING DASHBOARD")
    print("  Built with love by TradeHive")
    print("=" * 60)
    print("\n  Open http://localhost:8051 in your browser\n")
    print("=" * 60 + "\n")

    # Use full module path for reload to work from project root
    # Set reload=False if you experience issues on Windows
    uvicorn.run(
        "src.agents.crypto_polymarket.api:app",
        host="0.0.0.0",
        port=8051,
        reload=False,  # Disabled for stability - set True for development
    )
