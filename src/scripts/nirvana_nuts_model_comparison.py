"""
🥜 Nirvana Nuts Model Comparison
Compare Claude Sonnet 4.6 vs DeepSeek across all modes

Built with love by TradeHive
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from termcolor import cprint

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.model_factory import ModelFactory
from src.prompts.nirvana_nuts.modes import (
    CORE_IDENTITY,
    MODE_PROMPTS,
    MODE_TEMPERATURES,
    ALL_MODES,
)
from src.prompts.nirvana_nuts.prompts import (
    ANALYZER_PROMPT,
    REPLY_GENERATOR_PROMPT,
    TWEET_GENERATOR_PROMPT,
    THREAD_GENERATOR_PROMPT,
)

# Models to compare
MODELS = [
    ("claude", "claude-opus-4-7", "Opus 4.7"),
    ("openrouter", "moonshotai/kimi-k2.5", "Kimi K2.5"),
]

# Test tweets for comparison
TEST_TWEETS = [
    "Hustle culture is the only path to success. If you're not grinding 24/7, you're falling behind.",
    "Meditation is just sitting and doing nothing. It's a waste of time for productive people.",
    "Money can't buy happiness but I'd rather cry in a Ferrari than on a bicycle.",
]

MAX_TOKENS = 1500


def get_model(factory, model_type, model_name):
    """Get a model instance"""
    return factory.get_model(model_type, model_name)


def generate_response(model, system_prompt, user_content, temp=0.8):
    """Generate a response from the model"""
    try:
        response = model.generate_response(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temp,
            max_tokens=MAX_TOKENS
        )
        if response and hasattr(response, 'content'):
            return response.content
        return str(response) if response else ""
    except Exception as e:
        return f"[ERROR: {e}]"


def analyze_tweet(model, tweet):
    """Analyze a tweet"""
    prompt = ANALYZER_PROMPT.format(tweet=tweet)
    response = generate_response(model, "You are a tweet engagement analyst. Return only valid JSON.", prompt, temp=0.3)

    try:
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        return json.loads(response)
    except:
        return {
            "tone": "unknown",
            "assumptions": "their entire worldview",
            "angle": "challenge everything",
            "recommended_mode": "savage",
            "engagement_potential": "medium"
        }


def generate_reply(model, tweet, mode, analysis):
    """Generate a reply in a specific mode"""
    mode_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["savage"])
    temp = MODE_TEMPERATURES.get(mode, 0.8)

    prompt = REPLY_GENERATOR_PROMPT.format(
        core_identity=CORE_IDENTITY,
        mode_prompt=mode_prompt,
        tweet=tweet,
        tone=analysis.get("tone", "unknown"),
        assumption=analysis.get("assumptions", "everything"),
        angle=analysis.get("angle", "challenge it"),
        engagement_approach=analysis.get("engagement_approach", "controversial_stance"),
        mode=mode.upper()
    )

    response = generate_response(model, prompt, f"Generate a {mode} reply to: {tweet}", temp=temp)
    reply = response.strip().strip('"').strip("'")

    if len(reply) > 280:
        reply = reply[:277] + "..."

    return reply


def generate_tweets(model, topic):
    """Generate tweet ideas"""
    prompt = TWEET_GENERATOR_PROMPT.format(
        core_identity=CORE_IDENTITY,
        topic=topic
    )

    response = generate_response(model, prompt, f"Generate 5 tweets about: {topic}")

    tweets = []
    for line in response.split("\n"):
        line = line.strip()
        if len(line) < 3:
            continue
        if line.startswith("#"):
            continue
        if len(line) > 2 and line[0].isdigit():
            if line[1] in ".)/":
                line = line[2:].strip()
            elif len(line) > 3 and line[1].isdigit() and line[2] in ".)/":
                line = line[3:].strip()
        if line and len(line) > 10:
            tweets.append(line)

    return tweets[:5]


def run_comparison():
    """Run the full model comparison"""
    cprint("\n" + "=" * 70, "cyan")
    cprint("🥜 NIRVANA NUTS MODEL COMPARISON", "cyan", attrs=["bold"])
    cprint("   Claude Sonnet 4.6 vs DeepSeek", "cyan")
    cprint("=" * 70, "cyan")

    factory = ModelFactory()
    results = {"timestamp": datetime.now().isoformat(), "comparisons": []}

    # Test each tweet
    for tweet_idx, test_tweet in enumerate(TEST_TWEETS, 1):
        cprint(f"\n{'='*70}", "yellow")
        cprint(f"TEST TWEET #{tweet_idx}", "yellow", attrs=["bold"])
        cprint(f"{'='*70}", "yellow")
        cprint(f"\n\"{test_tweet}\"\n", "white")

        tweet_results = {"tweet": test_tweet, "models": {}}

        # Test each model
        for model_type, model_name, display_name in MODELS:
            cprint(f"\n{'─'*50}", "grey")
            cprint(f"🤖 {display_name} ({model_name})", "green", attrs=["bold"])
            cprint(f"{'─'*50}", "grey")

            model = get_model(factory, model_type, model_name)
            if not model:
                cprint(f"❌ Could not load {display_name}", "red")
                continue

            # Analyze tweet
            analysis = analyze_tweet(model, test_tweet)
            cprint(f"\n📊 Analysis:", "cyan")
            cprint(f"   Recommended Mode: {analysis.get('recommended_mode', 'unknown').upper()}", "white")
            cprint(f"   Engagement: {analysis.get('engagement_potential', 'unknown').upper()}", "white")

            model_results = {"analysis": analysis, "replies": {}}

            # Generate replies in all modes
            cprint(f"\n🔥 REPLIES:", "yellow", attrs=["bold"])

            for mode in ALL_MODES:
                reply = generate_reply(model, test_tweet, mode, analysis)
                model_results["replies"][mode] = reply

                # Color-code by mode type
                if mode in ["savage", "nuclear", "controversial"]:
                    color = "red"
                elif mode in ["funny"]:
                    color = "yellow"
                elif mode in ["philosophical", "osho"]:
                    color = "cyan"
                else:
                    color = "green"

                cprint(f"\n[{mode.upper()}]", color, attrs=["bold"])
                print(f"   {reply}")
                cprint(f"   ({len(reply)} chars)", "grey")

            tweet_results["models"][display_name] = model_results

        results["comparisons"].append(tweet_results)

    # Tweet generation comparison
    cprint(f"\n{'='*70}", "magenta")
    cprint("📝 TWEET GENERATION COMPARISON", "magenta", attrs=["bold"])
    cprint(f"{'='*70}", "magenta")

    topic = "the illusion of productivity and hustle culture"
    cprint(f"\nTopic: {topic}\n", "white")

    tweet_gen_results = {"topic": topic, "models": {}}

    for model_type, model_name, display_name in MODELS:
        cprint(f"\n{'─'*50}", "grey")
        cprint(f"🤖 {display_name}", "green", attrs=["bold"])
        cprint(f"{'─'*50}", "grey")

        model = get_model(factory, model_type, model_name)
        if not model:
            continue

        tweets = generate_tweets(model, topic)
        tweet_gen_results["models"][display_name] = tweets

        for i, tweet in enumerate(tweets, 1):
            cprint(f"\n[{i}]", "yellow", attrs=["bold"], end=" ")
            print(tweet)
            cprint(f"   ({len(tweet)} chars)", "grey")

    results["tweet_generation"] = tweet_gen_results

    # Save results
    output_file = PROJECT_ROOT / "src" / "data" / "model_comparison_nirvana_nuts.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    cprint(f"\n{'='*70}", "cyan")
    cprint(f"💾 Results saved to: {output_file}", "green")
    cprint(f"{'='*70}", "cyan")

    return results


if __name__ == "__main__":
    run_comparison()
