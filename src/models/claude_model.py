"""
TradeHive's Claude Model Implementation
"""

from anthropic import Anthropic
from termcolor import cprint
from .base_model import BaseModel, ModelResponse

class ClaudeModel(BaseModel):
    """Implementation for Anthropic's Claude models"""

    AVAILABLE_MODELS = {
        # Current official Claude 4 family
        "claude-opus-4-7": "Claude Opus 4.7 - latest and most capable Claude API model",
        "claude-sonnet-4-6": "Claude Sonnet 4.6 - latest Sonnet model",
        "claude-opus-4-6": "Claude Opus 4.6 - previous Opus model",
        "claude-opus-4-5-20251101": "Claude Opus 4.5 - previous frontier model",
        "claude-haiku-4-5-20251001": "Claude Haiku 4.5 - latest Haiku model",
        "claude-opus-4-1-20250805": "Claude Opus 4.1 - older official snapshot",
        "claude-opus-4-1": "Claude Opus 4.1 alias",
        "claude-opus-4-20250514": "Claude Opus 4 - previous flagship snapshot",
        "claude-opus-4-0": "Claude Opus 4 alias",
        "claude-sonnet-4-20250514": "Claude Sonnet 4 - Great balance of speed and intelligence",
        "claude-sonnet-4-0": "Claude Sonnet 4 alias",

        # Claude 3.7
        "claude-3-7-sonnet-20250219": "Claude Sonnet 3.7 - high-performance extended-thinking model",
        "claude-3-7-sonnet-latest": "Claude Sonnet 3.7 latest alias",

        # Claude 3.5 Series (Excellent for most tasks)
        "claude-3-5-sonnet-latest": "Claude 3.5 Sonnet - Great for creative content",
        "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (pinned version)",
        "claude-3-5-haiku-latest": "Claude 3.5 Haiku - Fast & efficient",
        "claude-3-5-haiku-20241022": "Claude 3.5 Haiku (pinned version)",

        # Claude 3 Series (Legacy but stable)
        "claude-3-opus-20240229": "Claude 3 Opus - Previous gen powerhouse",
        "claude-3-sonnet-20240229": "Claude 3 Sonnet - Previous gen balanced",
        "claude-3-haiku-20240307": "Claude 3 Haiku - Previous gen fast"
    }

    def __init__(self, api_key: str, model_name: str = "claude-opus-4-7", **kwargs):
        self.model_name = model_name
        super().__init__(api_key, **kwargs)

    def initialize_client(self, **kwargs) -> None:
        """Initialize the Anthropic client"""
        try:
            self.client = Anthropic(api_key=self.api_key)
            cprint(f"Initialized Claude model: {self.model_name}", "green")
        except Exception as e:
            cprint(f"Failed to initialize Claude model: {str(e)}", "red")
            self.client = None

    def generate_response(self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> ModelResponse:
        """Generate a response using Claude"""
        try:
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_content}
                ]
            )

            return ModelResponse(
                content=response.content[0].text.strip(),
                raw_response=response,
                model_name=self.model_name,
                usage={"completion_tokens": response.usage.output_tokens}
            )

        except Exception as e:
            cprint(f"Claude generation error: {str(e)}", "red")
            raise

    def generate_response_with_image(self,
        system_prompt: str,
        user_content: str,
        image_data: str,
        image_media_type: str = "image/png",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> ModelResponse:
        """Generate a response using Claude with image input (vision)"""
        try:
            # Build message with image content
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_media_type,
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": user_content
                        }
                    ]
                }
            ]

            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=messages
            )

            return ModelResponse(
                content=response.content[0].text.strip(),
                raw_response=response,
                model_name=self.model_name,
                usage={"completion_tokens": response.usage.output_tokens}
            )

        except Exception as e:
            cprint(f"Claude vision error: {str(e)}", "red")
            raise

    def is_available(self) -> bool:
        """Check if Claude is available"""
        return self.client is not None

    @property
    def model_type(self) -> str:
        return "claude"
