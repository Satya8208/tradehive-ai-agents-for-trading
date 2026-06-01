"""
Nirvana Nuts Twitter Growth Engine - Prompts & Modes
"""

# Mode definitions and constants
from .modes import (
    CORE_IDENTITY,
    MODE_PROMPTS,
    MODE_TEMPERATURES,
    ALL_MODES,
    CHALLENGE_MODES,
    ALIGN_MODES,
)

# Prompt templates
from .prompts import (
    IMAGE_ANALYZER_PROMPT,
    ANALYZER_PROMPT,
    IMAGE_REPLY_GENERATOR_PROMPT,
    REPLY_GENERATOR_PROMPT,
    TWEET_GENERATOR_PROMPT,
    THREAD_GENERATOR_PROMPT,
)

__all__ = [
    # Modes
    "CORE_IDENTITY",
    "MODE_PROMPTS",
    "MODE_TEMPERATURES",
    "ALL_MODES",
    "CHALLENGE_MODES",
    "ALIGN_MODES",
    # Prompts
    "IMAGE_ANALYZER_PROMPT",
    "ANALYZER_PROMPT",
    "IMAGE_REPLY_GENERATOR_PROMPT",
    "REPLY_GENERATOR_PROMPT",
    "TWEET_GENERATOR_PROMPT",
    "THREAD_GENERATOR_PROMPT",
]
