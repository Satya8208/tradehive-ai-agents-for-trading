"""
🎰 Blackjack Twitter - The Gambler's Growth Engine
Built for viral gambling wisdom on Twitter

A sophisticated gambler with the cool calculation of a card counter
and the swagger of a high roller. Engineered for virality.
"""

import os
import sys
import argparse
import json
import base64
import re
from datetime import datetime
from pathlib import Path
from termcolor import cprint, colored
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.model_factory import ModelFactory
from src.agents.blackjack_reel_engine import BlackjackReelEngine

# Import prompts
from src.prompts.blackjack.prompts import (
    ANALYZER_PROMPT,
    IMAGE_ANALYZER_PROMPT,
    REPLY_GENERATOR_PROMPT,
    IMAGE_REPLY_GENERATOR_PROMPT,
    TWEET_GENERATOR_PROMPT,
    THREAD_GENERATOR_PROMPT,
    ARTICLE_GENERATOR_PROMPT,
    ARTICLE_TYPE_PROMPTS,
    ARTICLE_TYPE_TEMPERATURES,
    ARTICLE_LENGTH_TARGETS,
    ARTICLE_TEASER_PROMPT,
)

# Import modes and constants
from src.prompts.blackjack.modes import (
    CORE_IDENTITY,
    MODE_PROMPTS,
    MODE_TEMPERATURES,
    MODE_COLORS,
    ALL_MODES,
    CHALLENGE_MODES,
    ALIGN_MODES,
    CARD_COUNTER_MODE,
)

# Configuration
MODEL_TYPE = "claude"
MODEL_NAME = "claude-sonnet-4-6"
DEFAULT_TEMPERATURE = 0.85
MAX_TOKENS = 1500
ARTICLE_MAX_TOKENS = 4000  # Articles need more output tokens

# Data paths
DATA_DIR = PROJECT_ROOT / "src" / "data" / "blackjack"
REPLIES_DIR = DATA_DIR / "generated_replies"
TWEETS_DIR = DATA_DIR / "generated_tweets"
THREADS_DIR = DATA_DIR / "generated_threads"
ARTICLES_DIR = DATA_DIR / "generated_articles"

# Ensure directories exist
for dir_path in [REPLIES_DIR, TWEETS_DIR, THREADS_DIR, ARTICLES_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


class BlackjackAgent:
    """The Blackjack Twitter Gambling Growth Engine"""

    def __init__(self):
        """Initialize the agent"""
        load_dotenv()

        cprint("\n🎰 BLACKJACK TWITTER ENGINE", "cyan", attrs=["bold"])
        cprint("━" * 40, "cyan")
        cprint("The house edge is ignorance. Your edge is wisdom.", "white")

        # Initialize model
        self.factory = ModelFactory()
        self.model = self.factory.get_model(MODEL_TYPE, MODEL_NAME)

        if not self.model:
            cprint(f"❌ Could not initialize {MODEL_TYPE} model", "red")
            cprint("Check your API keys in .env", "yellow")
            sys.exit(1)

        cprint(f"🎲 Using: {self.model.model_name}", "green")
        self.reel_engine = BlackjackReelEngine(self.model, DATA_DIR)

    def _generate(self, system_prompt: str, user_content: str, temp: float = DEFAULT_TEMPERATURE) -> str:
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

    def _generate_with_image(self, system_prompt: str, user_content: str,
                             image_data: str, image_media_type: str = "image/png",
                             temp: float = DEFAULT_TEMPERATURE) -> str:
        """Generate response with image input"""
        try:
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
            cprint(f"❌ Image generation error: {e}", "red")
            return ""

    def analyze_tweet(self, tweet: str) -> dict:
        """Analyze a tweet and determine best response strategy"""
        cprint("\n🎯 Reading the table...", "cyan")

        prompt = ANALYZER_PROMPT.format(tweet=tweet)
        response = self._generate(
            "You are a tweet engagement analyst with a gambler's eye. Return only valid JSON.",
            prompt,
            temp=0.3
        )

        try:
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            analysis = json.loads(response)

            cprint("\n📊 TABLE READ:", "yellow", attrs=["bold"])
            cprint(f"   Tone: {analysis.get('tone', 'unknown')}", "white")
            cprint(f"   The Bet: {analysis.get('the_bet', 'unknown')}", "cyan")
            cprint(f"   Angle: {analysis.get('angle', 'unknown')}", "white")
            cprint(f"   Best Mode: {analysis.get('recommended_mode', 'card_counter').upper()}", "green", attrs=["bold"])
            cprint(f"   Why: {analysis.get('why', '')}", "white")
            cprint(f"   Engagement: {analysis.get('engagement_potential', 'unknown').upper()}", "magenta")

            return analysis

        except json.JSONDecodeError:
            cprint("⚠️ Couldn't parse analysis, using card_counter mode", "yellow")
            return {
                "tone": "unknown",
                "the_bet": "their entire position",
                "assumptions": "they understand their odds",
                "angle": "show them the real math",
                "recommended_mode": "card_counter",
                "why": "when in doubt, count the cards",
                "engagement_potential": "medium"
            }

    def analyze_image(self, image_data: str, image_media_type: str = "image/png") -> dict:
        """Analyze an image tweet"""
        cprint("\n🖼️ Reading the image...", "cyan")

        response = self._generate_with_image(
            "You are an image analyst for @BlackjackTweets. Return only valid JSON.",
            IMAGE_ANALYZER_PROMPT,
            image_data,
            image_media_type,
            temp=0.3
        )

        try:
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]

            analysis = json.loads(response)

            cprint("\n🖼️ IMAGE READ:", "yellow", attrs=["bold"])
            cprint(f"   Type: {analysis.get('image_type', 'unknown')}", "white")
            cprint(f"   Text: {analysis.get('visible_text', '')[:50]}...", "cyan")
            cprint(f"   Message: {analysis.get('actual_message', '')[:50]}...", "white")

            return analysis

        except json.JSONDecodeError:
            cprint("⚠️ Couldn't parse image analysis", "yellow")
            return {
                "image_type": "unknown",
                "visible_text": "",
                "description": "",
                "actual_message": "",
                "gambling_angle": "find the bet",
                "tone": "unknown",
                "hook": ""
            }

    def generate_reply(self, tweet: str, mode: str, analysis: dict) -> str:
        """Generate a single reply in a specific mode"""
        mode_prompt = MODE_PROMPTS.get(mode, CARD_COUNTER_MODE)
        mode_temp = MODE_TEMPERATURES.get(mode, DEFAULT_TEMPERATURE)

        prompt = REPLY_GENERATOR_PROMPT.format(
            core_identity=CORE_IDENTITY,
            mode_prompt=mode_prompt,
            tweet=tweet,
            tone=analysis.get("tone", "unknown"),
            the_bet=analysis.get("the_bet", "unknown"),
            angle=analysis.get("angle", "gambling wisdom"),
            mode=mode.upper()
        )

        response = self._generate(prompt, f"Generate a {mode} reply to: {tweet}", temp=mode_temp)

        reply = response.strip().strip('"').strip("'")
        if len(reply) > 280:
            reply = reply[:277] + "..."

        return reply

    def generate_image_reply(self, mode: str, analysis: dict, image_analysis: dict, caption: str = "") -> str:
        """Generate a reply for an image tweet"""
        mode_prompt = MODE_PROMPTS.get(mode, CARD_COUNTER_MODE)
        mode_temp = MODE_TEMPERATURES.get(mode, DEFAULT_TEMPERATURE)

        prompt = IMAGE_REPLY_GENERATOR_PROMPT.format(
            core_identity=CORE_IDENTITY,
            mode_prompt=mode_prompt,
            visible_text=image_analysis.get("visible_text", ""),
            actual_message=image_analysis.get("actual_message", ""),
            tweet_tone=image_analysis.get("tone", "unknown"),
            description=image_analysis.get("description", ""),
            caption=caption,
            tone=analysis.get("tone", "unknown"),
            the_bet=analysis.get("the_bet", "unknown"),
            angle=analysis.get("angle", "gambling wisdom"),
            hook=image_analysis.get("hook", ""),
            mode=mode.upper()
        )

        response = self._generate(prompt, f"Generate a {mode} reply", temp=mode_temp)

        reply = response.strip().strip('"').strip("'")
        if len(reply) > 280:
            reply = reply[:277] + "..."

        return reply

    def generate_replies(self, tweet: str, mode_filter: str = None) -> list:
        """
        Generate reply options across modes.

        Args:
            tweet: The tweet to reply to
            mode_filter: 'challenge', 'align', specific mode name, or None for all
        """
        cprint("\n" + "━" * 40, "cyan")

        analysis = self.analyze_tweet(tweet)

        cprint("\n🎰 DEALING REPLIES...\n", "yellow", attrs=["bold"])

        # Select modes based on filter
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

            mode_label = f"[{mode.upper()}]"
            cprint(f"{mode_label}", MODE_COLORS.get(mode, "white"), attrs=["bold"], end=" ")
            print(reply)
            cprint(f"   ({len(reply)} chars)", "grey")
            print()

        self._save_replies(tweet, replies, analysis)

        return replies

    def generate_replies_for_image(self, image_data: str, caption: str = "",
                                   image_media_type: str = "image/png",
                                   mode_filter: str = None) -> tuple:
        """
        Generate replies for an image tweet.

        Returns:
            Tuple of (replies_list, analysis_dict, image_analysis_dict)
        """
        cprint("\n" + "━" * 40, "cyan")

        image_analysis = self.analyze_image(image_data, image_media_type)

        # Create analysis from image context
        visible_text = image_analysis.get("visible_text", "") or caption
        analysis = {
            "tone": image_analysis.get("tone", "unknown"),
            "the_bet": image_analysis.get("gambling_angle", "their position"),
            "angle": image_analysis.get("hook", "gambling wisdom")
        }

        cprint("\n🎰 DEALING IMAGE REPLIES...\n", "yellow", attrs=["bold"])

        # Select modes based on filter
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
            reply = self.generate_image_reply(mode, analysis, image_analysis, caption)
            replies.append({"mode": mode, "reply": reply})

            mode_label = f"[{mode.upper()}]"
            cprint(f"{mode_label}", MODE_COLORS.get(mode, "white"), attrs=["bold"], end=" ")
            print(reply)
            cprint(f"   ({len(reply)} chars)", "grey")
            print()

        # Save image replies
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

    def generate_tweets(self, topic: str = None, count: int = 5) -> list:
        """Generate original tweet ideas"""
        if not topic:
            topics = [
                "career decisions as bets",
                "relationship risk management",
                "startup odds most people ignore",
                "reading people like reading opponents",
                "position sizing your life",
                "the EV of meetings and networking",
                "why 'safe' choices aren't safe"
            ]
            import random
            topic = random.choice(topics)

        cprint(f"\n🎲 Generating tweets on: {topic}", "cyan")
        cprint("━" * 40, "cyan")

        prompt = TWEET_GENERATOR_PROMPT.format(
            core_identity=CORE_IDENTITY,
            topic=topic
        )

        response = self._generate(prompt, f"Generate 5 tweets about: {topic}")

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

        cprint("\n🎰 DEALT TWEETS:\n", "yellow", attrs=["bold"])
        for i, tweet in enumerate(tweets[:count], 1):
            cprint(f"[{i}]", "green", attrs=["bold"], end=" ")
            print(tweet)
            cprint(f"   ({len(tweet)} chars)", "grey")
            print()

        self._save_tweets(topic, tweets[:count])

        return tweets[:count]

    def generate_thread(self, topic: str, length: int = 5, thesis: str = None) -> list:
        """Generate a Twitter thread"""
        cprint(f"\n🧵 Dealing {length}-tweet thread on: {topic}", "cyan")
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

        thread = []
        current_tweet = ""

        for line in response.split("\n"):
            line = line.strip()
            if not line:
                if current_tweet:
                    thread.append(current_tweet)
                    current_tweet = ""
                continue

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

        cprint("\n🎰 DEALT THREAD:\n", "yellow", attrs=["bold"])
        for i, tweet in enumerate(thread, 1):
            role = "HOOK" if i == 1 else ("CLOSER" if i == len(thread) else "BODY")
            cprint(f"[{role}]", "magenta", attrs=["bold"])
            print(tweet)
            cprint(f"   ({len(tweet)} chars)", "grey")
            print()

        self._save_thread(topic, thread)

        return thread

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
        cprint(f"\n🎰 Generating {article_type.upper()} article on: {topic}", "cyan")
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
                system_prompt="You are an expert article writer with gambling wisdom. Return only valid JSON.",
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
            cprint("\n🎰 DEALT ARTICLE:\n", "yellow", attrs=["bold"])
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
            system_prompt="You are a Twitter expert with gambling edge. Return ONLY the teaser text, nothing else.",
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

    def _load_json_input(self, value: str):
        """Load JSON from disk if the input is a file path."""
        if not value:
            return value

        candidate = Path(value)
        if candidate.exists() and candidate.is_file():
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
        return value

    def generate_reel_concepts(self, count: int = 10, mix: str = "mixed", topic: str = None) -> dict:
        """Generate Blackjack God reel concepts."""
        return self.reel_engine.generate_reel_concepts(count=count, focus_mode=mix, topic=topic)

    def generate_reel_packet(
        self,
        concept_or_idea: str,
        series_name: str = None,
        pillar: str = None,
        duration_seconds: int = 35,
    ) -> dict:
        """Generate a production-ready reel packet."""
        concept_input = self._load_json_input(concept_or_idea)
        if isinstance(concept_input, dict) and "concept" in concept_input:
            concept_input = concept_input["concept"]

        bundle = self.reel_engine.generate_reel_packet(
            concept_input=concept_input,
            series_name=series_name,
            pillar=pillar,
            duration_seconds=duration_seconds,
        )

        packet = bundle["packet"]
        cprint("\n🎬 BLACKJACK GOD REEL PACKET", "yellow", attrs=["bold"])
        cprint(f"Series: {packet['series_name']} | Pillar: {packet['pillar']}", "cyan")
        cprint(f"Hook 1: {packet['hook_1']}", "white")
        cprint(f"Hook 2: {packet['hook_2']}", "white")
        cprint(f"Thumbnail: {packet['thumbnail_line']}", "magenta")
        return bundle

    def score_reel_packet(self, packet_file: str) -> dict:
        """Score an existing reel packet JSON file."""
        loaded = self._load_json_input(packet_file)
        packet = loaded.get("packet", loaded) if isinstance(loaded, dict) else loaded
        if not isinstance(packet, dict):
            raise ValueError("score_reel_packet expects a JSON file containing a reel packet.")

        score = self.reel_engine.score_reel_packet(packet)
        cprint("\n🧪 REEL QUALITY GATE", "yellow", attrs=["bold"])
        cprint(f"Approved: {score['approved']}", "green" if score["approved"] else "yellow")
        cprint(f"Overall: {score['overall_score']}/100", "cyan")
        cprint(f"Verdict: {score['verdict']}", "white")
        if score.get("standout_line"):
            cprint(f"Standout line: {score['standout_line']}", "magenta")
        return score

    def generate_batch_calendar(self, week_start: str = None, mix: str = "mixed") -> dict:
        """Generate a weekly Blackjack God content calendar."""
        payload = self.reel_engine.generate_batch_calendar(week_start=week_start, mix=mix)
        cprint("\n🗓️ WEEKLY CONTENT CALENDAR", "yellow", attrs=["bold"])
        for item in payload["calendar"][:6]:
            cprint(
                f"{item['date']} {item['publish_time']} [{item['series_name']}] {item['title']}",
                "white",
            )
        if len(payload["calendar"]) > 6:
            cprint(f"...and {len(payload['calendar']) - 6} more scheduled pieces", "grey")
        return payload

    def interactive_mode(self):
        """Run interactive CLI"""
        while True:
            cprint("\n" + "━" * 40, "cyan")
            cprint("\n🎰 What's your play?", "white", attrs=["bold"])
            cprint("[1] Reply to a tweet (read the table)", "white")
            cprint("[2] Generate original tweets (deal some hands)", "white")
            cprint("[3] Build a thread (stack the deck)", "white")
            cprint("[4] Generate reel concepts (build the bank)", "white")
            cprint("[5] Build a reel packet (production ready)", "white")
            cprint("[6] Build a weekly reel calendar (run the machine)", "white")
            cprint("[7] Score a reel packet JSON (quality gate)", "white")
            cprint("[8] Exit (cash out)", "white")

            choice = input("\n> ").strip()

            if choice == "1":
                cprint("\nPaste the tweet you want to reply to:", "yellow")
                tweet = input("> ").strip()
                if tweet:
                    cprint("\nMode filter? [all/challenge/align] (default: all):", "yellow")
                    mode_filter = input("> ").strip().lower() or None
                    if mode_filter == "all":
                        mode_filter = None

                    replies = self.generate_replies(tweet, mode_filter)

                    cprint("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━", "cyan")
                    cprint(f"Which one? (1-{len(replies)}, or 'r' to re-deal)", "white")
                    sub_choice = input("> ").strip().lower()

                    if sub_choice == "r":
                        self.generate_replies(tweet, mode_filter)
                    elif sub_choice.isdigit() and 1 <= int(sub_choice) <= len(replies):
                        idx = int(sub_choice) - 1
                        selected = replies[idx]["reply"]
                        cprint(f"\n✅ Selected reply!", "green")
                        cprint(f"\n{selected}", "white", attrs=["bold"])

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
                cprint("\nHow many reel concepts? (default: 10):", "yellow")
                count_input = input("> ").strip()
                count = int(count_input) if count_input.isdigit() else 10

                cprint("Focus mode? [mixed/evergreen/reactive/literal] (default: mixed):", "yellow")
                mix = input("> ").strip().lower() or "mixed"

                cprint("Optional topic override (or press Enter to skip):", "yellow")
                topic = input("> ").strip() or None

                self.generate_reel_concepts(count=count, mix=mix, topic=topic)

            elif choice == "5":
                cprint("\nPaste a raw idea or a path to a concept JSON:", "yellow")
                concept = input("> ").strip()
                if concept:
                    cprint("Optional series name (or press Enter to let Blackjack pick):", "yellow")
                    series_name = input("> ").strip() or None

                    cprint("Optional pillar (or press Enter to let Blackjack pick):", "yellow")
                    pillar = input("> ").strip() or None

                    cprint("Target duration in seconds (default: 35):", "yellow")
                    duration_input = input("> ").strip()
                    duration = int(duration_input) if duration_input.isdigit() else 35

                    self.generate_reel_packet(concept, series_name, pillar, duration)

            elif choice == "6":
                cprint("\nMix? [mixed/evergreen/reactive/literal] (default: mixed):", "yellow")
                mix = input("> ").strip().lower() or "mixed"

                cprint("Week start YYYY-MM-DD (or press Enter for this week):", "yellow")
                week_start = input("> ").strip() or None

                self.generate_batch_calendar(week_start=week_start, mix=mix)

            elif choice == "7":
                cprint("\nPath to reel packet JSON:", "yellow")
                packet_file = input("> ").strip()
                if packet_file:
                    self.score_reel_packet(packet_file)

            elif choice == "8":
                cprint("\n🎰 The table always favors the wise. Cash out!", "cyan")
                break

            else:
                cprint("Invalid choice. Try again.", "red")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Blackjack Twitter Engine - Gambling Wisdom for Life")
    parser.add_argument("--reply", type=str, help="Generate replies to a tweet")
    parser.add_argument("--tweets", type=int, help="Generate N original tweets")
    parser.add_argument("--topic", type=str, help="Topic for tweets/thread")
    parser.add_argument("--thread", type=int, help="Generate a thread of N tweets")
    parser.add_argument("--thesis", type=str, help="Thesis for thread")
    parser.add_argument("--mode", type=str, help="Mode filter: challenge, align, or specific mode")
    parser.add_argument("--reel-concepts", type=int, help="Generate N Blackjack God reel concepts")
    parser.add_argument("--reel-packet", type=str, help="Generate a reel packet from a concept file or raw idea")
    parser.add_argument("--reel-series", type=str, help="Preferred reel series")
    parser.add_argument("--reel-pillar", type=str, help="Preferred reel pillar")
    parser.add_argument("--reel-mix", type=str, default="mixed", help="Reel mix: mixed, evergreen, reactive, or literal")
    parser.add_argument("--reel-duration", type=int, default=35, help="Target reel duration in seconds")
    parser.add_argument("--calendar", action="store_true", help="Generate a weekly reel calendar")
    parser.add_argument("--week-start", type=str, help="Calendar week start date in YYYY-MM-DD format")
    parser.add_argument("--score-reel-file", type=str, help="Score a reel packet JSON file")

    args = parser.parse_args()

    agent = BlackjackAgent()

    if args.reel_concepts:
        agent.generate_reel_concepts(args.reel_concepts, args.reel_mix, args.topic)
    elif args.reel_packet:
        agent.generate_reel_packet(
            args.reel_packet,
            series_name=args.reel_series,
            pillar=args.reel_pillar,
            duration_seconds=args.reel_duration,
        )
    elif args.calendar:
        agent.generate_batch_calendar(week_start=args.week_start, mix=args.reel_mix)
    elif args.score_reel_file:
        agent.score_reel_packet(args.score_reel_file)
    elif args.reply:
        agent.generate_replies(args.reply, args.mode)
    elif args.tweets:
        agent.generate_tweets(args.topic, args.tweets)
    elif args.thread:
        agent.generate_thread(args.topic or "the biggest bets in life", args.thread, args.thesis)
    else:
        agent.interactive_mode()


if __name__ == "__main__":
    main()
