"""
Scalping Agent Dashboard API
Real-time control for the AI Scalping Strategy Generator
Runs on Port 8010
"""

import sys
import asyncio
import threading
import uuid
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "src" / "data" / "scalping_strategies"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Scalping Agent API",
    description="Dashboard API for AI Scalping Strategy Generator",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# ENUMS & MODELS
# =============================================================================

class ScalpingMode(str, Enum):
    PIRANHA = "1m_hft"
    SHARK = "5m_momentum"
    WHALE = "15m_swing"
    VIPER = "5m_contrarian"

class AgentStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    GENERATING = "generating"

# Request Models
class ModeChangeRequest(BaseModel):
    mode: ScalpingMode

class SettingsUpdateRequest(BaseModel):
    generation_interval: Optional[int] = Field(None, ge=5, le=3600)
    skip_consensus: Optional[bool] = None
    parallel_mode: Optional[bool] = None
    use_swarm_mode: Optional[bool] = None
    min_risk_reward_ratio: Optional[float] = Field(None, ge=1.0, le=10.0)
    novelty_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    use_market_context: Optional[bool] = None

class GenerationRequest(BaseModel):
    technique_hint: Optional[str] = None

# Response Models
class GeneratedStrategy(BaseModel):
    id: str
    timestamp: str
    mode: str
    technique: str
    novelty_score: float
    risk_reward_ratio: float
    validation_status: str
    source_model: str
    full_content: str
    entry_signal: Optional[str] = None
    exit_signal: Optional[str] = None

class AgentStats(BaseModel):
    total_generated: int = 0
    approved_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    low_novelty_count: int = 0
    average_novelty: float = 0.0
    average_risk_reward: float = 0.0
    session_start: Optional[str] = None
    last_generation: Optional[str] = None

class AgentSettings(BaseModel):
    generation_interval: int = 60
    skip_consensus: bool = True
    parallel_mode: bool = True
    use_swarm_mode: bool = True
    min_risk_reward_ratio: float = 2.0
    novelty_threshold: float = 0.4
    use_market_context: bool = False

class AgentState(BaseModel):
    status: AgentStatus
    current_mode: ScalpingMode
    settings: AgentSettings
    stats: AgentStats
    active_techniques: List[str] = []

class StrategyFeed(BaseModel):
    strategies: List[GeneratedStrategy]
    total: int
    has_more: bool

class ModeInfo(BaseModel):
    mode: str
    name: str
    timeframe: str
    style: str
    description: str
    icon: str
    color: str
    trades_per_day: str
    hold_time: str
    techniques_count: int

# =============================================================================
# SCALPING AGENT CONTROLLER
# =============================================================================

class ScalpingAgentController:
    """
    Singleton controller to manage the scalping agent from the dashboard.
    Wraps the existing scalping_agent.py functionality.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._status = AgentStatus.STOPPED
        self._mode = ScalpingMode.VIPER
        self._settings = AgentSettings()
        self._stats = AgentStats()
        self._strategies: List[GeneratedStrategy] = []
        self._generation_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._agent_module = None
        self._initialized = True

        # Load existing strategies from CSV
        self._load_existing_strategies()

    def _load_agent_module(self):
        """Lazy load the scalping agent module"""
        if self._agent_module is None:
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "scalping_agent",
                    PROJECT_ROOT / "src" / "agents" / "scalping_agent.py"
                )
                self._agent_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self._agent_module)
            except Exception as e:
                print(f"Warning: Could not load scalping agent module: {e}")
                self._agent_module = None
        return self._agent_module

    def _load_existing_strategies(self):
        """Load existing strategies from CSV file"""
        csv_path = DATA_DIR / "validated_strategies.csv"
        if csv_path.exists():
            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        strategy = GeneratedStrategy(
                            id=row.get('id', str(uuid.uuid4())[:8]),
                            timestamp=row.get('timestamp', ''),
                            mode=row.get('mode', 'unknown'),
                            technique=row.get('technique', 'unknown'),
                            novelty_score=float(row.get('novelty_score', 0)),
                            risk_reward_ratio=float(row.get('risk_reward_ratio', 0)),
                            validation_status='approved',
                            source_model=row.get('source_model', 'unknown'),
                            full_content=row.get('strategy', row.get('full_content', '')),
                        )
                        self._strategies.append(strategy)
                # Keep only last 100
                self._strategies = self._strategies[-100:]
                self._update_stats_from_strategies()
            except Exception as e:
                print(f"Warning: Could not load existing strategies: {e}")

    def _update_stats_from_strategies(self):
        """Update stats based on loaded strategies"""
        if self._strategies:
            approved = [s for s in self._strategies if s.validation_status == 'approved']
            self._stats.approved_count = len(approved)
            self._stats.total_generated = len(self._strategies)
            if approved:
                self._stats.average_novelty = sum(s.novelty_score for s in approved) / len(approved)
                self._stats.average_risk_reward = sum(s.risk_reward_ratio for s in approved) / len(approved)

    def get_state(self) -> AgentState:
        """Get current agent state"""
        return AgentState(
            status=self._status,
            current_mode=self._mode,
            settings=self._settings,
            stats=self._stats,
            active_techniques=self._get_active_techniques()
        )

    def _get_active_techniques(self) -> List[str]:
        """Get list of available techniques for current mode"""
        mode_techniques = {
            ScalpingMode.PIRANHA: ["Micro RSI Snap", "Volume Spike Fade", "VWAP Bounce", "Stoch Micro Snap", "Retail FOMO Fade"],
            ScalpingMode.SHARK: ["EMA Alignment Ride", "MACD Momentum Burst", "BB Squeeze Pop", "RSI Momentum Surge", "Gap Fade Morning"],
            ScalpingMode.WHALE: ["Trend Continuation", "Support/Resistance Bounce", "Session Breakout", "Exhaustion Reversal", "Higher TF Confluence"],
            ScalpingMode.VIPER: ["Retail FOMO Fade", "Failed Breakout Trap", "Panic Wick Scalp", "Round Number Fade", "News Spike Fade"],
        }
        return mode_techniques.get(self._mode, [])

    def start(self) -> AgentState:
        """Start the generation loop"""
        if self._status == AgentStatus.RUNNING:
            return self.get_state()

        self._stop_event.clear()
        self._pause_event.clear()
        self._status = AgentStatus.RUNNING
        self._stats.session_start = datetime.now().isoformat()

        # Start generation in background thread
        self._generation_thread = threading.Thread(target=self._generation_loop, daemon=True)
        self._generation_thread.start()

        return self.get_state()

    def stop(self) -> AgentState:
        """Stop the generation loop"""
        self._stop_event.set()
        self._status = AgentStatus.STOPPED

        if self._generation_thread and self._generation_thread.is_alive():
            self._generation_thread.join(timeout=5)

        return self.get_state()

    def pause(self) -> AgentState:
        """Pause generation"""
        if self._status == AgentStatus.RUNNING:
            self._pause_event.set()
            self._status = AgentStatus.PAUSED
        return self.get_state()

    def resume(self) -> AgentState:
        """Resume from paused state"""
        if self._status == AgentStatus.PAUSED:
            self._pause_event.clear()
            self._status = AgentStatus.RUNNING
        return self.get_state()

    def change_mode(self, mode: ScalpingMode) -> AgentState:
        """Change the scalping mode"""
        if self._status in [AgentStatus.RUNNING, AgentStatus.GENERATING]:
            raise HTTPException(status_code=400, detail="Stop agent before changing mode")
        self._mode = mode
        return self.get_state()

    def update_settings(self, updates: SettingsUpdateRequest) -> AgentSettings:
        """Update agent settings"""
        update_dict = updates.dict(exclude_unset=True)
        for key, value in update_dict.items():
            if hasattr(self._settings, key) and value is not None:
                setattr(self._settings, key, value)
        return self._settings

    def _generation_loop(self):
        """Main generation loop - runs in background thread"""
        while not self._stop_event.is_set():
            # Check for pause
            while self._pause_event.is_set() and not self._stop_event.is_set():
                import time
                time.sleep(0.5)

            if self._stop_event.is_set():
                break

            # Generate strategy
            self._status = AgentStatus.GENERATING
            strategy = self._generate_single_strategy()

            if strategy:
                self._strategies.insert(0, strategy)
                # Keep only last 100
                self._strategies = self._strategies[:100]
                self._update_stats(strategy)

            self._status = AgentStatus.RUNNING

            # Wait for interval
            for _ in range(self._settings.generation_interval * 10):
                if self._stop_event.is_set():
                    break
                import time
                time.sleep(0.1)

    def _generate_single_strategy(self) -> Optional[GeneratedStrategy]:
        """Generate a single strategy using the scalping agent"""
        import time
        import random

        # Try to use actual scalping agent
        agent_module = self._load_agent_module()

        if agent_module and hasattr(agent_module, 'generate_scalping_ideas_parallel'):
            try:
                # Set mode in the module
                agent_module.SCALPING_MODE = self._mode.value
                agent_module.PARALLEL_MODE = self._settings.parallel_mode
                agent_module.SKIP_CONSENSUS = self._settings.skip_consensus
                agent_module.MIN_RISK_REWARD_RATIO = self._settings.min_risk_reward_ratio

                # Generate
                if self._settings.parallel_mode:
                    ideas = agent_module.generate_scalping_ideas_parallel()
                    if ideas:
                        idea = ideas[0]  # Take first approved one
                        return self._parse_generated_idea(idea)
                else:
                    idea = agent_module.generate_scalping_idea_swarm()
                    if idea:
                        return self._parse_generated_idea(idea)
            except Exception as e:
                print(f"Error generating with agent: {e}")

        # Fallback: Generate mock strategy for testing
        return self._generate_mock_strategy()

    def _parse_generated_idea(self, idea: dict) -> GeneratedStrategy:
        """Parse a generated idea from the scalping agent"""
        return GeneratedStrategy(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            mode=self._mode.value,
            technique=idea.get('technique', 'Unknown'),
            novelty_score=float(idea.get('novelty_score', 0.5)),
            risk_reward_ratio=float(idea.get('risk_reward', 2.0)),
            validation_status=idea.get('status', 'approved'),
            source_model=idea.get('model', 'unknown'),
            full_content=idea.get('idea', idea.get('content', '')),
            entry_signal=idea.get('entry', ''),
            exit_signal=idea.get('exit', ''),
        )

    def _generate_mock_strategy(self) -> GeneratedStrategy:
        """Generate a mock strategy for testing when agent unavailable"""
        import random

        techniques = self._get_active_techniques()
        technique = random.choice(techniques) if techniques else "Test Technique"

        models = ["deepseek", "claude", "gpt4", "gemini"]
        statuses = ["approved", "approved", "approved", "duplicate", "rejected"]

        novelty = random.uniform(0.3, 0.95)
        rr = random.uniform(1.5, 4.0)
        status = random.choice(statuses) if random.random() > 0.3 else "approved"

        mock_content = f"""
{self._mode.value.upper()} Strategy: {technique}
Timeframe: {'1m' if 'hft' in self._mode.value else '5m' if '5m' in self._mode.value else '15m'}

ENTRY: Enter when RSI({random.randint(5, 14)}) crosses below {random.randint(25, 35)} with volume spike > {random.uniform(1.2, 2.0):.1f}x average
EXIT: Take profit at {rr:.1f}:1 R:R or when RSI crosses above {random.randint(65, 75)}
STOP: {random.uniform(0.2, 0.5):.2f}% below entry

Confirmation: EMA({random.randint(5, 21)}) alignment + MACD histogram divergence
Volume Filter: Require volume > 20-period average
        """.strip()

        return GeneratedStrategy(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            mode=self._mode.value,
            technique=technique,
            novelty_score=novelty,
            risk_reward_ratio=rr,
            validation_status=status,
            source_model=random.choice(models),
            full_content=mock_content,
            entry_signal=f"RSI below {random.randint(25, 35)} + volume spike",
            exit_signal=f"{rr:.1f}:1 R:R target",
        )

    def _update_stats(self, strategy: GeneratedStrategy):
        """Update stats after generating a strategy"""
        self._stats.total_generated += 1
        self._stats.last_generation = strategy.timestamp

        if strategy.validation_status == 'approved':
            self._stats.approved_count += 1
            # Update averages
            n = self._stats.approved_count
            self._stats.average_novelty = (
                (self._stats.average_novelty * (n - 1) + strategy.novelty_score) / n
            )
            self._stats.average_risk_reward = (
                (self._stats.average_risk_reward * (n - 1) + strategy.risk_reward_ratio) / n
            )
        elif strategy.validation_status == 'duplicate':
            self._stats.duplicate_count += 1
        else:
            self._stats.rejected_count += 1

    def get_strategies(self, limit: int = 50, offset: int = 0, status: Optional[str] = None) -> StrategyFeed:
        """Get strategies with pagination and filtering"""
        filtered = self._strategies
        if status:
            filtered = [s for s in filtered if s.validation_status == status]

        total = len(filtered)
        paginated = filtered[offset:offset + limit]

        return StrategyFeed(
            strategies=paginated,
            total=total,
            has_more=(offset + limit) < total
        )

    def trigger_single_generation(self) -> GeneratedStrategy:
        """Manually trigger a single strategy generation"""
        strategy = self._generate_single_strategy()
        if strategy:
            self._strategies.insert(0, strategy)
            self._strategies = self._strategies[:100]
            self._update_stats(strategy)
            return strategy
        raise HTTPException(status_code=500, detail="Failed to generate strategy")


# Global controller instance
controller: Optional[ScalpingAgentController] = None

def get_controller() -> ScalpingAgentController:
    global controller
    if controller is None:
        controller = ScalpingAgentController()
    return controller


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    return {"status": "Scalping Agent Dashboard API Online", "port": 8010}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Status & Control
@app.get("/api/scalping/status")
async def get_status() -> AgentState:
    """Get current agent status, mode, settings, and stats"""
    return get_controller().get_state()

@app.post("/api/scalping/start")
async def start_agent() -> AgentState:
    """Start the scalping agent generation loop"""
    return get_controller().start()

@app.post("/api/scalping/stop")
async def stop_agent() -> AgentState:
    """Stop the scalping agent"""
    return get_controller().stop()

@app.post("/api/scalping/pause")
async def pause_agent() -> AgentState:
    """Pause generation (can resume)"""
    return get_controller().pause()

@app.post("/api/scalping/resume")
async def resume_agent() -> AgentState:
    """Resume from paused state"""
    return get_controller().resume()

# Mode Selection
@app.post("/api/scalping/mode")
async def change_mode(request: ModeChangeRequest) -> AgentState:
    """Switch scalping mode (PIRANHA, SHARK, WHALE, VIPER)"""
    return get_controller().change_mode(request.mode)

@app.get("/api/scalping/modes")
async def get_modes() -> List[ModeInfo]:
    """Get all available modes with descriptions"""
    return [
        ModeInfo(
            mode="1m_hft",
            name="PIRANHA",
            timeframe="1m",
            style="High-Frequency Trading",
            description="Ultra-fast scalping on 1-minute charts. Aggressive entries, tight stops. Swarm attacks on micro mean reversion.",
            icon="zap",
            color="#ef4444",
            trades_per_day="20-50",
            hold_time="30s - 3m",
            techniques_count=23
        ),
        ModeInfo(
            mode="5m_momentum",
            name="SHARK",
            timeframe="5m",
            style="Momentum Trading",
            description="Ride momentum waves on 5-minute charts. Patient hunter that strikes when momentum builds.",
            icon="trending-up",
            color="#3b82f6",
            trades_per_day="10-25",
            hold_time="5-20m",
            techniques_count=20
        ),
        ModeInfo(
            mode="15m_swing",
            name="WHALE",
            timeframe="15m",
            style="Swing Trading",
            description="Patient swing trades on 15-minute charts. Rides the big waves with wider stops for massive moves.",
            icon="anchor",
            color="#8b5cf6",
            trades_per_day="5-12",
            hold_time="15-60m",
            techniques_count=20
        ),
        ModeInfo(
            mode="5m_contrarian",
            name="VIPER",
            timeframe="5m",
            style="Contrarian Trading",
            description="Strike fast on retail mistakes. Venomous precision fading FOMO, failed breakouts, and panic selling.",
            icon="repeat",
            color="#10b981",
            trades_per_day="10-30",
            hold_time="3-15m",
            techniques_count=20
        ),
    ]

# Settings
@app.get("/api/scalping/settings")
async def get_settings() -> AgentSettings:
    """Get current agent settings"""
    return get_controller()._settings

@app.patch("/api/scalping/settings")
async def update_settings(request: SettingsUpdateRequest) -> AgentSettings:
    """Update agent settings"""
    return get_controller().update_settings(request)

# Strategies
@app.get("/api/scalping/strategies")
async def get_strategies(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None
) -> StrategyFeed:
    """Get generated strategies with filtering and pagination"""
    return get_controller().get_strategies(limit, offset, status)

@app.post("/api/scalping/generate")
async def trigger_generation() -> GeneratedStrategy:
    """Manually trigger a single strategy generation"""
    return get_controller().trigger_single_generation()

# Stats
@app.get("/api/scalping/stats")
async def get_stats() -> AgentStats:
    """Get detailed statistics"""
    return get_controller()._stats

@app.get("/api/scalping/techniques")
async def get_techniques() -> Dict[str, Any]:
    """Get technique performance data"""
    ctrl = get_controller()

    # Try to load technique performance from file
    perf_file = DATA_DIR / "technique_performance.json"
    usage_file = DATA_DIR / "technique_usage.json"

    techniques = []
    top_performers = []

    if perf_file.exists():
        try:
            with open(perf_file, 'r') as f:
                perf_data = json.load(f)
                for name, data in perf_data.items():
                    techniques.append({
                        "name": name,
                        "win_rate": data.get("win_rate", 0.5),
                        "sharpe_ratio": data.get("avg_sharpe", 1.0),
                        "usage_count": data.get("attempts", 0),
                    })
                # Sort by win rate for top performers
                sorted_tech = sorted(techniques, key=lambda x: x["win_rate"], reverse=True)
                top_performers = [t["name"] for t in sorted_tech[:5]]
        except Exception as e:
            print(f"Error loading technique performance: {e}")

    return {
        "techniques": techniques,
        "top_performers": top_performers,
        "active_for_mode": ctrl._get_active_techniques()
    }


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("   SCALPING AGENT DASHBOARD API")
    print("   Starting on http://localhost:8010")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8010)
