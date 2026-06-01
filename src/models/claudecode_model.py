"""
🌙 TradeHive's Claude Code Model Implementation
Built with love by TradeHive 🚀

This model uses the Claude Code CLI (your subscription) instead of API calls.
No API costs - just uses your Claude Code subscription!

Usage:
    model = ClaudeCodeModel()
    response = model.generate_response(system_prompt, user_content)
"""

import subprocess
import shutil
import json
from termcolor import cprint
from .base_model import BaseModel, ModelResponse


class ClaudeCodeModel(BaseModel):
    """Implementation that uses Claude Code CLI instead of API calls"""

    AVAILABLE_MODELS = {
        "claude-code": "Claude Code CLI - Uses your subscription, no API costs!",
        "claude-code-opus": "Claude Code with Opus 4.7 (uses --model opus)",
        "claude-code-sonnet": "Claude Code with Sonnet (uses --model sonnet)",
        "claude-code-haiku": "Claude Code with Haiku (uses --model haiku)",
    }

    def __init__(self, api_key: str = None, model_name: str = "claude-code", **kwargs):
        """
        Initialize Claude Code model.

        Args:
            api_key: Not needed for Claude Code (uses CLI auth)
            model_name: One of claude-code, claude-code-opus, claude-code-sonnet, claude-code-haiku
        """
        self.model_name = model_name
        self._cli_available = False
        self._cli_path = None

        # Map model names to CLI model flags
        self._model_flags = {
            "claude-code": None,  # Use default
            "claude-code-opus": "opus",
            "claude-code-sonnet": "sonnet",
            "claude-code-haiku": "haiku",
        }

        # Don't call parent init since we don't need API key
        self.api_key = None
        self.client = None
        self.initialize_client(**kwargs)

    def initialize_client(self, **kwargs) -> None:
        """Check if Claude Code CLI is available"""
        try:
            # Find claude CLI
            self._cli_path = shutil.which("claude")

            if self._cli_path:
                # Verify it works by checking version
                result = subprocess.run(
                    [self._cli_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    self._cli_available = True
                    version = result.stdout.strip() or result.stderr.strip()
                    cprint(f"✨ Initialized Claude Code CLI: {self.model_name}", "green")
                    cprint(f"   CLI: {self._cli_path}", "grey")
                    if version:
                        cprint(f"   Version: {version}", "grey")
                else:
                    cprint(f"❌ Claude CLI found but returned error", "red")
                    self._cli_available = False
            else:
                cprint("❌ Claude Code CLI not found in PATH", "red")
                cprint("   Install with: npm install -g @anthropic-ai/claude-code", "yellow")
                self._cli_available = False

        except subprocess.TimeoutExpired:
            cprint("❌ Claude CLI timed out during initialization", "red")
            self._cli_available = False
        except Exception as e:
            cprint(f"❌ Failed to initialize Claude Code CLI: {str(e)}", "red")
            self._cli_available = False

    def generate_response(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> ModelResponse:
        """
        Generate a response using Claude Code CLI.

        Note: Claude Code CLI handles temperature/tokens differently than API.
        These params are included for compatibility but may not be used.
        """
        if not self._cli_available:
            raise RuntimeError("Claude Code CLI is not available")

        try:
            # Combine system prompt and user content
            # Claude Code works best with a clear prompt structure
            full_prompt = f"""<system>
{system_prompt}
</system>

<user>
{user_content}
</user>

Respond directly without any preamble."""

            # Build command
            cmd = [self._cli_path, "--print"]

            # Add model flag if specified
            model_flag = self._model_flags.get(self.model_name)
            if model_flag:
                cmd.extend(["--model", model_flag])

            # Add the prompt
            cmd.extend(["--", full_prompt])

            cprint(f"🚀 Running Claude Code CLI...", "cyan")

            # Run the command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for complex prompts
                cwd=None  # Use current directory
            )

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                cprint(f"❌ Claude Code CLI error: {error_msg}", "red")
                raise RuntimeError(f"Claude Code CLI failed: {error_msg}")

            response_text = result.stdout.strip()

            if not response_text:
                cprint("⚠️ Empty response from Claude Code CLI", "yellow")
                response_text = ""

            return ModelResponse(
                content=response_text,
                raw_response={"stdout": result.stdout, "stderr": result.stderr},
                model_name=self.model_name,
                usage={"note": "Claude Code CLI - no token count available"}
            )

        except subprocess.TimeoutExpired:
            cprint("❌ Claude Code CLI timed out", "red")
            raise RuntimeError("Claude Code CLI timed out after 5 minutes")
        except Exception as e:
            cprint(f"❌ Claude Code generation error: {str(e)}", "red")
            raise

    def generate_response_with_image(
        self,
        system_prompt: str,
        user_content: str,
        image_data: str,
        image_media_type: str = "image/png",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs
    ) -> ModelResponse:
        """
        Generate a response with image input.

        Note: Claude Code CLI has limited image support via CLI.
        For image analysis, consider saving the image temporarily and referencing it.
        """
        cprint("⚠️ Image support via Claude Code CLI is limited", "yellow")
        cprint("   Falling back to text-only mode", "yellow")

        # For now, fall back to text-only
        # Could potentially save image to temp file and include path
        return self.generate_response(
            system_prompt=system_prompt,
            user_content=f"[Image was provided but CLI doesn't support base64 images directly]\n\n{user_content}",
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    def is_available(self) -> bool:
        """Check if Claude Code CLI is available"""
        return self._cli_available

    @property
    def model_type(self) -> str:
        return "claudecode"


# Convenience function for quick testing
def test_claudecode_model():
    """Quick test of Claude Code model"""
    model = ClaudeCodeModel()

    if not model.is_available():
        cprint("Claude Code CLI not available!", "red")
        return

    response = model.generate_response(
        system_prompt="You are a helpful assistant.",
        user_content="Say 'Hello from Claude Code!' and nothing else."
    )

    cprint(f"\n✅ Response: {response.content}", "green")


if __name__ == "__main__":
    test_claudecode_model()
