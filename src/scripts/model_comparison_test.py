"""
Model Comparison Test for Twitter Agents
Compare quality across ALL available models for Nirvana Nuts / Blackjack Twitter

Tests the same prompt across every model and shows side-by-side comparison.
Run: python src/scripts/model_comparison_test.py
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from termcolor import cprint, colored
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from src.models.model_factory import ModelFactory

# ============================================
# MODEL CONFIGURATIONS WITH PRICING
# Pricing per 1M tokens (input, output)
# ============================================

MODEL_CONFIGS = {
    # Claude Models - The current baseline
    "claude": [
        {"name": "claude-sonnet-4-6", "label": "Sonnet 4.6", "input_price": 3.00, "output_price": 15.00},
        {"name": "claude-3-5-haiku-latest", "label": "Haiku 3.5", "input_price": 0.80, "output_price": 4.00},
        # {"name": "claude-opus-4-7", "label": "Opus 4.7", "input_price": 15.00, "output_price": 75.00},  # Expensive, skip unless needed
    ],
    # OpenAI Models
    "openai": [
        {"name": "gpt-5.5", "label": "GPT-5.5", "input_price": 5.00, "output_price": 30.00},
        {"name": "gpt-5.4-mini", "label": "GPT-5.4 mini", "input_price": 0.75, "output_price": 4.50},
    ],
    # DeepSeek Models - Great value
    "deepseek": [
        {"name": "deepseek-v4-flash", "label": "DeepSeek V4 Flash", "input_price": 0.27, "output_price": 1.10},
    ],
    # Groq Models - Fast inference
    "groq": [
        {"name": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B", "input_price": 0.59, "output_price": 0.79},
        {"name": "mixtral-8x7b-32768", "label": "Mixtral 8x7B", "input_price": 0.24, "output_price": 0.24},
    ],
    # xAI Grok Models
    "xai": [
        {"name": "grok-4-fast", "label": "Grok-4-Fast", "input_price": 2.00, "output_price": 10.00},
    ],
    # Gemini Models - Very cheap
    "gemini": [
        {"name": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "input_price": 0.075, "output_price": 0.30},
    ],
}

# ============================================
# TEST PROMPTS (from Nirvana Nuts)
# ============================================

CORE_IDENTITY = """You are Nirvana Nuts - a savage, philosophical Twitter voice.

CORE PRINCIPLES:
- Never explain the joke
- Paradox reveals truth
- Challenge ideas, not people
- Every word earns its place
- Brevity is power

VALUE-FIRST:
- Fresh insights only - pass the "Would I bookmark this?" test
- After observation, hint at WHAT TO DO with it

ENGAGEMENT:
- NO begging ("like if", "retweet if")
- Take a stance OR invite perspective

CHARACTER LIMIT: Under 280 characters. No hashtags. No emojis unless perfect. Don't start with "I".
"""

SAVAGE_MODE = """MODE: SAVAGE
You see through BS and name it with surgical precision. Not mean - accurate in ways that sting because they're true.

SIGNATURE PATTERNS:
1. THE EXPOSURE - Find the hidden flaw, hold up a mirror
   "You're not [what they claim]. You're [what they actually are]."

2. THE FLIP - Take their point and flip it back
   "Funny how people who [X] are usually [opposite]."

EXAMPLES:
- "Your morning routine isn't discipline. It's a costume for your anxiety."
- "The hustle you worship is just anxiety wearing a productivity costume."

NEVER:
- Be mean without insight
- Attack the person, only the idea
- Go over 2 sentences
"""

REPLY_PROMPT_TEMPLATE = """{core_identity}

{mode_prompt}

TWEET TO REPLY TO:
"{tweet}"

Generate ONE killer reply in SAVAGE mode.
- Must be under 280 characters
- Be engaging and shareable
- No hashtags, no emojis, no "I" starts

Return ONLY the reply text, nothing else.
"""

# Test tweets
TEST_TWEETS = [
    "I wake up at 4am every day and work 16 hour days. That's the secret to success.",
    "Just quit my 6-figure job to follow my passion. Scared but excited!",
    "Networking is just being fake nice to people you don't like for career benefits.",
]


def calculate_cost(input_tokens: int, output_tokens: int, input_price: float, output_price: float) -> float:
    """Calculate cost in dollars"""
    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price
    return input_cost + output_cost


def test_model(factory: ModelFactory, model_type: str, model_config: dict, tweet: str) -> dict:
    """Test a single model and return results"""
    model_name = model_config["name"]
    label = model_config["label"]

    try:
        model = factory.get_model(model_type, model_name)
        if not model:
            return {"error": f"Model not available", "label": label}

        prompt = REPLY_PROMPT_TEMPLATE.format(
            core_identity=CORE_IDENTITY,
            mode_prompt=SAVAGE_MODE,
            tweet=tweet
        )

        start_time = time.time()
        response = model.generate_response(
            system_prompt="You are a Twitter engagement expert. Generate viral replies.",
            user_content=prompt,
            temperature=0.75,
            max_tokens=200
        )
        elapsed = time.time() - start_time

        if response and response.content:
            # Estimate tokens (rough: 4 chars per token)
            input_tokens = len(prompt) // 4
            output_tokens = len(response.content) // 4

            cost = calculate_cost(
                input_tokens,
                output_tokens,
                model_config["input_price"],
                model_config["output_price"]
            )

            reply = response.content.strip().strip('"').strip("'")
            # Remove any "REPLY:" prefix if present
            if "REPLY:" in reply:
                reply = reply.split("REPLY:")[-1].strip()

            return {
                "label": label,
                "model_name": model_name,
                "model_type": model_type,
                "reply": reply,
                "chars": len(reply),
                "time_sec": round(elapsed, 2),
                "cost_usd": round(cost, 6),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        else:
            return {"error": "Empty response", "label": label}

    except Exception as e:
        return {"error": str(e), "label": label}


def run_comparison(tweet: str = None):
    """Run comparison across all available models"""

    cprint("\n" + "=" * 70, "cyan")
    cprint("   MODEL COMPARISON TEST - Twitter Reply Quality", "cyan", attrs=["bold"])
    cprint("   Testing ALL models to find best quality/cost ratio", "white")
    cprint("=" * 70, "cyan")

    # Use provided tweet or default
    if not tweet:
        tweet = TEST_TWEETS[0]

    cprint(f"\n📝 TEST TWEET:", "yellow", attrs=["bold"])
    cprint(f'   "{tweet}"', "white")

    # Initialize factory
    cprint("\n🔧 Initializing models...\n", "cyan")
    factory = ModelFactory()

    results = []
    available_count = 0
    tested_count = 0

    cprint("-" * 70, "grey")
    cprint("   GENERATING REPLIES FROM ALL MODELS...", "yellow", attrs=["bold"])
    cprint("-" * 70, "grey")

    for model_type, configs in MODEL_CONFIGS.items():
        # Check if this model type is available
        if not factory.is_model_available(model_type):
            cprint(f"\n⏭️  {model_type.upper()} - Skipped (no API key)", "grey")
            continue

        available_count += len(configs)
        cprint(f"\n🎯 {model_type.upper()}", "cyan", attrs=["bold"])

        for config in configs:
            tested_count += 1
            cprint(f"   Testing {config['label']}...", "white", end=" ")

            result = test_model(factory, model_type, config, tweet)
            results.append(result)

            if "error" in result:
                cprint(f"❌ {result['error']}", "red")
            else:
                cprint(f"✅ {result['time_sec']}s, ${result['cost_usd']:.6f}", "green")

    # Display results
    cprint("\n" + "=" * 70, "cyan")
    cprint("   RESULTS - SIDE BY SIDE COMPARISON", "cyan", attrs=["bold"])
    cprint("=" * 70, "cyan")

    successful_results = [r for r in results if "error" not in r]

    if not successful_results:
        cprint("\n❌ No models were able to generate responses!", "red")
        cprint("Check your API keys in .env file", "yellow")
        return results

    # Sort by cost (cheapest first)
    successful_results.sort(key=lambda x: x["cost_usd"])

    # Find Sonnet baseline for comparison
    baseline = next((r for r in successful_results if "Sonnet" in r["label"]), successful_results[-1])
    baseline_cost = baseline["cost_usd"]

    for i, result in enumerate(successful_results, 1):
        cprint(f"\n{'─' * 60}", "grey")

        # Calculate savings vs baseline
        if baseline_cost > 0:
            savings = ((baseline_cost - result["cost_usd"]) / baseline_cost) * 100
            savings_str = f"{savings:.0f}% cheaper" if savings > 0 else ("BASELINE" if savings == 0 else f"{-savings:.0f}% more")
        else:
            savings_str = ""

        # Header with ranking and cost
        cost_color = "green" if result["cost_usd"] < 0.001 else ("yellow" if result["cost_usd"] < 0.005 else "white")

        cprint(f"#{i} ", "white", attrs=["bold"], end="")
        cprint(f"{result['label']}", "cyan", attrs=["bold"], end="")
        cprint(f" ({result['model_type']})", "grey", end="")
        print()

        cprint(f"   Cost: ", "grey", end="")
        cprint(f"${result['cost_usd']:.6f}", cost_color, end="")
        cprint(f" | {result['time_sec']}s | {result['chars']} chars", "grey", end="")
        if savings_str:
            cprint(f" | {savings_str}", "green" if "cheaper" in savings_str else "grey")
        else:
            print()

        # The actual reply - this is what matters!
        reply = result["reply"]
        if len(reply) > 280:
            cprint(f"\n   ⚠️  OVER 280 CHARS ({len(reply)})", "red")

        # Print the reply with highlighting
        print(f"\n   {reply}")

    # Cost comparison table
    cprint(f"\n{'=' * 70}", "cyan")
    cprint("   COST RANKING (cheapest to most expensive)", "cyan", attrs=["bold"])
    cprint("=" * 70, "cyan")

    print(f"\n   {'Rank':<5} {'Model':<22} {'Cost/Reply':<14} {'vs Sonnet':<15} {'Speed':<8}")
    print(f"   {'-'*65}")

    for i, result in enumerate(successful_results, 1):
        if baseline_cost > 0:
            savings = ((baseline_cost - result["cost_usd"]) / baseline_cost) * 100
            savings_str = f"{savings:.0f}% cheaper" if savings > 0 else ("baseline" if savings == 0 else f"{-savings:.0f}% more")
        else:
            savings_str = "-"

        rank_color = "green" if i <= 3 else "white"
        cprint(f"   {i:<5} {result['label']:<22} ${result['cost_usd']:<13.6f} {savings_str:<15} {result['time_sec']}s", rank_color)

    # Quality reminder
    cprint(f"\n{'─' * 70}", "grey")
    cprint("   📋 QUALITY CHECK:", "yellow", attrs=["bold"])
    cprint("   Review the replies above and rate each 1-5 on:", "white")
    cprint("   • Savagery (does it sting with truth?)", "white")
    cprint("   • Wit (is it clever, not just mean?)", "white")
    cprint("   • Twitter-native (would it get engagement?)", "white")
    cprint("   • Voice consistency (sounds like Nirvana Nuts?)", "white")
    cprint(f"{'─' * 70}", "grey")

    # Save results
    results_file = PROJECT_ROOT / "src" / "data" / "model_comparison_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)

    with open(results_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "tweet": tweet,
            "results": [r for r in results if "error" not in r],
            "errors": [r for r in results if "error" in r]
        }, f, indent=2)

    cprint(f"\n💾 Results saved to: {results_file}", "grey")

    return results


def interactive_mode():
    """Run interactive comparison"""
    cprint("\n🎯 MODEL COMPARISON TEST", "cyan", attrs=["bold"])
    cprint("Compare tweet reply quality across ALL your AI models\n", "white")

    cprint("Enter a tweet to test (or press Enter to choose from samples):", "yellow")
    tweet = input("> ").strip()

    if not tweet:
        cprint("\nSample tweets:", "yellow")
        for i, t in enumerate(TEST_TWEETS, 1):
            cprint(f"  [{i}] {t}", "white")

        choice = input("\nChoice (1-3): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(TEST_TWEETS):
            tweet = TEST_TWEETS[int(choice) - 1]
        else:
            tweet = TEST_TWEETS[0]

    run_comparison(tweet)

    # Ask about running more tests
    cprint("\n\nRun another test? (y/n): ", "yellow", end="")
    if input().strip().lower() == 'y':
        interactive_mode()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Run with provided tweet
        tweet = " ".join(sys.argv[1:])
        run_comparison(tweet)
    else:
        interactive_mode()
