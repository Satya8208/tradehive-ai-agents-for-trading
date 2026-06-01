"""
ðŸŒ™ TradeHive's Groq Model Implementation
Built with love by TradeHive ðŸš€
"""

from groq import Groq
from termcolor import cprint
from .base_model import BaseModel, ModelResponse
import time

class GroqModel(BaseModel):
    """Implementation for Groq's models"""

    AVAILABLE_MODELS = {
        # Current Groq production and tool-capable models
        "openai/gpt-oss-120b": {
            "description": "GPT-OSS 120B on Groq - strong open-weight reasoning and coding",
            "input_price": "$0.15/1M tokens",
            "output_price": "$0.60/1M tokens"
        },
        "openai/gpt-oss-20b": {
            "description": "GPT-OSS 20B on Groq - fast open-weight model",
            "input_price": "$0.075/1M tokens",
            "output_price": "$0.30/1M tokens"
        },
        "openai/gpt-oss-safeguard-20b": {
            "description": "GPT-OSS Safeguard 20B on Groq",
            "input_price": "See Groq pricing",
            "output_price": "See Groq pricing"
        },
        "qwen/qwen3-32b": {
            "description": "Qwen 3 32B - production model with parallel tool use",
            "input_price": "$0.29/1M tokens",
            "output_price": "$0.59/1M tokens"
        },
        "meta-llama/llama-4-scout-17b-16e-instruct": {
            "description": "Llama 4 Scout 17B - current Groq-hosted Llama 4 model",
            "input_price": "See Groq pricing",
            "output_price": "See Groq pricing"
        },
        "llama-3.3-70b-versatile": {
            "description": "Llama 3.3 70B Versatile - Production - 128k context",
            "input_price": "$0.59/1M tokens",
            "output_price": "$0.79/1M tokens"
        },
        "llama-3.1-8b-instant": {
            "description": "Llama 3.1 8B Instant - Production - 128k context",
            "input_price": "$0.05/1M tokens",
            "output_price": "$0.08/1M tokens"
        },
        "groq/compound": {
            "description": "Groq Compound system with built-in tools",
            "input_price": "See Groq pricing",
            "output_price": "See Groq pricing"
        },
        "groq/compound-mini": {
            "description": "Lower-latency Groq Compound Mini system with built-in tools",
            "input_price": "See Groq pricing",
            "output_price": "See Groq pricing"
        },
        # Older/preview models kept for backward-compatible explicit requests.
        "mixtral-8x7b-32768": {
            "description": "Legacy Mixtral 8x7B entry; may not be available on current Groq accounts",
            "input_price": "$0.27/1M tokens",
            "output_price": "$0.27/1M tokens"
        },
        "gemma2-9b-it": {
            "description": "Legacy Google Gemma 2 9B entry; may not be available on current Groq accounts",
            "input_price": "$0.10/1M tokens",
            "output_price": "$0.10/1M tokens"
        },
        "deepseek-r1-distill-llama-70b": {
            "description": "DeepSeek R1 Distill Llama 70B - Preview - 128k context",
            "input_price": "$0.70/1M tokens",
            "output_price": "$0.90/1M tokens"
        }
    }

    def __init__(self, api_key: str, model_name: str = "openai/gpt-oss-120b", **kwargs):
        # Validate API key
        if not api_key or len(api_key.strip()) == 0:
            raise ValueError("API key is empty or None")

        # Validate model name
        if model_name not in self.AVAILABLE_MODELS:
            raise ValueError(f"Invalid model name: {model_name}")

        self.model_name = model_name
        super().__init__(api_key, **kwargs)

    def initialize_client(self, **kwargs) -> None:
        """Initialize the Groq client"""
        self.client = Groq(api_key=self.api_key)
        cprint(f"âœ¨ Initialized {self.model_name}", "green")

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

            # Remove <think>...</think> tags and their content (Qwen reasoning)
            import re

            # First, try to remove complete <think>...</think> blocks
            filtered_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

            # If <think> tag exists but wasn't removed (unclosed tag due to token limit),
            # remove everything from <think> onwards
            if '<think>' in filtered_content:
                filtered_content = filtered_content.split('<think>')[0].strip()

            # If filtering removed everything, return the original (in case it's not a Qwen model)
            final_content = filtered_content if filtered_content else raw_content

            return ModelResponse(
                content=final_content,
                raw_response=response,
                model_name=self.model_name,
                usage=response.usage
            )

        except Exception as e:
            error_str = str(e)

            # Handle rate limit errors (413)
            if "413" in error_str or "rate_limit_exceeded" in error_str:
                cprint(f"âš ï¸  Groq rate limit exceeded (request too large)", "yellow")
                cprint(f"   Model: {self.model_name}", "yellow")
                if "Requested" in error_str and "Limit" in error_str:
                    # Extract token info from error message
                    import re
                    limit_match = re.search(r'Limit (\d+)', error_str)
                    requested_match = re.search(r'Requested (\d+)', error_str)
                    if limit_match and requested_match:
                        cprint(f"   Limit: {limit_match.group(1)} tokens | Requested: {requested_match.group(1)} tokens", "yellow")
                cprint(f"   ðŸ’¡ Skipping this model for this request...", "cyan")
                return None

            # Raise 503 errors (service unavailable)
            if "503" in error_str:
                raise e

            # Log other errors
            cprint(f"âŒ Groq error: {error_str}", "red")
            return None

    def is_available(self) -> bool:
        """Check if Groq is available"""
        return self.client is not None

    @property
    def model_type(self) -> str:
        return "groq"
