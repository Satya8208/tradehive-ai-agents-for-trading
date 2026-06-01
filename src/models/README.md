# 🌙 TradeHive's Model Factory

A unified interface for managing multiple AI model providers. This module handles initialization, API key management, and provides a consistent interface for generating responses across different AI models.

## 🔑 Required API Keys

Add these to your `.env` file in the project root:
```env
ANTHROPIC_KEY=your_key_here    # For Claude models
GROQ_API_KEY=your_key_here     # For Groq models (includes Mixtral, Llama, etc.)
OPENAI_KEY=your_key_here       # For OpenAI models (GPT-4, O1, etc.)
DEEPSEEK_KEY=your_key_here     # For DeepSeek models
```

## 🤖 Available Models

### OpenAI Models
Latest Models:
- `gpt-5.5`: latest OpenAI flagship in the official OpenAI model docs
- `gpt-5.4`: more affordable current frontier model
- `gpt-5.4-mini`: current mini model for coding, computer use, and subagents
- `gpt-5.4-nano`: lowest-latency current GPT-5.4 family model
- `gpt-5.2`: previous GPT-5.2 family model kept for explicit compatibility
- `gpt-5`, `gpt-5-mini`, `gpt-5-nano`: prior GPT-5 family models
- `o3`, `o4-mini`: older reasoning models kept for explicit compatibility

### Claude Models (Anthropic)
Latest Models:
- `claude-opus-4-7`: latest and most capable Claude API model
- `claude-sonnet-4-6`: latest Sonnet model
- `claude-opus-4-6`: previous Opus model
- `claude-haiku-4-5-20251001`: latest Haiku model
- `claude-opus-4-1-20250805`: older official Opus snapshot
- `claude-3-7-sonnet-20250219`: high-performance extended-thinking model
- `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022`: older but stable fallbacks

### Groq Models
Production Models:
- `openai/gpt-oss-120b`: current default Groq model for reasoning/code
- `openai/gpt-oss-20b`: faster GPT-OSS model
- `qwen/qwen3-32b`: current Qwen 3 production model
- `meta-llama/llama-4-scout-17b-16e-instruct`: current Llama 4 Scout model
- `llama-3.3-70b-versatile`: stable Llama fallback
- `llama-3.1-8b-instant`: fast low-latency fallback
- `groq/compound`, `groq/compound-mini`: Groq tool-using systems

### DeepSeek Models
- `deepseek-v4-pro`: current DeepSeek Pro default
- `deepseek-v4-flash`: current fast DeepSeek model
- `deepseek-chat`: compatibility alias for v4 Flash non-thinking mode; deprecates 2026-07-24
- `deepseek-reasoner`: compatibility alias for v4 Flash thinking mode; deprecates 2026-07-24

### Gemini Models
- `gemini-3.1-pro-preview`: current Gemini Pro preview and the factory default
- `gemini-3.5-flash`: stable Gemini 3.5 Flash model
- `gemini-3.1-flash-lite`: stable fast Gemini 3.1 Flash-Lite model
- `gemini-3-flash-preview`: latest Gemini Flash preview
- `gemini-3-pro-image-preview`: Gemini 3 image-capable preview
- `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`: stable Gemini 2.5 fallbacks

### Local Ollama: Free, Fast, Private LLMs 🚀

To get started with Ollama:
1. Install Ollama: `curl https://ollama.ai/install.sh | sh`
2. Start the server: `ollama serve`
3. Pull our models:
   ```bash
   ollama pull llama4          # Meta's latest Llama family model in Ollama
   ollama pull deepseek-r1      # DeepSeek R1 7B - shows thinking process
   ollama pull gemma:2b         # Google's Gemma 2B - fast responses
   ```
4. Check they're ready: `ollama list`

Available Models:
- `llama4`: Latest Llama family default in the Ollama library
- `llama4:16x17b`: Llama 4 Scout
- `llama4:128x17b`: Llama 4 Maverick
- `qwen3`: Qwen 3 latest generation family
- `deepseek-r1`: Good for complex reasoning (7B parameters), shows thinking process with <think> tags
- `gemma:2b`: Fast and efficient for simple tasks, great for high-volume processing
- `llama3.2`: Balanced model good for most tasks, especially good at following instructions

Benefits:
- 🚀 Free to use - no API costs
- 🔒 Private - runs 100% local
- ⚡ Fast responses
- 🤔 DeepSeek shows thinking process
- 🛠️ Full model control

Usage Example:
```python
from src.models import model_factory

# Initialize with Llama 4 for the latest Ollama-hosted Llama family
model = factory.get_model("ollama", "llama4")

# Or use DeepSeek R1 for complex reasoning
model = factory.get_model("ollama", "deepseek-r1")

# Or Gemma for faster responses
model = factory.get_model("ollama", "gemma:2b")

# For the most powerful reasoning, use DeepSeek API
model = factory.get_model("deepseek", "deepseek-v4-pro")
```

Interesting models for future use:
- gemma - for quick llm tasks https://huggingface.co/google/gemma-2-9b
- coqui - for voice locally https://huggingface.co/coqui/XTTS-v2

## 🚀 Usage Example

```python
from src.models import model_factory

# Initialize the model factory
factory = model_factory.ModelFactory()

# Get a specific model
model = factory.get_model("openai", "gpt-5.5")

# Generate a response
response = model.generate_response(
    system_prompt="You are a helpful AI assistant.",
    user_content="Hello!",
    temperature=0.7,  # Optional: Control randomness (0.0-1.0)
    max_tokens=1024   # Optional: Control response length
)

print(response.content)
```

## 🌟 Features
- Unified interface for multiple AI providers
- Automatic API key validation and error handling
- Detailed debugging output with emojis
- Easy model switching with consistent interface
- Consistent response format across all providers
- Automatic handling of model-specific features:
  - Reasoning process display (O1, DeepSeek R1)
  - Context window management
  - Token counting and limits
  - Error recovery and retries

## 🔄 Model Updates
New models are regularly added to the factory. Check the TradeHive Discord or GitHub for announcements about new models and features.

## 🐛 Troubleshooting
- If a model fails to initialize, check your API key in the `.env` file
- Some models (O1, DeepSeek R1) show their thinking process - this is normal
- For rate limit errors, try using a different model or wait a few minutes
- Watch TradeHive's streams for live debugging and updates: [@tradehiveonyt](https://www.youtube.com/@tradehiveonyt)

## 🤝 Contributing
Feel free to contribute new models or improvements! Join the TradeHive community:
- YouTube: [@tradehiveonyt](https://www.youtube.com/@tradehiveonyt)
- GitHub: [tradehive-ai-agents-for-trading](https://github.com/tradehive-ai-agents-for-trading)

Built with 💖 by TradeHive 🌙
