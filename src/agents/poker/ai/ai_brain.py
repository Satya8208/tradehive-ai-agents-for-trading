"""
🧠 AI Brain - Multi-Model LLM Integration for Poker God Agent
Supports OpenRouter, Grok, Claude, GPT-4, Gemini, DeepSeek
Built with love by TradeHive
"""

import os
import json
import time
from typing import Optional, Dict, List, Literal
from dataclasses import dataclass
from enum import Enum
import httpx
from dotenv import load_dotenv

load_dotenv()


class AIModel(Enum):
    """Available AI models"""
    # Fast models for real-time decisions
    GROK = "grok"
    GEMINI_FLASH = "gemini-flash"
    DEEPSEEK = "deepseek"

    # Smart models for complex analysis
    CLAUDE_SONNET = "claude-sonnet"
    GPT5 = "gpt-5"
    GEMINI_PRO = "gemini-pro"

    # Via OpenRouter
    OPENROUTER = "openrouter"


@dataclass
class AIResponse:
    """Response from AI model"""
    content: str
    model: str
    tokens_used: int
    latency_ms: int
    success: bool
    error: Optional[str] = None


class AIBrain:
    """
    🧠 The Poker God's AI Brain

    Multi-model LLM integration supporting:
    - Real-time decisions (Grok/Gemini Flash for speed)
    - Complex analysis (Claude/GPT-4 for depth)
    - Session review (Gemini Pro for long context)

    Features:
    - Automatic model routing based on task
    - Fallback chain if primary model fails
    - Response caching for repeated queries
    - Poker-specific system prompts
    """

    # Model configurations
    MODELS = {
        AIModel.GROK: {
            "base_url": "https://api.x.ai/v1",
            "model": "grok-4.3",
            "api_key_env": "GROK_API_KEY",
            "max_tokens": 1024,
        },
        AIModel.CLAUDE_SONNET: {
            "base_url": "https://api.anthropic.com/v1",
            "model": "claude-sonnet-4-6",
            "api_key_env": "ANTHROPIC_KEY",
            "max_tokens": 2048,
        },
        AIModel.GPT5: {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5.5",
            "api_key_env": "OPENAI_KEY",
            "max_tokens": 2048,
        },
        AIModel.GEMINI_FLASH: {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "google/gemini-3.5-flash",
            "api_key_env": "OPENROUTER_API_KEY",
            "max_tokens": 1024,
        },
        AIModel.GEMINI_PRO: {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "google/gemini-3.1-pro-preview",
            "api_key_env": "OPENROUTER_API_KEY",
            "max_tokens": 4096,
        },
        AIModel.DEEPSEEK: {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "deepseek/deepseek-v3.2",
            "api_key_env": "OPENROUTER_API_KEY",
            "max_tokens": 2048,
        },
    }

    # Task-to-model routing
    TASK_ROUTING = {
        "realtime": [AIModel.GROK, AIModel.GEMINI_FLASH, AIModel.DEEPSEEK],
        "analysis": [AIModel.CLAUDE_SONNET, AIModel.GPT5, AIModel.GEMINI_PRO],
        "session_review": [AIModel.GEMINI_PRO, AIModel.CLAUDE_SONNET],
        "opponent_profile": [AIModel.GPT5, AIModel.CLAUDE_SONNET],
    }

    # Poker-specific system prompts
    SYSTEM_PROMPTS = {
        "advisor": """You are the Poker God - an elite poker advisor with deep GTO knowledge and exploitative adjustments.

Your role:
- Provide precise, actionable poker advice
- Explain decisions using poker math (equity, pot odds, EV)
- Consider position, stack depths, and opponent tendencies
- Use professional poker terminology
- Be concise but thorough

Format your responses clearly with:
- ACTION: The recommended play
- REASONING: Why this is optimal
- EV ESTIMATE: Expected value if applicable
- ALTERNATIVE: Second-best option if close""",

        "hand_analysis": """You are analyzing a poker hand as the Poker God.

Break down:
1. Preflop action and ranges
2. Board texture assessment
3. Street-by-street analysis
4. Key decision points
5. Alternative lines
6. Result evaluation (was it correct regardless of outcome?)

Be specific with numbers and ranges.""",

        "session_review": """You are reviewing a poker session as the Poker God.

For each notable hand:
- Identify any mistakes or leaks
- Highlight good plays worth reinforcing
- Suggest improvements
- Track patterns (tilt, fatigue, tendencies)

Provide:
1. Session overview
2. Key hands analysis
3. Leak identification
4. Improvement areas
5. Action items for next session""",

        "opponent_read": """You are profiling a poker opponent as the Poker God.

From the available data, determine:
- Player type (TAG, LAG, NIT, FISH, etc.)
- Key tendencies (VPIP, PFR, aggression)
- Exploitable leaks
- Recommended adjustments
- Danger signs

Be specific and actionable.""",
    }

    def __init__(self, preferred_model: AIModel = None, verbose: bool = False):
        """
        Initialize AI Brain

        Args:
            preferred_model: Force use of specific model
            verbose: Print debug info
        """
        self.preferred_model = preferred_model
        self.verbose = verbose
        self.cache: Dict[str, AIResponse] = {}
        self.request_count = 0
        self.total_tokens = 0

        # Check available models
        self.available_models = self._check_available_models()

        if verbose:
            print(f"🧠 AI Brain initialized with models: {[m.value for m in self.available_models]}")

    def _check_available_models(self) -> List[AIModel]:
        """Check which models have API keys configured"""
        available = []
        for model, config in self.MODELS.items():
            api_key = os.getenv(config["api_key_env"])
            if api_key and api_key not in ["your_key_here", ""]:
                available.append(model)
        return available

    def _get_api_key(self, model: AIModel) -> Optional[str]:
        """Get API key for model"""
        config = self.MODELS.get(model)
        if not config:
            return None
        return os.getenv(config["api_key_env"])

    def _select_model(self, task: str = "realtime") -> AIModel:
        """Select best available model for task"""
        if self.preferred_model and self.preferred_model in self.available_models:
            return self.preferred_model

        # Try models in priority order for task
        candidates = self.TASK_ROUTING.get(task, self.TASK_ROUTING["realtime"])
        for model in candidates:
            if model in self.available_models:
                return model

        # Fallback to any available
        if self.available_models:
            return self.available_models[0]

        raise ValueError("No AI models available! Please configure API keys in .env")

    async def _call_openai_compatible(self,
                                       model: AIModel,
                                       messages: List[Dict],
                                       max_tokens: int = None) -> AIResponse:
        """Call OpenAI-compatible API (OpenAI, Grok, OpenRouter)"""
        config = self.MODELS[model]
        api_key = self._get_api_key(model)

        if not api_key:
            return AIResponse(
                content="", model=model.value, tokens_used=0,
                latency_ms=0, success=False, error="API key not found"
            )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter specific headers
        if "openrouter" in config["base_url"]:
            headers["HTTP-Referer"] = "https://tradehive.poker"
            headers["X-Title"] = "Poker God Agent"

        payload = {
            "model": config["model"],
            "messages": messages,
            "max_tokens": max_tokens or config["max_tokens"],
            "temperature": 0.7,
        }

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{config['base_url']}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                latency = int((time.time() - start) * 1000)

                self.request_count += 1
                self.total_tokens += tokens

                return AIResponse(
                    content=content,
                    model=config["model"],
                    tokens_used=tokens,
                    latency_ms=latency,
                    success=True
                )

        except Exception as e:
            return AIResponse(
                content="", model=model.value, tokens_used=0,
                latency_ms=int((time.time() - start) * 1000),
                success=False, error=str(e)
            )

    async def _call_anthropic(self, messages: List[Dict], max_tokens: int = None) -> AIResponse:
        """Call Anthropic Claude API"""
        config = self.MODELS[AIModel.CLAUDE_SONNET]
        api_key = self._get_api_key(AIModel.CLAUDE_SONNET)

        if not api_key:
            return AIResponse(
                content="", model="claude", tokens_used=0,
                latency_ms=0, success=False, error="API key not found"
            )

        # Convert messages format for Anthropic
        system = ""
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                anthropic_messages.append(msg)

        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }

        payload = {
            "model": config["model"],
            "max_tokens": max_tokens or config["max_tokens"],
            "system": system,
            "messages": anthropic_messages
        }

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{config['base_url']}/messages",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                content = data["content"][0]["text"]
                tokens = data.get("usage", {}).get("input_tokens", 0) + \
                         data.get("usage", {}).get("output_tokens", 0)
                latency = int((time.time() - start) * 1000)

                self.request_count += 1
                self.total_tokens += tokens

                return AIResponse(
                    content=content,
                    model=config["model"],
                    tokens_used=tokens,
                    latency_ms=latency,
                    success=True
                )

        except Exception as e:
            return AIResponse(
                content="", model="claude", tokens_used=0,
                latency_ms=int((time.time() - start) * 1000),
                success=False, error=str(e)
            )

    async def ask(self,
                  prompt: str,
                  task: Literal["realtime", "analysis", "session_review", "opponent_profile"] = "realtime",
                  context: str = None,
                  model: AIModel = None) -> AIResponse:
        """
        Ask the AI Brain a question

        Args:
            prompt: The question or request
            task: Type of task (affects model selection and prompt)
            context: Additional context (hand history, opponent stats, etc.)
            model: Force specific model (overrides task routing)

        Returns:
            AIResponse with answer
        """
        # Select model
        selected_model = model or self._select_model(task)

        # Build messages
        system_prompt = self.SYSTEM_PROMPTS.get(
            "advisor" if task == "realtime" else task.replace("_", " "),
            self.SYSTEM_PROMPTS["advisor"]
        )

        messages = [{"role": "system", "content": system_prompt}]

        if context:
            messages.append({"role": "user", "content": f"Context:\n{context}"})
            messages.append({"role": "assistant", "content": "I understand the context. What would you like to know?"})

        messages.append({"role": "user", "content": prompt})

        if self.verbose:
            print(f"🧠 Asking {selected_model.value}: {prompt[:50]}...")

        # Call appropriate API
        if selected_model == AIModel.CLAUDE_SONNET:
            response = await self._call_anthropic(messages)
        else:
            response = await self._call_openai_compatible(selected_model, messages)

        # Fallback on failure
        if not response.success and len(self.available_models) > 1:
            if self.verbose:
                print(f"⚠️ {selected_model.value} failed, trying fallback...")

            for fallback in self.available_models:
                if fallback != selected_model:
                    if fallback == AIModel.CLAUDE_SONNET:
                        response = await self._call_anthropic(messages)
                    else:
                        response = await self._call_openai_compatible(fallback, messages)

                    if response.success:
                        break

        return response

    def ask_sync(self,
                 prompt: str,
                 task: Literal["realtime", "analysis", "session_review", "opponent_profile"] = "realtime",
                 context: str = None,
                 model: AIModel = None) -> AIResponse:
        """Synchronous wrapper for ask()"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.ask(prompt, task, context, model))

    # === Poker-Specific Methods ===

    def get_advice(self,
                   hole_cards: str,
                   board: str = "",
                   position: str = "BTN",
                   pot_size: float = 0,
                   bet_to_call: float = 0,
                   villain_action: str = "",
                   stack_size: float = 100) -> AIResponse:
        """
        Get real-time poker advice

        Args:
            hole_cards: Hero's cards (e.g., "AhKs")
            board: Community cards (e.g., "Qh Jc 2d")
            position: Hero's position
            pot_size: Current pot in BB
            bet_to_call: Amount to call in BB
            villain_action: What villain did
            stack_size: Effective stack in BB
        """
        prompt = f"""I have {hole_cards} in {position} position.
Board: {board if board else 'Preflop'}
Pot: {pot_size}bb | To call: {bet_to_call}bb | Stack: {stack_size}bb
Villain action: {villain_action if villain_action else 'First to act'}

What should I do?"""

        return self.ask_sync(prompt, task="realtime")

    def analyze_hand(self,
                     hand_history: str) -> AIResponse:
        """
        Analyze a complete hand

        Args:
            hand_history: Full hand history text
        """
        return self.ask_sync(
            "Please analyze this hand in detail:",
            task="analysis",
            context=hand_history
        )

    def review_session(self,
                       hands: List[Dict],
                       stats: Dict = None) -> AIResponse:
        """
        Review a poker session

        Args:
            hands: List of hand histories
            stats: Session statistics
        """
        context = f"Session stats: {json.dumps(stats)}\n\n" if stats else ""
        context += "Hands played:\n"
        for i, hand in enumerate(hands[:20], 1):  # Limit to 20 hands
            context += f"\n--- Hand {i} ---\n{json.dumps(hand)}\n"

        return self.ask_sync(
            "Please review this session and identify key learnings:",
            task="session_review",
            context=context
        )

    def profile_opponent(self,
                         stats: Dict,
                         notes: str = "") -> AIResponse:
        """
        Profile an opponent

        Args:
            stats: Opponent's HUD stats
            notes: Any observations
        """
        context = f"Opponent stats: {json.dumps(stats)}"
        if notes:
            context += f"\n\nNotes: {notes}"

        return self.ask_sync(
            "Please profile this opponent and suggest exploits:",
            task="opponent_profile",
            context=context
        )

    def explain_gto(self,
                    situation: str) -> AIResponse:
        """
        Explain GTO concept for a situation

        Args:
            situation: The poker situation to explain
        """
        return self.ask_sync(
            f"Explain the GTO approach for: {situation}",
            task="analysis"
        )

    def get_stats(self) -> Dict:
        """Get brain usage statistics"""
        return {
            "requests": self.request_count,
            "total_tokens": self.total_tokens,
            "available_models": [m.value for m in self.available_models],
            "preferred_model": self.preferred_model.value if self.preferred_model else None
        }


# === Quick Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n🧠 Testing AI Brain...\n", "cyan", attrs=["bold"])

    brain = AIBrain(verbose=True)

    cprint(f"Available models: {[m.value for m in brain.available_models]}", "green")

    # Test real-time advice
    cprint("\n📍 Testing real-time advice...", "yellow")
    response = brain.get_advice(
        hole_cards="AhKh",
        board="Qh Jc 2d",
        position="CO",
        pot_size=12,
        bet_to_call=8,
        villain_action="bet 8bb",
        stack_size=100
    )

    if response.success:
        cprint(f"\n{response.content}", "white")
        cprint(f"\n[{response.model} | {response.latency_ms}ms | {response.tokens_used} tokens]", "dim")
    else:
        cprint(f"Error: {response.error}", "red")

    cprint(f"\n📊 Stats: {brain.get_stats()}", "cyan")
