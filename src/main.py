"""
TradeHive AI trading system entrypoint.

This file intentionally imports agent implementations lazily. Disabled agents
should not require exchange SDKs, API keys, or external helper repos just to
start the orchestrator.
"""

import importlib
import os
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from termcolor import cprint


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from src.config import EXCLUDED_TOKENS, MONITORED_TOKENS, SLEEP_BETWEEN_RUNS_MINUTES
except ImportError:
    from config import EXCLUDED_TOKENS, MONITORED_TOKENS, SLEEP_BETWEEN_RUNS_MINUTES


load_dotenv()


ACTIVE_AGENTS = {
    "risk": False,
    "trading": False,
    "strategy": False,
    "copybot": False,
    "sentiment": False,
}


AGENT_SPECS = {
    "risk": ("src.agents.risk_agent", "RiskAgent"),
    "trading": ("src.agents.trading_agent", "TradingAgent"),
    "strategy": ("src.agents.strategy_agent", "StrategyAgent"),
    "copybot": ("src.agents.copybot_agent", "CopyBotAgent"),
    "sentiment": ("src.agents.sentiment_agent", "SentimentAgent"),
}


def _load_agent(agent_name):
    """Import and instantiate an enabled agent."""
    module_name, class_name = AGENT_SPECS[agent_name]
    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


def _build_active_agents():
    return {
        name: _load_agent(name)
        for name, enabled in ACTIVE_AGENTS.items()
        if enabled
    }


def run_agents():
    """Run all active agents in sequence."""
    if not any(ACTIVE_AGENTS.values()):
        cprint("No active agents enabled. Update ACTIVE_AGENTS to run the orchestrator.", "yellow")
        return

    try:
        agents = _build_active_agents()

        while True:
            try:
                risk_agent = agents.get("risk")
                if risk_agent:
                    cprint("\nRunning risk management...", "cyan")
                    risk_agent.run()

                trading_agent = agents.get("trading")
                if trading_agent:
                    cprint("\nRunning trading analysis...", "cyan")
                    trading_agent.run()

                strategy_agent = agents.get("strategy")
                if strategy_agent:
                    cprint("\nRunning strategy analysis...", "cyan")
                    for token in MONITORED_TOKENS:
                        if token not in EXCLUDED_TOKENS:
                            cprint(f"\nAnalyzing {token}...", "cyan")
                            strategy_agent.get_signals(token)

                copybot_agent = agents.get("copybot")
                if copybot_agent:
                    cprint("\nRunning CopyBot portfolio analysis...", "cyan")
                    copybot_agent.run_analysis_cycle()

                sentiment_agent = agents.get("sentiment")
                if sentiment_agent:
                    cprint("\nRunning sentiment analysis...", "cyan")
                    sentiment_agent.run()

                next_run = datetime.now() + timedelta(minutes=SLEEP_BETWEEN_RUNS_MINUTES)
                cprint(f"\nSleeping until {next_run.strftime('%H:%M:%S')}", "cyan")
                time.sleep(60 * SLEEP_BETWEEN_RUNS_MINUTES)

            except Exception as exc:
                cprint(f"\nError running agents: {exc}", "red")
                cprint("Continuing to next cycle...", "yellow")
                time.sleep(60)

    except KeyboardInterrupt:
        cprint("\nGracefully shutting down...", "yellow")
    except Exception as exc:
        cprint(f"\nFatal error in main loop: {exc}", "red")
        raise


if __name__ == "__main__":
    cprint("\nTradeHive AI Agent Trading System Starting...", "white", "on_blue")
    cprint("\nActive Agents:", "white", "on_blue")
    for agent, active in ACTIVE_AGENTS.items():
        status = "ON" if active else "OFF"
        cprint(f"  - {agent.title()}: {status}", "white", "on_blue")
    print()

    run_agents()
