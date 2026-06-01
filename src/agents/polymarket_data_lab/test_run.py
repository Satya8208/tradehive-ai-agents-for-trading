"""
Simple Test Runner for Crypto Polymarket Agent
Avoids unicode encoding issues on Windows
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, ExecutionMode
from src.agents.crypto_polymarket.orchestrator import CryptoPolymarketOrchestrator


async def test_agent():
    """Test the crypto polymarket agent"""
    print("=" * 60)
    print("CRYPTO POLYMARKET AGENT TEST RUN")
    print("=" * 60)

    # Create config
    config = CryptoPolymarketConfig(
        execution_mode=ExecutionMode.DRY_RUN, cycle_interval_seconds=30
    )

    # Create orchestrator
    orchestrator = CryptoPolymarketOrchestrator(config)

    # Print status
    orchestrator.print_status()

    print("\n" + "=" * 60)
    print("STARTING SINGLE TEST CYCLE...")
    print("=" * 60)

    try:
        # Run single cycle
        await orchestrator.run(cycles=1)

        print("\n" + "=" * 60)
        print("TEST CYCLE COMPLETED SUCCESSFULLY!")
        print("=" * 60)

        # Final status
        orchestrator.print_status()

    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
    finally:
        orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(test_agent())
