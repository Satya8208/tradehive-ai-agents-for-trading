"""
TradeHive's DeepSeek Model Implementation
"""

from openai import OpenAI
from termcolor import cprint
from .base_model import BaseModel, ModelResponse

class DeepSeekModel(BaseModel):
    """Implementation for DeepSeek's models"""

    AVAILABLE_MODELS = {
        "deepseek-v4-pro": "Current DeepSeek v4 Pro model",
        "deepseek-v4-flash": "Current DeepSeek v4 Flash model",
        "deepseek-chat": "Compatibility alias for DeepSeek v4 Flash non-thinking mode; deprecates 2026-07-24",
        "deepseek-reasoner": "Compatibility alias for DeepSeek v4 Flash thinking mode; deprecates 2026-07-24"
    }

    def __init__(self, api_key: str, model_name: str = "deepseek-v4-pro", base_url: str = "https://api.deepseek.com", **kwargs):
        self.model_name = model_name
        self.base_url = base_url
        super().__init__(api_key, **kwargs)

    def initialize_client(self, **kwargs) -> None:
        """Initialize the DeepSeek client"""
        try:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=20.0
            )
            cprint(f"Initialized DeepSeek model: {self.model_name}", "green")
        except Exception as e:
            cprint(f"Failed to initialize DeepSeek model: {str(e)}", "red")
            self.client = None

    def generate_response(self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> ModelResponse:
        """Generate a response using DeepSeek"""
        try:
            request_kwargs = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "max_tokens": max_tokens,
                "stream": False
            }

            thinking = kwargs.pop("thinking", None)
            if thinking is not None:
                extra_body = dict(kwargs.pop("extra_body", {}) or {})
                extra_body["thinking"] = {
                    "type": "enabled" if bool(thinking) else "disabled"
                }
                request_kwargs["extra_body"] = extra_body

            if thinking:
                request_kwargs["reasoning_effort"] = kwargs.pop(
                    "reasoning_effort",
                    "high",
                )
            else:
                request_kwargs["temperature"] = temperature

            for optional_key in (
                "response_format",
                "tools",
                "tool_choice",
                "reasoning_effort",
            ):
                if optional_key in kwargs:
                    request_kwargs[optional_key] = kwargs.pop(optional_key)

            if "extra_body" in kwargs:
                merged = dict(request_kwargs.get("extra_body") or {})
                merged.update(dict(kwargs.pop("extra_body") or {}))
                request_kwargs["extra_body"] = merged

            response = self.client.chat.completions.create(
                **request_kwargs
            )

            return ModelResponse(
                content=response.choices[0].message.content.strip(),
                raw_response=response,
                model_name=self.model_name,
                usage=response.usage.model_dump() if hasattr(response, 'usage') else None
            )

        except Exception as e:
            cprint(f"DeepSeek generation error: {str(e)}", "red")
            raise

    def is_available(self) -> bool:
        """Check if DeepSeek is available"""
        return self.client is not None

    @property
    def model_type(self) -> str:
        return "deepseek"
