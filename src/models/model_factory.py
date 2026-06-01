"""
TradeHive's Model Factory

This module manages all available AI models and provides a unified interface.
"""

import os
from typing import Dict, Optional, Type
from termcolor import cprint
from dotenv import load_dotenv
from pathlib import Path
from .base_model import BaseModel
from .claude_model import ClaudeModel
from .groq_model import GroqModel
from .openai_model import OpenAIModel
from .gemini_model import GeminiModel
from .deepseek_model import DeepSeekModel
from .ollama_model import OllamaModel
from .xai_model import XAIModel
from .openrouter_model import (
    OpenRouterModel,
)  # OpenRouter access to 200+ models
from .bridge_model import BridgeModel  # Bridge to subscription AI
import random


class ModelFactory:
    """Factory for creating and managing AI models"""

    # Map model types to their implementations
    MODEL_IMPLEMENTATIONS = {
        "claude": ClaudeModel,
        "groq": GroqModel,
        "openai": OpenAIModel,
        "gemini": GeminiModel,
        "deepseek": DeepSeekModel,
        "ollama": OllamaModel,  # Add Ollama implementation
        "xai": XAIModel,  # xAI Grok models
        "openrouter": OpenRouterModel,  # OpenRouter - 200+ models
        "bridge": BridgeModel,  # Bridge to subscription AI (Claude Code / Kimi)
    }

    # Default models for each type
    DEFAULT_MODELS = {
        "claude": "claude-opus-4-7",  # Latest Claude API model visible to this key
        "groq": "openai/gpt-oss-120b",  # Current Groq production reasoning/code model
        "openai": "gpt-5.5",  # Latest OpenAI flagship in official docs
        "gemini": "gemini-3.1-pro-preview",  # Current Gemini Pro preview in official docs
        "deepseek": "deepseek-v4-pro",  # Current DeepSeek v4 Pro API model
        "ollama": "llama4",  # Meta's latest Ollama library Llama family default
        "xai": "grok-4.3",  # Current xAI flagship model visible to this API key
        "openrouter": "openrouter/auto",  # OpenRouter auto-router tracks current frontier models
        "bridge": "subscription-ai",  # Bridge - uses your Claude Code / Kimi subscription
    }

    def __init__(self):
        # Load environment variables
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / ".env"
        load_dotenv(dotenv_path=env_path)

        self._models: Dict[str, BaseModel] = {}
        self._initialize_models()

    def _initialize_models(self):
        """Initialize all available models"""
        # Try to initialize each model type silently
        for model_type, key_name in self._get_api_key_mapping().items():
            if api_key := os.getenv(key_name):
                try:
                    if model_type in self.MODEL_IMPLEMENTATIONS:
                        model_class = self.MODEL_IMPLEMENTATIONS[model_type]
                        model_instance = model_class(
                            api_key,
                            model_name=self.DEFAULT_MODELS.get(model_type),
                        )

                        if model_instance.is_available():
                            self._models[model_type] = model_instance
                            # Just show the ready message
                            cprint(f"{model_instance.model_name} ready", "green")
                except:
                    pass  # Silently skip failed models

        # Initialize Ollama separately (no API key needed)
        try:
            model_class = self.MODEL_IMPLEMENTATIONS["ollama"]
            model_instance = model_class(model_name=self.DEFAULT_MODELS["ollama"])

            if model_instance.is_available():
                self._models["ollama"] = model_instance
                cprint(f"{model_instance.model_name} ready", "green")
        except:
            pass  # Silently skip if Ollama not available

        # Initialize Bridge separately (no API key needed - uses your subscription AI)
        try:
            model_class = self.MODEL_IMPLEMENTATIONS["bridge"]
            model_instance = model_class(model_name=self.DEFAULT_MODELS["bridge"])

            if model_instance.is_available():
                self._models["bridge"] = model_instance
                cprint("Bridge to subscription AI ready", "green")
            else:
                # Bridge is always "available" as a model type, just may not have server running
                self._models["bridge"] = model_instance
                cprint("Bridge model loaded (start server with: python src/bridge_server.py)", "yellow")
        except:
            pass  # Silently skip if bridge init fails

        if not self._models:
            cprint("WARNING: No AI models available - check API keys in .env", "yellow")

    def get_model(
        self, model_type: str, model_name: Optional[str] = None
    ) -> Optional[BaseModel]:
        """Get a specific model instance"""
        if (
            model_type not in self.MODEL_IMPLEMENTATIONS
            or model_type not in self._models
        ):
            return None

        model = self._models[model_type]
        if model_name and model.model_name != model_name:
            try:
                # Special handling for Ollama and Bridge models (no API key needed)
                if model_type in ("ollama", "bridge"):
                    model = self.MODEL_IMPLEMENTATIONS[model_type](
                        model_name=model_name
                    )
                else:
                    # For API-based models that need a key
                    if api_key := os.getenv(self._get_api_key_mapping()[model_type]):
                        model = self.MODEL_IMPLEMENTATIONS[model_type](
                            api_key, model_name=model_name
                        )
                    else:
                        return None

                self._models[model_type] = model
            except:
                return None

        return model

    def _get_api_key_mapping(self) -> Dict[str, str]:
        """Get mapping of model types to their API key environment variable names"""
        return {
            "claude": "ANTHROPIC_KEY",
            "groq": "GROQ_API_KEY",
            "openai": "OPENAI_KEY",
            "gemini": "GEMINI_KEY",
            "deepseek": "DEEPSEEK_KEY",
            "xai": "GROK_API_KEY",  # Grok/xAI uses GROK_API_KEY
            "openrouter": "OPENROUTER_API_KEY",  # OpenRouter
            # Ollama doesn't need an API key as it runs locally
        }

    @property
    def available_models(self) -> Dict[str, list]:
        """Get all available models and their configurations"""
        return {
            model_type: model.AVAILABLE_MODELS
            for model_type, model in self._models.items()
        }

    def is_model_available(self, model_type: str) -> bool:
        """Check if a specific model type is available"""
        return model_type in self._models and self._models[model_type].is_available()

    def generate_response(
        self, system_prompt, user_content, temperature=0.7, max_tokens=None
    ):
        """Generate a response from the model with no caching"""
        try:
            # Add random nonce to prevent caching
            nonce = f"_{random.randint(1, 1000000)}"

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"{user_content}{nonce}",
                    },  # Add nonce to force new response
                ],
                temperature=temperature,
                max_tokens=max_tokens if max_tokens else self.max_tokens,
            )

            return response.choices[0].message

        except Exception as e:
            if "503" in str(e):
                raise e  # Let the retry logic handle 503s
            cprint(f"Model error: {str(e)}", "red")
            return None


# Create a singleton instance
model_factory = ModelFactory()
