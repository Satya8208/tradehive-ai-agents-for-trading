"""
Poker Swarm Advisor — 3-Model LLM Consensus for Complex Decisions

Mirrors the polymarket_trader/swarm_analyzer.py pattern:
- 3 advisor personas: Tight, Balanced, Aggressive
- Query in parallel, aggregate consensus
- Returns majority-vote action with individual reasoning

Usage:
    # From live_advisor: type 'sw' for swarm advice
    # Or programmatically:
    swarm = PokerSwarmAdvisor()
    decision = swarm.analyze_hand("AhKs", "Qh 7c 2d", "BTN", pot=15, to_call=8)
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from termcolor import cprint

try:
    from .ai.ai_brain import AIBrain, AIModel, AIResponse
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


@dataclass
class AdvisorOpinion:
    """Single advisor's recommendation"""
    role: str
    action: str           # fold, call, check, bet, raise
    sizing: str           # e.g., "2/3 pot", "all-in"
    confidence: float     # 0-100
    reasoning: str
    model: str


@dataclass
class SwarmDecision:
    """Aggregated swarm consensus"""
    consensus_action: str
    consensus_sizing: str
    agreement_ratio: float  # 0-1 (1.0 = unanimous)
    opinions: List[AdvisorOpinion] = field(default_factory=list)
    reasoning_summary: str = ""


# Role-specific system prompts
ROLE_PROMPTS = {
    "tight": """You are a tight-conservative poker advisor. Your philosophy:
- Fold marginal hands. Only play premium/strong holdings.
- Value safety over potential. If in doubt, fold.
- Prefer smaller bets and pot control with medium-strength hands.
- Only bluff rarely and in obvious spots.
- Think about worst-case scenarios.

Respond with JSON: {"action": "fold/check/call/bet/raise", "sizing": "amount or description", "confidence": 0-100, "reasoning": "brief explanation"}""",

    "balanced": """You are a balanced GTO-oriented poker advisor. Your philosophy:
- Follow game-theory optimal ranges and frequencies.
- Balance your value bets with an appropriate number of bluffs.
- Use proper bet sizing based on pot geometry.
- Consider minimum defense frequency when facing bets.
- Make unexploitable plays as the default.

Respond with JSON: {"action": "fold/check/call/bet/raise", "sizing": "amount or description", "confidence": 0-100, "reasoning": "brief explanation"}""",

    "aggressive": """You are an aggressive LAG (loose-aggressive) poker advisor. Your philosophy:
- Apply maximum pressure. Betting and raising is usually better than calling.
- Look for bluff opportunities, especially on scare cards.
- Exploit tight players by widening your range.
- Overbet when you have range advantage.
- Use position aggressively — steal pots in position.

Respond with JSON: {"action": "fold/check/call/bet/raise", "sizing": "amount or description", "confidence": 0-100, "reasoning": "brief explanation"}""",
}

# Models to use for each role (fast models for real-time use)
ROLE_MODELS = {
    "tight": AIModel.GEMINI_FLASH,
    "balanced": AIModel.CLAUDE_SONNET,
    "aggressive": AIModel.GROK,
}


class PokerSwarmAdvisor:
    """
    3-model consensus advisor for complex poker decisions.

    Queries 3 LLMs in parallel with different strategic personas,
    then aggregates into a consensus recommendation.
    """

    def __init__(self):
        if not AI_AVAILABLE:
            cprint("AI Brain not available — swarm advisor disabled", "yellow")
            self.brain = None
            return

        self.brain = AIBrain()
        self.roles = list(ROLE_PROMPTS.keys())

    def analyze_hand(
        self,
        hole_cards: str,
        board: str = "",
        position: str = "BTN",
        pot: float = 0,
        to_call: float = 0,
        villain_action: str = "",
        stack: float = 100,
        extra_context: str = "",
    ) -> Optional[SwarmDecision]:
        """
        Get 3-advisor consensus on a poker decision.

        Args:
            hole_cards: e.g., "AhKs"
            board: e.g., "Qh 7c 2d"
            position: e.g., "BTN", "CO"
            pot: pot size in BB
            to_call: amount to call in BB
            villain_action: what villain did
            stack: effective stack in BB
            extra_context: any extra info

        Returns:
            SwarmDecision with consensus and individual opinions
        """
        if not self.brain:
            cprint("Swarm advisor not available (no AI Brain)", "red")
            return None

        # Build the hand context
        hand_context = f"""Hand Situation:
Hero: {hole_cards} from {position}
Board: {board if board else 'Preflop'}
Pot: {pot:.1f}bb | To call: {to_call:.1f}bb | Stack: {stack:.1f}bb
Villain: {villain_action if villain_action else 'First to act'}"""

        if extra_context:
            hand_context += f"\nNotes: {extra_context}"

        hand_context += "\n\nWhat is the best play here?"

        cprint(f"\n  Consulting 3 advisors...", "cyan")
        start = time.time()

        # Query all 3 advisors in parallel
        opinions = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for role in self.roles:
                model = ROLE_MODELS.get(role, AIModel.GEMINI_FLASH)
                future = executor.submit(
                    self._query_advisor, role, hand_context, model
                )
                futures[future] = role

            for future in as_completed(futures):
                role = futures[future]
                try:
                    opinion = future.result()
                    if opinion:
                        opinions.append(opinion)
                except Exception as e:
                    cprint(f"  {role} advisor failed: {e}", "red")

        elapsed = time.time() - start

        if not opinions:
            cprint("  All advisors failed!", "red")
            return None

        # Aggregate consensus
        decision = self._aggregate(opinions)

        # Display results
        self._display(decision, elapsed)

        return decision

    def _query_advisor(self, role: str, context: str, model: AIModel) -> Optional[AdvisorOpinion]:
        """Query a single advisor."""
        system_prompt = ROLE_PROMPTS[role]

        response = self.brain.ask_sync(
            prompt=context,
            task="realtime",
            context=system_prompt,
            model=model,
        )

        if not response.success:
            return None

        # Parse JSON response
        try:
            # Try to extract JSON from response
            content = response.content.strip()
            # Find JSON in response
            start = content.find('{')
            end = content.rfind('}') + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
            else:
                # Fallback: interpret as plain text
                data = {
                    "action": self._extract_action(content),
                    "sizing": "",
                    "confidence": 50,
                    "reasoning": content[:200],
                }
        except json.JSONDecodeError:
            data = {
                "action": self._extract_action(response.content),
                "sizing": "",
                "confidence": 50,
                "reasoning": response.content[:200],
            }

        return AdvisorOpinion(
            role=role,
            action=data.get("action", "check").lower(),
            sizing=str(data.get("sizing", "")),
            confidence=float(data.get("confidence", 50)),
            reasoning=str(data.get("reasoning", "")),
            model=response.model,
        )

    def _extract_action(self, text: str) -> str:
        """Extract action keyword from plain text response."""
        text_lower = text.lower()
        for action in ["all-in", "raise", "bet", "call", "check", "fold"]:
            if action in text_lower:
                return action
        return "check"

    def _aggregate(self, opinions: List[AdvisorOpinion]) -> SwarmDecision:
        """Aggregate opinions into consensus."""
        # Count actions
        action_counts: Dict[str, int] = {}
        for op in opinions:
            action = op.action
            action_counts[action] = action_counts.get(action, 0) + 1

        # Find majority action
        max_count = max(action_counts.values())
        majority_actions = [a for a, c in action_counts.items() if c == max_count]

        if len(majority_actions) == 1:
            consensus_action = majority_actions[0]
        else:
            # Tie — use balanced model's recommendation
            balanced_op = next((o for o in opinions if o.role == "balanced"), opinions[0])
            consensus_action = balanced_op.action

        # Get sizing from the advisor with consensus action + highest confidence
        matching = [o for o in opinions if o.action == consensus_action]
        if matching:
            best = max(matching, key=lambda o: o.confidence)
            consensus_sizing = best.sizing
        else:
            consensus_sizing = ""

        agreement = max_count / len(opinions) if opinions else 0

        # Build reasoning summary
        reasons = [f"[{o.role.upper()}] {o.action}: {o.reasoning[:100]}" for o in opinions]
        summary = " | ".join(reasons)

        return SwarmDecision(
            consensus_action=consensus_action,
            consensus_sizing=consensus_sizing,
            agreement_ratio=agreement,
            opinions=opinions,
            reasoning_summary=summary,
        )

    def _display(self, decision: SwarmDecision, elapsed: float) -> None:
        """Display swarm decision."""
        cprint(f"\n  {'=' * 50}", "cyan")
        cprint(f"  SWARM CONSENSUS ({elapsed:.1f}s)", "cyan", attrs=["bold"])
        cprint(f"  {'=' * 50}", "cyan")

        # Individual opinions
        for op in decision.opinions:
            role_colors = {"tight": "blue", "balanced": "white", "aggressive": "red"}
            color = role_colors.get(op.role, "white")
            action_color = "green" if op.action in ("raise", "bet") else "yellow" if op.action == "call" else "red"
            cprint(f"  {op.role:12s} -> {op.action:6s} {op.sizing:15s} "
                   f"({op.confidence:.0f}% conf) [{op.model}]", color)
            cprint(f"    {op.reasoning[:80]}", "dark_grey")

        # Consensus
        agreement_pct = decision.agreement_ratio * 100
        if agreement_pct >= 100:
            agree_tag = "UNANIMOUS"
            agree_color = "green"
        elif agreement_pct >= 66:
            agree_tag = "MAJORITY"
            agree_color = "yellow"
        else:
            agree_tag = "SPLIT"
            agree_color = "red"

        action_upper = decision.consensus_action.upper()
        cprint(f"\n  VERDICT: {action_upper} {decision.consensus_sizing} "
               f"({agree_tag} — {agreement_pct:.0f}% agree)", agree_color, attrs=["bold"])
        cprint(f"  {'=' * 50}\n", "cyan")


# Standalone test
if __name__ == "__main__":
    cprint("\n=== Poker Swarm Advisor Test ===\n", "cyan", attrs=["bold"])

    swarm = PokerSwarmAdvisor()

    if swarm.brain:
        decision = swarm.analyze_hand(
            hole_cards="AsKh",
            board="Qh Jc 2d",
            position="BTN",
            pot=12,
            to_call=6,
            villain_action="CO bets 6bb",
            stack=95,
        )
    else:
        cprint("AI Brain not available for test", "yellow")
