"""Shared pytest fixtures and environment defaults for the test suite."""

import os

# Allow imports of modules that optionally read trading/LLM credentials at runtime.
os.environ.setdefault("BIRDEYE_API_KEY", "test_birdeye_key")
os.environ.setdefault("ANTHROPIC_KEY", "test_anthropic_key")
os.environ.setdefault("OPENAI_KEY", "test_openai_key")
