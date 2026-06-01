"""
Pytest-friendly smoke tests for Poker God mode.

The module can still be run directly for a quick terminal summary:
    python src/agents/poker/test_god_mode.py
"""

from pathlib import Path
import sys

from termcolor import cprint


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.poker.poker_agent import PokerAgent, parse_cards, Position, GameMode


def collect_god_mode_checks() -> dict:
    """Run a small offline smoke suite and return structured results."""
    god = PokerAgent(mode=GameMode.ADVISOR)

    status = god.god_mode_status()
    neural = god.quick_eval("AhKh", "Qh Jc 2d")

    god.hand_state.position = Position.BTN
    solver = god.get_solver_solution("dry_unpaired", "top_pair_good")
    population = god.get_population_profile("live_low", "live_rec")
    dynamic_range = god.get_adjusted_range(stack_bb=150, table_type="passive", is_live=True)

    cards = parse_cards("AhKs")
    god.new_hand(cards, Position.CO)
    god.set_board(parse_cards("Kc 7h 2d"))
    god.set_pot(15, 8)
    advice = god.get_postflop_advice()

    return {
        "status": status,
        "neural": neural,
        "solver": solver,
        "population": population,
        "dynamic_range": dynamic_range,
        "advice": advice,
        "hole_cards": god.hand_state.hole_cards,
        "board": god.hand_state.board,
    }


def test_god_mode_offline_components():
    results = collect_god_mode_checks()

    assert results["status"]
    assert any(results["status"].values())
    assert "strength" in results["neural"]
    assert "action" in results["solver"]
    assert "vpip" in results["population"]
    assert "base" in results["dynamic_range"]
    assert results["advice"]
    assert len(results["hole_cards"]) == 2
    assert len(results["board"]) == 3


def main():
    cprint("\n" + "=" * 60, "cyan")
    cprint("POKER GOD AGENT - ADVISOR MODE TEST", "cyan", attrs=["bold"])
    cprint("=" * 60 + "\n", "cyan")

    results = collect_god_mode_checks()
    active = sum(1 for value in results["status"].values() if value)

    cprint(f"God mode components active: {active}/{len(results['status'])}", "green" if active else "yellow")
    cprint(
        f"Neural evaluator: {results['neural'].get('description', 'n/a')} = {results['neural'].get('equity', 0) * 100:.1f}%",
        "green",
    )
    cprint(
        f"Solver: {results['solver'].get('action', 'n/a')} @ {results['solver'].get('frequency', 0) * 100:.0f}%",
        "green",
    )
    cprint(
        f"Population DB: VPIP={results['population'].get('vpip', 'n/a')}%",
        "green",
    )
    cprint(
        f"Dynamic range factor: {results['dynamic_range'].get('factor', 0):.2f}x",
        "green",
    )
    cprint("Postflop advice generated successfully", "green")


if __name__ == "__main__":
    main()
