"""
🌙 TradeHive's OpenRouter Model Implementation
Built with love by TradeHive 🚀

OpenRouter provides unified access to all major AI models through a single API.
"""

from openai import OpenAI
from termcolor import cprint
from .base_model import BaseModel, ModelResponse
import time

class OpenRouterModel(BaseModel):
    """Implementation for OpenRouter's model routing"""

    AVAILABLE_MODELS = {
        # OpenRouter routing and current frontier models
        "openrouter/auto": {
            "description": "OpenRouter auto-router over its current curated frontier pool",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openrouter/free": {
            "description": "OpenRouter free router where available",
            "input_price": "FREE/variable",
            "output_price": "FREE/variable"
        },
        "openai/gpt-5.5": {
            "description": "GPT-5.5 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.5-pro": {
            "description": "GPT-5.5 Pro via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.4": {
            "description": "GPT-5.4 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.4-mini": {
            "description": "GPT-5.4 Mini via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.4-nano": {
            "description": "GPT-5.4 Nano via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.2": {
            "description": "GPT-5.2 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.2-pro": {
            "description": "GPT-5.2 Pro via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.2-chat": {
            "description": "GPT-5.2 Chat via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5.2-codex": {
            "description": "GPT-5.2 Codex via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "anthropic/claude-opus-4.7": {
            "description": "Claude Opus 4.7 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "anthropic/claude-sonnet-4.6": {
            "description": "Claude Sonnet 4.6 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "deepseek/deepseek-v3.2": {
            "description": "DeepSeek V3.2 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "deepseek/deepseek-v3.2-speciale": {
            "description": "DeepSeek V3.2 Speciale via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "x-ai/grok-4.20": {
            "description": "Grok 4.20 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "x-ai/grok-4.20-multi-agent": {
            "description": "Grok 4.20 Multi-Agent via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "x-ai/grok-4.3": {
            "description": "Grok 4.3 via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "google/gemini-3.1-pro-preview": {
            "description": "Gemini 3.1 Pro Preview via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "google/gemini-3.5-flash": {
            "description": "Gemini 3.5 Flash via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "google/gemini-3.1-flash-lite": {
            "description": "Gemini 3.1 Flash-Lite via OpenRouter",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        # Qwen Models
        "qwen/qwen3-vl-32b-instruct": {
            "description": "Qwen 3 VL 32B - Vision & Language - 32k context",
            "input_price": "$0.25/1M tokens",
            "output_price": "$0.25/1M tokens"
        },
        "qwen/qwen3-max": {
            "description": "Qwen 3 Max - Flagship model - 32k context",
            "input_price": "$1.00/1M tokens",
            "output_price": "$1.00/1M tokens"
        },

        # GLM Models
        "z-ai/glm-4.6": {
            "description": "GLM 4.6 - Zhipu AI - 128k context",
            "input_price": "$0.50/1M tokens",
            "output_price": "$0.50/1M tokens"
        },

        # DeepSeek Models
        "deepseek/deepseek-r1-0528": {
            "description": "DeepSeek R1 - Advanced reasoning - 64k context",
            "input_price": "$0.55/1M tokens",
            "output_price": "$2.19/1M tokens"
        },

        # OpenAI Models
        "openai/gpt-5": {
            "description": "GPT-5 - Next-gen OpenAI model - 200k context",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5-mini": {
            "description": "GPT-5 Mini - Fast & efficient - 128k context",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "openai/gpt-5-nano": {
            "description": "GPT-5 Nano - Ultra-fast & cheap - 64k context",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },

        # Anthropic Claude Models
        "anthropic/claude-haiku-4.5": {
            "description": "Claude Haiku 4.5 - Fast & efficient - 200k context",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },
        "anthropic/claude-opus-4.1": {
            "description": "Claude Opus 4.1 - Most powerful - 200k context",
            "input_price": "See openrouter.ai/docs",
            "output_price": "See openrouter.ai/docs"
        },

        # ============================================
        # 🐍 CODING SPECIALISTS - For RBI Backtester
        # ============================================

        # MiniMax Models - Best price/performance for coding (Dec 2025)
        "minimax/minimax-m2": {
            "description": "MiniMax M2 - 230B MoE (10B active) - 1M context - 74% SWE-bench",
            "input_price": "$0.20/1M tokens",
            "output_price": "$1.10/1M tokens"
        },
        "minimax/minimax-m2.1": {
            "description": "MiniMax M2.1 - Latest Dec 2025 - Best open-source coder",
            "input_price": "$0.20/1M tokens",
            "output_price": "$1.10/1M tokens"
        },
        "minimax/minimax-m2:free": {
            "description": "MiniMax M2 FREE - Same model, free tier",
            "input_price": "FREE",
            "output_price": "FREE"
        },

        # Kimi K2 Models - Strong agentic coding
        "moonshotai/kimi-k2": {
            "description": "Kimi K2 - 1T MoE (32B active) - 131K context - 65.8% SWE-bench",
            "input_price": "$0.55/1M tokens",
            "output_price": "$2.20/1M tokens"
        },
        "moonshotai/kimi-k2-thinking": {
            "description": "Kimi K2 Thinking - Extended reasoning chains",
            "input_price": "$0.55/1M tokens",
            "output_price": "$2.20/1M tokens"
        },
        "moonshotai/kimi-k2:free": {
            "description": "Kimi K2 FREE - Same model, free tier",
            "input_price": "FREE",
            "output_price": "FREE"
        },

        # Qwen Coder Models - Alibaba's coding specialist
        "qwen/qwen-2.5-coder-32b-instruct": {
            "description": "Qwen 2.5 Coder 32B - Coding specialist - 128K context",
            "input_price": "$0.50/1M tokens",
            "output_price": "$1.50/1M tokens"
        },

        # DeepSeek via OpenRouter (for comparison)
        "deepseek/deepseek-coder": {
            "description": "DeepSeek Coder - Code specialist - 64K context",
            "input_price": "$0.14/1M tokens",
            "output_price": "$0.28/1M tokens"
        },

        # 🌙 TradeHive: ADD MORE MODELS HERE!
        # Copy the format above and paste model info from https://openrouter.ai/docs
    }

    def __init__(self, api_key: str, model_name: str = "openrouter/auto", **kwargs):
        # Validate API key
        if not api_key or len(api_key.strip()) == 0:
            raise ValueError("API key is empty or None")

        self.model_name = model_name
        self.max_tokens = 4096  # 🌙 TradeHive: Default max tokens for OpenRouter
        super().__init__(api_key, **kwargs)

    def initialize_client(self, **kwargs) -> None:
        """Initialize the OpenRouter client (uses OpenAI SDK)"""
        # OpenRouter uses OpenAI-compatible API
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=20.0
        )
        cprint(f"✨ Initialized {self.model_name}", "green")

    def generate_response(self, system_prompt, user_content, temperature=0.7, max_tokens=None):
        """Generate response with no caching"""
        try:
            # Force unique request every time
            timestamp = int(time.time() * 1000)  # Millisecond precision

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{user_content}_{timestamp}"}  # Make each request unique
                ],
                temperature=temperature,
                max_tokens=max_tokens if max_tokens else self.max_tokens,
                stream=False  # Disable streaming to prevent caching
            )

            # Extract content and filter out thinking tags
            raw_content = response.choices[0].message.content

            # Remove <think>...</think> tags and their content (for reasoning models)
            import re

            # First, try to remove complete <think>...</think> blocks
            filtered_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

            # If <think> tag exists but wasn't removed (unclosed tag due to token limit),
            # remove everything from <think> onwards
            if '<think>' in filtered_content:
                filtered_content = filtered_content.split('<think>')[0].strip()

            # If filtering removed everything, return the original
            final_content = filtered_content if filtered_content else raw_content

            return ModelResponse(
                content=final_content,
                raw_response=response,
                model_name=self.model_name,
                usage=response.usage
            )

        except Exception as e:
            error_str = str(e)

            # Handle rate limit errors (429)
            if "429" in error_str or "rate_limit" in error_str:
                cprint(f"⚠️  OpenRouter rate limit exceeded", "yellow")
                cprint(f"   Model: {self.model_name}", "yellow")
                cprint(f"   💡 Skipping this model for this request...", "cyan")
                return None

            # Handle quota errors (402)
            if "402" in error_str or "insufficient" in error_str:
                cprint(f"⚠️  OpenRouter credits insufficient", "yellow")
                cprint(f"   Model: {self.model_name}", "yellow")
                cprint(f"   💡 Add credits at: https://openrouter.ai/credits", "cyan")
                return None

            # Raise 503 errors (service unavailable)
            if "503" in error_str:
                raise e

            # Log other errors
            cprint(f"❌ OpenRouter error: {error_str}", "red")
            return None

    def is_available(self) -> bool:
        """Check if OpenRouter is available"""
        return self.client is not None

    @property
    def model_type(self) -> str:
        return "openrouter"
