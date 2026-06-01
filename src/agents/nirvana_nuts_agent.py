"""
🥜 Nirvana Nuts - Twitter Growth Engine
Built with love for @NirvanaNuts

A strategic engagement agent with Osho-inspired savage wisdom.
Not just content generation - a growth machine.
"""

import os
import sys
import argparse
import json
from datetime import datetime
from pathlib import Path
from termcolor import cprint, colored
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.model_factory import ModelFactory
from src.prompts.nirvana_nuts.modes import (
    CORE_IDENTITY,
    MODE_PROMPTS,
    MODE_TEMPERATURES,
    CHALLENGE_MODES,
    ALIGN_MODES,
    ALL_MODES,
)
from src.prompts.nirvana_nuts.prompts import (
    IMAGE_ANALYZER_PROMPT,
    ANALYZER_PROMPT,
    IMAGE_REPLY_GENERATOR_PROMPT,
    REPLY_GENERATOR_PROMPT,
    TWEET_GENERATOR_PROMPT,
    THREAD_GENERATOR_PROMPT,
    ARTICLE_GENERATOR_PROMPT,
    ARTICLE_TYPE_PROMPTS,
    ARTICLE_TYPE_TEMPERATURES,
    ARTICLE_LENGTH_TARGETS,
    ARTICLE_TEASER_PROMPT,
)

# Configuration
# MODEL OPTIONS:
# - "claude" with "claude-3-5-haiku-latest" (fast, creative, recommended)
# - "claude" with "claude-3-5-sonnet-latest" (higher quality, slower)
# - "claude" with "claude-sonnet-4-20250514" (best quality)
# - "deepseek" with "deepseek-v4-flash" (best value - sharp, concise, Twitter-native)
# - "xai" with "grok-4-fast-reasoning" (2M context, cheap)
MODEL_TYPE = "claude"
MODEL_NAME = "claude-sonnet-4-6"  # Claude Sonnet 4.6 - Latest and best
TEMPERATURE = 0.80  # Default temperature (fallback)
MAX_TOKENS = 1500

# Data paths
DATA_DIR = PROJECT_ROOT / "src" / "data" / "nirvana_nuts"
REPLIES_DIR = DATA_DIR / "generated_replies"
TWEETS_DIR = DATA_DIR / "generated_tweets"
THREADS_DIR = DATA_DIR / "generated_threads"
ARTICLES_DIR = DATA_DIR / "generated_articles"

# Article generation settings
ARTICLE_MAX_TOKENS = 4000  # Articles need more output tokens

# Ensure directories exist
for dir_path in [REPLIES_DIR, TWEETS_DIR, THREADS_DIR, ARTICLES_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


# Mode display colors for CLI output
MODE_COLORS = {
    "savage": "red",
    "funny": "yellow",
    "philosophical": "cyan",
    "controversial": "magenta",
    "nuclear": "red",
    "osho": "blue",
    "align_insight": "green",
    "align_humor": "green"
}


class NirvanaNutsAgent:
    """The Nirvana Nuts Twitter Growth Engine"""

    def __init__(self):
        """Initialize the agent"""
        load_dotenv()

        cprint("\n🥜 NIRVANA NUTS GROWTH ENGINE", "cyan", attrs=["bold"])
        cprint("━" * 40, "cyan")

        # Initialize model
        self.factory = ModelFactory()
        self.model = self.factory.get_model(MODEL_TYPE, MODEL_NAME)

        if not self.model:
            cprint(f"❌ Could not initialize {MODEL_TYPE} model", "red")
            cprint("Check your API keys in .env", "yellow")
            sys.exit(1)

        cprint(f"🤖 Using: {self.model.model_name}", "green")

    def _generate(self, system_prompt: str, user_content: str, temp: float = TEMPERATURE) -> str:
        """Generate response from model"""
        try:
            response = self.model.generate_response(
                system_prompt=system_prompt,
                user_content=user_content,
                temperature=temp,
                max_tokens=MAX_TOKENS
            )
            if response and hasattr(response, 'content'):
                return response.content
            return str(response) if response else ""
        except Exception as e:
            cprint(f"❌ Generation error: {e}", "red")
            return ""

    def _generate_with_image(self, system_prompt: str, user_content: str, image_data: str,
                              image_media_type: str = "image/png", temp: float = TEMPERATURE) -> str:
        """Generate response from model with image input"""
        try:
            # Check if model supports vision
            if not hasattr(self.model, 'generate_response_with_image'):
                cprint("❌ Current model doesn't support vision", "red")
                return ""

            response = self.model.generate_response_with_image(
                system_prompt=system_prompt,
                user_content=user_content,
                image_data=image_data,
                image_media_type=image_media_type,
                temperature=temp,
                max_tokens=MAX_TOKENS
            )
            if response and hasattr(response, 'content'):
                return response.content
            return str(response) if response else ""
        except Exception as e:
            cprint(f"❌ Vision generation error: {e}", "red")
            return ""

    def analyze_image_tweet(self, image_data: str, caption: str = "",
                            image_media_type: str = "image/png") -> dict:
        """Analyze an image tweet and extract context"""
        cprint("\n🖼️ Analyzing image tweet...", "cyan")

        response = self._generate_with_image(
            system_prompt="You are an image analyst. Return only valid JSON.",
            user_content=IMAGE_ANALYZER_PROMPT,
            image_data=image_data,
            image_media_type=image_media_type,
            temp=0.3
        )

        try:
            # Try to extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            image_analysis = json.loads(response)

            cprint("\n📸 IMAGE ANALYSIS:", "yellow", attrs=["bold"])
            cprint(f"   Type: {image_analysis.get('image_type', 'unknown')}", "white")
            cprint(f"   Text found: {image_analysis.get('visible_text', 'none')[:150]}...", "cyan")
            cprint(f"   Actual message: {image_analysis.get('actual_message', 'unknown')}", "white")
            cprint(f"   Tone: {image_analysis.get('tone', 'unknown')}", "white")
            cprint(f"   Hook: {image_analysis.get('hook', 'unknown')}", "green")

            return image_analysis

        except json.JSONDecodeError:
            cprint("⚠️ Couldn't parse image analysis", "yellow")
            return {
                "image_type": "unknown",
                "description": "Could not analyze image",
                "visible_text": caption if caption else "",
                "actual_message": caption if caption else "Image tweet",
                "tone": "unknown",
                "hook": "the image itself"
            }

    def generate_reply_for_image(self, image_analysis: dict, caption: str, mode: str, analysis: dict) -> str:
        """Generate a reply for an image tweet in a specific mode"""
        mode_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["savage"])

        # Get mode-specific temperature
        temp = MODE_TEMPERATURES.get(mode, TEMPERATURE)

        prompt = IMAGE_REPLY_GENERATOR_PROMPT.format(
            core_identity=CORE_IDENTITY,
            mode_prompt=mode_prompt,
            visible_text=image_analysis.get("visible_text", ""),
            actual_message=image_analysis.get("actual_message", image_analysis.get("context", "")),
            tweet_tone=image_analysis.get("tone", "unknown"),
            description=image_analysis.get("description", ""),
            caption=caption if caption else "(no caption)",
            tone=analysis.get("tone", "unknown"),
            assumption=analysis.get("assumptions", "everything"),
            angle=analysis.get("angle", "challenge it"),
            engagement_approach=analysis.get("engagement_approach", "controversial_stance"),
            hook=image_analysis.get("hook", ""),
            mode=mode.upper()
        )

        response = self._generate(prompt, f"Generate a {mode} reply to this image tweet", temp=temp)

        # Clean up response
        reply = response.strip().strip('"').strip("'")

        # Ensure under 280 chars
        if len(reply) > 280:
            reply = reply[:277] + "..."

        return reply

    def generate_replies_for_image(self, image_data: str, caption: str = "",
                                    image_media_type: str = "image/png",
                                    mode_filter: str = None) -> tuple:
        """
        Generate reply options for an image tweet.

        Args:
            image_data: Base64 encoded image data
            caption: Optional caption text
            image_media_type: MIME type of the image
            mode_filter: Optional. One of:
                - None: Generate all modes (default behavior)
                - "challenge": Only challenge modes
                - "align": Only align modes
                - A specific mode name
        """
        cprint("\n" + "━" * 40, "cyan")

        # First analyze the image
        image_analysis = self.analyze_image_tweet(image_data, caption, image_media_type)

        # Create a text representation for the standard analyzer
        combined_context = f"[IMAGE: {image_analysis.get('description', '')}] "
        if image_analysis.get('visible_text'):
            combined_context += f"Text in image: {image_analysis.get('visible_text')} "
        if caption:
            combined_context += f"Caption: {caption}"

        # Use standard analyzer for strategy
        analysis = self.analyze_tweet(combined_context)

        cprint("\n🔥 GENERATING IMAGE REPLIES...\n", "yellow", attrs=["bold"])

        # Select modes based on filter (using imported constants)
        if mode_filter is None:
            modes = ALL_MODES
        elif mode_filter == "challenge":
            modes = CHALLENGE_MODES
        elif mode_filter == "align":
            modes = ALIGN_MODES
        elif mode_filter in ALL_MODES:
            modes = [mode_filter]
        else:
            modes = ALL_MODES

        replies = []

        for mode in modes:
            reply = self.generate_reply_for_image(image_analysis, caption, mode, analysis)
            replies.append({"mode": mode, "reply": reply})

            # Display with mode-specific color
            mode_label = f"[{mode.upper()}]"
            cprint(f"{mode_label}", MODE_COLORS.get(mode, "white"), attrs=["bold"], end=" ")
            print(reply)
            cprint(f"   ({len(reply)} chars)", "grey")
            print()

        # Save to file
        self._save_image_replies(image_analysis, caption, replies, analysis)

        return replies, analysis, image_analysis

    def _save_image_replies(self, image_analysis: dict, caption: str, replies: list, analysis: dict):
        """Save generated image replies to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = REPLIES_DIR / f"image_replies_{timestamp}.json"

        data = {
            "timestamp": timestamp,
            "image_analysis": image_analysis,
            "caption": caption,
            "strategy_analysis": analysis,
            "replies": replies
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        cprint(f"💾 Saved to: {filename}", "grey")

    def analyze_tweet(self, tweet: str) -> dict:
        """Analyze a tweet and determine best response strategy"""
        cprint("\n🔍 Analyzing tweet...", "cyan")

        prompt = ANALYZER_PROMPT.format(tweet=tweet)
        response = self._generate("You are a tweet engagement analyst. Return only valid JSON.", prompt, temp=0.3)

        try:
            # Try to extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            analysis = json.loads(response)

            cprint("\n📊 ANALYSIS:", "yellow", attrs=["bold"])
            cprint(f"   Tone: {analysis.get('tone', 'unknown')}", "white")
            cprint(f"   Assumption: {analysis.get('assumptions', 'unknown')}", "white")
            cprint(f"   Angle: {analysis.get('angle', 'unknown')}", "white")
            cprint(f"   Best Mode: {analysis.get('recommended_mode', 'savage').upper()}", "green", attrs=["bold"])
            cprint(f"   Why: {analysis.get('why', '')}", "white")
            cprint(f"   Engagement: {analysis.get('engagement_potential', 'unknown').upper()}", "magenta")

            return analysis

        except json.JSONDecodeError:
            cprint("⚠️ Couldn't parse analysis, using savage mode", "yellow")
            return {
                "tone": "unknown",
                "assumptions": "their entire worldview",
                "angle": "challenge everything",
                "recommended_mode": "savage",
                "why": "when in doubt, be savage",
                "engagement_potential": "medium"
            }

    def generate_reply(self, tweet: str, mode: str, analysis: dict) -> str:
        """Generate a single reply in a specific mode"""
        mode_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["savage"])

        # Get mode-specific temperature
        temp = MODE_TEMPERATURES.get(mode, TEMPERATURE)

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

        response = self._generate(prompt, f"Generate a {mode} reply to: {tweet}", temp=temp)

        # Clean up response
        reply = response.strip().strip('"').strip("'")

        # Ensure under 280 chars
        if len(reply) > 280:
            reply = reply[:277] + "..."

        return reply

    def generate_replies(self, tweet: str, mode_filter: str = None) -> list:
        """
        Generate reply options across modes.

        Args:
            tweet: The tweet to reply to
            mode_filter: Optional. One of:
                - None: Generate all modes (default behavior)
                - "challenge": Only challenge modes (savage, funny, controversial, nuclear, philosophical)
                - "align": Only align modes (align_insight, align_humor, osho)
                - A specific mode name like "align_insight", "savage", etc.
        """
        cprint("\n" + "━" * 40, "cyan")

        # First analyze the tweet
        analysis = self.analyze_tweet(tweet)

        cprint("\n🔥 GENERATING REPLIES...\n", "yellow", attrs=["bold"])

        # Select modes based on filter (using imported constants)
        if mode_filter is None:
            modes = ALL_MODES
        elif mode_filter == "challenge":
            modes = CHALLENGE_MODES
        elif mode_filter == "align":
            modes = ALIGN_MODES
        elif mode_filter in ALL_MODES:
            modes = [mode_filter]
        else:
            cprint(f"⚠️ Unknown mode_filter '{mode_filter}', using all modes", "yellow")
            modes = ALL_MODES

        replies = []

        for mode in modes:
            reply = self.generate_reply(tweet, mode, analysis)
            replies.append({"mode": mode, "reply": reply})

            # Display with mode-specific color
            mode_label = f"[{mode.upper()}]"
            cprint(f"{mode_label}", MODE_COLORS.get(mode, "white"), attrs=["bold"], end=" ")
            print(reply)
            cprint(f"   ({len(reply)} chars)", "grey")
            print()

        # Save to file
        self._save_replies(tweet, replies, analysis)

        return replies

    def generate_tweets(self, topic: str = None, count: int = 5) -> list:
        """Generate original tweet ideas"""
        if not topic:
            topics = [
                "modern life and its absurdities",
                "the hustle culture myth",
                "meditation and mindfulness",
                "success and failure",
                "relationships and connection",
                "technology and humanity",
                "ego and authenticity"
            ]
            import random
            topic = random.choice(topics)

        cprint(f"\n🐦 Generating tweets on: {topic}", "cyan")
        cprint("━" * 40, "cyan")

        prompt = TWEET_GENERATOR_PROMPT.format(
            core_identity=CORE_IDENTITY,
            topic=topic
        )

        response = self._generate(prompt, f"Generate 5 tweets about: {topic}")

        # Parse tweets
        tweets = []
        for line in response.split("\n"):
            line = line.strip()
            if len(line) < 3:  # Skip very short lines
                continue
            if line.startswith("#"):
                continue

            # Remove numbering like "1. " or "1) " or "1/ "
            if len(line) > 2 and line[0].isdigit():
                if line[1] in ".)/":
                    line = line[2:].strip()
                elif len(line) > 3 and line[1].isdigit() and line[2] in ".)/":
                    line = line[3:].strip()

            if line and len(line) > 10:
                tweets.append(line)

        cprint("\n🔥 GENERATED TWEETS:\n", "yellow", attrs=["bold"])
        for i, tweet in enumerate(tweets[:count], 1):
            cprint(f"[{i}]", "green", attrs=["bold"], end=" ")
            print(tweet)
            cprint(f"   ({len(tweet)} chars)", "grey")
            print()

        # Save to file
        self._save_tweets(topic, tweets[:count])

        return tweets[:count]

    def generate_thread(self, topic: str, length: int = 5, thesis: str = None) -> list:
        """Generate a Twitter thread"""
        cprint(f"\n🧵 Generating {length}-tweet thread on: {topic}", "cyan")
        cprint("━" * 40, "cyan")

        thesis_section = ""
        if thesis:
            thesis_section = f"THESIS: {thesis}"

        prompt = THREAD_GENERATOR_PROMPT.format(
            core_identity=CORE_IDENTITY,
            topic=topic,
            length=length,
            body_end=length - 1,
            thesis_section=thesis_section
        )

        response = self._generate(prompt, f"Create a {length}-tweet thread about: {topic}")

        # Parse thread
        thread = []
        current_tweet = ""

        for line in response.split("\n"):
            line = line.strip()
            if not line:
                if current_tweet:
                    thread.append(current_tweet)
                    current_tweet = ""
                continue

            # Check if new tweet (starts with "1/" or "2/" etc)
            is_new_tweet = len(line) >= 2 and line[0].isdigit() and "/" in line[:3]

            if is_new_tweet:
                if current_tweet:
                    thread.append(current_tweet)
                current_tweet = line
            else:
                if current_tweet:
                    current_tweet += " " + line
                else:
                    current_tweet = line

        if current_tweet:
            thread.append(current_tweet)

        cprint("\n🔥 GENERATED THREAD:\n", "yellow", attrs=["bold"])
        for i, tweet in enumerate(thread, 1):
            role = "HOOK" if i == 1 else ("CLOSER" if i == len(thread) else "BODY")
            cprint(f"[{role}]", "magenta", attrs=["bold"])
            print(tweet)
            cprint(f"   ({len(tweet)} chars)", "grey")
            print()

        # Save to file
        self._save_thread(topic, thread)

        return thread

    def generate_article(self, topic: str, article_type: str = "deep_dive",
                         length: str = "medium", thesis: str = None) -> dict:
        """
        Generate a Twitter/X Article (long-form content for Premium+ users).

        Args:
            topic: The article topic
            article_type: One of: deep_dive, listicle, opinion, howto, contrarian
            length: One of: short (2-3K), medium (5-8K), long (10-15K)
            thesis: Optional thesis/angle for the article

        Returns:
            dict with title, hook, sections, closer, and metadata
        """
        cprint(f"\n📝 Generating {article_type.upper()} article on: {topic}", "cyan")
        cprint(f"   Target length: {length}", "cyan")
        cprint("━" * 40, "cyan")

        # Get article type prompt
        article_type_prompt = ARTICLE_TYPE_PROMPTS.get(article_type, ARTICLE_TYPE_PROMPTS["deep_dive"])

        # Get length targets
        length_min, length_max = ARTICLE_LENGTH_TARGETS.get(length, ARTICLE_LENGTH_TARGETS["medium"])

        # Get temperature for this article type
        temp = ARTICLE_TYPE_TEMPERATURES.get(article_type, 0.75)

        # Build thesis section
        thesis_section = f"THESIS: {thesis}" if thesis else ""

        # Format the prompt
        prompt = ARTICLE_GENERATOR_PROMPT.format(
            core_identity=CORE_IDENTITY,
            topic=topic,
            thesis_section=thesis_section,
            article_type_prompt=article_type_prompt,
            length_min=length_min,
            length_max=length_max
        )

        # Generate with higher max tokens for articles
        try:
            response = self.model.generate_response(
                system_prompt="You are an expert article writer. Return only valid JSON.",
                user_content=prompt,
                temperature=temp,
                max_tokens=ARTICLE_MAX_TOKENS
            )
            if response and hasattr(response, 'content'):
                response_text = response.content
            else:
                response_text = str(response) if response else ""
        except Exception as e:
            cprint(f"❌ Article generation error: {e}", "red")
            return {}

        # Parse the JSON response
        try:
            response_text = response_text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            article_data = json.loads(response_text)

            # Build full content string
            full_content = f"# {article_data.get('title', topic)}\n\n"
            full_content += f"{article_data.get('hook', '')}\n\n"

            for section in article_data.get('sections', []):
                full_content += f"## {section.get('heading', '')}\n\n"
                full_content += f"{section.get('body', '')}\n\n"

            full_content += f"---\n\n{article_data.get('closer', '')}"

            # Calculate stats
            char_count = len(full_content)
            word_count = len(full_content.split())

            # Build result
            result = {
                "topic": topic,
                "article_type": article_type,
                "length": length,
                "thesis": thesis,
                "title": article_data.get("title", ""),
                "hook": article_data.get("hook", ""),
                "sections": article_data.get("sections", []),
                "closer": article_data.get("closer", ""),
                "full_content": full_content,
                "char_count": char_count,
                "word_count": word_count
            }

            # Display the article
            cprint("\n📄 GENERATED ARTICLE:\n", "yellow", attrs=["bold"])
            cprint(f"📰 {result['title']}", "white", attrs=["bold"])
            cprint(f"\n{result['hook']}\n", "cyan")

            for section in result["sections"]:
                cprint(f"\n## {section['heading']}", "green", attrs=["bold"])
                # Show first 200 chars of each section
                body_preview = section['body'][:200] + "..." if len(section['body']) > 200 else section['body']
                print(body_preview)

            cprint(f"\n---\n{result['closer']}", "magenta")
            cprint(f"\n📊 Stats: {char_count:,} chars | {word_count:,} words", "grey")

            # Save to file
            self._save_article(result)

            return result

        except json.JSONDecodeError as e:
            cprint(f"⚠️ Couldn't parse article JSON: {e}", "yellow")
            cprint("Raw response:", "grey")
            print(response_text[:500])
            return {
                "topic": topic,
                "article_type": article_type,
                "error": "Failed to parse article structure",
                "raw_content": response_text
            }

    def generate_teaser(self, title: str, hook: str, key_insight: str = "") -> str:
        """
        Generate a tweet-length teaser to promote an article.

        Args:
            title: The article title
            hook: The article's opening hook
            key_insight: Optional key insight or thesis to highlight

        Returns:
            A 280-char max teaser tweet
        """
        cprint("\n🎯 Generating article teaser...", "cyan")

        # Use the key insight or extract from hook if not provided
        if not key_insight:
            key_insight = hook[:150] if len(hook) > 150 else hook

        prompt = ARTICLE_TEASER_PROMPT.format(
            core_identity=CORE_IDENTITY,
            title=title,
            hook=hook,
            key_insight=key_insight
        )

        response = self._generate(
            system_prompt="You are a Twitter expert. Return ONLY the teaser text, nothing else.",
            user_content=prompt,
            temp=0.80  # Creative but focused
        )

        # Clean up response
        teaser = response.strip().strip('"').strip("'")

        # Ensure under 280 chars
        if len(teaser) > 280:
            teaser = teaser[:277] + "..."

        cprint("\n📣 TEASER:", "yellow", attrs=["bold"])
        print(teaser)
        cprint(f"   ({len(teaser)} chars)", "grey")

        return teaser

    def _save_article(self, article: dict):
        """Save generated article to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save as JSON for structured data
        json_filename = ARTICLES_DIR / f"article_{timestamp}.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            article_data = {
                "timestamp": timestamp,
                **article
            }
            json.dump(article_data, f, indent=2)

        # Also save as markdown for easy reading
        md_filename = ARTICLES_DIR / f"article_{timestamp}.md"
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(f"# {article.get('title', 'Untitled')}\n\n")
            f.write(f"> Topic: {article.get('topic', '')}\n")
            f.write(f"> Type: {article.get('article_type', '')}\n")
            f.write(f"> Generated: {timestamp}\n\n")
            f.write("---\n\n")
            f.write(article.get('full_content', ''))

        cprint(f"💾 Saved to: {json_filename}", "grey")
        cprint(f"💾 Saved to: {md_filename}", "grey")

    def _save_replies(self, tweet: str, replies: list, analysis: dict):
        """Save generated replies to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = REPLIES_DIR / f"replies_{timestamp}.json"

        data = {
            "timestamp": timestamp,
            "original_tweet": tweet,
            "analysis": analysis,
            "replies": replies
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        cprint(f"💾 Saved to: {filename}", "grey")

    def _save_tweets(self, topic: str, tweets: list):
        """Save generated tweets to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = TWEETS_DIR / f"tweets_{timestamp}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"Topic: {topic}\n")
            f.write(f"Generated: {timestamp}\n")
            f.write("=" * 40 + "\n\n")
            for i, tweet in enumerate(tweets, 1):
                f.write(f"{i}. {tweet}\n\n")

        cprint(f"💾 Saved to: {filename}", "grey")

    def _save_thread(self, topic: str, thread: list):
        """Save generated thread to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = THREADS_DIR / f"thread_{timestamp}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"Topic: {topic}\n")
            f.write(f"Generated: {timestamp}\n")
            f.write("=" * 40 + "\n\n")
            for tweet in thread:
                f.write(f"{tweet}\n\n")

        cprint(f"💾 Saved to: {filename}", "grey")

    def interactive_mode(self):
        """Run interactive CLI"""
        while True:
            cprint("\n" + "━" * 40, "cyan")
            cprint("\nWhat do you want to do?", "white", attrs=["bold"])
            cprint("[1] Reply to a tweet", "white")
            cprint("[2] Generate original tweets", "white")
            cprint("[3] Build a thread", "white")
            cprint("[4] Exit", "white")

            choice = input("\n> ").strip()

            if choice == "1":
                cprint("\nPaste the tweet you want to reply to:", "yellow")
                tweet = input("> ").strip()
                if tweet:
                    replies = self.generate_replies(tweet)

                    cprint("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━", "cyan")
                    cprint("Which one do you want to use? (1-6, or 'r' to regenerate)", "white")
                    sub_choice = input("> ").strip().lower()

                    if sub_choice == "r":
                        self.generate_replies(tweet)
                    elif sub_choice.isdigit() and 1 <= int(sub_choice) <= 6:
                        idx = int(sub_choice) - 1
                        selected = replies[idx]["reply"]
                        cprint(f"\n✅ Selected reply copied!", "green")
                        cprint(f"\n{selected}", "white", attrs=["bold"])

                        # Try to copy to clipboard
                        try:
                            import pyperclip
                            pyperclip.copy(selected)
                            cprint("(Copied to clipboard)", "grey")
                        except:
                            pass

            elif choice == "2":
                cprint("\nEnter a topic (or press Enter for random):", "yellow")
                topic = input("> ").strip() or None
                self.generate_tweets(topic)

            elif choice == "3":
                cprint("\nEnter the thread topic:", "yellow")
                topic = input("> ").strip()
                if topic:
                    cprint("How many tweets? (default: 5):", "yellow")
                    length_input = input("> ").strip()
                    length = int(length_input) if length_input.isdigit() else 5

                    cprint("Optional thesis (or press Enter to skip):", "yellow")
                    thesis = input("> ").strip() or None

                    self.generate_thread(topic, length, thesis)

            elif choice == "4":
                cprint("\n🥜 Keep being savage! Goodbye.", "cyan")
                break

            else:
                cprint("Invalid choice. Try again.", "red")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Nirvana Nuts Twitter Growth Engine")
    parser.add_argument("--reply", type=str, help="Generate replies to a tweet")
    parser.add_argument("--tweets", type=int, help="Generate N original tweets")
    parser.add_argument("--topic", type=str, help="Topic for tweets/thread")
    parser.add_argument("--thread", type=int, help="Generate a thread of N tweets")
    parser.add_argument("--thesis", type=str, help="Thesis for thread")

    args = parser.parse_args()

    agent = NirvanaNutsAgent()

    if args.reply:
        agent.generate_replies(args.reply)
    elif args.tweets:
        agent.generate_tweets(args.topic, args.tweets)
    elif args.thread:
        agent.generate_thread(args.topic or "life and wisdom", args.thread, args.thesis)
    else:
        # Interactive mode
        agent.interactive_mode()


if __name__ == "__main__":
    main()
