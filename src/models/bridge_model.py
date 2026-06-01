"""
🌉 TradeHive's Bridge Model
Built with love by TradeHive 🚀

HTTP Bridge Model - Routes AI requests to subscription AI (Claude Code / Kimi)
instead of paying per-token API costs.
"""
from src.models.base_model import BaseModel, ModelResponse
import requests
import os
import base64
from pathlib import Path
from termcolor import cprint

BRIDGE_URL = os.getenv('BRIDGE_URL', 'http://localhost:9999/generate')
BRIDGE_TIMEOUT = int(os.getenv('BRIDGE_TIMEOUT', 300))  # 5 min default


class BridgeModel(BaseModel):
    """Routes AI requests through HTTP bridge to subscription AI"""

    def __init__(self, api_key: str = None, model_name: str = "bridge", **kwargs):
        self.model_name = model_name
        self.max_tokens = kwargs.get('max_tokens', 2000)
        self.client = None
        # No API key needed - uses your subscription AI

    def initialize_client(self, **kwargs):
        """No client to initialize - we use HTTP requests"""
        pass

    def generate_response(self, system_prompt, user_content, temperature=0.7, max_tokens=None):
        """Send request to bridge server and wait for human-relayed response"""
        payload = {
            "system_prompt": system_prompt,
            "user_content": user_content,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens
        }

        try:
            response = requests.post(BRIDGE_URL, json=payload, timeout=BRIDGE_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            return ModelResponse(
                content=data.get('content', ''),
                raw_response=data,
                model_name=data.get('model', 'subscription-ai'),
                usage=data.get('usage')
            )
        except requests.exceptions.Timeout:
            raise Exception("Bridge timeout - did you respond in the bridge server?")
        except requests.exceptions.ConnectionError:
            raise Exception("Bridge server not running! Start it with: python src/bridge_server.py")
        except Exception as e:
            raise Exception(f"Bridge error: {e}")

    def generate_response_with_image(self, system_prompt, user_content, image_data,
                                     image_media_type="image/png", temperature=0.7, max_tokens=None):
        """Handle image requests by saving image for user to view"""
        # Save image to temp file for user to view
        temp_dir = Path("src/data/bridge_temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / "temp_image.png"

        try:
            temp_path.write_bytes(base64.b64decode(image_data))
            enhanced_content = f"{user_content}\n\n[IMAGE ATTACHED - {image_media_type}]\n[Image saved to: {temp_path.absolute()}]"
        except Exception as e:
            enhanced_content = f"{user_content}\n\n[IMAGE ATTACHED - {image_media_type}]\n[Could not save image: {e}]"

        return self.generate_response(system_prompt, enhanced_content, temperature, max_tokens)

    def is_available(self):
        """Check if bridge server is running"""
        try:
            health_url = BRIDGE_URL.replace('/generate', '/health')
            response = requests.get(health_url, timeout=5)
            return response.status_code == 200
        except:
            return False

    @property
    def model_type(self):
        return "bridge"
